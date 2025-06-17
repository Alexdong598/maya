"""UI implementation for Maya Menu Bar."""
import os
import importlib
import maya.cmds as cmds
import maya.utils as utils

# Dynamically import all command modules from commands directory
COMMANDS = {}
commands_dir = os.path.join(os.path.dirname(__file__), 'commands')
for filename in os.listdir(commands_dir):
    if filename.endswith('.py') and not filename.startswith('_'):
        module_name = filename[:-3]
        module = importlib.import_module(f'mayaMenuBar.commands.{module_name}')
        COMMANDS[module_name] = module.execute

def create_menu():
    """Create the main menu in Maya."""
    # Delete existing menu if it exists
    menu_name = "Maya_Dy_Plugins"
    if cmds.menu(menu_name, exists=True):
        cmds.deleteUI(menu_name)
    
    # Create main menu
    main_menu = cmds.menu(
        menu_name,
        label="Maya_Dy_Plugins",
        parent="MayaWindow",
        tearOff=True
    )

 ##################################################################################   
    # MDL Submenu
    mdl_menu = cmds.menuItem(
        label="MDL",
        subMenu=True,
        tearOff=True
    )
    cmds.menuItem(
        label="Asset Publish",
        command=lambda *args: utils.executeDeferred(COMMANDS['asset_publish']),
        parent=mdl_menu
    )
    cmds.setParent('..', menu=True)

 ##################################################################################   
    # ANIM Submenu
    anim_menu = cmds.menuItem(
        label="ANIM",
        subMenu=True,
        tearOff=True
    )
    cmds.menuItem(
        label="Load MM Files",
        command=lambda *args: utils.executeDeferred(COMMANDS['load_MM_files']),
        parent=anim_menu
    )
    cmds.menuItem(
        label="Anim Playblast",
        command=lambda *args: utils.executeDeferred(COMMANDS['anim_playblast']),
        parent=anim_menu
    )
    cmds.menuItem(
        label="Anim Publish",
        command=lambda *args: utils.executeDeferred(COMMANDS['anim_publish']),
        parent=anim_menu
    )
    cmds.setParent('..', menu=True)



 ##################################################################################   
   
    # UTILS Submenu
    utils_menu = cmds.menuItem(
        label="UTILS",
        subMenu=True,
        tearOff=True
    )
    
    # Save and Load Submenu under UTILS
    save_load_menu = cmds.menuItem(
        label="Save and Load",
        subMenu=True,
        tearOff=True,
        parent=utils_menu
    )
    cmds.menuItem(
        label="Open",
        command=lambda *args: utils.executeDeferred(COMMANDS['open_file']),
        parent=save_load_menu
    )
    cmds.menuItem(
        label="Save", 
        command=lambda *args: utils.executeDeferred(COMMANDS['save_file']),
        parent=save_load_menu
    )
    
    # Return to main menu level
    cmds.setParent('..', menu=True)
    cmds.setParent('..', menu=True)
###################################################################################
