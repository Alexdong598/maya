# -*- coding: utf-8 -*-
from pxr import Usd, UsdGeom, Sdf, Vt

def fix_arnold_usd_structure(usd_path):
    """
    正面修复 Arnold USD 数据的结构性问题 (V3.1 最终稳定版)
    1. 移除 elementSize (修复 Houdini 数组步长误判) - 关键修复
    2. 修复索引越界 (修复 Crash)
    3. 强制类型转换 (修复 Python 属性访问报错)
    """
    print(f"\n[Cleaner] >>> START PROCESSING: {usd_path}")
    layer = Sdf.Layer.FindOrOpen(usd_path)
    if not layer:
        print(f"[Cleaner] !!! Error: Failed to open layer: {usd_path}")
        return

    stage = Usd.Stage.Open(layer)
    has_changes = False
    
    # 开启 Sdf 修改块
    with Sdf.ChangeBlock():
        for prim in stage.Traverse():
            if not prim.IsA(UsdGeom.Mesh):
                continue
            
            mesh_prim = prim
            prim_path = prim.GetPath()
            
            # 获取底层 Spec 对象
            prim_spec = layer.GetPrimAtPath(prim_path)
            if not prim_spec:
                continue

            # =========================================================
            # 1. 强力修复 UV (st)
            # =========================================================
            st_attr_name = "primvars:st"
            st_attr = mesh_prim.GetAttribute(st_attr_name)
            
            if st_attr.IsValid():
                # A. 强制修正插值
                if st_attr.GetMetadata("interpolation") != UsdGeom.Tokens.faceVarying:
                    st_attr.SetMetadata("interpolation", UsdGeom.Tokens.faceVarying)
                    has_changes = True

                # B. 【关键】删除 elementSize 元数据
                if st_attr.HasMetadata("elementSize"):
                    st_attr.ClearMetadata("elementSize")
                    print(f"  [FIX] Cleared elementSize on {prim_path}.st")
                    has_changes = True

                # C. 【关键修正】强制类型转换为 TexCoord2fArray
                # 使用 attributes[] 而不是 properties[] 以获取 AttributeSpec (可写)
                if st_attr_name in prim_spec.attributes:
                    attr_spec = prim_spec.attributes[st_attr_name]
                    try:
                        # 只有 AttributeSpec 才有 typeName 属性
                        if attr_spec.typeName != Sdf.ValueTypeNames.TexCoord2fArray:
                            attr_spec.typeName = Sdf.ValueTypeNames.TexCoord2fArray
                            # print(f"  [FIX] Cast {prim_path}.st to TexCoord2fArray")
                            has_changes = True
                    except Exception as e:
                        print(f"  [WARN] Could not cast type for {st_attr_name}: {e}")
                
                # D. 索引越界检查
                st_indices_attr = mesh_prim.GetAttribute("primvars:st:indices")
                if st_indices_attr.IsValid():
                    values = st_attr.Get()
                    indices = st_indices_attr.Get()
                    if values and indices:
                        num_values = len(values)
                        max_sample = 0
                        try: max_sample = max(indices)
                        except: pass
                        
                        if max_sample >= num_values:
                            print(f"  [FIX] FOUND BAD ST INDICES on {prim_path}")
                            new_indices = [0 if (i >= num_values or i < 0) else i for i in indices]
                            st_indices_attr.Set(new_indices)
                            has_changes = True

            # =========================================================
            # 2. 强力修复 Normals
            # =========================================================
            n_attr_name = "primvars:normals"
            n_attr = mesh_prim.GetAttribute(n_attr_name)
            
            if n_attr.IsValid():
                if n_attr.GetMetadata("interpolation") != UsdGeom.Tokens.faceVarying:
                    n_attr.SetMetadata("interpolation", UsdGeom.Tokens.faceVarying)
                    has_changes = True
                
                if n_attr.HasMetadata("elementSize"):
                    n_attr.ClearMetadata("elementSize")
                    print(f"  [FIX] Cleared elementSize on {prim_path}.normals")
                    has_changes = True

                # 类型转换 (使用 attributes 字典)
                if n_attr_name in prim_spec.attributes:
                    attr_spec = prim_spec.attributes[n_attr_name]
                    try:
                        if attr_spec.typeName != Sdf.ValueTypeNames.Normal3fArray:
                            attr_spec.typeName = Sdf.ValueTypeNames.Normal3fArray
                            has_changes = True
                    except: pass

                # 索引检查
                n_indices_attr = mesh_prim.GetAttribute("primvars:normals:indices")
                if n_indices_attr.IsValid():
                    values = n_attr.Get()
                    indices = n_indices_attr.Get()
                    if values and indices:
                        num_values = len(values)
                        max_sample = 0
                        try: max_sample = max(indices)
                        except: pass
                        
                        if max_sample >= num_values:
                            print(f"  [FIX] FOUND BAD NORMAL INDICES on {prim_path}")
                            new_indices = [0 if (i >= num_values or i < 0) else i for i in indices]
                            n_indices_attr.Set(new_indices)
                            has_changes = True

            # =========================================================
            # 3. 彻底抹杀 arnold:id
            # =========================================================
            # 必须从 Spec 层面移除
            keys_to_kill = []
            for name in prim_spec.properties.keys():
                if "arnold:id" in name:
                    keys_to_kill.append(name)
                # StringArray -> TokenArray (内存优化)
                elif name.startswith("primvars:arnold:"):
                    # 尝试转换类型
                    if name in prim_spec.attributes:
                        attr_spec = prim_spec.attributes[name]
                        if attr_spec.typeName == Sdf.ValueTypeNames.StringArray:
                            try:
                                vals = mesh_prim.GetAttribute(name).Get()
                                if vals:
                                    attr_spec.typeName = Sdf.ValueTypeNames.TokenArray
                                    attr_spec.default = Vt.TokenArray([str(v) for v in vals])
                            except: pass
            
            for key in keys_to_kill:
                if key in prim_spec.properties:
                    del prim_spec.properties[key]
                    has_changes = True

    if has_changes:
        layer.Save()
        print(f"[Cleaner] >>> FIXED METADATA/TYPES AND SAVED: {usd_path}\n")
    else:
        print(f"[Cleaner] >>> No structural issues found: {usd_path}\n")