"""Alembic export utility for Maya."""
import os
import maya.cmds as cmds
import importlib
import sys

def exportABC(path, start_frame=0, end_frame=0):
    """Export selected objects to Alembic file with detailed settings.
    
    Args:
        path (str): The output file path
        start_frame (int): Start frame for animation export
        end_frame (int): End frame for animation export
    """
    # Ensure Alembic plugin is loaded
    if not cmds.pluginInfo("AbcExport", loaded=True, query=True):
        cmds.loadPlugin("AbcExport.mll")

    # Get selection with error handling
    selected_nodes = cmds.ls(sl=True, flatten=True)
    if not selected_nodes:
        cmds.warning("No objects selected for Alembic export")
        raise RuntimeError("Export failed: No selection")

    # Create output directory if needed
    output_dir = os.path.dirname(path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Build roots parameter
    roots = " ".join([f"-root {node}" for node in selected_nodes])

    # Build export command with recommended settings
    command = (
        f"-frameRange {start_frame} {end_frame} "
        "-uvWrite -worldSpace -writeFaceSets "
        "-dataFormat ogawa "  # Binary format is more efficient
        f"{roots} "
        f"-file {path}"
    )

    # Execute export
    try:
        cmds.AbcExport(j=command)
        cmds.inViewMessage(
            msg=f"Exported Alembic to: {path}",
            pos="topLeft",
            fade=True
        )
    except Exception as e:
        cmds.error(f"Alembic export failed: {str(e)}")
        raise

def get_command():
    """Return the command implementation."""
    def _command():
        importlib.reload(sys.modules[__name__])
        exportABC()
    return _command

def execute():
    """Execute the command with reloading."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()
