import maya.cmds as cmds
import importlib
import sys

# --- CONFIG: keep these if you rely on them ---
WHITELIST = {
    "mayaUsdPlugin", "mtoa", "fbxmaya", "objExport",
    "gpuCache", "Substance", "AbcExport", "AbcImport"
}

def _print_header(title):
    print("\n" + "-"*70 + f"\n{title}\n" + "-"*70)

def plugins_in_use():
    # Returns a set of plugin names currently reported as "in use"
    used = set()
    try:
        # returns like ["mtoa (5.3.4)", "mayaUsdPlugin (0.27.0)"] in some builds
        items = cmds.pluginInfo(q=True, pluginsInUse=True) or []
        for item in items:
            # take first token as name
            name = item.split()[0]
            used.add(name)
    except Exception:
        pass
    return used

def list_all_plugins():
    try:
        return set(cmds.pluginInfo(q=True, listPlugins=True) or [])
    except Exception:
        return set()

def list_unknown_plugins():
    try:
        # These are *missing* plugin stubs recorded in the scene file
        return set(cmds.unknownPlugin(q=True, list=True) or [])
    except Exception:
        return set()

def remove_unknown_plugin_records():
    removed = []
    for p in list_unknown_plugins():
        try:
            cmds.unknownPlugin(p, remove=True)
            removed.append(p)
        except Exception as e:
            print(f"[WARN] Could not remove unknown plugin record '{p}': {e}")
    return removed

def delete_unknown_nodes():
    deleted = []
    for t in ("unknown", "unknownDag"):
        nodes = cmds.ls(type=t) or []
        for n in nodes:
            try:
                cmds.lockNode(n, l=False)
                cmds.delete(n)
                deleted.append(n)
            except Exception as e:
                print(f"[WARN] Could not delete {t} node '{n}': {e}")
    return deleted

def unload_non_core_plugins(whitelist=WHITELIST):
    unloaded = []
    all_plugs = list_all_plugins()
    for p in sorted(all_plugs):
        try:
            if p in whitelist:
                continue
            if cmds.pluginInfo(p, q=True, loaded=True):
                # Turn off autoload first
                try:
                    cmds.pluginInfo(p, e=True, autoload=False)
                except Exception:
                    pass
                # Then unload
                cmds.unloadPlugin(p, force=True)
                unloaded.append(p)
        except Exception:
            # ignore bad/locked plugins
            pass
        # Also disable autoload for not-loaded plugins outside whitelist
        try:
            if p not in whitelist:
                cmds.pluginInfo(p, e=True, autoload=False)
        except Exception:
            pass
    return unloaded

def scene_unknowns_summary():
    return {
        "unknown_nodes": (cmds.ls(type="unknown") or []) + (cmds.ls(type="unknownDag") or []),
        "unknown_plugin_records": list(list_unknown_plugins()),
        "plugins_in_use": sorted(list(plugins_in_use()))
    }

def clean_scene_for_format_change(unload_plugins=False):
    _print_header("Before cleanup (summary)")
    print(scene_unknowns_summary())

    _print_header("Removing unknown plugin records")
    removed_plug_records = remove_unknown_plugin_records()
    print("Removed records:", removed_plug_records)

    _print_header("Deleting unknown/unknownDag nodes")
    deleted_nodes = delete_unknown_nodes()
    print("Deleted nodes:", deleted_nodes)

    if unload_plugins:
        _print_header("Unloading non-core plugins and disabling autoload")
        unloaded = unload_non_core_plugins()
        print("Unloaded:", unloaded)

    cmds.flushUndo()  # optional: drop references to deleted nodes

    _print_header("After cleanup (summary)")
    print(scene_unknowns_summary())
    print("\n[OK] Cleanup finished. Try Save As to the new format now.")

###########Hot Load###########
def get_command():
    def _command():
        clean_scene_for_format_change(unload_plugins=False)
    return _command

def execute():
    """Execute the command with reloading."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()