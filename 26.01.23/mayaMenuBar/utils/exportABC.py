"""
Alembic export utility for Maya, using a MEL command call from Python
for maximum stability.

This script provides a primary function `export_abc` that can be used
for both animated sequences and static, single-frame exports.
"""
import os
import maya.cmds as cmds
import maya.mel as mel
import importlib
import sys

def export_abc(path, start_frame, end_frame, include_curves=False, strip_namespaces=True):
    """
    Core function to export the current selection to an Alembic file.
    It builds and executes a raw MEL command for stability.

    To export a static model, pass the same value for start_frame and end_frame.

    Args:
        path (str): The full output file path.
        start_frame (int): The start frame of the export range.
        end_frame (int): The end frame of the export range.
        include_curves (bool, optional): If False, nurbs curves will not be
                                         exported. Defaults to False.
        strip_namespaces (bool, optional): If True, namespaces will be stripped
                                           from object names during export.
                                           Defaults to True.
    """
    # Ensure Alembic plugin is loaded
    if not cmds.pluginInfo("AbcExport", query=True, loaded=True):
        try:
            cmds.loadPlugin("AbcExport.mll")
        except RuntimeError as e:
            cmds.error(f"Failed to load AbcExport plugin: {e}")
            return

    # Get the current selection
    selected_nodes = cmds.ls(sl=True, long=True)
    if not selected_nodes:
        cmds.warning("Cannot export Alembic: No objects selected.")
        raise RuntimeError("No objects selected for Alembic export.")

    # Ensure the output directory exists
    output_dir = os.path.dirname(path)
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
        except OSError as e:
            cmds.error(f"Could not create directory {output_dir}: {e}")
            return

    # --- MEL Command Construction ---
    path = path.replace('\\', '/')
    roots_arg = " ".join([f"-root {node}" for node in selected_nodes])
    
    # Base arguments
    job_args = [
        f"-frameRange {start_frame} {end_frame}",
        "-uvWrite",
        "-writeColorSets",
        "-writeUVSets",
        "-dataFormat ogawa",
        roots_arg,
    ]

    # Add the renderableOnly flag if curves should NOT be included.
    # This is the key change for the new functionality.
    if not include_curves:
        job_args.append("-renderableOnly")

    # Add the stripNamespaces flag if enabled
    if strip_namespaces:
        job_args.append("-stripNamespaces 0")

    # Finally, add the file path argument, ensuring it's correctly escaped
    job_args.append(f'-file \\"{path}\\"')
    
    job_arg_string = " ".join(job_args)
    mel_command = f'AbcExport -j "{job_arg_string}";'
    
    # --- Execute MEL Command ---
    print(f"Executing MEL command: {mel_command}")
    try:
        mel.eval(mel_command)
        success_message = f"Successfully exported Alembic to: {path}"
        cmds.inViewMessage(msg=success_message, pos="topLeft", fade=True, fadeStayTime=3000)
        print(success_message)
    except Exception as e:
        cmds.error(f"Alembic export failed. See script editor for details. Error: {e}")
        raise

def execute_with_dialog():
    """
    A helper function for standalone testing. It opens a dialog to let the user
    pick a path and exports the current timeline's animation range.
    """
    print("Executing animated Alembic export with dialog...")
    
    # Get frame range from the playback timeline.
    start_frame = cmds.playbackOptions(q=True, minTime=True)
    end_frame = cmds.playbackOptions(q=True, maxTime=True)

    # Open file dialog for the user to select a save path.
    file_path_raw = cmds.fileDialog2(
        fileFilter="Alembic (*.abc)",
        dialogStyle=2,
        fileMode=0,
        caption="Export Animated Alembic (MEL Method)"
    )

    if not file_path_raw:
        print("Alembic export cancelled by user.")
        return
    
    path = file_path_raw[0]
    
    # Call the core export function with the animation range (and default curve and namespace settings)
    export_abc(path, start_frame, end_frame)


def get_command():
    """Returns the command implementation for standalone execution."""
    def _command():
        importlib.reload(sys.modules[__name__])
        execute_with_dialog()
    return _command

def execute():
    """
    Main entry point for running this script standalone to export an animation.
    """
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()