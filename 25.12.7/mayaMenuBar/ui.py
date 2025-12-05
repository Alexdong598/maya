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
    # SHD Submenu
    shader_menu = cmds.menuItem(
        label="SHD",
        subMenu=True,
        tearOff=True
    )
    cmds.menuItem(
        label="Shader Publish",
        command=lambda *args: utils.executeDeferred(COMMANDS['shader_publish']),
        parent=shader_menu
    )
    cmds.setParent('..', menu=True)

 ##################################################################################   
    # RIG Submenu
    rig_menu = cmds.menuItem(
        label="RIG",
        subMenu=True,
        tearOff=True
    )
    cmds.menuItem(
        label="Rig Publish",
        command=lambda *args: utils.executeDeferred(COMMANDS['rig_publish']),
        parent=rig_menu
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

###################################################################################
    # Layout Submenu
    layout_menu = cmds.menuItem(
        label="LAYOUT",
        subMenu=True,
        tearOff=True
    )
    cmds.menuItem(
        label="Load MM Files",
        command=lambda *args: utils.executeDeferred(COMMANDS['load_MM_files']),
        parent=layout_menu
    )
    cmds.menuItem(
        label="Layout Playblast",
        command=lambda *args: utils.executeDeferred(COMMANDS['layout_playblast']),
        parent=layout_menu
    )
    cmds.menuItem(
        label="Layout Publish",
        command=lambda *args: utils.executeDeferred(COMMANDS['layout_publish']),
        parent=layout_menu
    )
    cmds.setParent('..', menu=True)

 ##################################################################################   
    # MMM Submenu
    mm_menu = cmds.menuItem(
        label="MM",
        subMenu=True,
        tearOff=True
    )
    cmds.menuItem(
        label="MM Playblast",
        command=lambda *args: utils.executeDeferred(COMMANDS['mm_playblast']),
        parent=mm_menu
    )
    cmds.menuItem(
        label="MM Publish",
        command=lambda *args: utils.executeDeferred(COMMANDS['mm_publish']),
        parent=mm_menu
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
    # Get Start End Frame Submenu under UTILS
    cmds.menuItem(
        label="Get Start End Frame",
        command=lambda *args: utils.executeDeferred(COMMANDS['get_start_end_frame']),
        parent=utils_menu
    )
    # Shotgun Library Submenu under UTILS
    cmds.menuItem(
        label="Shotgun Library",
        command=lambda *args: utils.executeDeferred(COMMANDS['shotgun_library']),
        parent=utils_menu
    )
    # Rename Tool Submenu under UTILS
    cmds.menuItem(
        label="Rename Tool",
        command=lambda *args: utils.executeDeferred(COMMANDS['rename_tool']),
        parent=utils_menu
    )
    # Texture Replacer Submenu under UTILS
    cmds.menuItem(
        label="Texture Replacer",
        command=lambda *args: utils.executeDeferred(COMMANDS['texture_replacer']),
        parent=utils_menu
    )

    # Save and Load Submenu under UTILS
    cmds.menuItem(
        label="Random Transforms",
        command=lambda *args: utils.executeDeferred(COMMANDS['random_transforms']),
        parent=utils_menu
    )

    # Pause Update and Auto Update Submenu under UTILS
    pause_auto_menu = cmds.menuItem(
        label="Pause and Auto Update",
        subMenu=True,
        tearOff=True,
        parent=utils_menu
    )
    cmds.menuItem(
        label="Pause Update",
        command=lambda *args: utils.executeDeferred(COMMANDS['pause_update']),
        parent=pause_auto_menu
    )
    cmds.menuItem(
        label="Auto Update", 
        command=lambda *args: utils.executeDeferred(COMMANDS['auto_update']),
        parent=pause_auto_menu
    )

    # Remove Unknown Plugins Submenu under UTILS
    cmds.menuItem(
        label="Remove Unknown Plugins",
        command=lambda *args: utils.executeDeferred(COMMANDS['remove_unknown_plugins']),
        parent=utils_menu
    )

    # Deadline Submenu under UTILS
    cmds.menuItem(
        label="Submit Job To Deadline",
        command=lambda *args: utils.executeDeferred(COMMANDS['submit_job_to_deadline']),
        parent=utils_menu
    )

    # Maya Lookdev Tool Submenu under UTILS
    cmds.menuItem(
        label="Maya Lookdev Tool",
        command=lambda *args: utils.executeDeferred(COMMANDS['maya_lookdev_tool']),
        parent=utils_menu
    )


    # Return to main menu level
    cmds.setParent('..', menu=True)
    cmds.setParent('..', menu=True)
###################################################################################
