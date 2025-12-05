import maya.cmds as cmds
import os
import re
import glob

def replace_textures(local_dir):
    # Get all file texture nodes
    file_nodes = cmds.ls(type='file')
    if not file_nodes:
        cmds.warning("No file texture nodes found in the scene.")
        return
    updated_count = 0
    for file_node in file_nodes:
        # Get current texture path
        old_path = cmds.getAttr(file_node + '.fileTextureName')
        if not old_path:
            continue
        # Extract filename (including possible UDIM placeholders)
        basename = os.path.basename(old_path)
        # Check if it contains UDIM or other placeholders
        has_placeholder = '<UDIM>' in basename or '<UVTILE>' in basename or re.search(r'<\w+>', basename)
        if has_placeholder:
            # Determine uvTilingMode to choose wildcard pattern
            uv_mode = cmds.getAttr(file_node + '.uvTilingMode')
            wildcard = None
            if '<UDIM>' in basename:
                wildcard = basename.replace('<UDIM>', '*')
                cmds.warning(f"Using wildcard {wildcard} for UDIM in {basename}.")
            elif '<UVTILE>' in basename:
                wildcard = basename.replace('<UVTILE>', '*_*')
                cmds.warning(f"Using wildcard {wildcard} for UVTILE in {basename}.")
            else:
                # General placeholder, warn and skip replacement to single file
                cmds.warning(f"Unknown placeholder in {basename}. Skipping replacement to single file.")
                continue
            
            if wildcard:
                # Find matching files in local_dir
                matching_files = glob.glob(os.path.join(local_dir, wildcard))
                if not matching_files:
                    cmds.warning(f"No matching files found for wildcard {wildcard} in {local_dir}. Skipping.")
                    continue
                # Take the first matching file as test
                test_path = matching_files[0]
                test_basename = os.path.basename(test_path)
            
            # Build new path as single file
            new_path = os.path.join(local_dir, test_basename).replace('\\', '/')
            # Disable sequence mode
            if cmds.attributeQuery('uvTilingMode', node=file_node, exists=True):
                cmds.setAttr(file_node + '.uvTilingMode', 0)
            if cmds.attributeQuery('useFrameExtension', node=file_node, exists=True):
                cmds.setAttr(file_node + '.useFrameExtension', 0)
        else:
            # For regular textures, check if the same name file exists in the local directory
            potential_path = os.path.join(local_dir, basename)
            if os.path.exists(potential_path):
                new_path = potential_path.replace('\\', '/')
            else:
                cmds.warning(f"File {basename} not found in {local_dir}. Skipping.")
                continue
        # Set new path
        cmds.setAttr(file_node + '.fileTextureName', new_path, type='string')
        # Force reload by setting the attribute again to the same value
        cmds.setAttr(file_node + '.fileTextureName', new_path, type='string')
        updated_count += 1
    # Refresh the File Path Editor multiple times to ensure update
    cmds.filePathEditor(refresh=True)
    cmds.filePathEditor(refresh=True)
    cmds.confirmDialog(title='Replacement Complete', message=f'Updated {updated_count} texture paths.')

def set_uv_tiling_mode(mode_field):
    selected_mode = cmds.optionMenu(mode_field, query=True, value=True)
    mode_map = {'Off': 0, '0-based (ZBrush)': 1, '1-based (Mudbox)': 2, 'UDIM (Mari)': 3, 'Explicit Tiles': 4}
    mode_value = mode_map.get(selected_mode, 0)
    
    file_nodes = cmds.ls(type='file')
    if not file_nodes:
        cmds.warning("No file texture nodes found in the scene.")
        return
    
    updated_count = 0
    for file_node in file_nodes:
        if cmds.attributeQuery('uvTilingMode', node=file_node, exists=True):
            cmds.setAttr(file_node + '.uvTilingMode', mode_value)
            # Force reload and resolution
            current_path = cmds.getAttr(file_node + '.fileTextureName')
            cmds.setAttr(file_node + '.fileTextureName', current_path, type='string')
            try:
                cmds.getAttr(file_node + '.computedFileTextureNamePattern')
            except:
                pass
            updated_count += 1
    
    # Refresh File Path Editor to resolve paths (e.g., show 1021 or other tile)
    cmds.filePathEditor(refresh=True)
    cmds.filePathEditor(refresh=True)
    
    cmds.confirmDialog(title='UV Tiling Mode Applied', message=f'Updated {updated_count} nodes to mode {selected_mode}.')

def browse_directory(field):
    # Open folder selection dialog
    dir_path = cmds.fileDialog2(dialogStyle=2, fileMode=3, caption='Select Local Texture Directory')
    if dir_path:
        cmds.textField(field, edit=True, text=dir_path[0])

def create_ui():
    if cmds.window('textureReplacerWin', exists=True):
        cmds.deleteUI('textureReplacerWin')
    
    window = cmds.window('textureReplacerWin', title='Texture Path Replacer', widthHeight=(400, 150))
    cmds.columnLayout(adjustableColumn=True)
    
    cmds.text(label='Select Local Texture Directory:')
    dir_field = cmds.textField()
    
    cmds.rowLayout(numberOfColumns=2)
    cmds.button(label='Browse', command=lambda x: browse_directory(dir_field))
    cmds.button(label='Replace Textures', command=lambda x: replace_textures(cmds.textField(dir_field, query=True, text=True)))
    cmds.setParent('..')
    
    # Add UV Tiling Mode option after replacement
    cmds.separator(height=10)
    cmds.text(label='UV Tiling Mode (Apply after replacement):')
    mode_menu = cmds.optionMenu()
    cmds.menuItem(label='Off')
    cmds.menuItem(label='0-based (ZBrush)')
    cmds.menuItem(label='1-based (Mudbox)')
    cmds.menuItem(label='UDIM (Mari)')
    cmds.menuItem(label='Explicit Tiles')
    
    cmds.button(label='Apply UV Tiling Mode', command=lambda x: set_uv_tiling_mode(mode_menu))
    
    cmds.showWindow(window)

# For menu integration
def execute():
    create_ui()