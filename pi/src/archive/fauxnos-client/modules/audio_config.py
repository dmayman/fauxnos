#!/usr/bin/env python3
"""
Audio Configuration and Utilities
---------------------------------
Handles configuration loading, logging setup, and common utility functions.
"""

import os
import json
import logging
import logging.handlers
import threading

# Constants
FADE_STEP = 5  # Volume change per step (percentage)
FADE_DELAY = 0.05  # Delay between fade steps (seconds)

def load_config():
    """Load audio configuration from JSON file"""
    # Look for config file in the parent src directory
    src_dir = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(src_dir, 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

def setup_logging(config):
    """Set up logging with file and console handlers"""
    logger = logging.getLogger('AudioController')
    logger.setLevel(logging.INFO)

    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Rotating file handler - ensure log directory exists
    log_file = os.path.expanduser(config["log_file"].format(name=config["name"]))
    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)
    
    # Use RotatingFileHandler to limit file size (1MB max, keep 5 backup files)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, 
        maxBytes=1*1024*1024,   # 1MB
        backupCount=5
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger

def play_sound(sound_file):
    """Play notification sound in a non-blocking way"""
    def play_sound_thread():
        try:
            os.system(f"aplay -D pulse:systemsink '{sound_file}' >/dev/null 2>&1")
        except Exception as e:
            logger = logging.getLogger('AudioController')
            logger.error(f"Error playing sound {sound_file}: {e}")
    
    # Start the sound in a daemon thread so it doesn't block program exit
    thread = threading.Thread(target=play_sound_thread, daemon=True)
    thread.start()

def get_sound_paths(config):
    """Get expanded sound file paths from configuration"""
    sounds = config.get("sounds", {})
    return {
        'switch': os.path.expanduser(sounds.get("switch", "")),
        'volume_up': os.path.expanduser(sounds.get("volume_up", "")),
        'volume_down': os.path.expanduser(sounds.get("volume_down", ""))
    }