import re
import pymel.core as pm


SIDE_LIST = ["_lf_", "_rt_", "_cn_", "_all_"]
NAME_VARIANTS = ["nameA", "nameB", "nameC"]
HEIGHT = 30
BLUE = [0.3, 0.5, 0.7]
GREEN = [0.5, 0.6, 0.3]
PURPLE = [0.6, 0.4, 0.9]
LIGHT_GREY = [0.7, 0.7, 0.7]


class RenameToolUI(object):
    """The main UI class for the renamer tool."""

    def __init__(self):
        """Initialize the RenamerToolUI object."""
        self.widgets = {}
        self.window = "jwRenameTool"
        self.title = "Rename Tool (Python 3)"
        self.window_width = 600
        self.window_height = 300
        self.dock = False
        self.sizeable = True
        self.allowArea = ["left", "right"]
        self.topColumnWidth = self.window_width - 15

    def show(self):
        """Display the renamer tool UI."""
        if pm.window(self.window, exists=True):
            pm.deleteUI(self.window)

        self.widgets["window"] = pm.window(
            self.window,
            title=self.title,
            sizeable=self.dock or self.sizeable,
            mnb=True,
            mxb=True,
            rtf=True,
            width=self.window_width,
            height=self.window_height,
        )

        # Use a 'with' statement to manage the parent context.
        # This is the modern, compatible way to build PyMEL UIs.
        with self.widgets["window"]:
            self.widgets["master_layout"] = pm.verticalLayout()
            with self.widgets["master_layout"]:
                # initialize_layout will build its UI inside master_layout
                self.initialize_layout()

        # Redistribute Layout
        self.widgets["master_layout"].redistribute(0)

        pm.showWindow(self.window)
        return self.widgets["window"]

    def create_icon_text_button(
            self, button_label, style_type, command, height=False, **options
    ):
        """Create and return a new icon text button."""
        style_options = {"icon": "iconAndTextHorizontal", "text": "textOnly"}
        if height:
            options["height"] = HEIGHT

        return pm.iconTextButton(
            label=button_label,
            style=style_options[style_type],
            commandRepeatable=True,
            enableBackground=True,
            command=command,
            **options
        )

    def make_section(self, section_name, background_color):
        """Create a title section for various areas of the UI."""
        pm.separator(style="shelf")
        pm.text(label=section_name, bgc=background_color)
        pm.separator(style="shelf")

    def initialize_layout(self):
        """Build the UI."""
        # The parent is already set by the 'with' block in show().
        # We remove the 'p' (parent) flag from this call.
        self.widgets["top_level_column"] = pm.columnLayout(
            adj=True,
            rowSpacing=5,
            columnAttach=["both", 5],
        )
        
        # The rest of the function uses pm.setParent(), which is a correct
        # way to change the active parent for the subsequent controls.
        pm.setParent(self.widgets["top_level_column"])
        
        # Naming =====================================
        self.make_section("Naming", BLUE)
        pm.setParent(self.widgets["top_level_column"])
        h_layout = pm.horizontalLayout()

        pm.text(label="Name:")
        for name in NAME_VARIANTS:
            self.widgets[name] = pm.textField(text="", w=150)

        pm.text(label="", w=50)
        pm.text(label="Starting Number:")
        self.widgets["num"] = pm.textField(text="001", w=100)

        self.widgets["side"] = pm.optionMenuGrp(
            label="Side", cw1=30, cw2=(30, 100)
        )
        for side in SIDE_LIST:
            side_label = side.strip("_")
            pm.menuItem(label=side_label)

        h_layout.redistribute(0, 1, 1, 1, 0, 0, 1, 1)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        self.create_icon_text_button(
            "Rename Nodes", "text", pm.Callback(self.rename_nodes_run)
        )
        h_layout.redistribute(1)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        create_group_opts = {"image1": "group.png", "marginWidth": 100}
        self.create_icon_text_button(
            "Create Group",
            "icon",
            pm.Callback(self.add_group_rename_run),
            height=True,
            **create_group_opts
        )
        create_group_on_selection_opts = {
            "image1": "hypergraph.png",
            "marginWidth": 70,
        }
        self.create_icon_text_button(
            "Create Group on Each Selection",
            "icon",
            pm.Callback(self.group_on_each_run),
            height=True,
            **create_group_on_selection_opts
        )
        h_layout.redistribute(1, 1)
        pm.setParent(self.widgets["top_level_column"])

        # Search and Replace =========================
        self.make_section("Search and Replace", GREEN)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        pm.text(label="Search:")
        self.widgets["search"] = pm.textField(text="")
        h_layout.redistribute(0, 5)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        pm.text(label="Replace:")
        self.widgets["replace"] = pm.textField(text="")
        h_layout.redistribute(0, 5)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        replace_name_selection_opts = {
            "image1": "hypergraph.png",
            "marginWidth": 70,
        }
        self.create_icon_text_button(
            "Replace Names on Selections",
            "icon",
            pm.Callback(self.get_search_replace_values, False),
            height=True,
            **replace_name_selection_opts
        )
        replace_name_hierarchy_opts = {
            "image1": "replaceCache.png",
            "marginWidth": 70,
        }
        self.create_icon_text_button(
            "Replace Names on Hierarchy",
            "icon",
            pm.Callback(self.get_search_replace_values, True),
            height=True,
            **replace_name_hierarchy_opts
        )
        h_layout.redistribute(1, 1)
        pm.setParent(self.widgets["top_level_column"])

        # Quick Rename ===============================
        self.make_section("Quick Rename", PURPLE)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        self.create_icon_text_button(
            "Rename Children Mesh",
            "text",
            pm.Callback(self.rename_children_mesh),
        )
        delete_first_character_opts = {
            "image1": "timenext.png",
            "marginWidth": 20,
        }
        self.create_icon_text_button(
            "Delete First Character",
            "icon",
            pm.Callback(self.delete_character, True),
            height=True,
            **delete_first_character_opts
        )
        delete_last_character_opts = {
            "image1": "timeprev.png",
            "marginWidth": 20,
        }
        self.create_icon_text_button(
            "Delete Last Character",
            "icon",
            pm.Callback(self.delete_character),
            height=True,
            **delete_last_character_opts
        )
        h_layout.redistribute(2, 1, 1)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        self.create_icon_text_button(
            "Add Prefix ===>", "text", pm.Callback(self.add_prefix)
        )
        self.widgets["preSuffix"] = pm.textField(text="")
        self.create_icon_text_button(
            "<=== Add Suffix", "text", pm.Callback(self.add_suffix)
        )
        add_auto_suffix_opts = {
            "image1": "hairCacheAppend.png",
            "marginWidth": 20,
            "annotation": "Auto add suffix to geo or group",
        }
        self.create_icon_text_button(
            "Add Auto Suffix",
            "icon",
            pm.Callback(self.add_auto_suffix),
            height=True,
            **add_auto_suffix_opts
        )
        h_layout.redistribute(1, 1, 1, 1)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        delete_prefix_opts = {"image1": "Erase.png", "marginWidth": 75}
        self.create_icon_text_button(
            "Delete Prefix",
            "icon",
            pm.Callback(self.delete_prefix_suffix, "pre"),
            height=True,
            **delete_prefix_opts
        )
        delete_suffix_opts = {
            "image1": "hairCacheTruncate.png",
            "marginWidth": 75,
        }
        self.create_icon_text_button(
            "Delete Suffix",
            "icon",
            pm.Callback(self.delete_prefix_suffix, "suf"),
            height=True,
            **delete_suffix_opts
        )
        add_pivot_suffix_opts = {
            "image1": "CenterPivot.png",
            "marginWidth": 20,
        }
        self.create_icon_text_button(
            "Add pivot suffix",
            "icon",
            pm.Callback(self.add_pivot_suffix),
            height=True,
            **add_pivot_suffix_opts
        )
        h_layout.redistribute(3, 3, 2)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        pm.text(label="Rename Side To:")
        for side_name in SIDE_LIST:
            side_label = side_name.split("_")[1]
            self.create_icon_text_button(
                side_label,
                "text",
                pm.Callback(self.set_side_suffix, side_name),
            )
        h_layout.redistribute(0, 1, 1, 1, 1)
        pm.setParent(self.widgets["top_level_column"])

        # Extra miscellaneous functionality ==========
        self.make_section("Extra", LIGHT_GREY)
        pm.setParent(self.widgets["top_level_column"])

        h_layout = pm.horizontalLayout()
        create_all_groups_opts = {
            "annotation": "Get the name from first selection"
        }
        self.create_icon_text_button(
            "Create All Group",
            "text",
            pm.Callback(self.add_suffix_to_group),
            height=True,
            **create_all_groups_opts
        )
        create_pivot_group_opts = {
            "annotation": "Get name and pivot from the first selection"
        }
        self.create_icon_text_button(
            "Create Pivot Group",
            "text",
            pm.Callback(self.add_suffix_to_group, True),
            height=True,
            **create_pivot_group_opts
        )
        h_layout.redistribute(1)
        pm.setParent(self.widgets["top_level_column"])
        pm.separator(style="none", h=20)
        pm.separator(style="in")
        pm.text(label="Written by JIWON LEE", al="right")
        pm.separator(style="in")

    def get_name_values(self):
        """Fetch the values entered in the name fields."""
        values_dict = dict()
        for name in NAME_VARIANTS:
            values_dict[name] = self.widgets[name].getText()
        values_dict["num"] = str(self.widgets["num"].getText())
        values_dict["side"] = self.widgets["side"].getValue()
        return values_dict

    def get_geo(self, nodes):
        """Filter the nodes in the selected group(s) for meshes only."""
        mesh_nodes = list()
        for node in nodes:
            shape = node.getShape()
            if shape is not None and shape.type() == "mesh":
                mesh_nodes.append(node)
        return mesh_nodes

    def rename_nodes_run(self):
        """Run the rename nodes logic."""
        values = self.get_name_values()
        self.rename_nodes(pm.selected(), **values)

    def add_group_rename_run(self):
        """Run the add group to selection logic."""
        values = self.get_name_values()
        self.add_group_on_selection(pm.selected(), **values)

    def get_parent_nodes(self, node_list):
        """Given a list of nodes, return the number of parent nodes."""
        if not node_list:
            return 0, None
        parent_list = list()
        parent_node = node_list[0].getParent()
        for node in node_list:
            if not node.getParent() == parent_node:
                parent_list.append(node.getParent())
        return len(parent_list), parent_node

    def add_suffix_to_group(self, pivot_group=False):
        """Group selected into a new group with the proper suffix."""
        nodes = pm.selected()
        if not nodes:
            pm.warning("Please select one or more objects to group.")
            return
            
        parent_list_length, parent_node = self.get_parent_nodes(nodes)
        if not pivot_group:
            name = "%s_all_grp" % str(nodes[0]).split("_")[0]
        else:
            name = "%s_pivot_grp" % str(nodes[0]).split("_")[0]
        group = pm.group(em=1, n=name)
        if pivot_group:
            pm.delete(pm.parentConstraint(nodes[0], group, mo=0))
        pm.parent(nodes, group)
        if parent_list_length == 0 and parent_node is not None:
            pm.parent(group, parent_node)

    def get_search_replace_values(self, hierarchy):
        """Fetch the search and replace text field values."""
        search_name = self.widgets["search"].getText()
        replace_name = self.widgets["replace"].getText()
        self.search_replace(pm.selected(), search_name, replace_name, hierarchy)

    def group_on_each_run(self):
        """Group each node to a new group."""
        nodes = pm.selected()
        for node in nodes:
            parent_node = node.getParent()
            name = str(node).replace(str(node).split("_")[-1], "grp")
            nums = re.findall(r"\d+", name)
            name_val = name.split("_")
            for num in nums:
                try:
                    ind = name_val.index(num)
                    name_val.pop(ind)
                except ValueError:
                    continue # number not in list
            group_name = "_".join(name_val)
            group = pm.group(em=1, n=group_name)
            pm.parent(node, group)
            if parent_node:
                pm.parent(group, parent_node)

    def rename_children_mesh(self):
        """Rename each mesh within a group to the name of the parent group."""
        groups = pm.selected()
        for group in groups:
            nodes = group.getChildren()
            mesh_nodes = self.get_geo(nodes)
            name = str(group).split("_")[0]
            new_side = None
            for side_name in SIDE_LIST:
                if side_name in str(group):
                    new_side = side_name.strip("_")
                    break
            if new_side is None:
                new_side = "cn"
                name = str(group)[:-4] if str(group).endswith("_grp") else str(group)
            
            for index, node in enumerate(mesh_nodes):
                number = str(index + 1).zfill(3)
                new_name = "{name}_{number}_{side}_geo".format(
                    name=name, number=number, side=new_side
                )
                pm.rename(node, new_name)

    def set_side_suffix(self, new_side):
        """Rename selected nodes to the new side suffix."""
        self.rename_side(pm.selected(), new_side)

    def add_prefix(self):
        """Add prefix to selected transform nodes."""
        prefix = self.widgets["preSuffix"].getText()
        nodes = pm.selected(type="transform")
        for node in nodes:
            pm.rename(node, "_".join([prefix, node.name()]))

    def add_suffix(self):
        """Add suffix to selected transform nodes."""
        suffix = self.widgets["preSuffix"].getText()
        nodes = pm.selected(type="transform")
        for node in nodes:
            pm.rename(node, "_".join([node.name(), suffix]))

    def add_auto_suffix(self):
        """Add the proper suffix based on the type of the node."""
        nodes = pm.selected(type="transform")
        for node in nodes:
            node_type = self.get_type(node)
            if str(node).split("_")[-1] != node_type:
                pm.rename(node, "_".join([node.name(), node_type]))

    def add_pivot_suffix(self):
        """Add `pivot` suffix to selected transform nodes."""
        nodes = pm.selected(type="transform")
        for node in nodes:
            node_type = self.get_type(node)
            node_name = "_".join(node.name().split("_")[:-1])
            suffix = str(node).split("_")[-1]
            if node_type != "grp":
                continue
            if not any((suffix == node_type, str(node).split("_")[-1] == "pivot")):
                pm.rename(node, "_".join([node.name(), "pivot_grp"]))
            elif suffix == "pivot":
                pm.rename(node, "_".join([node.name(), "grp"]))
            elif suffix == node_type:
                if "pivot_grp" not in str(str(node).split("|")[-1]):
                    pm.rename(node, node_name + "_pivot_grp")

    def delete_character(self, delete_first_character=False):
        """Delete the first or last character of the selected node(s)."""
        for node in pm.selected():
            if not delete_first_character:
                new_name = str(node)[:-1]
            else:
                new_name = str(node)[1:]
            pm.rename(node, new_name)

    def delete_prefix_suffix(self, part):
        """Delete the prefix or suffix of the selected node(s)."""
        nodes = pm.selected()
        for node in nodes:
            if part == "pre":
                new_name = "_".join(str(node).split("_")[1:])
            elif part == "suf":
                new_name = "_".join(str(node).split("_")[:-1])
            pm.rename(node, new_name)

    def get_name(self, name_a, name_b, name_c):
        """Fetch the text field values for the new name of the selected node(s)."""
        if not name_a:
            pm.error("Please add a name first!")
        return name_a + name_b.capitalize() + name_c.capitalize()

    def get_type(self, node):
        """Get the type of the selected node."""
        shape = node.getShape()
        if shape is None:
            suffix = "grp"
        elif shape.type() == "mesh":
            suffix = "geo"
        elif shape.type() == "locator":
            suffix = "loc"
        else:
            suffix = "null"
        return suffix

    def rename_nodes(self, nodes, **options):
        """Rename the selected node(s) given keyword options passed in."""
        for index, node in enumerate(nodes):
            node_type = self.get_type(node)
            name = self.get_name(
                options["nameA"], options["nameB"], options["nameC"]
            )
            if not options["num"] or node_type == "grp":
                pm.rename(node, "_".join([name, options["side"], node_type]))
            else:
                number = str(int(options["num"]) + index).zfill(
                    len(options["num"])
                )
                pm.rename(
                    node, "_".join([name, number, options["side"], node_type])
                )

    def add_group_on_selection(self, nodes, **name_values):
        """Create a group and place the selected nodes inside."""
        parent_list_length, parent_node = self.get_parent_nodes(nodes)
        name = self.get_name(
            name_values["nameA"], name_values["nameB"], name_values["nameC"]
        )
        group = pm.group(em=1, n="%s_%s_grp" % (name, name_values["side"]))
        if nodes:
            pm.parent(nodes, group)
        if parent_list_length == 0 and parent_node is not None:
            pm.parent(group, parent_node)

    def search_replace(self, nodes, name, new_name, hierarchy):
        """Search and replace names on selection or hierarchy."""
        if not name:
            pm.warning("Search field is empty.")
            return

        for node in nodes:
            if not hierarchy:
                pm.rename(node, str(node).replace(name, new_name))
                continue
                
            child_list = node.listRelatives(allDescendents=True, type='transform')
            child_list.reverse()
            child_list.append(node)
            
            for child in child_list:
                try:
                    pm.rename(child, str(child).replace(name, new_name))
                except RuntimeError as e:
                    pm.warning("Could not rename {}: {}".format(child, e))


    def rename_side(self, nodes, new_side):
        """Rename the side suffix."""
        for node in nodes:
            old_side_found = False
            for side in SIDE_LIST:
                if side in str(node):
                    pm.rename(node, str(node).replace(side, new_side))
                    old_side_found = True
                    break

            if not old_side_found:
                parts = str(node).split("_")
                if len(parts) > 1:
                    name = "_".join(parts[:-1]) + new_side + parts[-1]
                    pm.rename(node, name)

def get_command():
    """Return the command function to show the rename tool UI."""
    def _command():
        try:
            tool = RenameToolUI()
            tool.show()
        except Exception as e:
            import maya.cmds as cmds
            cmds.warning(f"Error in Rename Tool command: {str(e)}")
            raise
            
    return _command

def execute():
    """Execute the command with module reloading."""
    try:
        import importlib
        importlib.reload(sys.modules[__name__])
    except Exception as e:
        print(f"Could not reload module: {e}")
        
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    """
    This block allows the script to be run directly in Maya's Script Editor.
    It creates an instance of the UI and shows it.
    """
    tool = RenameToolUI()
    tool.show()
