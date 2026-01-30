"""Command to mirror selected joints in Maya with 2024 optimized settings."""
import maya.cmds as cmds
import importlib
import sys

def get_command():
    """Return the current implementation of the command."""
    def _command():
        """Mirror selected joints (L→R) with 2024 optimized settings."""
        try:
            selected = cmds.ls(selection=True, type="joint")
            if not selected:
                raise RuntimeError("No joints selected")
            
            cmds.mirrorJoint(
                mirrorXY=False, 
                mirrorYZ=True,
                searchReplace=("L_", "R_"),
                mirrorBehavior=True
            )
            cmds.select(clear=True)
        except Exception as e:
            cmds.warning(f"Mirror Failed: {str(e)}")
    return _command

def execute():
    """Execute the command with reloading."""
    # Reload module to get latest implementation
    importlib.reload(sys.modules[__name__])
    # Get fresh command implementation
    cmd = get_command()
    # Execute it
    cmd()
