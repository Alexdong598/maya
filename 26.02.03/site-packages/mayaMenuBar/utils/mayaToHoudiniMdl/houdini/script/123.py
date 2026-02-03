import hou

# 创建OBJ层级的geo节点
obj = hou.node("/obj")
geo_node = obj.createNode("geo", "my_geo")

# 在geo节点内创建sphere节点
sphere_node = geo_node.createNode("sphere", "my_sphere")

# 创建transform节点并连接输入
transform_node = geo_node.createNode("xform", "my_transform")
transform_node.setInput(0, sphere_node)

# 设置transform节点的tx参数为20
transform_node.parm("tx").set(20)

# 创建color节点并连接输入
color_node = geo_node.createNode("color", "my_color")
color_node.setInput(0, transform_node)

# 设置color节点的颜色参数
color_node.parm("colorr").set(1)
color_node.parm("colorg").set(0)
color_node.parm("colorb").set(0)

# 设置color节点为显示节点
color_node.setDisplayFlag(True)

# 布局节点以便于查看
geo_node.layoutChildren()    