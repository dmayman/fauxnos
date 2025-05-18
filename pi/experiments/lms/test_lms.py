#!/usr/bin/env python3
"""
Simple test script for LMS pause command
"""

import subprocess
import argparse

def test_lms_pause(ip, port, mac_address):
    """Test LMS pause command for a Squeezelite player"""
    print(f"Testing LMS pause command with:")
    print(f"  LMS Server: {ip}:{port}")
    print(f"  Player MAC: {mac_address}")
    
    # Construct command
    full_url = (
        f"http://{ip}:{port}/jsonrpc.js?request="
        f"{{'id':1,'method':'slim.request','params':['{mac_address}',['pause']]}}"
    )
    
    cmd = ["wget", "-q", "-O", "/dev/null", full_url]
    
    print("\nExecuting command:")
    print(f"wget -q -O /dev/null \"{full_url}\"")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("\nCommand executed successfully!")
        else:
            print(f"\nCommand failed with return code: {result.returncode}")
            print(f"Error output: {result.stderr}")
            
        # Try a more verbose command to see the actual response
        print("\nTrying more verbose command to see actual response:")
        verbose_cmd = ["wget", "-O", "-", full_url]
        print(f"wget -O - \"{full_url}\"")
        
        verbose_result = subprocess.run(verbose_cmd, capture_output=True, text=True)
        print("\nResponse:")
        print(verbose_result.stdout)
        
        if verbose_result.stderr:
            print("\nErrors:")
            print(verbose_result.stderr)
            
    except Exception as e:
        print(f"\nError executing command: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test LMS pause command")
    parser.add_argument("--ip", default="127.0.0.1", help="LMS server IP address")
    parser.add_argument("--port", default=9000, type=int, help="LMS server port")
    parser.add_argument("--mac", required=True, help="Player MAC address")
    
    args = parser.parse_args()
    test_lms_pause(args.ip, args.port, args.mac)