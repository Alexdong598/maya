# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.api.OpenMaya as om
import importlib
import sys

def get_dominant_material_via_api(shape_path):
    """
    使用 API 计算 Shape 上占比最大的材质。
    只返回最强的那个 SG 名字，不再关心比例是否够高。
    """
    try:
        sel_list = om.MSelectionList()
        sel_list.add(shape_path)
        dag_path = sel_list.getDagPath(0)
        mesh_fn = om.MFnMesh(dag_path)
        
        shaders, face_indices = mesh_fn.getConnectedShaders(dag_path.instanceNumber())
        
        if not shaders: return None
            
        if len(face_indices) == 0: return None

        # 统计每个 shader 的面数
        counts = {}
        for s_idx in face_indices:
            if s_idx != -1:
                counts[s_idx] = counts.get(s_idx, 0) + 1
        
        if not counts: return None

        # 找出最大值
        best_sg_obj = None
        max_count = -1
        
        for s_idx, count in counts.items():
            if count > max_count:
                max_count = count
                if s_idx < len(shaders):
                    best_sg_obj = shaders[s_idx]
        
        if best_sg_obj:
            return om.MFnDependencyNode(best_sg_obj).name()
            
    except Exception as e:
        print(f"[API Error] {shape_path}: {e}")
        return None
    
    return None

def force_unify_pipeline_materials():
    """
    Pipeline 强制合规脚本。
    不接受多维材质。所有 Mesh 强制统一为面数最多的材质，并指认给 Transform。
    """
    selection = cmds.ls(sl=True, long=True)
    if not selection:
        cmds.warning("请选择资产顶层组！")
        return

    print(f"\n{'='*20} PIPELINE FORCE UNIFY START {'='*20}")
    
    all_shapes = cmds.listRelatives(selection, allDescendents=True, type='mesh', fullPath=True) or []
    all_shapes.extend(cmds.ls(selection, type='mesh', long=True))
    all_shapes = list(set(all_shapes))
    
    fixed_count = 0
    
    for shape in all_shapes:
        if cmds.getAttr(f"{shape}.intermediateObject"):
            continue

        parent = cmds.listRelatives(shape, parent=True, fullPath=True)
        if not parent: continue
        xform = parent[0]
        short_name = xform.split('|')[-1]

        # 1. 检查是否有材质连接 (只要有连接，不管是Shape还是Face，都要处理)
        connections = cmds.listConnections(shape, type='shadingEngine') or []
        connections += (cmds.listConnections(f"{shape}.instObjGroups", type='shadingEngine') or [])
        connections += (cmds.listConnections(f"{shape}.instObjGroups.objectGroups", type='shadingEngine') or [])
        
        if not connections:
            continue

        # 2. 找出“胜者”材质
        target_sg = get_dominant_material_via_api(shape)
        
        if target_sg:
            try:
                # 3. 【关键步骤】物理切断所有面级连接 (GeomSubset 根源)
                # 即使 Maya sets() 命令有时会自动断开，但显式切断是最安全的
                plugs = cmds.listConnections(f"{shape}.instObjGroups[0].objectGroups", plugs=True, c=True) or []
                if plugs:
                    # print(f"  - Cleaning sub-face connections on {short_name}...")
                    for i in range(0, len(plugs), 2):
                        try:
                            cmds.disconnectAttr(plugs[i], plugs[i+1])
                        except:
                            pass
                
                # 4. 强制指认给 Transform
                # 这会覆盖掉 Mesh 上的一切，只保留这一个材质
                cmds.sets(xform, forceElement=target_sg)
                
                # print(f"[UNIFIED] {short_name} -> {target_sg}")
                fixed_count += 1
                
            except Exception as e:
                print(f"[FAIL] {short_name}: {e}")

    cmds.select(selection, r=True)
    print(f"\n{'='*20} DONE {'='*20}")
    
    if fixed_count > 0:
        cmds.inViewMessage(msg=f"Pipeline 合规化完成！\n强制统一了 {fixed_count} 个对象。", pos="topCenter", fade=True)
        print(f"Pipeline 合规化完成。强制统一了 {fixed_count} 个对象。")
        print("注意：如果对象原本包含设计好的多维材质，次要材质已被移除。")
    else:
        print("未发现需要修复的对象 (可能已经是合规状态)。")

# 运行
def get_command():
    """Return the current implementation of the command."""
    def _command():
        force_unify_pipeline_materials()
    return _command

def execute():
    """Execute the command with reloading."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()