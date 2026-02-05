"""Command to launch Shotgun Library UI in Maya."""

import os
import sys
import importlib
import maya.cmds as cmds

def get_command():
    def _command():
        try:
            # Check for environment variable
            lib_path = os.environ.get("SHOTGUN_LIBRARY_PATH")
            if not lib_path:
                cmds.warning("SHOTGUN_LIBRARY_PATH environment variable not set")
                return
            
            # Construct path to startup.py
            startup_path = os.path.join(lib_path, "startup.py")
            if not os.path.exists(startup_path):
                cmds.warning(f"startup.py not found at: {startup_path}")
                return
            
            # Add to Python path if needed
            if lib_path not in sys.path:
                sys.path.append(lib_path)
            
            # Import and execute
            try:
                import startup
                importlib.reload(startup)
                startup.launch_ui()
            except Exception as e:
                cmds.warning(f"Failed to launch Shotgun Library UI: {str(e)}")
                raise
                
        except Exception as e:
            cmds.warning(f"Error in Shotgun Library command: {str(e)}")
            
    return _command

def execute():
    """Execute the command with module reloading."""
    try:
        importlib.reload(sys.modules[__name__])
    except Exception as e:
        print(f"Could not reload module: {e}")
        
    cmd = get_command()
    cmd()
