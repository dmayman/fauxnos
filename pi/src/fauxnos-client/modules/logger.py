#!/usr/bin/env python3
"""
Logging Setup for Fauxnos Client

Centralized logging configuration with file and console output
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional


def setup_logging(log_file: str, log_level: str = 'INFO', console: bool = True) -> logging.Logger:
    """
    Set up centralized logging for the Fauxnos client

    Args:
        log_file: Path to log file (will be created if doesn't exist)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        console: Whether to also log to console

    Returns:
        Root logger instance
    """
    # Convert log level string to constant
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Create log directory if it doesn't exist
    log_path = Path(log_file).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear any existing handlers (prevent duplicates)
    root_logger.handlers.clear()

    # File handler with rotation (1MB max, 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=1 * 1024 * 1024,  # 1MB
        backupCount=5
    )
    file_handler.setLevel(level)

    # Detailed format for file logs
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Console handler (optional)
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)

        # Simpler format for console
        console_formatter = logging.Formatter(
            '%(levelname)s - %(name)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    # Log startup message
    root_logger.info("=" * 60)
    root_logger.info("Fauxnos Client Starting")
    root_logger.info(f"Log level: {log_level}")
    root_logger.info(f"Log file: {log_path}")
    root_logger.info("=" * 60)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module

    Args:
        name: Module name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Standalone testing
if __name__ == '__main__':
    # Test logging setup
    setup_logging('/tmp/fauxnos-client-test.log', 'DEBUG')

    logger = get_logger(__name__)
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")

    print("\nLog file created at: /tmp/fauxnos-client-test.log")
    print("Check the file to verify logging is working correctly")
