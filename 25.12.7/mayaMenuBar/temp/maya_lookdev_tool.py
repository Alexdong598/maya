import maya.cmds as cmds
import os
import math

def calculate_framing_distance(camera_shape_name, object_name):
    """
    根据一个指定的相机形状节点(camera shape)的FOV和物体的边界框，
    计算能完整容纳该物体的最小相机距离。
    """
    # 这个辅助函数保持不变
    print("\n--- Debug: Calculating Framing Distance ---")
    try:
        if not cmds.objExists(camera_shape_name) or cmds.nodeType(camera_shape_name) != 'camera':
            cmds.warning(f"Fatal Error: '{camera_shape_name}' is not a valid camera shape node.")
            return None
        
        fov_h_deg = cmds.camera(camera_shape_name, query=True, horizontalFieldOfView=True)
        fov_v_deg = cmds.camera(camera_shape_name, query=True, verticalFieldOfView=True)
        fov_h_rad = math.radians(fov_h_deg)
        fov_v_rad = math.radians(fov_v_deg)
        bbox = cmds.xform(object_name, query=True, boundingBox=True, worldSpace=True)
        obj_width = bbox[3] - bbox[0]
        obj_height = bbox[4] - bbox[1]

        if obj_width == 0 and obj_height == 0: return 0.0
        dist_for_width = (obj_width / 2.0) / math.tan(fov_h_rad / 2.0) if fov_h_rad > 0 else float('inf')
        dist_for_height = (obj_height / 2.0) / math.tan(fov_v_rad / 2.0) if fov_v_rad > 0 else float('inf')
        
        fit_distance = max(dist_for_width, dist_for_height)
        final_distance = fit_distance * 1.1
        
        print(f"  - Calculated distance to fit '{object_name}': {final_distance:.4f}")
        print("--- End Debug ---")
        return final_distance
        
    except Exception as e:
        cmds.warning(f"An unexpected error occurred in calculation: {e}")
        print("--- End Debug ---")
        return None

def analyze_lookdev_setup():
    """
    主函数，执行完整的场景分析和设置流程，不包含对相机绑定的整体缩放。
    """
    # --- 1. 获取 "True Obj" 并进行所有初始测量 ---
    selection = cmds.ls(selection=True, type='transform')
    if len(selection) != 1:
        cmds.warning("请只选择一个作为 'true obj' 的几何体。")
        return
    true_obj_name = selection[0]
    
    true_obj_bbox = cmds.xform(true_obj_name, query=True, boundingBox=True, worldSpace=True)
    true_obj_height = true_obj_bbox[4] - true_obj_bbox[1]
    
    print("--- True Object Analysis ---")
    print(f"True Obj: {true_obj_name}")
    print(f"True Obj Original Height (Y): {true_obj_height:.4f}")
    print("-" * 25)

    # --- 2. 导入参考场景 ---
    reference_file = "U:/_lookdev/maya/antares_image_lookdev_v03.mb"
    if not os.path.exists(reference_file):
        cmds.warning(f"参考文件未找到: {reference_file}")
        return

    try:
        cmds.file(reference_file, i=True, type="mayaBinary", ignoreVersion=True, mergeNamespacesOnClash=False, namespace=":")
        print(f"成功导入参考场景: {reference_file}")
    except Exception as e:
        cmds.error(f"导入时发生错误: {e}")
        return

    # --- 3. 定义关键节点名称 ---
    controller_name = 'turntableControl'
    camera_transform_name = 'turntableControl'
    camera_shape_name = 'cam_tntblShape'
    reference_obj_name = 'ASSET_ANIM'
    panel_name = 'perspView'

    # --- 4. 在场景变换前，进行所有必要的计算 ---
    print("\n--- Pre-computation Step ---")
    
    # a) 计算精确的相机拉远距离
    new_cam_pull = calculate_framing_distance(camera_shape_name, true_obj_name)
    if new_cam_pull is None: return
    
    # b) 计算要设置的 cam_heightsh 值
    new_cam_height = true_obj_height / 2.0
    print(f"  - Calculated value for 'cam_heightsh': {new_cam_height:.4f}")

    # --- 5. 应用所有变换和属性设置 ---
    print("\n--- Applying All Transformations ---")
    
    # a) 设置相机视角
    cmds.lookThru(panel_name, camera_transform_name, nc=0.1, fc=100)
    print(f"- Set panel '{panel_name}' to view through '{camera_transform_name}'.")

    # b) 设置 cam_heightsh 属性
    if cmds.attributeQuery('cam_height', node=controller_name, exists=True):
        cmds.setAttr(f'{controller_name}.cam_height', new_cam_height)
        print(f"- Set '{controller_name}.cam_height' to: {new_cam_height:.4f}")
    else:
        cmds.warning(f"控制器 '{controller_name}' 没有 'cam_height' 属性。")

    # c) 隐藏参考物体子物体
    if cmds.objExists(reference_obj_name):
        ref_children = cmds.listRelatives(reference_obj_name, children=True, type='transform') or []
        for child in ref_children:
            cmds.setAttr(f'{child}.visibility', 0)
        if ref_children:
            print(f"- Hid {len(ref_children)} children of '{reference_obj_name}'.")

        # d) 设置父子关系
        cmds.parent(true_obj_name, reference_obj_name)
        print(f"- Parented '{true_obj_name}' under '{reference_obj_name}'.")
    else:
        cmds.warning(f"参考物体 '{reference_obj_name}' 未找到，跳过隐藏和父子关联步骤。")

    # e) 应用预先计算好的相机拉远距离
    if cmds.attributeQuery('cam_pull', node=controller_name, exists=True):
        cmds.setAttr(f'{controller_name}.cam_pull', new_cam_pull)
        print(f"- Set '{controller_name}.cam_pull' to pre-calculated distance: {new_cam_pull:.4f}")
    else:
        cmds.warning(f"控制器 '{controller_name}' 没有 'cam_pull' 属性。")
# --- 使用方法 ---
# 1. 在Maya中，选择你想要进行lookdev的那个物体。
# 2. 运行此脚本。
analyze_lookdev_setup()