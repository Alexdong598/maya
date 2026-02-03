import maya.cmds as cmds
import math
import importlib
import sys

def get_command():
    """Return command implementation"""
    def _command():
        importlib.reload(sys.modules[__name__])
        frame_all_top_level_objects_in_maya()
    return _command

def execute():
    """Execute with reloading"""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

def frame_all_top_level_objects_in_maya(spin_offset=0, pitch_offset=0):
    """
    Creates a camera in Maya and frames all top-level objects with meshes in the scene.
    The camera is positioned based on the combined bounding box of these objects, with
    user-defined spin and pitch offsets. The distance from the camera to the objects
    is set to 1.5 times the distance calculated by viewFit.

    Args:
        spin_offset (float): Additional rotation around the Y-axis (spin) for the camera's
                             viewpoint relative to the objects' center. Default is 0.
        pitch_offset (float): Additional rotation around the X-axis (pitch) for the camera's
                              viewpoint relative to the objects' center. Default is 0.

    Returns:
        str: Name of the created camera transform node
    """
    # Create default camera even if no objects found
    default_cam = cmds.camera(name="defaultFramedCamera")[0]
    
    try:
        # Get all top-level transforms that have at least one mesh in their hierarchy
        top_level_objects = [
            obj for obj in cmds.ls(assemblies=True, type='transform')
            if cmds.listRelatives(obj, allDescendents=True, type='mesh')
        ]
        
        # Check if there are any qualifying objects
        if not top_level_objects:
            cmds.warning("No top-level objects with meshes found in the scene.")
            return default_cam
        
        # Calculate the combined bounding box of all top-level objects
        bbox = cmds.exactWorldBoundingBox(top_level_objects)
        
        # Calculate the center of the combined bounding box
        center_x = (bbox[0] + bbox[3]) / 2.0
        center_y = (bbox[1] + bbox[4]) / 2.0
        center_z = (bbox[2] + bbox[5]) / 2.0
        object_center = (center_x, center_y, center_z)
        
        # Create a new camera
        camera_transform, camera_shape = cmds.camera(name="framedCamera_#")
        
        # Create a temporary rig to position and orient the camera
        temp_rig = cmds.group(empty=True, name=f"{camera_transform}_rig_temp")
        cmds.xform(temp_rig, worldSpace=True, translation=object_center)
        
        # Parent the camera to the rig
        cmds.parent(camera_transform, temp_rig)
        
        # Apply rotations to the rig (default pitch=5, spin=-35, adjusted by offsets)
        final_rig_rotate_x = 5 + pitch_offset
        final_rig_rotate_y = -35 + spin_offset
        cmds.xform(temp_rig, rotation=(final_rig_rotate_x, final_rig_rotate_y, 0), worldSpace=False)
        
        # Unparent the camera and delete the rig
        cmds.parent(camera_transform, world=True)
        cmds.delete(temp_rig)
        
        # Frame all top-level objects in the camera view
        cmds.viewFit(camera_transform, top_level_objects, fitFactor=1.1)
        
        # Get the current camera position
        cam_pos = cmds.xform(camera_transform, query=True, translation=True, worldSpace=True)
        
        # Calculate the current distance from the camera to the center
        current_distance = math.sqrt(
            (cam_pos[0] - object_center[0])**2 +
            (cam_pos[1] - object_center[1])**2 +
            (cam_pos[2] - object_center[2])**2
        )
        
        # Move the camera along its local +Z axis to increase distance to 1.5 times
        cmds.move(0, 0, 0.2 * current_distance, camera_transform, relative=True, objectSpace=True)
        
        # Get the new camera position
        new_cam_pos = cmds.xform(camera_transform, query=True, translation=True, worldSpace=True)
        
        # Calculate the new distance
        new_distance = math.sqrt(
            (new_cam_pos[0] - object_center[0])**2 +
            (new_cam_pos[1] - object_center[1])**2 +
            (new_cam_pos[2] - object_center[2])**2
        )
        
        # Update the center of interest
        cmds.setAttr(camera_shape + ".centerOfInterest", new_distance)
        
        # Set the viewport to look through the camera
        cmds.lookThru(camera_transform)
        
        # Select the camera
        cmds.select(camera_transform)
        
        # Display a confirmation message
        cmds.inViewMessage(
            bgc=[0, 0.5, 0],
            message='<h1 style="color:white; font-size:18px;">Camera Created and Framed!</h1>',
            pos='midCenter',
            fade=True
        )
        
        # Ensure consistent camera naming (Maya may append numbers)
        camera_transform = cmds.rename(camera_transform, "defaultFramedCamera")
        return camera_transform  # Returns the actual name Maya created (e.g. "defaultFramedCamera1")
    except Exception as e:
        cmds.warning(f"Error creating camera: {str(e)}. Using default camera.")
        return default_cam

if __name__ == "__main__":
    execute()
