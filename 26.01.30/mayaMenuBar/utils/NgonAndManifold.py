import maya.cmds as cmds
import maya.OpenMaya as om
import importlib
import sys
from pymel.core import *

def check_ngon_and_manifold(selection=None):
    """Check for ngons and non-manifold geometry in hierarchy"""
    sel = selection if selection else ls(sl=1, fl=1)
    if not sel:
        warning("Please select objects to check")
        return
        
    # Get all mesh descendants
    meshes = []
    for obj in sel:
        if obj.type() == 'transform':
            meshes.extend(listRelatives(obj, allDescendents=True, type='mesh', fullPath=True) or [])
    
    if not meshes:
        warning("No mesh objects found in selection")
        return
    
    problem_meshes = {}
    problem_faces = []
    
    for mesh in meshes:
        mesh_name = str(mesh)
        # Check for ngons (faces with >4 sides)
        all_faces = cmds.polyListComponentConversion(mesh_name, toFace=True)
        all_faces = cmds.filterExpand(all_faces, selectionMask=34)  # 34 = polygon faces
        ngon_faces = []
        
        for face in all_faces:
            # Get vertex count for this face
            verts = cmds.polyInfo(face, faceToVertex=True)[0].split()[2:]
            if len(verts) > 4:
                ngon_faces.append(face)
                
        if ngon_faces:
            problem_faces.extend(ngon_faces)
            problem_meshes.setdefault(mesh_name, []).append(f"{len(ngon_faces)} ngon faces")
            
        # Check for non-manifold geometry
        non_manifold = cmds.polyInfo(mesh_name, nonManifoldEdges=True) or []
        if non_manifold:
            problem_faces.extend(non_manifold)
            problem_meshes.setdefault(mesh_name, []).append("non-manifold geometry")

    # Build results message
    message = "Ngon and Manifold Check Results:\n\n"
    if problem_meshes:
        for mesh, issues in problem_meshes.items():
            message += f"{mesh}:\n  - " + "\n  - ".join(issues) + "\n"
    else:
        message += "✅ No ngons or non-manifold geometry found"

    # Show results dialog
    confirmDialog(
        title="Ngon & Manifold Check",
        message=message,
        button=["OK"],
        defaultButton="OK"
    )
    
    # Select problematic faces
    if problem_faces:
        select(problem_faces, r=1)
    return problem_faces

def get_command():
    """Return command implementation"""
    def _command():
        check_ngon_and_manifold()
    return _command

def execute():
    """Execute with reloading"""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    execute()
