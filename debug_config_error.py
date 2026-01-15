import sys
import os
import copy
from config_manager import config

def test_empty_config():
    print("----- TESTING EMPTY CONFIG -----")
    # 1. Backup existing config
    if os.path.exists("config.json"):
        os.rename("config.json", "config.json.bak")
    
    try:
        # 2. Create empty config
        with open("config.json", "w") as f:
            f.write("") # Completely empty
            
        # 3. Trigger reload
        print("Reloading config...")
        config.reload()
        
        # 4. Check results
        print(f"Last Error: {config.last_error}")
        
    finally:
        # Restore
        if os.path.exists("config.json.bak"):
            os.replace("config.json.bak", "config.json")
            
if __name__ == "__main__":
    test_empty_config()
