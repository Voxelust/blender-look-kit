bl_info = {
    "name": "Look Kit (ink outlines, light rig, render preset, grade)",
    "author": "you",
    "version": (0, 1, 4),
    "blender": (4, 2, 0),
    "location": "3D Viewport > N panel > Look Kit",
    "description": "One-click ink outlines, a warm/cool light rig, a render preset and a simple grade",
    "category": "Render",
}

# HOW TO USE
#   Quick: Scripting workspace > Open this file > Run Script. A "Look Kit" tab
#          appears in the 3D Viewport sidebar (press N).
#   Permanent: Edit > Preferences > Add-ons > Install from Disk > pick this file.
#
# Written for Blender 4.2 through 5.x. It was not possible to test it inside
# Blender while writing it, so if a button errors, open Window > Toggle System
# Console (Windows) or check the terminal, and send me the message.

import bpy
from mathutils import Vector

OUTLINE_MOD = "LK_Outline"
OUTLINE_MAT = "LK_Outline_Mat"
DEFAULT_MAT = "LK_Default_Mat"
LIGHT_COLLECTION = "LK_Lights"
TARGET_NAME = "LK_Target"
FS_COLLECTION = "LK_Outline_Set"
LINE_GROUP = "LK_Line"  # optional vertex group: weight 1 = full line, 0 = thin line


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _is_5_plus():
    return bpy.app.version >= (5, 0, 0)


def _try_set(owner, name, value):
    try:
        setattr(owner, name, value)
        return True
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False


def _prop_or_socket(node, names, value, socket_names=None):
    """Set a node setting whether this Blender version stores it as a property
    or as an input socket. Returns True if something took the value."""
    candidates = [value]
    if isinstance(value, tuple) and len(value) == 3:
        candidates.append(value + (1.0,))
    for name in names:
        if hasattr(node, name):
            for v in candidates:
                if _try_set(node, name, v):
                    return True
    for sname in (socket_names or names):
        sock = node.inputs.get(sname) if hasattr(node, "inputs") else None
        if sock is not None and hasattr(sock, "default_value"):
            for v in candidates:
                try:
                    sock.default_value = v
                    return True
                except (TypeError, ValueError, AttributeError):
                    pass
    return False


def _set_enum_socket(sock, candidates):
    for v in candidates:
        try:
            sock.default_value = v
            return True
        except (TypeError, ValueError, AttributeError):
            pass
    return False


def _set_by_keyword(node, prop_names, keywords, value):
    """Set `value` on a node property AND on any input socket whose name contains
    one of `keywords` (case-insensitive). Handles 3- and 4-value colors."""
    done = _prop_or_socket(node, prop_names, value, [])
    candidates = [value]
    if isinstance(value, tuple) and len(value) == 3:
        candidates.append(value + (1.0,))
    for sock in node.inputs:
        lname = sock.name.lower()
        if any(k in lname for k in keywords) and hasattr(sock, "default_value"):
            for v in candidates:
                try:
                    sock.default_value = v
                    done = True
                    break
                except (TypeError, ValueError, AttributeError):
                    pass
    return done


def _selected_meshes(context):
    return [o for o in context.selected_objects if o.type == "MESH"]


def _selection_bounds(objs):
    pts = []
    for o in objs:
        for corner in o.bound_box:
            pts.append(o.matrix_world @ Vector(corner))
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return (mn + mx) / 2.0, (mx - mn)


def _ensure_material_nodes(mat):
    if not _is_5_plus():
        mat.use_nodes = True
    if mat.node_tree is None:  # safety net
        mat.use_nodes = True


# ----------------------------------------------------------------------------
# settings
# ----------------------------------------------------------------------------
class LK_Props(bpy.types.PropertyGroup):
    outline_thickness: bpy.props.FloatProperty(
        name="Line thickness (m)",
        description="World-space thickness of the ink line. ~0.002 close-ups, ~0.004 full body",
        default=0.003, min=0.0002, max=0.03, precision=4, step=5,
    )
    outline_color: bpy.props.FloatVectorProperty(
        name="Line color", subtype="COLOR", size=3, min=0.0, max=1.0,
        default=(0.03, 0.015, 0.012),
        description="Dark brown reads as 'inked' but a bit more natural than pure black",
    )
    light_scale: bpy.props.FloatProperty(
        name="Light intensity x", default=1.0, min=0.05, max=20.0,
        description="Multiplies all rig lights",
    )
    world_strength: bpy.props.FloatProperty(
        name="World strength", default=0.2, min=0.0, max=5.0,
        description="Dims the environment lighting so your rig lights lead",
    )
    engine: bpy.props.EnumProperty(
        name="Engine",
        items=[("CYCLES", "Cycles", "Slower, most realistic"),
               ("EEVEE", "EEVEE", "Fast, good for animation")],
        default="CYCLES",
    )
    dispersion: bpy.props.FloatProperty(
        name="Edge color fringe", default=0.02, min=0.0, max=0.2,
        description="Chromatic-aberration look from the reference images",
    )
    fs_thickness: bpy.props.FloatProperty(
        name="Freestyle line (px)", default=2.0, min=0.5, max=10.0,
        description="Line width in pixels for the Freestyle outline method",
    )


# ----------------------------------------------------------------------------
# 1. outlines (inverted hull: works in EEVEE and Cycles, stable in animation)
# ----------------------------------------------------------------------------
def _get_outline_material(color):
    mat = bpy.data.materials.get(OUTLINE_MAT) or bpy.data.materials.new(OUTLINE_MAT)
    _ensure_material_nodes(mat)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mix = nt.nodes.new("ShaderNodeMixShader")
    emit.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
    emit.inputs["Strength"].default_value = 1.0
    # The shell is only visible to the CAMERA and only on its far (front-facing)
    # side, where it peeks out around the silhouette as the line. Everything else
    # (shadow rays, bounce light, reflections, back-facing side) sees straight
    # through it. Without this the closed shell blocks every light from reaching
    # the character and the whole model renders dark.
    light = nt.nodes.new("ShaderNodeLightPath")
    not_cam = nt.nodes.new("ShaderNodeMath")
    not_cam.operation = "SUBTRACT"
    not_cam.inputs[0].default_value = 1.0
    hide = nt.nodes.new("ShaderNodeMath")
    hide.operation = "MAXIMUM"
    nt.links.new(light.outputs["Is Camera Ray"], not_cam.inputs[1])
    nt.links.new(geo.outputs["Backfacing"], hide.inputs[0])
    nt.links.new(not_cam.outputs["Value"], hide.inputs[1])
    nt.links.new(hide.outputs["Value"], mix.inputs["Fac"])
    nt.links.new(emit.outputs["Emission"], mix.inputs[1])
    nt.links.new(trans.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    _try_set(mat, "use_backface_culling", True)
    # EEVEE shadow settings so the shell doesn't shadow the character
    _try_set(mat, "use_backface_culling_shadow", True)
    _try_set(mat, "use_transparent_shadow", True)
    _try_set(mat, "shadow_method", "NONE")  # older EEVEE only
    _try_set(mat, "blend_method", "HASHED")  # older EEVEE only; ignored elsewhere
    return mat


def _remove_outline(ob):
    mod = ob.modifiers.get(OUTLINE_MOD)
    if mod:
        ob.modifiers.remove(mod)
    mat = bpy.data.materials.get(OUTLINE_MAT)
    if mat and ob.type == "MESH":
        for i, m in enumerate(ob.data.materials):
            if m == mat:
                ob.data.materials.pop(index=i)
                break


class LK_OT_add_outlines(bpy.types.Operator):
    bl_idname = "look_kit.add_outlines"
    bl_label = "Add Outlines to Selected"
    bl_description = "Adds an ink outline to every selected mesh (re-run to update thickness/color)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.scene.look_kit
        meshes = _selected_meshes(context)
        if not meshes:
            self.report({"ERROR"}, "Select the character meshes first (not the whole environment).")
            return {"CANCELLED"}
        mat = _get_outline_material(p.outline_color)
        for ob in meshes:
            _remove_outline(ob)
            # Some models have faces pointing at a slot number past the end of the
            # list (Blender quietly shows them with the last slot). Adding the outline
            # slot would make those faces turn into the outline material, so pin them
            # to the real last slot first.
            n_before = len(ob.data.materials)
            if n_before > 0:
                polys = ob.data.polygons
                idxs = [0] * len(polys)
                polys.foreach_get("material_index", idxs)
                fixed = [min(i, n_before - 1) for i in idxs]
                if fixed != idxs:
                    polys.foreach_set("material_index", fixed)
                    ob.data.update()
            if len(ob.data.materials) == 0:
                dm = bpy.data.materials.get(DEFAULT_MAT) or bpy.data.materials.new(DEFAULT_MAT)
                ob.data.materials.append(dm)
            ob.data.materials.append(mat)
            idx = len(ob.data.materials) - 1  # outline slot is last

            scale = sum(ob.matrix_world.to_scale()) / 3.0
            scale = scale if scale > 1e-6 else 1.0

            mod = ob.modifiers.new(OUTLINE_MOD, "SOLIDIFY")
            mod.thickness = p.outline_thickness / scale
            mod.offset = 1.0
            mod.use_flip_normals = True
            mod.use_quality_normals = True
            mod.use_rim = True
            # push every shell face to the outline slot (indices past the last
            # slot fall back to the last slot)
            mod.material_offset = idx
            mod.material_offset_rim = idx
            if LINE_GROUP in ob.vertex_groups:
                mod.vertex_group = LINE_GROUP
                mod.thickness_vertex_group = 0.3
        self.report({"INFO"}, "Outlines added to %d object(s)." % len(meshes))
        return {"FINISHED"}


class LK_OT_remove_outlines(bpy.types.Operator):
    bl_idname = "look_kit.remove_outlines"
    bl_label = "Remove Outlines from Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for ob in _selected_meshes(context):
            _remove_outline(ob)
        return {"FINISHED"}


class LK_OT_freestyle_on(bpy.types.Operator):
    bl_idname = "look_kit.freestyle_on"
    bl_label = "Freestyle Outlines (selected)"
    bl_description = ("Render-time ink lines that never touch your materials or meshes. "
                      "They only show in F12 renders, not in the viewport")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.look_kit
        meshes = _selected_meshes(context)
        if not meshes:
            self.report({"ERROR"}, "Select the character meshes first.")
            return {"CANCELLED"}

        coll = bpy.data.collections.get(FS_COLLECTION) or bpy.data.collections.new(FS_COLLECTION)
        for o in list(coll.objects):
            coll.objects.unlink(o)
        for o in meshes:
            coll.objects.link(o)

        scene.render.use_freestyle = True
        _try_set(scene.render, "line_thickness_mode", "ABSOLUTE")
        vl = context.view_layer
        vl.use_freestyle = True
        fs = vl.freestyle_settings
        lineset = fs.linesets.get("LK_Lines") or fs.linesets.new("LK_Lines")
        style = bpy.data.linestyles.get("LK_Line_Style") or bpy.data.linestyles.new("LK_Line_Style")
        style.color = tuple(p.outline_color)
        style.thickness = p.fs_thickness
        lineset.linestyle = style
        lineset.select_by_visibility = True
        lineset.select_silhouette = True
        lineset.select_border = True
        lineset.select_contour = True
        lineset.select_crease = True
        lineset.select_material_boundary = False
        lineset.select_by_collection = True
        lineset.collection = coll
        self.report({"INFO"}, "Freestyle outlines on. Press F12 to see them (not shown in the viewport).")
        return {"FINISHED"}


class LK_OT_freestyle_off(bpy.types.Operator):
    bl_idname = "look_kit.freestyle_off"
    bl_label = "Turn Freestyle Off"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.render.use_freestyle = False
        return {"FINISHED"}


# ----------------------------------------------------------------------------
# 2. light rig (warm key, cool fill, teal rim, warm kicker) + dim the world
# ----------------------------------------------------------------------------
class LK_OT_build_lights(bpy.types.Operator):
    bl_idname = "look_kit.build_lights"
    bl_label = "Build Light Rig for Selected"
    bl_description = "Places key/fill/rim/kicker lights around the selected characters, relative to the active camera"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.look_kit
        cam = scene.camera
        if cam is None:
            self.report({"ERROR"}, "Set an active camera first.")
            return {"CANCELLED"}
        objs = _selected_meshes(context)
        if not objs:
            self.report({"ERROR"}, "Select the character meshes first.")
            return {"CANCELLED"}

        center, size = _selection_bounds(objs)
        dist = max(size.length, 0.8) * 1.4

        coll = bpy.data.collections.get(LIGHT_COLLECTION)
        if coll is None:
            coll = bpy.data.collections.new(LIGHT_COLLECTION)
            scene.collection.children.link(coll)
        for o in list(coll.objects):
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if isinstance(data, bpy.types.Light) and data.users == 0:
                bpy.data.lights.remove(data)

        target = bpy.data.objects.new(TARGET_NAME, None)
        target.empty_display_type = "PLAIN_AXES"
        target.location = center
        coll.objects.link(target)

        cam_rot = cam.matrix_world.to_3x3()
        right = (cam_rot @ Vector((1, 0, 0))).normalized()
        up = Vector((0, 0, 1))
        toward = cam.matrix_world.translation - center
        toward = toward.normalized() if toward.length > 1e-6 else Vector((0, -1, 0))

        def place(t, r, u):
            v = toward * t + right * r + up * u
            if v.length < 1e-6:
                v = toward
            return center + v.normalized() * dist

        energy_scale = (dist / 3.0) ** 2 * p.light_scale
        specs = [
            # name,          (toward cam, right, up),  color,              watts
            ("LK_Key",       (0.8, -0.7, 0.6),  (1.00, 0.78, 0.58), 900),
            ("LK_Fill",      (0.9, 0.9, -0.1),  (0.55, 0.72, 1.00), 220),
            ("LK_Rim_Teal",  (-0.9, 0.7, 0.5),  (0.35, 0.90, 1.00), 700),
            ("LK_Kick_Warm", (-0.9, -0.8, 0.3), (1.00, 0.55, 0.30), 450),
        ]
        for name, (t, r, u), color, watts in specs:
            ld = bpy.data.lights.new(name, "AREA")
            ld.shape = "DISK"
            ld.size = dist * 0.5
            ld.color = color
            ld.energy = watts * energy_scale
            ob = bpy.data.objects.new(name, ld)
            coll.objects.link(ob)
            ob.location = place(t, r, u)
            con = ob.constraints.new("TRACK_TO")
            con.target = target
            con.track_axis = "TRACK_NEGATIVE_Z"
            con.up_axis = "UP_Y"
        self.report({"INFO"}, "Light rig built. Adjust 'Light intensity x' and re-run if too bright/dark.")
        return {"FINISHED"}


class LK_OT_dim_world(bpy.types.Operator):
    bl_idname = "look_kit.dim_world"
    bl_label = "Dim World Lighting"
    bl_description = "Sets the world/HDRI Background strength so your rig lights lead"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        world = scene.world
        if world is None:
            world = bpy.data.worlds.new("World")
            scene.world = world
        if not _is_5_plus():
            world.use_nodes = True
        bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
        if bg is None:
            self.report({"WARNING"}, "No Background node found in the world; set its strength by hand.")
            return {"CANCELLED"}
        bg.inputs["Strength"].default_value = scene.look_kit.world_strength
        return {"FINISHED"}


# ----------------------------------------------------------------------------
# 3. render preset (image or animation)
# ----------------------------------------------------------------------------
class LK_OT_render_preset(bpy.types.Operator):
    bl_idname = "look_kit.render_preset"
    bl_label = "Apply Render Preset"
    bl_description = "Sets engine, sampling, denoising, color management and 16-bit PNG output"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.look_kit
        r = scene.render

        if p.engine == "CYCLES":
            r.engine = "CYCLES"
            c = scene.cycles
            _try_set(c, "samples", 256)
            _try_set(c, "use_adaptive_sampling", True)
            _try_set(c, "adaptive_threshold", 0.01)
            _try_set(c, "use_denoising", True)
            _try_set(c, "denoiser", "OPENIMAGEDENOISE")
            _try_set(c, "denoising_input_passes", "RGB_ALBEDO_NORMAL")
            _try_set(c, "max_bounces", 8)
            _try_set(c, "sample_clamp_indirect", 10.0)
            _try_set(c, "device", "GPU")
        else:
            ids = {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
            r.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in ids else "BLENDER_EEVEE"
            e = scene.eevee
            _try_set(e, "taa_render_samples", 128)
            _try_set(e, "use_raytracing", True)
            _try_set(e, "use_shadows", True)

        vs = scene.view_settings
        if not _try_set(vs, "view_transform", "AgX"):
            _try_set(vs, "view_transform", "Filmic")
        for look in ("AgX - Medium High Contrast", "Medium High Contrast", "Filmic - Medium High Contrast"):
            if _try_set(vs, "look", look):
                break

        r.image_settings.file_format = "PNG"
        _try_set(r.image_settings, "color_depth", "16")
        r.film_transparent = False
        self.report({"INFO"}, "Render preset applied. For video, render a PNG sequence and encode it afterwards.")
        return {"FINISHED"}


# ----------------------------------------------------------------------------
# 4. compositor grade: soft glow, edge color fringe, teal shadows / warm highlights
# ----------------------------------------------------------------------------
def _get_comp_tree(scene):
    if hasattr(scene, "compositing_node_group"):  # Blender 5.0+
        tree = scene.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new("LK_Compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        return tree
    scene.use_nodes = True
    return scene.node_tree


class LK_OT_compositor(bpy.types.Operator):
    bl_idname = "look_kit.compositor"
    bl_label = "Set Up Compositor Grade"
    bl_description = "Replaces the compositor setup with glow + color fringe + color balance"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        p = scene.look_kit
        tree = _get_comp_tree(scene)
        scene.render.use_compositing = True
        tree.nodes.clear()
        nodes, links = tree.nodes, tree.links

        rl = nodes.new("CompositorNodeRLayers")
        if hasattr(rl, "scene") and rl.scene is None:
            rl.scene = scene
        rl.location = (-600, 0)

        last = rl.outputs["Image"]
        x = -350
        skipped = []

        def add_effect(idname, label, setup):
            nonlocal last, x
            node = nodes.new(idname)
            node.location = (x, 0)
            ok = setup(node)
            if not ok:
                print("[Look Kit] could not configure", idname,
                      "| inputs:", [s.name for s in node.inputs],
                      "| props:", [pr.identifier for pr in node.bl_rna.properties
                                   if pr.identifier not in ("rna_type", "name", "label")])
                nodes.remove(node)
                skipped.append(label)
                return
            links.new(last, node.inputs["Image"])
            last = node.outputs["Image"]
            x += 250

        def setup_glare(n):
            typed = False
            for gtype in ("BLOOM", "FOG_GLOW"):
                if hasattr(n, "glare_type") and _try_set(n, "glare_type", gtype):
                    typed = True
                    break
            if not typed:  # newer Blender: glare type is a menu input socket
                for sock in n.inputs:
                    if sock.name.lower() == "type" and _set_enum_socket(
                        sock, ["Bloom", "BLOOM", "Fog Glow", "FOG_GLOW"]
                    ):
                        typed = True
                        break
            if not typed:
                return False
            _prop_or_socket(n, ["quality"], "HIGH")
            _set_by_keyword(n, ["threshold"], ("threshold",), 0.8)
            if any(s.name.lower() == "strength" for s in n.inputs):
                _set_by_keyword(n, [], ("strength",), 0.35)
            else:
                _prop_or_socket(n, ["mix"], -0.7)
            return True

        def setup_lens(n):
            ok = _prop_or_socket(n, ["dispersion"], p.dispersion, ["Dispersion"])
            _prop_or_socket(n, ["use_fit"], True)
            return ok

        def setup_balance(n):
            _prop_or_socket(n, ["correction_method"], "LIFT_GAMMA_GAIN")
            a = _set_by_keyword(n, ["lift"], ("lift",), (0.95, 1.0, 1.04))
            b = _set_by_keyword(n, ["gain"], ("gain",), (1.05, 1.0, 0.94))
            return a or b

        add_effect("CompositorNodeGlare", "glow", setup_glare)
        add_effect("CompositorNodeLensdist", "color fringe", setup_lens)
        add_effect("CompositorNodeColorBalance", "color balance", setup_balance)

        if hasattr(scene, "compositing_node_group"):  # 5.0+: Group Output replaces Composite
            has_out = any(getattr(i, "in_out", "") == "OUTPUT" for i in tree.interface.items_tree)
            if not has_out:
                tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            out = nodes.new("NodeGroupOutput")
            out.location = (x, 0)
            links.new(last, out.inputs[0])
        else:
            out = nodes.new("CompositorNodeComposite")
            out.location = (x, 0)
            links.new(last, out.inputs["Image"])

        if skipped:
            self.report({"WARNING"}, "Skipped (settings differ in this Blender version): " + ", ".join(skipped))
        else:
            self.report({"INFO"}, "Compositor grade set up.")
        return {"FINISHED"}


class LK_OT_compositor_off(bpy.types.Operator):
    bl_idname = "look_kit.compositor_off"
    bl_label = "Turn Compositor Off"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.render.use_compositing = False
        return {"FINISHED"}


# ----------------------------------------------------------------------------
# panel
# ----------------------------------------------------------------------------
class LK_PT_panel(bpy.types.Panel):
    bl_label = "Look Kit"
    bl_idname = "LK_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Look Kit"

    def draw(self, context):
        p = context.scene.look_kit
        col = self.layout.column(align=True)

        box = col.box()
        box.label(text="1. Ink outlines (select characters)")
        box.prop(p, "outline_thickness")
        box.prop(p, "outline_color")
        row = box.row(align=True)
        row.operator("look_kit.add_outlines", icon="MOD_SOLIDIFY")
        row.operator("look_kit.remove_outlines", text="", icon="X")
        box.label(text="Alternative if the model turns brown:")
        box.prop(p, "fs_thickness")
        row = box.row(align=True)
        row.operator("look_kit.freestyle_on", icon="LINE_DATA")
        row.operator("look_kit.freestyle_off", text="", icon="X")

        box = col.box()
        box.label(text="2. Lights (select characters, camera set)")
        box.prop(p, "light_scale")
        box.operator("look_kit.build_lights", icon="LIGHT_AREA")
        box.prop(p, "world_strength")
        box.operator("look_kit.dim_world", icon="WORLD")

        box = col.box()
        box.label(text="3. Render preset")
        box.prop(p, "engine")
        box.operator("look_kit.render_preset", icon="RENDER_STILL")

        box = col.box()
        box.label(text="4. Grade (compositor)")
        box.prop(p, "dispersion")
        row = box.row(align=True)
        row.operator("look_kit.compositor", icon="NODE_COMPOSITING")
        row.operator("look_kit.compositor_off", text="", icon="X")


classes = (
    LK_Props,
    LK_OT_add_outlines,
    LK_OT_remove_outlines,
    LK_OT_freestyle_on,
    LK_OT_freestyle_off,
    LK_OT_build_lights,
    LK_OT_dim_world,
    LK_OT_render_preset,
    LK_OT_compositor,
    LK_OT_compositor_off,
    LK_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.look_kit = bpy.props.PointerProperty(type=LK_Props)


def unregister():
    try:
        del bpy.types.Scene.look_kit
    except Exception:
        pass
    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass


if __name__ == "__main__":
    unregister()  # lets you re-run the script from the Text Editor
    register()
