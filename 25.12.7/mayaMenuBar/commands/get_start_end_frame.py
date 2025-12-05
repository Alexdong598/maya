"""Command to set Maya playback range from ShotGrid frame data."""
import maya.cmds as cmds
import importlib
import sys

def get_command():
    def _command():
        try:
            from ..utils.SGlogin import ShotgunDataManager
            sg_manager = ShotgunDataManager()
            SHOTID = int(sg_manager.HAL_SHOT_SGID)
            frame_data = sg_manager.getSGData("Shot", SHOTID)
            
            # Initialize with None
            startFrame = None
            endFrame = None
            
            # Get frame data from ShotGrid
            sg_head_in = frame_data[0].get('sg_head_in')
            sg_tail_out = frame_data[0].get('sg_tail_out')
            sg_cut_in = frame_data[0].get('sg_cut_in')
            sg_cut_out = frame_data[0].get('sg_cut_out')

            # Set start frame (head_in with cut_in-8 fallback)
            if sg_head_in is not None:
                startFrame = sg_head_in
            elif sg_cut_in is not None:
                startFrame = sg_cut_in - 8
            else:
                cmds.warning("No valid start frame data found in ShotGrid")

            # Set end frame (tail_out with cut_out+8 fallback)
            if sg_tail_out is not None:
                endFrame = sg_tail_out
            elif sg_cut_out is not None:
                endFrame = sg_cut_out + 8
            else:
                cmds.warning("No valid end frame data found in ShotGrid")

            # Only set playback range if we have valid frame values
            if startFrame is not None and endFrame is not None:
                cmds.playbackOptions(minTime=startFrame)
                cmds.playbackOptions(maxTime=endFrame)
                cmds.playbackOptions(animationStartTime=startFrame)
                cmds.playbackOptions(animationEndTime=endFrame)
            else:
                cmds.warning("Could not set playback range - missing frame data")

        except Exception as e:
            cmds.warning(f"Get_Start_End_Frame Failed: {str(e)}")
    return _command

def execute():
    # Reload module to get latest implementation
    importlib.reload(sys.modules[__name__])
    # Get fresh command implementation
    cmd = get_command()
    # Execute it
    cmd()
