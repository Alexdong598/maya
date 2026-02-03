# -*- coding: utf-8 -*-
import os
import sys
import importlib
import subprocess
import shutil
import json
import concurrent.futures
import tempfile
import glob
import re
import time

import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMayaUI as omui

from PySide2 import QtWidgets, QtCore, QtUiTools
from PySide2.QtWidgets import QMainWindow, QMessageBox, QWidget
from shiboken2 import wrapInstance

try:
    import arnold
except ImportError:
    pass

# Try importing USD libraries
try:
    from pxr import Usd, UsdGeom, UsdShade, Sdf, Ar, Kind, Vt, Tf
    USD_AVAILABLE = True
except ImportError:
    USD_AVAILABLE = False
    print("[WARN] pxr USD libraries not found. USD export will fail.")

# Import your Utils
from ..utils import camThumbnail
from ..utils.SGlogin import ShotgunDataManager

# ==============================================================================
# 0. CORE UTILS & CLEANER
# ==============================================================================
def getMayaVersion():
    maya_version = cmds.about(version=True)
    if "." in maya_version:
        maya_version = maya_version.split(".")[0]
    return maya_version

def _ensure_plugins():
    if not cmds.pluginInfo("mtoa", q=True, loaded=True):
        try: cmds.loadPlugin("mtoa")
        except: print("[Error] Could not load mtoa")
    if not cmds.pluginInfo("mayaUsdPlugin", q=True, loaded=True):
        try: cmds.loadPlugin("mayaUsdPlugin")
        except: print("[Error] Could not load mayaUsdPlugin")
    global arnold
    try: import arnold
    except: pass

def _safe_rename(node, new_name):
    if not node or not cmds.objExists(node): return new_name
    try:
        new = cmds.rename(node, new_name)
        return cmds.ls(new, l=True)[0]
    except:
        found = cmds.ls(node, l=True)
        return found[0] if found else new_name

def _non_intermediate_mesh_shapes_under(root):
    shapes = cmds.listRelatives(root, ad=True, type='mesh', fullPath=True) or []
    out = []
    for s in shapes:
        try:
            if not cmds.getAttr(s + '.intermediateObject'): out.append(s)
        except: out.append(s)
    return out

def _unique_parents_of_shapes(shapes):
    parents = set()
    for s in shapes:
        p = cmds.listRelatives(s, parent=True, fullPath=True) or []
        if p: parents.add(p[0])
    return parents

def _reduce_with_cleanup(xform, percent):
    try:
        cmds.polyReduce(xform, ver=1, trm=0, p=float(percent), replaceOriginal=1, ch=1)
        cmds.polySoftEdge(xform, angle=180, ch=1)
        return True
    except RuntimeError:
        try:
            cmds.polyCleanup(xform, ch=False, nonManifoldGeometry=1, laminaFace=1, facesWithMoreThanFourSides=1)
            cmds.polyReduce(xform, ver=1, trm=0, p=float(percent), replaceOriginal=1, ch=1)
            cmds.polySoftEdge(xform, angle=180, ch=1)
            return True
        except: 
            return False

def _duplicate_and_reduce(src, suffix='_proxy', percent=50.0):
    dup = cmds.duplicate(src, rr=True)[0]
    dup = cmds.ls(dup, l=True)[0]
    
    # Rename shapes and transforms to avoid clashes
    mesh_shapes = _non_intermediate_mesh_shapes_under(dup)
    for x in sorted(_unique_parents_of_shapes(mesh_shapes), key=lambda p: p.count('|'), reverse=True):
        short = x.split('|')[-1]
        if not short.endswith(suffix): _safe_rename(x, short + suffix)
    for s in _non_intermediate_mesh_shapes_under(dup):
        short = s.split('|')[-1]
        if not short.endswith(suffix): _safe_rename(s, short + suffix)
        
    top_short = src.split('|')[-1]
    dup = _safe_rename(dup, f'{top_short}{suffix}')
    
    # Reduce
    for x in sorted(_unique_parents_of_shapes(_non_intermediate_mesh_shapes_under(dup)), key=lambda p: p.count('|')):
        _reduce_with_cleanup(x, percent)
    return dup

def get_rez_packages_from_maya():
    REZ_USED_RESOLVE = os.environ.get("REZ_USED_RESOLVE")
    packagesList = REZ_USED_RESOLVE.split(" ")
    allAddPkgs = []
    for package in packagesList:
        addPkg = f"+p {package}"
        allAddPkgs.append(addPkg)
    allPackagesList = " ".join(allAddPkgs)
    return allPackagesList

# -----------------------------------------------------------------------------
# USD CLEANER (Integrated from utils.usd_cleaner)
# -----------------------------------------------------------------------------
# ==============================================================================
# HELPERS: CLEANER & METADATA
# ==============================================================================

def _rename_nonmesh_parents_in_layer_with_sdf(usd_file, suffix='_proxy'):
    layer = Sdf.Layer.FindOrOpen(usd_file)
    if not layer: return

    stage = Usd.Stage.Open(layer)
    candidates = set()
    
    # 1. Identify Prim Paths to Rename
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            p = prim.GetParent()
            while p and p != stage.GetPseudoRoot():
                if not p.IsA(UsdGeom.Mesh):
                    nm = p.GetName()
                    if nm.endswith(suffix) and len(nm) > len(suffix):
                        candidates.add(p.GetPath().pathString)
                p = p.GetParent()
                
    if not candidates:
        layer.Save()
        return

    # 2. Sort longest paths first to avoid parent rename invalidating children
    paths = sorted(candidates, key=lambda s: s.count('/'), reverse=True)
    mapping = {} # Track renames to fix path strings dynamically

    def get_current_path(original_path_str):
        # Apply all previous renames to find where this prim lives now
        res = original_path_str
        for old, new in mapping.items():
            if res.startswith(old):
                res = res.replace(old, new, 1)
        return res

    with Sdf.ChangeBlock():
        for old_s in paths:
            current_s = get_current_path(old_s)
            cur = Sdf.Path(current_s)
            
            if layer.GetPrimAtPath(cur):
                parent_path = cur.GetParentPath()
                old_name = cur.name
                new_base = Tf.MakeValidIdentifier(old_name[:-len(suffix)]) or "renamed"
                
                # Check for collision in parent
                dst_path = parent_path.AppendChild(new_base)
                i = 1
                while layer.GetPrimAtPath(dst_path):
                    dst_path = parent_path.AppendChild(f"{new_base}_r{i}")
                    i += 1
                
                # Perform Rename
                edit = Sdf.BatchNamespaceEdit()
                edit.Add(cur, dst_path)
                if layer.Apply(edit):
                    mapping[current_s] = dst_path.pathString

    layer.Save()
    print(f"[Cleaner] Renamed {len(mapping)} proxy parents.")

def fix_arnold_usd_structure(usd_path):
    """
    Cleans Arnold-exported USDs to prevent Houdini crashes.
    Fixes UV/Normal interpolation, removes elementSize, and casts types.
    """
    print(f"\n[Cleaner] >>> PROCESSING: {usd_path}")
    layer = Sdf.Layer.FindOrOpen(usd_path)
    if not layer: return

    stage = Usd.Stage.Open(layer)
    has_changes = False
    
    with Sdf.ChangeBlock():
        for prim in stage.Traverse():
            if not prim.IsA(UsdGeom.Mesh): continue
            
            mesh_prim = prim
            prim_path = prim.GetPath()
            prim_spec = layer.GetPrimAtPath(prim_path)
            if not prim_spec: continue

            # 1. Fix UVs (st)
            st_attr = mesh_prim.GetAttribute("primvars:st")
            if st_attr.IsValid():
                if st_attr.GetMetadata("interpolation") != UsdGeom.Tokens.faceVarying:
                    st_attr.SetMetadata("interpolation", UsdGeom.Tokens.faceVarying)
                    has_changes = True
                if st_attr.HasMetadata("elementSize"):
                    st_attr.ClearMetadata("elementSize")
                    has_changes = True
                
                # FIX: Nuclear Type Casting (Delete & Recreate)
                attr_name = "primvars:st"
                if attr_name in prim_spec.attributes:
                    attr_path = prim_path.AppendProperty(attr_name)
                    attr_spec = layer.GetAttributeAtPath(attr_path)
                    
                    if attr_spec:
                        target_type = Sdf.ValueTypeNames.TexCoord2fArray
                        if str(attr_spec.typeName) != str(target_type):
                            # 1. Preserve existing data/metadata
                            default_val = attr_spec.default
                            metadata = {k: attr_spec.GetInfo(k) for k in attr_spec.ListInfoKeys()}
                            
                            # 2. Delete the old spec (Using RemoveProperty)
                            prim_spec.RemoveProperty(prim_spec.attributes[attr_name])
                            
                            # 3. Create new spec with correct type
                            new_attr = Sdf.AttributeSpec(prim_spec, attr_name, target_type)
                            
                            # 4. Restore data
                            if default_val is not None:
                                new_attr.default = default_val
                            
                            # Restore metadata (excluding typeName)
                            for k, v in metadata.items():
                                if k != "typeName":
                                    try: new_attr.SetInfo(k, v)
                                    except: pass
                                    
                            has_changes = True
                            print(f"   [FIX] Recreated {attr_name} as TexCoord2fArray")

            # 2. Fix Normals
            n_attr = mesh_prim.GetAttribute("primvars:normals")
            if n_attr.IsValid():
                if n_attr.GetMetadata("interpolation") != UsdGeom.Tokens.faceVarying:
                    n_attr.SetMetadata("interpolation", UsdGeom.Tokens.faceVarying)
                    has_changes = True
                if n_attr.HasMetadata("elementSize"):
                    n_attr.ClearMetadata("elementSize")
                    has_changes = True

            # 3. Kill Arnold IDs
            # Note: RemoveProperty expects a Spec object, not a string key
            keys_to_kill = [k for k in prim_spec.properties.keys() if "arnold:id" in k]
            for key in keys_to_kill:
                if key in prim_spec.properties:
                    # FIX: Use RemoveProperty with the spec object
                    prop_spec = prim_spec.properties[key]
                    prim_spec.RemoveProperty(prop_spec)
                    has_changes = True

            # 4. Set Purpose (Render vs Proxy)
            # FIX: Wrap prim in UsdGeom.Imageable to access purpose attribute
            imageable = UsdGeom.Imageable(mesh_prim)
            
            if mesh_prim.GetName().endswith("_proxy"):
                if imageable.GetPurposeAttr().Get() != UsdGeom.Tokens.proxy:
                    imageable.CreatePurposeAttr(UsdGeom.Tokens.proxy)
                    has_changes = True
            else:
                if imageable.GetPurposeAttr().Get() != UsdGeom.Tokens.render:
                    imageable.CreatePurposeAttr(UsdGeom.Tokens.render)
                    has_changes = True

    if has_changes:
        layer.Save()
        print(f"[Cleaner] >>> FIXED & SAVED: {usd_path}")
    else:
        print(f"[Cleaner] >>> Clean.")

def _inject_binding_metadata(stage, maya_root):
    """
    Queries Maya for material assignments and writes them into USD metadata.
    """
    print(f"   [Metadata] Injecting bindings from {maya_root}...")
    shape_to_mat = {} 
    
    # Map Maya Shapes to Material Names
    maya_meshes = cmds.listRelatives(maya_root, allDescendents=True, type='mesh', fullPath=True) or []
    for mesh in maya_meshes:
        ses = cmds.listConnections(mesh, type='shadingEngine')
        if ses:
            surfaces = cmds.listConnections(ses[0] + ".surfaceShader")
            if surfaces:
                mat_name = surfaces[0].split(":")[-1]
                short_name = mesh.split('|')[-1]
                # Strip 'Shape' suffix for matching
                clean_name = short_name[:-5] if short_name.endswith("Shape") else short_name
                shape_to_mat[clean_name] = mat_name

    # Write to USD
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            prim_name = prim.GetName()
            search_key = prim_name[:-5] if prim_name.endswith("Shape") else prim_name
            
            found_mat = shape_to_mat.get(search_key)
            if not found_mat:
                # Fuzzy fallback
                for key, mat in shape_to_mat.items():
                    if key in search_key or search_key in key:
                        found_mat = mat; break
            
            if found_mat:
                prim.SetCustomDataByKey("bindingMat", found_mat)

# ==============================================================================
# 1. TEXTURE PROCESSING (OIIO)
# ==============================================================================
class TextureLODProcessor:
    def __init__(self, max_workers=16):
        self.MAX_WORKERS = max_workers
        self.OIIO_TOOL = self._find_oiio_tool()
        self.LOD_SPECS = [
            {"suffix": "LOD2",  "scale": 2},
            {"suffix": "LOD4",  "scale": 4},
            {"suffix": "LOD10", "scale": 10}
        ]
        self._udim_token_re = re.compile(r"(<UDIM>|<udim>)", re.IGNORECASE)
        self._udim_number_re = re.compile(r"[._](1[0-9]{3})[._]") 

    def _find_oiio_tool(self):
        mtoa_path = os.environ.get("MTOA_PATH")
        if mtoa_path:
            ext = ".exe" if os.name == "nt" else ""
            candidate = os.path.join(mtoa_path, "bin", "oiiotool" + ext)
            if os.path.isfile(candidate): return candidate.replace("\\", "/")
        return shutil.which("hoiiotool") or shutil.which("oiiotool")

    def scan_scene_textures(self, maya_node):
        shapes = cmds.listRelatives(maya_node, shapes=True, fullPath=True) or []
        if not shapes and cmds.nodeType(maya_node) == 'transform':
             shapes = cmds.listRelatives(maya_node, allDescendents=True, type='mesh', fullPath=True) or []
        if not shapes: return []

        engines = cmds.listConnections(shapes, type='shadingEngine') or []
        shaders = cmds.listConnections(engines, type='aiStandardSurface') or [] 
        file_nodes = cmds.listConnections(shaders, type='file') or []
        ai_images = cmds.listConnections(shaders, type='aiImage') or []
        all_file_nodes = list(set(file_nodes + ai_images))
        
        unique_paths = set()
        for fn in all_file_nodes:
            path = ""
            if cmds.attributeQuery("fileTextureName", node=fn, exists=True):
                path = cmds.getAttr(f"{fn}.fileTextureName")
            elif cmds.attributeQuery("filename", node=fn, exists=True):
                path = cmds.getAttr(f"{fn}.filename")
            
            if path:
                path = path.replace("\\", "/")
                # Abstract UDIMs
                if self._udim_token_re.search(path):
                    unique_paths.add(path)
                else:
                    m = self._udim_number_re.search(os.path.basename(path))
                    if m:
                        concrete_udim = m.group(1)
                        abstract_path = path.replace(concrete_udim, "<UDIM>")
                        unique_paths.add(abstract_path)
                    else:
                        unique_paths.add(path)
        return list(unique_paths)

    def _expand_udim_tiles(self, pattern):
        pattern = os.path.normpath(pattern)

        if self._udim_token_re.search(pattern):
            glob_pat = self._udim_token_re.sub("[0-9][0-9][0-9][0-9]", pattern)
            hits = glob.glob(glob_pat)
        else:
            if os.path.exists(pattern):
                hits = [pattern]
            else:
                hits = glob.glob(pattern)

        tiles = {} 
        for p in hits:
            p = os.path.normpath(p).replace("\\", "/")
            
            m = re.search(r"(1\d{3})", os.path.basename(p))
            if m:
                udim_id = int(m.group(1))
            else:
                udim_id = 1001 
            
            tiles[udim_id] = p
            
        return tiles

    def get_dst_path(self, src, lod):
        src = src.replace("\\", "/")
        parts = src.split("/")
        idx = -1
        for i, seg in enumerate(parts):
            if seg.lower() == "export": 
                idx = i; break

        if idx != -1:
            if idx + 1 < len(parts) - 1: parts.insert(idx + 2, lod)
            else: parts.insert(idx + 1, lod)
        else:
            parts.insert(-1, lod)
            
        new_path = "/".join(parts)
        d, n = os.path.split(new_path)
        suffix = f"_{lod}"
        
        m = self._udim_token_re.search(n)
        if m:
            span = m.span()
            prefix = n[:span[0]]
            rest = n[span[0]:]
            if prefix.endswith('.') or prefix.endswith('_'):
                sep = prefix[-1]; prefix = prefix[:-1]
                n = f"{prefix}{suffix}{sep}{rest}"
            else:
                n = f"{prefix}{suffix}{rest}"
        else:
            stem, ext = os.path.splitext(n)
            if not stem.endswith(suffix): n = f"{stem}{suffix}{ext}"
                
        return os.path.join(d, n).replace("\\", "/")

    def _convert_single_file(self, src, dst, scale):
        if os.path.exists(dst) and os.path.getsize(dst) > 0: return True, "Skipped"
        try: os.makedirs(os.path.dirname(dst), exist_ok=True)
        except OSError: pass
        
        pct = int(100.0 / scale)
        cmd = [self.OIIO_TOOL, src, "--resize", f"{pct}%", "-o", dst]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        try:
            subprocess.run(cmd, check=True, startupinfo=startupinfo, stderr=subprocess.PIPE)
            return True, "Processed"
        except Exception as e: return False, str(e)

    def convert_texture_task(self, src_path):
        if not self.OIIO_TOOL: return [(False, "No OIIO Tool")]
        results = []
        is_udim = bool(self._udim_token_re.search(src_path))
        
        if is_udim:
            tiles = self._expand_udim_tiles(src_path)
            if not tiles: return [(False, "No tiles found")]
            for spec in self.LOD_SPECS:
                dst_pattern = self.get_dst_path(src_path, spec['suffix'])
                for udim_id, tile_src in tiles.items():
                    tile_dst = self._udim_token_re.sub(str(udim_id), dst_pattern)
                    ok, msg = self._convert_single_file(tile_src, tile_dst, spec['scale'])
                    results.append((ok, msg))
        else:
            if not os.path.exists(src_path): return [(False, "Missing Source")]
            for spec in self.LOD_SPECS:
                dst = self.get_dst_path(src_path, spec['suffix'])
                ok, msg = self._convert_single_file(src_path, dst, spec['scale'])
                results.append((ok, msg))
        return results

    def run_local(self, texture_list):
        if not texture_list: return
        print(f"--- [TextureLOD] Processing {len(texture_list)} paths ---")
        if not self.OIIO_TOOL: return
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {executor.submit(self.convert_texture_task, p): p for p in texture_list}
            for future in concurrent.futures.as_completed(futures):
                try: future.result()
                except: pass

# ==============================================================================
# 2. USD MANAGERS & EXPORTERS
# ==============================================================================

def arnold_usd_mask(shaderOrNot=True):
    import arnold
    
    mask = arnold.AI_NODE_SHAPE    
    if shaderOrNot:
        mask |= arnold.AI_NODE_SHADER
        mask |= arnold.AI_NODE_COLOR_MANAGER
    return mask

def _inject_binding_metadata(stage, maya_root):
    """ Inject Material Binding Data from Maya into USD customData """
    print(f"   [Metadata] Injecting Material Binding Data from {maya_root}...")
    shape_to_mat = {} 
    maya_meshes = cmds.listRelatives(maya_root, allDescendents=True, type='mesh', fullPath=True) or []
    
    for mesh in maya_meshes:
        ses = cmds.listConnections(mesh, type='shadingEngine')
        if ses:
            surfaces = cmds.listConnections(ses[0] + ".surfaceShader")
            if surfaces:
                mat_name = surfaces[0].split(":")[-1]
                short_name = mesh.split('|')[-1]
                clean_name = short_name[:-5] if short_name.endswith("Shape") else short_name
                shape_to_mat[clean_name] = mat_name

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            prim_name = prim.GetName()
            search_key = prim_name[:-5] if prim_name.endswith("Shape") else prim_name
            found_mat = shape_to_mat.get(search_key)
            
            if not found_mat:
                # Fuzzy Search
                for key, mat in shape_to_mat.items():
                    if key in search_key or search_key in key:
                        found_mat = mat; break
            
            if found_mat:
                prim.SetCustomDataByKey("bindingMat", found_mat)

class TextureLODManager:
    def __init__(self, stage_or_path, lod_level=0, dry_run=False, strict_udim=True):
        self.lod_level = int(lod_level)
        self.dry_run = dry_run
        self.strict_udim = strict_udim
        
        if isinstance(stage_or_path, str): self.stage = Usd.Stage.Open(stage_or_path)
        else: self.stage = stage_or_path
        self._udim_re = re.compile(r"(<UDIM>)", re.IGNORECASE)

    def process(self):
        if not self.stage: return
        target_label = "ORIGINAL (LOD0)" if self.lod_level == 0 else f"LOD{self.lod_level}"
        print(f"=== Switch LOD: {target_label} ===")
        
        for prim in self.stage.Traverse():
            if not prim.IsA(UsdShade.Shader): continue
            
            # Find inputs
            target_attrs = ['inputs:filename', 'inputs:file', 'inputs:image']
            for attr_name in target_attrs:
                attr = prim.GetAttribute(attr_name)
                if not attr: continue
                
                raw_val = attr.Get()
                if not raw_val: continue
                current_path = raw_val.path if isinstance(raw_val, Sdf.AssetPath) else str(raw_val)
                current_path = current_path.replace(os.sep, "/")
                
                if self.lod_level == 0:
                    target_path = self._to_original_path(current_path)
                else:
                    target_path = self._to_lod_path(current_path, self.lod_level)
                
                if current_path != target_path:
                    attr.Set(Sdf.AssetPath(target_path))

    def _to_lod_path(self, path, level):
        directory = os.path.dirname(path)
        filename = os.path.basename(path)
        lod_dir_name = f"LOD{level}"
        new_directory = f"{directory}/{lod_dir_name}"
        suffix = f"_{lod_dir_name}"
        
        if self._udim_re.search(filename):
            parts = self._udim_re.split(filename)
            if len(parts) >= 3:
                prefix = parts[0]
                if not prefix.endswith(suffix) and not prefix.endswith(suffix + "."):
                    if prefix.endswith('.'): new_prefix = prefix[:-1] + suffix + "."
                    else: new_prefix = prefix + suffix
                    new_filename = new_prefix + "".join(parts[1:])
                else: new_filename = filename
            else: new_filename = filename
        else:
            name, ext = os.path.splitext(filename)
            if not name.endswith(suffix): new_filename = f"{name}{suffix}{ext}"
            else: new_filename = filename
        return f"{new_directory}/{new_filename}"

    def _to_original_path(self, path):
        new_path = re.sub(r"/LOD\d+/", "/", path)
        new_path = re.sub(r"_LOD\d+(?=\.|<)", "", new_path)
        return new_path

class LODVariantExporter:
    def _create_single_lod_usd(self, top_name, src, output_dir, variant_type, mask, lod_index, percent):
        if not os.path.isdir(output_dir): os.makedirs(output_dir)
            
        suffix_map = {"geoVariant": "geoLOD", "shdVariant": "shdLOD"}
        suffix = suffix_map.get(variant_type, "LOD")
        temp_node_name = f"{top_name}_{suffix}"
        
        filename = f"{variant_type}_{suffix}{lod_index}.usdc"
        lod_path = os.path.join(output_dir, filename).replace("\\", "/")

        # 1. Duplication
        lod_dup = cmds.duplicate(src, rr=True)[0]
        lod_dup = _safe_rename(lod_dup, temp_node_name)

        try:
            # 2. Reduction (Geo Only)
            if variant_type == "geoVariant":
                mesh_shapes = _non_intermediate_mesh_shapes_under(lod_dup)
                parents = sorted(_unique_parents_of_shapes(mesh_shapes), key=lambda p: p.count('|'))
                for p in parents: _reduce_with_cleanup(p, percent)

            # 3. Export
            cmds.select(lod_dup, r=True)
            cmds.arnoldExportAss(
                f=lod_path, selected=True, mask=mask, 
                lightLinks=False, shadowLinks=False, expandProcedurals=True
            )

            # 4. CLEAN & INJECT (Critical Step)
            fix_arnold_usd_structure(lod_path)
            
            if variant_type == "geoVariant":
                lyr = Sdf.Layer.FindOrOpen(lod_path)
                if lyr:
                    stg = Usd.Stage.Open(lyr)
                    _inject_binding_metadata(stg, lod_dup) # Read from Temp Node
                    stg.GetRootLayer().Save()

            # 5. Texture Swap (Shader Only)
            if variant_type == "shdVariant":
                print(f"   [TextureLOD] Switching {filename} to LOD {lod_index}...")
                manager = TextureLODManager(lod_path, lod_level=lod_index)
                manager.process()
                manager.stage.GetRootLayer().Save()

            # 6. Metadata
            lyr = Sdf.Layer.FindOrOpen(lod_path)
            if lyr:
                stage = Usd.Stage.Open(lyr)
                prim = stage.GetPrimAtPath(f"/{temp_node_name}")
                if prim: 
                    prim.SetCustomDataByKey("geo", top_name)
                    prim.SetCustomDataByKey("variantType", variant_type)
                    prim.SetCustomDataByKey("lodIndex", lod_index)
                lyr.Save()

        except Exception as e:
            print(f"[Error] Failed exporting {lod_path}: {e}")
            import traceback; traceback.print_exc()
        finally:
            if cmds.objExists(lod_dup): cmds.delete(lod_dup)
        
        return lod_path

    def task_export_single_lod(self, top_node, paths, variant_key, lod_index=1, percent=50.0, shaderOrNot=True):
        mask = arnold_usd_mask(shaderOrNot=shaderOrNot)
        dict_path_key = f"{variant_key}_dir"
        if dict_path_key not in paths: return None
        
        target_dir = paths[dict_path_key]
        print(f"--- Exporting LOD {lod_index} ({variant_key}) Reduce: {percent:.2f}%")
        
        return self._create_single_lod_usd(
            paths['top_name'], top_node, target_dir, 
            variant_key, mask, lod_index, percent
        )

# ==============================================================================
# 3. ASSEMBLY FUNCTIONS
# ==============================================================================
def referenceToVariantEditContext(variantSet, renderFile, geoFile, top_name, isLOD0=True, isShd=True):
    root_prim = variantSet.GetPrim()
    stage = root_prim.GetStage()
    
    with variantSet.GetVariantEditContext():
        rel_render = os.path.relpath(renderFile, os.path.dirname(geoFile)).replace("\\", "/")
        
        if isShd:
            mtl_scope_path = root_prim.GetPath().AppendChild("mtl")
            mtl_scope = stage.DefinePrim(mtl_scope_path, "Scope")            
            source_prim_path = Sdf.Path("/mtl")            
            mtl_scope.GetReferences().AddReference(rel_render, source_prim_path)
        else:
            if isLOD0:
                source_prim_path = Sdf.Path(f"/{top_name}")
                root_prim.GetReferences().AddReference(rel_render, source_prim_path)
            else:
                root_prim.GetReferences().AddReference(rel_render)

def clean_shader_file(dirty_path, clean_path):
    if not os.path.exists(dirty_path): return False    
    src_layer = Sdf.Layer.FindOrOpen(dirty_path)
    if not src_layer: return False
    
    dst_layer = Sdf.Layer.CreateNew(clean_path, args={'format':'usdc'})
    mtl_path = Sdf.Path("/mtl")
    mtl_prim_spec = Sdf.CreatePrimInLayer(dst_layer, mtl_path)
    mtl_prim_spec.specifier = Sdf.SpecifierDef
    mtl_prim_spec.typeName = "Scope"
    stage_tmp = Usd.Stage.Open(src_layer)
    
    materials_copied = 0
    for prim in stage_tmp.Traverse():
        if prim.IsA(UsdShade.Material):
            mat_name = prim.GetName()
            src_path = prim.GetPath()            
            dst_path = mtl_path.AppendChild(mat_name)            
            Sdf.CopySpec(src_layer, src_path, dst_layer, dst_path)
            materials_copied += 1
    dst_layer.Save()
    print(f"[CLEAN] Extracted {materials_copied} materials to {os.path.basename(clean_path)}")
    return True

def geoUsdExport(rootPrimPath, folderPath):
    rootPrimPathSdf = Sdf.Path(rootPrimPath)
    pathFolder = folderPath.replace(os.sep, "/")
    
    geoFile   = f"{pathFolder}/geo.usdc"
    proxyFile = f"{pathFolder}/proxy.usdc"
    geoLayer = Sdf.Layer.CreateNew(geoFile, args={'format':'usdc'})
    
    if os.path.exists(proxyFile):
        rel_proxy = os.path.relpath(proxyFile, os.path.dirname(geoFile)).replace("\\", "/")
        geoLayer.subLayerPaths.append(rel_proxy)
    
    # 2. Define Root
    geo_stage = Usd.Stage.Open(geoLayer)
    if not geo_stage.GetPrimAtPath(rootPrimPathSdf):
        geo_stage.DefinePrim(rootPrimPathSdf, "Xform")
    
    prim = geo_stage.GetPrimAtPath(rootPrimPathSdf)
    geo_stage.SetDefaultPrim(prim)
    Usd.ModelAPI(prim).SetKind(Kind.Tokens.component)
    for p in geo_stage.Traverse():
        if p.IsA(UsdGeom.Imageable):
            if p.GetName().endswith("_proxy"):
                UsdGeom.Imageable(p).CreatePurposeAttr(UsdGeom.Tokens.proxy)
            else:
                if p.GetPath() != rootPrimPathSdf:
                    UsdGeom.Imageable(p).CreatePurposeAttr(UsdGeom.Tokens.render)
                    
    geoLayer.Save()
    print(f"--- Geo Assembly Initialized: {geoFile} (With Proxy) ---")

def addGeoVariantsIntoGeoUsd(rootPrimPath, folderPath, paths, lod_count):
    pathFolder = folderPath.replace(os.sep, "/")
    geoFile = f"{pathFolder}/geo.usdc"
    renderFile = f"{pathFolder}/render.usdc"
    if not os.path.exists(geoFile): return

    stage = Usd.Stage.Open(geoFile)
    rootPrim = stage.GetPrimAtPath(rootPrimPath)
    stage.GetRootLayer().defaultPrim = rootPrim.GetName()
    stage.SetDefaultPrim(rootPrim)
    
    vset = rootPrim.GetVariantSets().AddVariantSet("levels")
    top_name = paths['top_name']

    vset.AddVariant("LOD0")
    vset.SetVariantSelection("LOD0")
    referenceToVariantEditContext(vset, renderFile, geoFile, top_name=top_name, isLOD0=True, isShd=False)

    for i in range(1, lod_count + 1):
        lod_name = f"LOD{i}"
        filename = f"geoVariant_geoLOD{i}.usdc"
        lod_file_path = f"{paths['geoVariant_dir']}/{filename}"
        if not os.path.exists(lod_file_path): continue
            
        vset.AddVariant(lod_name)
        vset.SetVariantSelection(lod_name)
        referenceToVariantEditContext(vset, lod_file_path, geoFile, top_name=top_name, isLOD0=False, isShd=False)
                                     
    vset.SetVariantSelection("LOD0")
    stage.GetRootLayer().Save()
    print(f"[INFO] Added {lod_count} geo variants.")

def addShdVariantsIntoShdUsd(rootPrimPath, folderPath, paths):
    pathFolder = folderPath.replace(os.sep, "/")
    shdFile = f"{pathFolder}/shd.usdc"
    if os.path.exists(shdFile): stage = Usd.Stage.Open(shdFile)
    else: stage = Usd.Stage.CreateNew(shdFile)
    
    rootPrim = stage.DefinePrim(rootPrimPath, "Xform")
    stage.SetDefaultPrim(rootPrim)
    vset = rootPrim.GetVariantSets().AddVariantSet("mtl")
    top_name = paths['top_name']

    def process_shd_lod(lod_name, dirty_file_path):
        clean_filename = f"shdVariant_{lod_name}_CLEAN.usdc"
        clean_file_path = f"{paths['shdVariant_dir']}/{clean_filename}"
        if os.path.exists(dirty_file_path):
            if clean_shader_file(dirty_file_path, clean_file_path):
                vset.AddVariant(lod_name)
                vset.SetVariantSelection(lod_name)
                referenceToVariantEditContext(vset, clean_file_path, shdFile, top_name=top_name, isLOD0=False, isShd=True)

    process_shd_lod("LOD0", f"{paths['shdVariant_dir']}/shdVariant_shdLOD0.usdc")
    tex_lods = [2, 4, 10]
    for i in tex_lods:
        lod_name = f"LOD{i}"
        dirty_path = f"{paths['shdVariant_dir']}/shdVariant_shdLOD{i}.usdc"
        process_shd_lod(lod_name, dirty_path)

    vset.SetVariantSelection("LOD0")
    stage.GetRootLayer().Save()
    print(f"[INFO] Assemble Shd Complete: {shdFile}") 

def create_payload_file(top_name, version_dir):
    payload_path = f"{version_dir}/payload.usdc"      
    stage = Usd.Stage.CreateNew(payload_path)      
    root_prim = stage.DefinePrim(f"/{top_name}", "Xform")
    stage.SetDefaultPrim(root_prim)
    Usd.ModelAPI(root_prim).SetKind(Kind.Tokens.component)
    root_prim.GetReferences().AddReference("./shd.usdc")
    root_prim.GetReferences().AddReference("./geo.usdc")
    stage.GetRootLayer().Save()
    print(f"[INFO] Payload Created: {payload_path}")
    return payload_path

def bind_materials_in_payload(payload_path, top_node_name):
    print(f"[BIND] Binding materials in {os.path.basename(payload_path)}...")
    stage = Usd.Stage.Open(payload_path)
    root_prim = stage.GetPrimAtPath(f"/{top_node_name}")
    mtl_root_path = root_prim.GetPath().AppendChild("mtl")
    edits = 0
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            target_mat_name = prim.GetCustomDataByKey("bindingMat")
            if target_mat_name:
                mat_path = mtl_root_path.AppendChild(target_mat_name)
                binding_api = UsdShade.MaterialBindingAPI.Apply(prim)
                binding_api.Bind(UsdShade.Material(stage.GetPrimAtPath(mat_path)))
                edits += 1
    if edits > 0:
        stage.GetRootLayer().Save()
        print(f"[BIND] Successfully bound {edits} meshes.")

def _write_interface_top_layer(top_name, payload_path, out_path):
    stage = Usd.Stage.CreateNew(out_path)
    
    class_root = Sdf.Path("/__class__")
    stage.CreateClassPrim(class_root)
    asset_class_path = class_root.AppendChild(top_name)
    asset_class = stage.CreateClassPrim(asset_class_path)
    
    root_prim = stage.DefinePrim(f"/{top_name}", "Xform")
    
    stage.SetDefaultPrim(root_prim)
    Usd.ModelAPI(root_prim).SetKind(Kind.Tokens.component)
    Usd.ModelAPI(root_prim).SetAssetName(top_name)
    Usd.ModelAPI(root_prim).SetAssetIdentifier(out_path)
    
    root_prim.GetInherits().AddInherit(asset_class_path)

    rel_payload_path = "./payload.usdc" 
    root_prim.GetPayloads().AddPayload(rel_payload_path)
    
    stage.GetRootLayer().Save()
    print(f"[INFO] Asset Interface Created: {out_path}")
    return out_path

# ==============================================================================
# DEADLINE INTEGRATION
# ==============================================================================
class DeadlineSubmitter:
    def __init__(self):
        self.deadline_bin = r"C:\Program Files\Thinkbox\Deadline10\bin"
        self.deadline_path = os.path.join(self.deadline_bin, "deadlinecommand.exe")
        if not os.path.exists(self.deadline_path):
            self.deadline_bin = r"C:\Program Files\Thinkbox\Deadline8\bin"
            self.deadline_path = os.path.join(self.deadline_bin, "deadlinecommand.exe")
            if not os.path.exists(self.deadline_path):
                raise RuntimeError("Deadline executable not found")
        
    def write_temp_file(self, info_dict:dict, suffix:str):
        lines = []
        for k, v in info_dict.items():
            try:
                k_str = str(k).encode('ascii', 'ignore').decode('ascii')
                v_str = str(v).encode('ascii', 'ignore').decode('ascii')
                lines.append(f"{k_str}={v_str}")
            except:
                continue

        text = "\n".join(lines)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='w', encoding='utf-8') as f:
            f.write(text)
            return f.name

    def submit_job(self, job_info:dict, plugin_info:dict, auxiliary_files=None):
        job_file = self.write_temp_file(job_info, ".job")
        plugin_file = self.write_temp_file(plugin_info, ".plugin")

        if "JobDependencies" in job_info and isinstance(job_info["JobDependencies"], list):
            job_info["JobDependencies"] = ",".join(job_info["JobDependencies"])

        cmd = [self.deadline_path, job_file, plugin_file]

        if auxiliary_files:
            if isinstance(auxiliary_files, list):
                cmd.extend(auxiliary_files)
            elif isinstance(auxiliary_files, str):
                cmd.append(auxiliary_files)

        startupinfo = None
        # silent run
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        print(f"[Deadline] Submitting {job_info.get('Name')}...")

        if None in cmd:
            print(f"[CRITICAL ERROR] Command contains None: {cmd}")
            return None

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
        except Exception as e:
            raise RuntimeError(f"Deadline execution failed: {e}") 

        try:
            os.remove(job_file)
            os.remove(plugin_file)
        except: pass

        job_id = None
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.startswith("JobID="):
                    job_id = line.split("=")[1].strip()
                    break
        
        return job_id
    
    def get_environment(self):
        """ Capture relevant environment variables for the farm """
        blocklist = ["PYTHONHOME", "TEMP", "TMP", "USER", "USERNAME"]
        
        force_keys = [
            "PATH", 
            "PYTHONPATH", 
            "MAYA_PLUG_IN_PATH", 
            "MAYA_MODULE_PATH", 
            "MTOA_PATH",
            "ARNOLD_PLUGIN_PATH",
            "PXR_PLUGINPATH_NAME"
        ]
        
        prefixes = ["HAL_", "REZ_", "ARNOLD_", "PEREGRINE_", "YETI_", "USD_"]
        exacts = ["JOB", "SHOW", "SHOT", "SEQ", "OCIO"]
        
        env = {}
        for k, v in os.environ.items():
            if k in blocklist: continue
            
            try:
                k.encode('ascii')
                v.encode('ascii')
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            
            is_force = k in force_keys
            is_match = k in exacts or any(k.startswith(p) for p in prefixes)
            
            if is_force or is_match:
                env[k] = v
                
        return env



# ==============================================================================
# UI & EXECUTION
# ==============================================================================

def maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QWidget)

def load_ui(ui_file):
    loader = QtUiTools.QUiLoader()
    file = QtCore.QFile(ui_file)
    if not file.open(QtCore.QFile.ReadOnly): raise RuntimeError(f"Cannot open UI: {ui_file}")
    ui = loader.load(file)
    file.close()
    return ui

def get_publish_paths(top_node):
    hal_root = os.environ.get('HAL_TASK_ROOT', '')
    if not hal_root:
        hal_root = os.path.join(os.environ.get('USERPROFILE') or os.environ.get('HOME'), 'Desktop', 'MayaDebug_Publish')
    maya_pub_root = os.path.join(hal_root, '_publish', 'maya')
    if not os.path.isdir(maya_pub_root): os.makedirs(maya_pub_root)
    
    pat = re.compile(r'^v(\d{3,})$', re.IGNORECASE)
    max_n = 0
    for name in os.listdir(maya_pub_root):
        if os.path.isdir(os.path.join(maya_pub_root, name)):
            m = pat.match(name)
            if m: max_n = max(max_n, int(m.group(1)))
    version = f'v{(max_n+1):03d}'
    version_dir = os.path.join(maya_pub_root, version).replace('\\', '/')
    if not os.path.isdir(version_dir): os.makedirs(version_dir)
    
    top_name = top_node.split('|')[-1]
    return {
        "top_name": top_name,
        "version": version,
        "version_dir": version_dir,
        "render_path": f"{version_dir}/render.usdc",
        "proxy_path": f"{version_dir}/proxy.usdc",
        "payload_path": f"{version_dir}/payload.usdc",
        "geoVariant_dir": os.path.join(version_dir, 'geoVariants').replace('\\', '/'),
        "shdVariant_dir": os.path.join(version_dir, 'shdVariants').replace('\\', '/'),
        "top_path": f"{version_dir}/{top_name}.usdc"
    }

class PublishToolWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(540, 400)
        self.setWindowTitle("着色器发布工具")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        maya_menu_dir = os.path.dirname(script_dir)
        ui_file = os.path.join(maya_menu_dir, "QtWindows", "shader_publish_tool.ui")
        self.ui = load_ui(ui_file)
        self.setCentralWidget(self.ui)
        self.ui.actionOpen_Project_Folder_2.triggered.connect(self.open_project_folder)
        self.ui.PublishInfoButton.clicked.connect(self.run_local_publish)
        self.ui.DeadlinePublishInfoButton.clicked.connect(self.run_deadline_publish)
        
        # Connect UI logic elements
        self.ui.proxyGroupBox.toggled.connect(self.sync_proxy_options)
        self.ui.lodGroupBox.toggled.connect(self.sync_lod_options)
        self.ui.proxyReduceSlider.valueChanged.connect(lambda v: self.ui.proxyReduceSpinBox.setValue(v / 10.0))
        self.ui.proxyReduceSpinBox.valueChanged.connect(lambda v: self.ui.proxyReduceSlider.setValue(int(v * 10)))
        self.ui.lodReduceSlider.valueChanged.connect(lambda v: self.ui.lodReduceSpinBox.setValue(v / 10.0))
        self.ui.lodReduceSpinBox.valueChanged.connect(lambda v: self.ui.lodReduceSlider.setValue(int(v * 10)))

    def _publish_ma_scene(self, version, version_dir):
            src = cmds.file(q=True, sn=True)
            
            # Get naming components from Env, or defaults
            project = os.environ.get("HAL_PROJECT_ABBR", "PROJ")
            asset   = os.environ.get("HAL_ASSET", "ASSET")
            task    = os.environ.get("HAL_TASK", "shd")
            user    = os.environ.get("HAL_USER_ABBR", "user")
            
            # Standard naming convention
            name = f"{project}_{asset}_{task}_{version}_{user}.ma"
            dst = os.path.join(version_dir, name)
            
            shutil.copy2(src, dst)
            return dst

    def sync_proxy_options(self, checked):
            layout = self.ui.proxyGroupBox.layout()
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget():
                    item.widget().setVisible(checked)

    def sync_lod_options(self, checked):
        layout = self.ui.lodGroupBox.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget():
                item.widget().setVisible(checked)

    def auto_save_scene(self):
        try:
            current = cmds.file(q=True, sn=True)
            if not current:
                tmp = os.path.join(cmds.internalVar(userTmpDir=True), "temp_publish_scene.ma")
                cmds.file(rename=tmp)
            cmds.file(save=True, type='mayaAscii')
            return True
        except: return False

    def open_project_folder(self):
        """Open Windows Explorer at specified project path"""
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        project_path = HAL_TASK_ROOT
        try:
            subprocess.Popen(f'explorer "{project_path}"')
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open folder:\n{str(e)}")

    def run_local_publish(self):
        # 1. Save Scene
        if not self.auto_save_scene(): return
        
        # 2. Get Selection
        sel = cmds.ls(sl=True, long=True)
        if not sel or len(sel) != 1 or cmds.nodeType(sel[0]) != 'transform':
            QMessageBox.warning(self, "Warning", "Select exactly ONE top transform.")
            return
        
        top_node = sel[0]
        paths = get_publish_paths(top_node) 
        print(f"Local Publish to: {paths['version_dir']}")
        
        try:
            # ==================================================================
            # STEP 0: TEXTURE GENERATION (OIIO)
            # ==================================================================
            do_tex = self.ui.texLodCheckBox.isChecked()
            if do_tex:
                tex_proc = TextureLODProcessor()
                tex_files = tex_proc.scan_scene_textures(top_node)
                if tex_files:
                    tex_proc.run_local(tex_files)

            # ==================================================================
            # STEP 1: EXPORT SHADER (LOD0) & INJECT METADATA
            # ==================================================================
            print(f"--- Exporting Render (LOD0) to {paths['render_path']}")
            
            # Export
            mask = arnold_usd_mask(shaderOrNot=False)
            cmds.select(top_node, r=True)
            cmds.arnoldExportAss(f=paths['render_path'], selected=True, mask=mask, 
                                lightLinks=False, shadowLinks=False, expandProcedurals=True)
            
            # Clean & Inject
            fix_arnold_usd_structure(paths['render_path'])
            
            if os.path.exists(paths['render_path']):
                lyr = Sdf.Layer.FindOrOpen(paths['render_path'])
                if lyr:
                    stg = Usd.Stage.Open(lyr)
                    _inject_binding_metadata(stg, top_node) # Inject from LIVE scene
                    stg.GetRootLayer().Save()

            # ==================================================================
            # STEP 2: EXPORT PROXY
            # ==================================================================
            has_proxy = self.ui.proxyGroupBox.isChecked()
            if has_proxy:
                print(f"--- Exporting Proxy to {paths['proxy_path']}")
                pct = self.ui.proxyReduceSpinBox.value() # Percent to REMOVE
                
                # Helper to create proxy geometry
                proxy_dup = _duplicate_and_reduce(top_node, suffix='_proxy', percent=pct)
                
                top_name = paths['top_name']
                src_tmp = _safe_rename(top_node, f"{top_name}_origTmp")
                proxy_as_src = _safe_rename(proxy_dup, top_name)
                
                try:
                    cmds.select(proxy_as_src, r=True)
                    cmds.arnoldExportAss(f=paths['proxy_path'], selected=True, mask=mask, 
                                        lightLinks=False, shadowLinks=False, expandProcedurals=True)
                    
                    fix_arnold_usd_structure(paths['proxy_path'])
                    _rename_nonmesh_parents_in_layer_with_sdf(paths['proxy_path'], suffix='_proxy')
                finally:
                    if cmds.objExists(proxy_as_src): cmds.delete(proxy_as_src)
                    _safe_rename(src_tmp, top_name)

            # ==================================================================
            # STEP 3: EXPORT GEO LODS (Dynamic Reduction)
            # ==================================================================
            has_lods = self.ui.lodGroupBox.isChecked()
            lod_count = self.ui.lodCountSpinBox.value()
            
            if has_lods:
                # The slider represents "Keep Percentage" per level relative to previous
                # E.g. 50% means LOD1 is 50% of LOD0, LOD2 is 50% of LOD1 (25% total)
                base_keep_percent = self.ui.lodReduceSpinBox.value() 
                
                if not os.path.exists(paths['geoVariant_dir']): 
                    os.makedirs(paths['geoVariant_dir'])
                
                exporter = LODVariantExporter()

                for i in range(1, lod_count + 1):
                    # Calculate cumulative retention
                    # Formula: 100 * ( (base/100) ^ i )
                    keep_ratio = (base_keep_percent / 100.0) ** i
                    
                    # polyReduce 'p' argument is percentage to REMOVE
                    remove_percent = 100.0 - (keep_ratio * 100.0)
                    remove_percent = max(0.0, min(99.0, remove_percent))
                    
                    exporter.task_export_single_lod(
                        top_node, paths, "geoVariant", 
                        lod_index=i, 
                        percent=remove_percent, 
                        shaderOrNot=False
                    )

            # ==================================================================
            # STEP 4: EXPORT SHADER LODS (Texture Swapping)
            # ==================================================================
            if do_tex: 
                if not os.path.exists(paths['shdVariant_dir']): 
                    os.makedirs(paths['shdVariant_dir'])
                
                exporter = LODVariantExporter()
                
                # LOD 0 (Original)
                exporter.task_export_single_lod(top_node, paths, "shdVariant", lod_index=0, shaderOrNot=True)
                
                # LODs (2, 4, 10)
                for i in [2, 4, 10]:
                    exporter.task_export_single_lod(top_node, paths, "shdVariant", lod_index=i, shaderOrNot=True)

            # ==================================================================
            # STEP 5-8: ASSEMBLE
            # ==================================================================
            
            # 5. Geo Assembly
            geoUsdExport(f"/{paths['top_name']}", paths['version_dir'])
            addGeoVariantsIntoGeoUsd(f"/{paths['top_name']}", paths['version_dir'], paths, lod_count)
            
            # 6. Shader Assembly
            if do_tex:
                addShdVariantsIntoShdUsd(f"/{paths['top_name']}", paths['version_dir'], paths)
            
            # 7. Payload & Binding
            payload_file = create_payload_file(paths['top_name'], paths['version_dir'])
            bind_materials_in_payload(payload_file, paths['top_name'])
            
            # 8. Asset Shell
            final_usd = _write_interface_top_layer(
                paths['top_name'], 
                paths['payload_path'], 
                paths['top_path']
            )

            # Finalize
            thumb = self._create_publish_thumbnail(paths['top_name'])
            self.submit_to_shotgun(paths['top_path'], thumb)
            ma_path = self._publish_ma_scene(paths['version'], paths['version_dir'])
            self.submit_to_shotgun(ma_path.replace(os.sep, "/"), thumb)
            
            QMessageBox.information(self, "Success", f"Published {paths['version']}")

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            import traceback
            traceback.print_exc()

    def run_deadline_publish(self):
            # ==============================================================================
            # 1. SETUP & VALIDATION
            # ==============================================================================
            if not self.auto_save_scene(): return
            
            sel = cmds.ls(sl=True, long=True)
            if not sel or len(sel) != 1:
                QMessageBox.warning(self, "Warning", "Select exactly ONE top transform.")
                return
                
            top_node = sel[0]
            paths = get_publish_paths(top_node)
            current_scene = cmds.file(q=True, sn=True)
            current_scene_name = os.path.splitext(os.path.basename(current_scene))[0]

            # ==============================================================================
            # 2. CONFIG & SCRIPTS
            # ==============================================================================
            config_data = {
                "scene_file": current_scene,
                "paths": paths,
                "has_proxy": self.ui.proxyGroupBox.isChecked(),
                "proxy_percent": self.ui.proxyReduceSpinBox.value(),
                "has_lods": self.ui.lodGroupBox.isChecked(),
                "lod_count": self.ui.lodCountSpinBox.value(),
                "lod_percent": self.ui.lodReduceSpinBox.value(),
                "do_tex": self.ui.texLodCheckBox.isChecked()
            }

            # Write Config JSON
            publish_config_json_path = os.path.join(paths['version_dir'], "_temp", "publish_config.json").replace("\\", "/")     
            config_dir = os.path.dirname(publish_config_json_path)
            if not os.path.exists(config_dir): os.makedirs(config_dir)

            with open(publish_config_json_path, 'w') as f:
                json.dump(config_data, f, indent=4)

            # Write Unified Worker Script
            def get_clean_lines(file_path):
                clean_lines = []
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if line.strip().startswith("from ..utils"): clean_lines.append("# " + line)
                            elif not line.isascii(): clean_lines.append("# [Non-ASCII line removed]\n")
                            else: clean_lines.append(line)
                except Exception as e: print(f"Error reading {file_path}: {e}")
                return clean_lines

            worker_lines = get_clean_lines(__file__)
            worker_lines.append("\n\n# --- TEMPLATE START ---\n\n")
            template_path = os.path.join(os.path.dirname(__file__), '..', 'utils', 'mayaUsdDeadlineJobs.py')
            worker_lines.extend(get_clean_lines(template_path))
            
            self.worker_script_path = os.path.join(config_dir, "farm_worker.py").replace("\\", "/")
            with open(self.worker_script_path, 'w', encoding='utf-8') as f:
                f.write("".join(worker_lines))

            # Copy OIIO Script
            self.oiio_worker_path = os.path.join(config_dir, "OIIO_process_LOD_Tasks.py").replace("\\", "/")
            source_oiio_path = os.path.join(os.path.dirname(__file__), '..', 'utils', 'OIIO_process_LOD_Tasks.py')
            try: shutil.copy2(source_oiio_path, self.oiio_worker_path)
            except: pass

            # Environment & Paths
            raw_env = DeadlineSubmitter().get_environment()
            env_vars = {}
            for k, v in raw_env.items():
                try: 
                    if k.encode('ascii') and v.encode('ascii'): env_vars[k] = v
                except: continue

            raw_batch_name = f"{os.path.basename(current_scene)} - {paths['version']}"
            batch_name = raw_batch_name.encode('ascii', 'ignore').decode('ascii')
            safe_json_path = publish_config_json_path.encode('ascii', 'ignore').decode('ascii')
            safe_worker_path = self.worker_script_path.encode('ascii', 'ignore').decode('ascii')
            safe_oiio_path = self.oiio_worker_path.encode('ascii', 'ignore').decode('ascii')

            # ==============================================================================
            # 3. HELPER FUNCTIONS
            # ==============================================================================
            def _get_Job_Info_Dict(suffix, plugin, concurrent="1", frames="1", dependencies=None):
                job_info = {
                    "Name": f"{current_scene_name}-{suffix}",
                    "Plugin": plugin, 
                    "Pool": "3d", "Group": "3d",
                    "BatchName": batch_name,
                    "ConcurrentTasks": concurrent, 
                    "Frames": frames
                }
                if dependencies:
                    if isinstance(dependencies, list): job_info["JobDependencies"] = ",".join(dependencies)
                    else: job_info["JobDependencies"] = dependencies

                job_info["OutputFilename0"] = paths['top_path']

                i = 0
                for k, v in env_vars.items():
                    job_info[f"EnvironmentKeyValue{i}"] = f"{k}={v}"
                    i += 1
                return job_info

            def _get_Plugin_Info_Dict(script_path, data_file, task_type, extra_arg=""):
                packages = get_rez_packages_from_maya()
                if extra_arg:
                    args = f'{packages} run mayapy "{script_path}" "{data_file}" {task_type} {extra_arg}'
                else:
                    args = f'{packages} run mayapy "{script_path}" "{data_file}" {task_type}'
                
                return {
                    "Executable": "afx.cmd",
                    "Arguments": args, 
                    "Shell": "default",
                    "StartupDirectory": config_dir
                }

            # ==============================================================================
            # 4. JOB SUBMISSION LOGIC
            # ==============================================================================
            
            # --- EXPORT BASE (LOD0 Geo) ---
            def submit_export_job():
                job_info = _get_Job_Info_Dict("Maya_Export_Base", "CommandLine", frames="1")
                plugin_info = _get_Plugin_Info_Dict(safe_worker_path, safe_json_path, "export_base")
                return DeadlineSubmitter().submit_job(job_info, plugin_info, auxiliary_files=[safe_json_path])

            # --- OIIO (Parallel) ---
            def submit_oiio_job(dependency_id=None):
                tex_proc = TextureLODProcessor()
                tex_files = tex_proc.scan_scene_textures(top_node)
                if not tex_files: return None
                
                final_list = set()
                for p in tex_files:
                    tiles = tex_proc._expand_udim_tiles(p)
                    if tiles: final_list.update(tiles.values())
                
                sorted_files = sorted(list(final_list))
                if not sorted_files: return None

                manifest_name = f"{current_scene_name}-OIIO_Manifest.json"
                manifest_path = os.path.join(config_dir, manifest_name).replace("\\", "/")
                with open(manifest_path, 'w') as f: json.dump(sorted_files, f, indent=4)
                safe_manifest = manifest_path.encode('ascii', 'ignore').decode('ascii')

                chunk = "50" if len(sorted_files) > 50 else str(len(sorted_files))
                job_info = _get_Job_Info_Dict("OIIO_Convert", "CommandLine", frames=f"0-{len(sorted_files)-1}", dependencies=dependency_id)
                job_info["ChunkSize"] = chunk
                
                plugin_info = _get_Plugin_Info_Dict(safe_oiio_path, safe_manifest, "<STARTFRAME> <ENDFRAME>")
                return DeadlineSubmitter().submit_job(job_info, plugin_info, auxiliary_files=[safe_manifest])

            # --- GEO TASKS (Proxy & LODs) ---
            def submit_geo_job(task_identifier, specific_name, extra_arg=""):
                job_info = _get_Job_Info_Dict(f"Geo_{specific_name}", "CommandLine", frames="1")
                plugin_info = _get_Plugin_Info_Dict(safe_worker_path, safe_json_path, task_identifier, extra_arg)
                return DeadlineSubmitter().submit_job(job_info, plugin_info, auxiliary_files=[safe_json_path])

            # --- ASSEMBLE ---
            def submit_assemble_job(dependency_ids):
                deps = dependency_ids if isinstance(dependency_ids, list) else [dependency_ids]
                job_info = _get_Job_Info_Dict("Assemble_Shotgun_Submission", "CommandLine", frames="1", dependencies=deps)
                plugin_info = _get_Plugin_Info_Dict(safe_worker_path, safe_json_path, "assemble")
                return DeadlineSubmitter().submit_job(job_info, plugin_info, auxiliary_files=[safe_json_path])

            # ==============================================================================
            # 5. EXECUTION CHAIN
            # ==============================================================================
            print("--- Starting Deadline Submission Chain (Parallel) ---")
            assembly_dependencies = []

            # 1. Export Base
            mayaExportJobId = submit_export_job() 
            print(f">>> Export Base Job ID: {mayaExportJobId}")
            assembly_dependencies.append(mayaExportJobId)
            
            # 2. OIIO (Parallel - No dependency on geometry)
            if config_data.get('do_tex'):
                OiioConvertJobId = submit_oiio_job(None) 
                if OiioConvertJobId: 
                    print(f">>> OIIO Job ID: {OiioConvertJobId}")
                    assembly_dependencies.append(OiioConvertJobId)

            # 3. Proxy (Parallel)
            if config_data.get('has_proxy'):
                proxy_job_id = submit_geo_job("proxy", "Proxy") 
                if proxy_job_id:
                    print(f">>> Proxy Job ID: {proxy_job_id}")
                    assembly_dependencies.append(proxy_job_id)

            # 4. Geo LODs (Parallel Fan-Out)
            if config_data.get('has_lods'):
                lod_count = config_data.get('lod_count', 0)
                for i in range(1, lod_count + 1):
                    lod_job_id = submit_geo_job("lod", f"LOD{i}", str(i))
                    if lod_job_id:
                        print(f">>> Geo LOD {i} Job ID: {lod_job_id}")
                        assembly_dependencies.append(lod_job_id)

            # 5. Assemble (Fan-In - Generates Shaders & Stitches)
            AssembleUsdJobId = submit_assemble_job(assembly_dependencies)
            print(f">>> Assembly Job ID: {AssembleUsdJobId}")
            
            QMessageBox.information(self, "Success", f"成功上传Maya USD到Deadline 10！\nUSD资产名称: {paths['top_name']}\nUSD资产路径: {paths['top_path']}\n请打开Deadline Monitor10查看任务进度！")


    # ==============================================================================
    # 2. GLOBAL THUMBNAIL GENERATOR (Updated Logic)
    # ==============================================================================
    def _create_publish_thumbnail(self, top_node_name):
            """
            Creates a thumbnail if one does not exist.
            Path: {HAL_TASK_ROOT}/_publish/_SGthumbnail/{top_node_name}_temp.1001.png
            """
            created_cam = None
            try:
                # 1. Define Path
                hal_root = os.environ.get("HAL_TASK_ROOT", "")
                thumb_dir = os.path.join(hal_root, "_publish", "_SGthumbnail")
                if not os.path.exists(thumb_dir): 
                    os.makedirs(thumb_dir)
                
                # Use top_node_name directly as requested
                final_thumb_path = os.path.join(thumb_dir, f"{top_node_name}_temp.1001.png").replace("\\", "/")
                
                # 2. Check Existence (Skip if exists)
                if os.path.exists(final_thumb_path):
                    print(f"[Thumbnail] Found existing: {final_thumb_path}")
                    return final_thumb_path

                print(f"[Thumbnail] Generating new: {final_thumb_path}")

                # 3. Generate Camera & Frame
                created_cam = camThumbnail.frame_all_top_level_objects_in_maya(spin_offset=45, pitch_offset=-20)
                cmds.lookThru(created_cam)
                
                # 4. Playblast
                # Note: Playblast requires the filename prefix without extension for some formats, 
                # but we need to target the specific .1001.png logic.
                # We strip the extension and frame number for the playblast 'filename' arg
                pb_prefix = os.path.join(thumb_dir, f"{top_node_name}_temp").replace("\\", "/")
                
                generated_files = cmds.playblast(
                    f=pb_prefix, 
                    startTime=1001, endTime=1001, 
                    fmt='image', compression='png', 
                    quality=100, percent=100, 
                    widthHeight=(1920, 1080), 
                    viewer=False, 
                    framePadding=4, 
                    forceOverwrite=True, 
                    showOrnaments=False  # Hide grid/HUD
                )
                
                # Verify result
                if os.path.exists(final_thumb_path):
                    return final_thumb_path
                
                # Fallback check (sometimes maya returns full path in generated_files)
                if generated_files and os.path.exists(generated_files):
                    # Rename it to match our strict requirement if needed
                    if generated_files.replace("\\", "/") != final_thumb_path:
                        try:
                            shutil.move(generated_files, final_thumb_path)
                            return final_thumb_path
                        except:
                            return generated_files.replace("\\", "/")
                
                return None

            except Exception as e:
                print(f"[Thumbnail] Error: {e}")
                return None
                
            finally:
                if created_cam and cmds.objExists(created_cam):
                    try: cmds.delete(created_cam)
                    except: pass
                defaults = cmds.ls("defaultFramedCamera*", type='transform')
                if defaults:
                    try: cmds.delete(defaults)
                    except: pass
    def submit_to_shotgun(self, path, thumb):
        try:
            sg = ShotgunDataManager()
            sg.Create_SG_Version(thumb, path)
        except: pass

SHADER_PUBLISH_TOOL_INSTANCE = None
def execute():
    global SHADER_PUBLISH_TOOL_INSTANCE
    UI_NAME = "ShaderPublishToolWindow"

    if cmds.window(UI_NAME, exists=True):
        cmds.deleteUI(UI_NAME, window=True)
        
    try:
        if 'mayaMenuBar.utils.camThumbnail' in sys.modules:
            importlib.reload(sys.modules['mayaMenuBar.utils.camThumbnail'])
        if 'mayaMenuBar.utils.SGlogin' in sys.modules:
            importlib.reload(sys.modules['mayaMenuBar.utils.SGlogin'])

        this_path = os.path.normpath(__file__).lower()
        target_mod = None
        
        for name, mod in sys.modules.items():
            if not mod or not hasattr(mod, '__file__') or not mod.__file__: continue
            if os.path.normpath(mod.__file__).lower() == this_path:
                target_mod = mod
                break
        
        if target_mod:
            print(f"[HotLoader] Reloading: {target_mod.__name__}")
            importlib.reload(target_mod)
        elif __name__ in sys.modules:
            # Fallback to standard reload
            print(f"[HotLoader] Reloading by name: {__name__}")
            importlib.reload(sys.modules[__name__])
            
    except Exception as e:
        print(f"[HotLoader] Error reloading modules: {e}")

    parent = maya_main_window()
    SHADER_PUBLISH_TOOL_INSTANCE = PublishToolWindow(parent=parent)
    SHADER_PUBLISH_TOOL_INSTANCE.setObjectName(UI_NAME)
    SHADER_PUBLISH_TOOL_INSTANCE.show()