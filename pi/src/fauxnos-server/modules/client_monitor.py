#!/usr/bin/env python3
"""
Snapcast Client Event Monitor
=============================
Monitors snapcast client connect/disconnect events and triggers group assignments.
"""

import json
import socket
import threading
import time
from typing import Callable, Optional, Dict, Any
import logging

class SnapcastClientMonitor:
    """Monitors snapcast client events via JSON-RPC notifications"""

    def __init__(self, snapcast_host: str = "localhost", snapcast_port: int = 1705):
        self.snapcast_host = snapcast_host
        self.snapcast_port = snapcast_port
        self.running = False
        self.socket = None
        self.monitor_thread = None

        # Event callbacks
        self.on_client_connect: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_client_disconnect: Optional[Callable[[Dict[str, Any]], None]] = None

        # Logging
        self.logger = logging.getLogger(__name__)

    def set_connect_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for client connect events"""
        self.on_client_connect = callback

    def set_disconnect_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for client disconnect events"""
        self.on_client_disconnect = callback

    def log(self, message: str, level: str = "INFO"):
        """Log with color coding"""
        colors = {
            "INFO": "\033[1;36m",    # Bright Cyan
            "SUCCESS": "\033[0;32m", # Green
            "WARNING": "\033[1;33m", # Yellow
            "ERROR": "\033[0;31m",   # Red
        }
        reset = "\033[0m"
        prefix = "🔍" if level == "INFO" else "✓" if level == "SUCCESS" else "⚠" if level == "WARNING" else "✗"
        print(f"{colors.get(level, '')}{prefix} [CLIENT-MONITOR] {message}{reset}")

    def connect_to_snapcast(self) -> bool:
        """Connect to snapcast server for event monitoring"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)  # 10 second timeout for connection
            self.socket.connect((self.snapcast_host, self.snapcast_port))
            self.log(f"Connected to snapcast server at {self.snapcast_host}:{self.snapcast_port}")
            return True
        except Exception as e:
            self.log(f"Failed to connect to snapcast server: {e}", "ERROR")
            return False

    def process_notification(self, notification: Dict[str, Any]):
        """Process incoming snapcast notifications"""
        try:
            method = notification.get("method")
            params = notification.get("params", {})

            if method == "Client.OnConnect":
                client_info = params.get("client", {})
                client_id = client_info.get("id")
                client_name = client_info.get("host", {}).get("name", "unknown")

                self.log(f"Client connected: {client_id} ({client_name})", "SUCCESS")

                if self.on_client_connect:
                    self.on_client_connect(client_info)

            elif method == "Client.OnDisconnect":
                client_info = params.get("client", {})
                client_id = client_info.get("id")
                client_name = client_info.get("host", {}).get("name", "unknown")

                self.log(f"Client disconnected: {client_id} ({client_name})", "WARNING")

                if self.on_client_disconnect:
                    self.on_client_disconnect(client_info)

            elif method in ["Group.OnMute", "Group.OnStreamChanged", "Stream.OnUpdate"]:
                # Log other events for debugging but don't process
                self.log(f"Received event: {method}", "INFO")

        except Exception as e:
            self.log(f"Error processing notification: {e}", "ERROR")

    def monitor_events(self):
        """Main event monitoring loop"""
        buffer = ""

        while self.running:
            try:
                # Receive data from snapcast
                data = self.socket.recv(4096)
                if not data:
                    self.log("Connection closed by server", "WARNING")
                    break

                # Decode and add to buffer
                buffer += data.decode('utf-8')

                # Process complete JSON messages (newline delimited)
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()

                    if line:
                        try:
                            notification = json.loads(line)
                            # Only process notifications (no 'id' field)
                            if 'id' not in notification:
                                self.process_notification(notification)
                        except json.JSONDecodeError:
                            self.log(f"Invalid JSON received: {line}", "WARNING")

            except socket.timeout:
                # Timeout is normal, continue monitoring
                continue
            except Exception as e:
                self.log(f"Monitor error: {e}", "ERROR")
                break

        self.log("Event monitoring stopped")

    def start_monitoring(self) -> bool:
        """Start the client event monitoring"""
        if self.running:
            self.log("Monitor already running", "WARNING")
            return False

        if not self.connect_to_snapcast():
            return False

        self.running = True
        self.socket.settimeout(1)  # Use short timeout for recv to allow clean shutdown

        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self.monitor_events, daemon=True)
        self.monitor_thread.start()

        self.log("Started client event monitoring")
        return True

    def stop_monitoring(self):
        """Stop the client event monitoring"""
        if not self.running:
            return

        self.running = False

        if self.socket:
            try:
                self.socket.close()
            except:
                pass

        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

        self.log("Stopped client event monitoring")

    def __enter__(self):
        """Context manager entry"""
        self.start_monitoring()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop_monitoring()


def main():
    """Test the client monitor"""
    import argparse

    parser = argparse.ArgumentParser(description="Monitor snapcast client events")
    parser.add_argument('--host', default='localhost', help='Snapcast server host')
    parser.add_argument('--port', type=int, default=1705, help='Snapcast server port')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    def on_connect(client_info):
        print(f"📱 CLIENT CONNECTED: {client_info.get('id')} ({client_info.get('host', {}).get('name')})")

    def on_disconnect(client_info):
        print(f"📱 CLIENT DISCONNECTED: {client_info.get('id')} ({client_info.get('host', {}).get('name')})")

    monitor = SnapcastClientMonitor(args.host, args.port)
    monitor.set_connect_callback(on_connect)
    monitor.set_disconnect_callback(on_disconnect)

    print("🔍 Starting client monitor (Ctrl+C to stop)...")

    try:
        if monitor.start_monitoring():
            # Keep main thread alive
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping monitor...")
    finally:
        monitor.stop_monitoring()


if __name__ == '__main__':
    main()