"""Entry point for Maya to load the menu bar package."""
import maya.utils as utils

def load_menu():
    """Load the custom menu bar."""
    try:
        from mayaMenuBar import initialize
        initialize()
    except ImportError as e:
        print(f"Failed to load menu bar: {e}")

# Defer loading until Maya is fully initialized
utils.executeDeferred(load_menu)
