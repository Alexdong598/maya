import maya.cmds as cmds
import random

def apply_random_transforms(min_tx, max_tx, min_ty, max_ty, min_tz, max_tz,
                            min_rx, max_rx, min_ry, max_ry, min_rz, max_rz,
                            percentage):
    selected_objects = cmds.ls(selection=True)

    if not selected_objects:
        cmds.warning("No objects selected. Please select some model boxes and run the script again.")
        return

    # Normalize percentage to [0,1]
    prob = percentage / 100.0
    if prob < 0.0 or prob > 1.0:
        cmds.warning("Percentage must be between 0 and 100.")
        return

    # Validate min <= max for each
    if (min_tx > max_tx or min_ty > max_ty or min_tz > max_tz or
        min_rx > max_rx or min_ry > max_ry or min_rz > max_rz):
        cmds.warning("All Min values should be less than or equal to corresponding Max values.")
        return

    transformed_count = 0
    for obj in selected_objects:
        if random.random() > prob:
            continue  # Skip this object with probability (1 - prob)

        # Random displacement in X, Y, Z
        dx = random.uniform(min_tx, max_tx)
        dy = random.uniform(min_ty, max_ty)
        dz = random.uniform(min_tz, max_tz)
        cmds.move(dx, dy, dz, obj, relative=True)

        # Random rotation in X, Y, Z
        rx = random.uniform(min_rx, max_rx)
        ry = random.uniform(min_ry, max_ry)
        rz = random.uniform(min_rz, max_rz)
        cmds.rotate(rx, ry, rz, obj, relative=True)

        transformed_count += 1

    print("Random displacement and rotation applied to {} out of {} objects ({}%).".format(transformed_count, len(selected_objects), percentage))

def create_ui():
    if cmds.window("randomTransformWindow", exists=True):
        cmds.deleteUI("randomTransformWindow", window=True)

    window = cmds.window("randomTransformWindow", title="Random Transform Tool", widthHeight=(400, 400))

    cmds.columnLayout(adjustableColumn=True)

    cmds.text(label="Translation Ranges:")
    tx_field = cmds.floatFieldGrp(numberOfFields=2, label="Translate X Min/Max", value1=0, value2=0)
    ty_field = cmds.floatFieldGrp(numberOfFields=2, label="Translate Y Min/Max", value1=0, value2=0)
    tz_field = cmds.floatFieldGrp(numberOfFields=2, label="Translate Z Min/Max", value1=0, value2=0)

    cmds.text(label="Rotation Ranges (degrees):")
    rx_field = cmds.floatFieldGrp(numberOfFields=2, label="Rotate X Min/Max", value1=0, value2=0)
    ry_field = cmds.floatFieldGrp(numberOfFields=2, label="Rotate Y Min/Max", value1=0, value2=0)
    rz_field = cmds.floatFieldGrp(numberOfFields=2, label="Rotate Z Min/Max", value1=0, value2=0)

    cmds.text(label="Percentage to Transform (0-100):")
    percentage_field = cmds.floatFieldGrp(numberOfFields=1, label="%", value1=100.0)

    def apply_button_callback(*args):
        min_tx = cmds.floatFieldGrp(tx_field, query=True, value1=True)
        max_tx = cmds.floatFieldGrp(tx_field, query=True, value2=True)
        min_ty = cmds.floatFieldGrp(ty_field, query=True, value1=True)
        max_ty = cmds.floatFieldGrp(ty_field, query=True, value2=True)
        min_tz = cmds.floatFieldGrp(tz_field, query=True, value1=True)
        max_tz = cmds.floatFieldGrp(tz_field, query=True, value2=True)

        min_rx = cmds.floatFieldGrp(rx_field, query=True, value1=True)
        max_rx = cmds.floatFieldGrp(rx_field, query=True, value2=True)
        min_ry = cmds.floatFieldGrp(ry_field, query=True, value1=True)
        max_ry = cmds.floatFieldGrp(ry_field, query=True, value2=True)
        min_rz = cmds.floatFieldGrp(rz_field, query=True, value1=True)
        max_rz = cmds.floatFieldGrp(rz_field, query=True, value2=True)

        percentage = cmds.floatFieldGrp(percentage_field, query=True, value1=True)

        apply_random_transforms(min_tx, max_tx, min_ty, max_ty, min_tz, max_tz,
                                min_rx, max_rx, min_ry, max_ry, min_rz, max_rz,
                                percentage)

    cmds.button(label="Apply", command=apply_button_callback)
    cmds.button(label="Close", command=('cmds.deleteUI(\"' + window + '\", window=True)'))

    cmds.setParent('..')
    cmds.showWindow(window)

def execute():
    create_ui()