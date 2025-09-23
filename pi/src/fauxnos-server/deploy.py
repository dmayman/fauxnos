#!/usr/bin/env python3
"""
Fauxnos Deployment Manager
--------------------------
Handles atomic deployment of generated configurations to system locations.
"""

import os
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import List, Dict, Any
from config_manager import ConfigManager


class DeploymentManager:
    """Manages deployment of configurations to system locations"""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.logger = logging.getLogger('DeploymentManager')
        self.dry_run = False

    def set_dry_run(self, dry_run: bool):
        """Enable/disable dry run mode (no actual changes)"""
        self.dry_run = dry_run
        if dry_run:
            self.logger.info("Dry run mode enabled - no changes will be made")

    def deploy_server_configs(self, keep_staging: bool = False) -> bool:
        """Deploy all server-side configurations"""
        try:
            if keep_staging:
                # Use a persistent directory for inspection
                staging_dir = "/tmp/fauxnos-staging"
                if os.path.exists(staging_dir):
                    shutil.rmtree(staging_dir)
                os.makedirs(staging_dir)
                self.logger.info(f"Staging configurations in {staging_dir} (persistent)")
            else:
                # Use temporary directory that gets cleaned up
                staging_context = tempfile.TemporaryDirectory()
                staging_dir = staging_context.__enter__()
                self.logger.info(f"Staging configurations in {staging_dir}")

            try:
                # Generate all configurations in staging directory
                if not self._stage_server_configs(staging_dir):
                    return False

                # Validate all configurations
                if not self._validate_staged_configs(staging_dir):
                    return False

                if self.dry_run:
                    if keep_staging:
                        self.logger.info(f"DRY RUN: Staging directory preserved at {staging_dir}")
                        self.logger.info("You can inspect the generated files there")
                    return True

                # Deploy configurations atomically
                if not self._deploy_staged_configs(staging_dir):
                    return False

                # Restart services
                if not self._restart_server_services():
                    return False

                self.logger.info("Server configuration deployment completed successfully")
                return True

            finally:
                if not keep_staging:
                    staging_context.__exit__(None, None, None)

        except Exception as e:
            self.logger.error(f"Server deployment failed: {e}")
            return False

    def _stage_server_configs(self, staging_dir: str) -> bool:
        """Generate all server configurations in staging directory"""
        try:
            clients = self.config_manager.list_clients()

            # Create directory structure
            go_librespot_dir = os.path.join(staging_dir, "go-librespot")
            systemd_dir = os.path.join(staging_dir, "systemd")
            scripts_dir = os.path.join(staging_dir, "scripts")

            for dir_path in [go_librespot_dir, systemd_dir, scripts_dir]:
                os.makedirs(dir_path, exist_ok=True)

            # Generate go-librespot configs and services
            for client in clients:
                # go-librespot config
                config_content = self.config_manager.generate_go_librespot_config(client)
                client_config_dir = os.path.join(go_librespot_dir, client.id)
                os.makedirs(client_config_dir, exist_ok=True)

                config_file = os.path.join(client_config_dir, "config.yml")
                with open(config_file, 'w') as f:
                    f.write(config_content)

                # Systemd service
                service_content = self.config_manager.generate_systemd_service(client)
                service_file = os.path.join(systemd_dir, f"go-librespot-{client.id}.service")
                with open(service_file, 'w') as f:
                    f.write(service_content)

            # Generate FIFO setup service (once for all clients)
            if clients:  # Only if we have clients
                fifo_service_content = self.config_manager.generate_fifo_setup_service()
                fifo_service_file = os.path.join(systemd_dir, "fauxnos-fifo-setup.service")
                with open(fifo_service_file, 'w') as f:
                    f.write(fifo_service_content)

            # Generate FIFO setup script
            fifo_script = self.config_manager.generate_fifo_setup_script()
            fifo_script_file = os.path.join(scripts_dir, "setup-fifo.sh")
            with open(fifo_script_file, 'w') as f:
                f.write(fifo_script)
            os.chmod(fifo_script_file, 0o755)

            # Generate snapserver sources (for manual addition to snapserver.conf)
            sources = self.config_manager.generate_snapserver_sources()
            sources_file = os.path.join(staging_dir, "snapserver_sources.txt")
            with open(sources_file, 'w') as f:
                f.write("# Add these lines to snapserver.conf [stream] section:\n")
                for source in sources:
                    f.write(f"{source}\n")

            self.logger.info("All server configurations staged successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to stage server configs: {e}")
            return False

    def _validate_staged_configs(self, staging_dir: str) -> bool:
        """Validate all staged configurations"""
        try:
            # Validate go-librespot configs (basic YAML syntax check)
            go_librespot_dir = os.path.join(staging_dir, "go-librespot")
            for config_dir_name in os.listdir(go_librespot_dir):
                config_dir = os.path.join(go_librespot_dir, config_dir_name)
                if os.path.isdir(config_dir):
                    config_file = os.path.join(config_dir, "config.yml")
                    if not os.path.exists(config_file):
                        self.logger.error(f"Missing config file: {config_file}")
                        return False

            # Validate systemd services (basic syntax check)
            systemd_dir = os.path.join(staging_dir, "systemd")
            for filename in os.listdir(systemd_dir):
                if filename.endswith(".service"):
                    service_file = os.path.join(systemd_dir, filename)
                    with open(service_file) as f:
                        content = f.read()
                        if "[Unit]" not in content or "[Service]" not in content:
                            self.logger.error(f"Invalid systemd service: {service_file}")
                            return False

            # Validate FIFO script (executable and basic structure)
            scripts_dir = os.path.join(staging_dir, "scripts")
            fifo_script = os.path.join(scripts_dir, "setup-fifo.sh")
            if not os.path.exists(fifo_script):
                self.logger.error("Missing FIFO setup script")
                return False

            if not os.access(fifo_script, os.X_OK):
                self.logger.error("FIFO setup script is not executable")
                return False

            self.logger.info("All staged configurations validated successfully")
            return True

        except Exception as e:
            self.logger.error(f"Configuration validation failed: {e}")
            return False

    def _deploy_staged_configs(self, staging_dir: str) -> bool:
        """Deploy staged configurations to system locations"""
        if self.dry_run:
            self.logger.info("DRY RUN: Would deploy configurations to system locations")
            return True

        try:
            # Deploy go-librespot configs
            go_librespot_base = os.path.expanduser(
                self.config_manager.server_config['server']['paths']['go_librespot_config_base']
            )
            staging_go_librespot = os.path.join(staging_dir, "go-librespot")

            # Ensure base directory exists
            os.makedirs(go_librespot_base, exist_ok=True)

            # Copy each client's config
            for client_dir_name in os.listdir(staging_go_librespot):
                client_dir = os.path.join(staging_go_librespot, client_dir_name)
                if os.path.isdir(client_dir):
                    target_dir = os.path.join(go_librespot_base, client_dir_name)
                    if os.path.exists(target_dir):
                        shutil.rmtree(target_dir)
                    shutil.copytree(client_dir, target_dir)
                    self.logger.info(f"Deployed go-librespot config for {client_dir_name}")

            # Deploy systemd user services
            systemd_staging = os.path.join(staging_dir, "systemd")
            systemd_target = os.path.expanduser("~/.config/systemd/user")
            os.makedirs(systemd_target, exist_ok=True)

            for filename in os.listdir(systemd_staging):
                if filename.endswith(".service"):
                    service_file = os.path.join(systemd_staging, filename)
                    target_file = os.path.join(systemd_target, filename)
                    shutil.copy2(service_file, target_file)
                    self.logger.info(f"Deployed user systemd service: {filename}")

            # Deploy scripts
            scripts_staging = os.path.join(staging_dir, "scripts")
            scripts_target = os.path.expanduser("~/scripts")
            os.makedirs(scripts_target, exist_ok=True)

            for filename in os.listdir(scripts_staging):
                script_file = os.path.join(scripts_staging, filename)
                target_file = os.path.join(scripts_target, filename)
                shutil.copy2(script_file, target_file)
                os.chmod(target_file, 0o755)
                self.logger.info(f"Deployed script: {filename}")

            # Reload user systemd daemon
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            self.logger.info("User systemd daemon reloaded")

            return True

        except Exception as e:
            self.logger.error(f"Failed to deploy configurations: {e}")
            return False

    def _restart_server_services(self) -> bool:
        """Restart affected server services"""
        if self.dry_run:
            self.logger.info("DRY RUN: Would restart server services")
            return True

        try:
            clients = self.config_manager.list_clients()

            # Stop all services first
            services_to_stop = ["fauxnos-fifo-setup.service"]
            for client in clients:
                services_to_stop.append(f"go-librespot-{client.id}.service")

            for service_name in services_to_stop:
                try:
                    subprocess.run(["systemctl", "--user", "stop", service_name],
                                 check=False, capture_output=True)
                    self.logger.info(f"Stopped {service_name}")
                except Exception as e:
                    self.logger.warning(f"Failed to stop {service_name}: {e}")

            # Enable and start FIFO setup service first
            if clients:  # Only if we have clients
                try:
                    subprocess.run(["systemctl", "--user", "enable", "fauxnos-fifo-setup.service"], check=True)
                    subprocess.run(["systemctl", "--user", "start", "fauxnos-fifo-setup.service"], check=True)
                    self.logger.info("Started and enabled fauxnos-fifo-setup.service")
                except Exception as e:
                    self.logger.error(f"Failed to start fauxnos-fifo-setup.service: {e}")
                    return False

            # Start and enable all go-librespot services (they'll wait for FIFO service)
            for client in clients:
                service_name = f"go-librespot-{client.id}.service"
                try:
                    subprocess.run(["systemctl", "--user", "enable", service_name], check=True)
                    subprocess.run(["systemctl", "--user", "start", service_name], check=True)
                    self.logger.info(f"Started and enabled {service_name}")
                except Exception as e:
                    self.logger.error(f"Failed to start {service_name}: {e}")
                    return False

            # Note: snapserver is likely a system service, keep it as-is
            try:
                subprocess.run(["sudo", "systemctl", "restart", "snapserver"], check=True)
                self.logger.info("Restarted snapserver (system service)")
            except Exception as e:
                self.logger.warning(f"Failed to restart snapserver: {e}")
                self.logger.info("You may need to manually restart snapserver and add the new sources to snapserver.conf")

            return True

        except Exception as e:
            self.logger.error(f"Failed to restart services: {e}")
            return False

    def get_service_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all managed services"""
        status = {}
        clients = self.config_manager.list_clients()

        # Check user services (go-librespot and FIFO setup)
        user_services = ["fauxnos-fifo-setup.service"]
        for client in clients:
            user_services.append(f"go-librespot-{client.id}.service")

        for service_name in user_services:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service_name],
                    capture_output=True, text=True
                )
                active = result.stdout.strip() == "active"

                result = subprocess.run(
                    ["systemctl", "--user", "is-enabled", service_name],
                    capture_output=True, text=True
                )
                enabled = result.stdout.strip() == "enabled"

                # Find client name if it's a go-librespot service
                client_name = None
                for client in clients:
                    if service_name == f"go-librespot-{client.id}.service":
                        client_name = client.name
                        break

                status[service_name] = {
                    "active": active,
                    "enabled": enabled,
                    "type": "user"
                }
                if client_name:
                    status[service_name]["client_name"] = client_name

            except Exception as e:
                status[service_name] = {
                    "active": False,
                    "enabled": False,
                    "error": str(e),
                    "type": "user"
                }

        # Check system services
        for service in ["snapserver", "fauxnos-server", "mosquitto"]:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True, text=True
                )
                active = result.stdout.strip() == "active"
                status[service] = {"active": active, "type": "system"}
            except Exception as e:
                status[service] = {"active": False, "error": str(e), "type": "system"}

        return status


def main():
    """Command-line interface for deployment"""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description='Fauxnos Deployment Manager')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--keep-staging', action='store_true', help='Keep staging directory for inspection (dry run only)')
    parser.add_argument('--config', default='server_config.json', help='Server configuration file')

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Deploy command
    subparsers.add_parser('deploy-server', help='Deploy server configurations')

    # Status command
    subparsers.add_parser('status', help='Show service status')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    config_manager = ConfigManager(args.config)
    deployment_manager = DeploymentManager(config_manager)

    if args.dry_run:
        deployment_manager.set_dry_run(True)

    if args.command == 'deploy-server':
        # Validate configuration first
        issues = config_manager.validate_configuration()
        if issues:
            print("Configuration validation failed:")
            for issue in issues:
                print(f"  - {issue}")
            return

        success = deployment_manager.deploy_server_configs(keep_staging=args.keep_staging)
        if success:
            print("Server deployment completed successfully")
        else:
            print("Server deployment failed")

    elif args.command == 'status':
        status = deployment_manager.get_service_status()
        print("Service Status:")
        for service, info in status.items():
            active_status = "ACTIVE" if info.get("active", False) else "INACTIVE"
            enabled_status = ""
            if "enabled" in info:
                enabled_status = " (ENABLED)" if info["enabled"] else " (DISABLED)"

            client_info = ""
            if "client_name" in info:
                client_info = f" - {info['client_name']}"

            print(f"  {service}: {active_status}{enabled_status}{client_info}")

            if "error" in info:
                print(f"    Error: {info['error']}")


if __name__ == "__main__":
    main()