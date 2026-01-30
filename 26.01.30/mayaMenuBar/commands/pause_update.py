"""Pause Update - Close Heavy Mode for performance optimization."""
import maya.cmds as cmds
import importlib
import sys

def close_heavy_mode():
    """Close heavy mode by disabling various performance-intensive features."""
    # 1) 暂停刷新 + 评估
    try: cmds.refresh(suspend=True)
    except: pass
    try: cmds.evaluationManager(mode='off')
    except: pass

    # 2) 关Undo、自动关键帧、时间滑条自动刷新
    try: cmds.undoInfo(stateWithoutFlush=False)
    except: pass
    try: cmds.autoKeyframe(state=False)
    except: pass
    try: cmds.optionVar(iv=('timeSliderAutoRefresh', 0))
    except: pass

    # 3) Viewport尽量轻：关纹理/阴影/灯光，线框显示
    panels = cmds.getPanel(type='modelPanel') or []
    for p in panels:
        try: cmds.modelEditor(p, e=True, displayTextures=False)
        except: pass
        try: cmds.modelEditor(p, e=True, shadows=False)
        except: pass
        try: cmds.modelEditor(p, e=True, displayLights='none')
        except: pass
        try: cmds.modelEditor(p, e=True, twoSidedLighting=False)
        except: pass
        try: cmds.modelEditor(p, e=True, wireframeOnShaded=True)
        except: pass
        try: cmds.modelEditor(p, e=True, sel=False)
        except: pass
        try: cmds.modelEditor(p, e=True, displayAppearance='wireframe')
        except: pass

    # 4) 全局包围盒显示
    try: cmds.displayPref(displayBoundingBox=True)
    except: pass

    print(u'🚀 Heavy Mode: CLOSED（已极限降载）')

def get_command():
    """Return command implementation with auto-reload functionality."""
    def _command():
        close_heavy_mode()
    return _command

def execute():
    """Execute with reloading to enable script updates without restarting Maya."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    execute()
