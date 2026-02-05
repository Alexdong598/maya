# Import all references found under the currently selected top DAG node(s).
# Works in Maya's Script Editor (Python tab).

import maya.cmds as cmds

def import_references_under_selection(verbose=True):
    sel = cmds.ls(sl=True, long=True) or []
    if not sel:
        cmds.warning("Select one or more TOP DAG nodes in the Outliner first.")
        return

    # Gather all DAG nodes under the selected roots (including the roots)
    dag_nodes = set()
    for root in sel:
        dag_nodes.add(root)
        children = cmds.listRelatives(root, ad=True, fullPath=True) or []
        dag_nodes.update(children)

    # Find unique reference nodes associated with those DAG nodes
    refnodes = set()
    for n in dag_nodes:
        try:
            if cmds.referenceQuery(n, isNodeReferenced=True):
                rn = cmds.referenceQuery(n, referenceNode=True)
                if rn:
                    refnodes.add(rn)
        except Exception:
            # Some node types may not answer referenceQuery; ignore them
            pass

    if not refnodes:
        if verbose:
            print("No referenced content found under the selection.")
        return

    # Import each reference node (deduped)
    imported = []
    failed = []
    for rn in sorted(refnodes):
        try:
            if verbose:
                print(f"Importing reference: {rn} ...")
            cmds.file(importReference=True, referenceNode=rn)
            imported.append(rn)
        except Exception as e:
            failed.append((rn, str(e)))

    # Report
    if imported:
        print("\nImported references:")
        for rn in imported:
            print("  -", rn)

    if failed:
        cmds.warning("\nSome references failed to import:")
        for rn, msg in failed:
            print(f"  - {rn}: {msg}")

# Run it:
import_references_under_selection()
