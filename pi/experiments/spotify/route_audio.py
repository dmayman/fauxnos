#!/usr/bin/env python3
import subprocess
import time

class AudioRouter:
    def __init__(self):
        self.current_output = 'local'
    
    def set_output(self, output_type):
        """Switch between 'local' and 'snapcast' output"""
        if output_type == 'local':
            # Set Output Selector to 0 (local)
            subprocess.run(['amixer', '-c', '0', 'set', 'Output Selector', '0%'])
            self.current_output = 'local'
            print("Switched to local output")
        
        elif output_type == 'snapcast':
            # Set Output Selector to 100% (snapcast)
            subprocess.run(['amixer', '-c', '0', 'set', 'Output Selector', '100%'])
            self.current_output = 'snapcast'
            print("Switched to Snapcast output")
    
    def toggle_output(self):
        """Toggle between local and snapcast output"""
        if self.current_output == 'local':
            self.set_output('snapcast')
        else:
            self.set_output('local')
    
    def get_current_output(self):
        """Get the current output setting"""
        result = subprocess.run(['amixer', '-c', '0', 'get', 'Output Selector'], 
                              capture_output=True, text=True)
        if '100%' in result.stdout:
            return 'snapcast'
        else:
            return 'local'

# Example usage
if __name__ == "__main__":
    router = AudioRouter()
    
    # Set to local
    router.set_output('local')
    time.sleep(5)
    
    # Switch to snapcast
    router.set_output('snapcast')
    time.sleep(5)
    
    # Toggle back
    router.toggle_output()