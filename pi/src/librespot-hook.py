#!/usr/bin/env python3
"""
Librespot Event Hook Script
---------------------------
This script receives librespot events and forwards them to the main fauxnos-client.py
via Unix socket or file-based communication as fallback.
"""

import os
import socket
import json
import logging

# Set up logging with more detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/user/librespot-hook.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('LibrespotHook')

def send_event_to_fauxnos():
    """Collect librespot environment variables and send to fauxnos-client"""
    
    logger.info("=== LIBRESPOT HOOK TRIGGERED ===")
    
    # Log all available environment variables for debugging
    all_env = {k: v for k, v in os.environ.items() if k.startswith(('PLAYER_', 'TRACK_', 'NAME', 'ARTISTS', 'ALBUM', 'POSITION_', 'VOLUME', 'DURATION_', 'URI', 'IS_', 'POPULARITY', 'NUMBER', 'DISC_', 'SHUFFLE', 'REPEAT', 'AUTO_', 'CONNECTION_', 'CLIENT_', 'USER_'))}
    logger.debug(f"All librespot environment variables: {all_env}")
    
    # Collect all relevant librespot environment variables
    event_data = {
        'event': os.getenv('PLAYER_EVENT'),
        'track_id': os.getenv('TRACK_ID'),
        'track_name': os.getenv('NAME'),
        'artist': os.getenv('ARTISTS'),
        'album': os.getenv('ALBUM'),
        'position_ms': os.getenv('POSITION_MS'),
        'volume': os.getenv('VOLUME'),
        'duration_ms': os.getenv('DURATION_MS'),
        'uri': os.getenv('URI'),
        'is_explicit': os.getenv('IS_EXPLICIT'),
        'popularity': os.getenv('POPULARITY'),
        'track_number': os.getenv('NUMBER'),
        'disc_number': os.getenv('DISC_NUMBER'),
        'shuffle': os.getenv('SHUFFLE'),
        'repeat': os.getenv('REPEAT'),
        'auto_play': os.getenv('AUTO_PLAY'),
    }
    
    # Remove None values to keep payload clean
    event_data = {k: v for k, v in event_data.items() if v is not None}
    
    logger.info(f"Event type: {event_data.get('event', 'UNKNOWN')}")
    logger.info(f"Event data: {event_data}")
    
    # Try to send via Unix socket first
    socket_path = '/home/user/fauxnos-librespot.sock'
    try:
        # Check if socket file exists
        if os.path.exists(socket_path):
            logger.debug(f"Socket file exists: {socket_path}")
        else:
            logger.debug(f"Socket file does not exist: {socket_path}")
            raise FileNotFoundError(f"Socket file not found: {socket_path}")
            
        logger.debug(f"Attempting to connect to socket: {socket_path}")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)  # 2 second timeout
        sock.connect(socket_path)
        message = json.dumps(event_data).encode() + b'\n'
        sock.send(message)
        sock.close()
        logger.info(f"✓ Event sent via socket to fauxnos-client successfully")
        return
    except FileNotFoundError:
        logger.warning(f"Socket file not found: {socket_path} - fauxnos-client may not be running")
    except ConnectionRefusedError:
        logger.warning(f"Connection refused to socket: {socket_path} - fauxnos-client may not be listening")
    except socket.timeout:
        logger.warning(f"Socket connection timeout: {socket_path} - fauxnos-client may be unresponsive")
    except Exception as e:
        logger.warning(f"Failed to send via socket: {e}")
    
    # No file fallback - socket should work
    logger.error(f"✗ Failed to send event via socket - no fallback used")
        
    logger.info("=== LIBRESPOT HOOK COMPLETED ===\n")

if __name__ == '__main__':
    send_event_to_fauxnos()