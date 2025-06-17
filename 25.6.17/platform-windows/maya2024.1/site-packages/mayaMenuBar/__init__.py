"""Main package initialization for Maya Menu Bar."""
from . import commands
from . import ui
 
def initialize():
    """Initialize the menu bar package."""
    ui.create_menu()
