"""Build editable, metre-scale research scenes using Blender's own Python.

Run with: blender --background --python blender/build_scene.py -- --help
No third-party assets or Python packages beyond Blender's bundled numpy required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

import bpy
from mathutils import Matrix, Vector
import numpy as np


SCENE_VERSION = "procedural-1.0"
MATERIALS = {}


def material(name, color, roughness=.5, metallic=0., noise=0., scale=8., emission=0.):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    if noise:
        coords = nodes.new("ShaderNodeTexCoord")
        texture = nodes.new("ShaderNodeTexNoise")
        texture.inputs["Scale"].default_value = scale
        texture.inputs["Detail"].default_value = 4
        links.new(coords.outputs["Object"], texture.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = .12
        ramp.color_ramp.elements[0].color = (*(max(c * (1-noise), .005) for c in color), 1)
        ramp.color_ramp.elements[1].position = .88
        ramp.color_ramp.elements[1].color = (*(min(c * (1+noise), 1.) for c in color), 1)
        links.new(texture.outputs["Fac"], ramp.inputs[0])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = .3
        bump.inputs["Distance"].default_value = .012 if name == "concrete" else .002
        links.new(texture.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    MATERIALS[name] = mat
    return mat


def setup_materials():
    material("concrete", (.36, .38, .39), .82, noise=.35, scale=14)
    material("paint", (.68, .68, .62), .84, noise=.08, scale=8)
    material("metal", (.20, .24, .27), .3, .85, .2, 25)
    material("orange", (.72, .19, .025), .35, .45, .06)
    material("blue", (.025, .15, .28), .36, .55, .12)
    material("yellow", (.85, .56, .035), .4, .25)
    material("cardboard", (.41, .24, .10), .94, noise=.25, scale=30)
    material("tape", (.66, .49, .22), .44, noise=.08)
    material("wood", (.28, .15, .065), .8, noise=.5, scale=18)
    material("black", (.016, .019, .023), .45, noise=.25)
    material("white", (.75, .77, .79), .5)
    material("screen", (.025, .15, .23), .3, emission=.4)
    material("light", (.91, .95, 1), .3, emission=5)
    material("window", (.50, .68, .83), .25, emission=.6)
    material("asphalt", (.075, .081, .085), .95, noise=.5, scale=26)
    material("brick", (.36, .15, .09), .9, noise=.3)
    material("leaf", (.045, .17, .035), .9, noise=.5)
    material("bark", (.12, .07, .035), .95, noise=.6)
    material("red", (.45, .025, .018), .33, .4)


def assign(obj, mat, semantic=None):
    obj.data.materials.append(MATERIALS[mat])
    obj["semantic_class"] = semantic or mat
    return obj


def box(name, pos, size, mat, bevel=.015, semantic=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign(obj, mat, semantic)
    if bevel:
        modifier = obj.modifiers.new("Manufactured edge radius", "BEVEL")
        modifier.width = min(bevel, min(size)/4)
        modifier.segments = 2
    return obj


def cylinder(name, pos, radius, depth, mat, axis="Z", vertices=20):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=pos)
    obj = bpy.context.object
    obj.name = name
    if axis == "X":
        obj.rotation_euler[1] = math.pi/2
    elif axis == "Y":
        obj.rotation_euler[0] = math.pi/2
    assign(obj, mat)
    return obj


def light(name, pos, power, size=3., color=(1, .9, .76), target=None):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size, data.color = power, "DISK", size, color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = pos
    if target:
        obj.rotation_euler = (Vector(target)-obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def text_label(name, body, pos, size=.2, rot=(math.pi/2, 0, math.pi/2), mat="black"):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body, curve.size, curve.extrude = body, size, .0005
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location, obj.rotation_euler = pos, rot
    curve.materials.append(MATERIALS[mat])
    obj["semantic_class"] = "sign"
    return obj


def crate(name, pos, size):
    x, y, z = pos
    sx, sy, sz = size
    box(name, pos, size, "cardboard", .008)
    box(name+" packing tape", (x, y, z+sz/2+.0006), (sx+.001, .05, .001), "tape", 0)
    box(name+" label", (x-sx/2-.001, y, z), (.001, sy*.3, sz*.2), "white", 0)


def pallet(name, x, y, z=.08):
    for dx in (-.47, 0, .47):
        box(name+" bearer", (x+dx,y,z), (.10,.9,.12), "wood", .006)
    for dy in np.linspace(-.44,.44,6):
        box(name+" board", (x,y+dy,z+.08), (1.2,.12,.035), "wood", .004)


def warehouse():
    box("Concrete slab", (7,0,-.13), (24,17,.25), "concrete", 0)
    box("Rear wall", (18,0,3.4), (.25,17,6.8), "paint", .01)
    box("West wall", (6,8.3,3.4), (24,.25,6.8), "paint", .01)
    box("East wall", (6,-8.3,3.4), (24,.25,6.8), "paint", .01)
    box("Ceiling", (6,0,6.8), (24,17,.2), "paint", 0)
    for x in (-3,3,9,15):
        for y in (-7.9,7.9):
            box("Steel column", (x,y,3.25), (.28,.28,6.5), "metal")
        box("Roof beam", (x,0,6.3), (.22,16,.4), "metal")
    for y in (-6.2,5.8):
        for x in (3.5,7.5,11.5,15.5):
            for dx in (-1.7,1.7):
                for dy in (-.65,.65):
                    box("Rack upright", (x+dx,y+dy,2.4), (.10,.10,4.8), "blue")
            for z in (.35,1.9,3.45):
                box("Rack shelf", (x,y,z), (3.5,1.4,.07), "metal")
                for dy in (-.71,.71):
                    box("Rack crossbeam", (x,y+dy,z-.04), (3.6,.08,.14), "orange")
                for j in range(4):
                    height=random.uniform(.45,1.10)
                    crate("Stored carton", (x-1.3+j*.82,y,z+.04+height/2), (.7,1.1,height))
    for x,y in ((5,2),(10,-2.2),(14,2.4),(2,-3.4)):
        pallet("Pallet", x,y)
        crate("Freight", (x,y,.78), (1.05,.85,1.2))
    for y in (-1.8,-.9,0):
        cylinder("Oil barrel", (15,y,.5), .34,1,"blue")
        for z in (.15,.8):
            cylinder("Barrel rim", (15,y,z), .35,.04,"metal")
    # Forklift silhouette with independent actual geometry for both sensors.
    box("Forklift chassis", (10,2.8,.7), (1.7,1.05,.6), "yellow", .08)
    box("Forklift battery", (10.5,2.8,1.2), (.6,.9,.65), "yellow", .06)
    box("Forklift seat", (9.9,2.8,1.3), (.45,.6,.22), "black", .05)
    for y in (2.3,3.3):
        for x in (9.5,10.5):
            cylinder("Forklift tyre", (x,y,.39), .32,.18,"black", "Y")
    for y in (2.45,3.15):
        box("Forklift mast", (9.03,y,1.6), (.12,.1,2.7), "metal")
        box("Fork", (8.5,y,.17), (1.1,.12,.08), "metal")
    box("Roller shutter", (17.84,1.5,2), (.04,3.8,4), "metal", .004)
    for z in np.arange(.12,4,.14):
        box("Shutter rib", (17.8,1.5,float(z)), (.03,3.8,.025), "white", .002)
    box("Pedestrian door", (17.8,-5,1.15), (.08,1.2,2.3), "blue")
    for y in (-7.95,7.95):
        for x in (2,8,14):
            box("High window", (x,y,4.8), (3,.03,1.2), "window", .005)
            light("Window daylight", (x,y*.96,4.6), 300,3,(.7,.82,1), (x,0,1))
    for y in (-3.8,3.8):
        for x in (0,6,12):
            box("Luminaire housing", (x,y,6.1), (1.6,.35,.14), "metal")
            box("Luminaire diffuser", (x,y,6.015), (1.45,.3,.02), "light", .004)
            light("Industrial LED", (x,y,5.95), 650,2.5)
    for y in (-1.4,1.4):
        box("Floor aisle marking", (7,y,.003), (20,.07,.005), "yellow", 0)
    for y,z in ((7.8,5.6),(-7.8,5.5)):
        cylinder("Service pipe", (6,y,z), .08,23,"metal","X")
    text_label("Loading sign", "LOADING  03", (17.65,3.0,4.5), .4)


def laboratory():
    box("Floor", (5,0,-.1), (19,13,.2), "concrete", 0)
    box("End wall", (14,0,1.7), (.2,13,3.4), "paint")
    for y in (-6.4,6.4):
        box("Office wall", (5,y,1.7), (19,.2,3.4), "paint")
    box("Ceiling", (5,0,3.5), (19,13,.15), "white", 0)
    for x in (2,5,8,11):
        for y in (-3.3,3.3):
            box("Desk top", (x,y,.76), (2.0,1.0,.065), "wood", .025)
            for dx in (-.85,.85):
                for dy in (-.4,.4):
                    box("Desk leg", (x+dx,y+dy,.37), (.055,.055,.74), "metal")
            box("Monitor stand", (x+.35,y,.91), (.08,.08,.3), "metal")
            box("Monitor", (x+.35,y,1.2), (.06,.72,.44), "black")
            box("Display", (x+.313,y,1.2), (.006,.66,.38), "screen", 0)
            for k in range(5):
                box("Display code line", (x+.307,y-.24+float(k)*.10,1.20), (.002,.025,.25), "window", 0)
            box("Keyboard", (x-.2,y,.81), (.25,.52,.025), "black", .008)
            cylinder("Chair pedestal", (x-1.1,y,.28), .045,.5,"metal")
            box("Chair seat", (x-1.1,y,.53), (.48,.5,.10), "black", .04)
            box("Chair back", (x-1.3,y,.85), (.08,.5,.6), "black", .04)
            for angle in np.linspace(0,2*math.pi,5,endpoint=False):
                foot=box("Chair foot", (x-1.1+.14*math.cos(angle),y+.14*math.sin(angle),.05), (.4,.035,.025),"metal")
                foot.rotation_euler[2]=angle
    for x in (1.5,5,8.5,12):
        box("Window", (x,6.27,1.9), (2.4,.03,1.6), "window")
        for dx in (-1.2,0,1.2):
            box("Window mullion", (x+dx,6.22,1.9), (.04,.06,1.65), "metal")
        light("Daylight", (x,5.9,2.4),300,2,(.73,.84,1),(x,0,1))
    for y in (-5.4,-3.9):
        box("Equipment cabinet", (13.3,y,1), (1,1.25,2),"white")
        box("Cabinet door seam", (12.79,y,1),(.006,.014,1.9),"black",0)
        for z in (.65,1.1,1.55):
            box("Instrument", (12.74,y,z),(.1,1,.25),"metal")
            box("Instrument display", (12.68,y-.22,z),(.012,.2,.1),"screen",0)
    box("Lab door",(13.87,4.2,1.1),(.06,1.3,2.2),"wood")
    box("Whiteboard",(9,-6.26,1.8),(3,.03,1.2),"white")
    for x in (0,4,8,12):
        for y in (-2,2):
            box("LED panel", (x,y,3.37),(1.2,.6,.02),"light",0)
            light("Ceiling illumination",(x,y,3.32),150,2)
    for x in np.arange(-4,15,.6):
        box("Floor joint", (float(x),0,.002),(.005,13,.003),"metal",0)


def tree(x,y,scale=1):
    cylinder("Tree trunk",(x,y,1.5*scale),.18*scale,3*scale,"bark")
    for dx,dy,dz in ((0,0,3.7),(.7,0,3.4),(-.6,.4,3.5),(0,-.6,4.4)):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1.2*scale,location=(x+dx*scale,y+dy*scale,dz*scale))
        obj=bpy.context.object
        obj.name="Foliage"
        obj.scale=(1,.85,1.1)
        assign(obj,"leaf","tree")


def car(x,y,mat):
    box("Parked vehicle body",(x,y,.65),(4.3,1.8,.75),mat,.18)
    box("Vehicle cabin",(x-.25,y,1.18),(2.25,1.65,.75),mat,.18)
    box("Windshield",(x+.9,y,1.28),(.035,1.42,.45),"window",.025)
    box("Rear windshield",(x-1.4,y,1.28),(.035,1.4,.4),"window",.025)
    for yy in (-.84,.84):
        box("Side windows",(x-.25,y+yy,1.3),(1.9,.025,.43),"window",.04)
    for xx in (-1.35,1.35):
        for yy in (-.88,.88):
            cylinder("Tyre",(x+xx,y+yy,.4),.38,.22,"black","Y")
            cylinder("Wheel rim",(x+xx,y+yy*1.13,.4),.22,.025,"metal","Y")
    for yy in (-.65,.65):
        box("Headlamp",(x+2.16,y+yy,.8),(.02,.32,.16),"light",.02)


def urban():
    box("Road",(27,0,-.13),(100,11,.25),"asphalt",0)
    for y in (-7,7):
        box("Pavement",(27,y,.03),(100,3,.3),"concrete",.02)
        box("Kerb",(27,y-math.copysign(1.45,y),.12),(100,.15,.35),"paint",.02)
    for x in np.arange(-15,78,5):
        box("Road centre line",(float(x),0,.005),(2.5,.12,.008),"white",0)
    for side in (-1,1):
        for i,x in enumerate((0,10,22,36,53,70)):
            height=(7,10,8,13,9,15)[i]
            y=side*12
            box("Building",(x,y,height/2),(8,7,height),"brick" if i%2 else "paint",.035)
            for z in np.arange(1.7,height-1,2.5):
                for xx in (x-2.5,x,x+2.5):
                    box("Window frame",(xx,y-side*3.54,float(z)),(1.4,.08,1.5),"metal",.01)
                    box("Building glazing",(xx,y-side*3.60,float(z)),(1.23,.025,1.32),"window",.005)
            box("Shop door",(x,y-side*3.62,1.1),(1.2,.05,2.2),"blue")
        for x in (5,18,32,48,65):
            tree(x,side*7.2,.75 if x<20 else 1)
            cylinder("Streetlight pole",(x-1,side*5.9,3),.06,6,"metal")
            box("Streetlight head",(x-1,side*5.4,6),(.5,1.1,.15),"metal")
    for x,y,mat in ((8,-4,"red"),(17,4,"blue"),(32,-4,"white"),(46,4,"metal")):
        car(x,y,mat)
    cylinder("Sign post",(13,6,1.5),.035,3,"metal")
    box("Road sign",(13,6,2.5),(.05,.75,.8),"blue",.02)
    text_label("Speed sign", "40",(12.96,6.28,2.28),.4,mat="white")
    bpy.ops.object.light_add(type="SUN", location=(0,0,20))
    obj=bpy.context.object
    obj.name="Afternoon sun"
    obj.data.energy=3
    obj.data.angle=math.radians(1.5)
    obj.rotation_euler=(.45,-.55,-.7)


def corridor():
    box("Corridor floor",(23,0,-.12),(58,5,.24),"concrete",0)
    box("Corridor ceiling",(23,0,3.5),(58,5,.2),"paint",0)
    for y in (-2.5,2.5):
        box("Parallel wall",(23,y,1.75),(58,.2,3.5),"paint",.005)
        box("Skirting",(23,y*.96,.08),(58,.04,.16),"metal",.003)
        for x in np.arange(-3,51,4):
            box("Repeated pier",(float(x),y*.95,1.75),(.20,.18,3.5),"concrete",.01)
        for x in (9,21,33,45):
            box("Service door",(x,y*.955,1.1),(1.25,.06,2.2),"metal")
    box("Terminal wall",(52,0,1.75),(.2,5,3.5),"concrete")
    for x in np.arange(0,52,4):
        box("Repeated crossbeam",(float(x),0,3.3),(.22,5,.3),"concrete")
        box("Ceiling strip",(float(x)+1,0,3.36),(.8,.15,.02),"light",0)
        light("Passage light",(float(x)+1,0,3.25),50 if int(x)%8 else 20,1.5,(.7,.85,1))
    cylinder("Ceiling pipe",(23,1.8,3.1),.08,57,"metal","X")
    cylinder("Ceiling pipe",(23,-1.8,3.1),.05,57,"metal","X")
    box("Partial obstruction",(15,1.45,1),(.5,1.2,2),"metal")
    box("Maintenance cabinet",(31,-1.85,.8),(.7,.8,1.6),"blue")


def select_device(requested):
    scene=bpy.context.scene
    scene.render.engine="CYCLES"
    prefs=bpy.context.preferences.addons["cycles"].preferences
    attempts=[]
    for backend in dict.fromkeys([requested,"CUDA","CPU"] if requested != "CPU" else ["CPU"]):
        if backend == "CPU":
            if requested != "CPU":
                # Never fall back to the CPU silently when the user asked for the GPU.
                raise RuntimeError("GPU rendering was requested ("+requested+") but no OptiX/CUDA device was usable: "+json.dumps(attempts)+". Choose the CPU device explicitly to render without a GPU.")
            scene.cycles.device="CPU"
            return {"requested":requested,"actual":"CPU","devices":["CPU"],"attempts":attempts}
        try:
            prefs.compute_device_type=backend
            prefs.get_devices()
            selected=[d for d in prefs.devices if d.type==backend]
            for d in prefs.devices:
                d.use=d in selected
            if selected:
                scene.cycles.device="GPU"
                return {"requested":requested,"actual":backend,"devices":[d.name for d in selected],"attempts":attempts}
            attempts.append({"backend":backend,"error":"No matching devices"})
        except Exception as exc:
            attempts.append({"backend":backend,"error":str(exc)})
    raise RuntimeError("No rendering device")


def camera_at(T_WC, width, height, fov=100.):
    scene=bpy.context.scene
    if scene.camera is None:
        data=bpy.data.cameras.new("ResearchCamera")
        obj=bpy.data.objects.new("ResearchCamera",data)
        bpy.context.collection.objects.link(obj)
        scene.camera=obj
    camera=scene.camera
    camera.matrix_world=Matrix(np.asarray(T_WC).tolist()) @ Matrix.Diagonal((1,-1,-1,1))
    camera.data.type="PERSP"
    camera.data.sensor_fit="HORIZONTAL"
    camera.data.sensor_width=36.
    camera.data.lens=18./math.tan(math.radians(fov)/2)
    camera.data.clip_start=.01
    camera.data.clip_end=1000
    scene.render.resolution_x=width
    scene.render.resolution_y=height
    scene.render.resolution_percentage=100
    scene.render.pixel_aspect_x=scene.render.pixel_aspect_y=1
    # Blender image pixel centres: central optical axis is between the central pixels.
    focal=width/(2*math.tan(math.radians(fov)/2))
    return [[focal,0,(width-1)/2],[0,focal,(height-1)/2],[0,0,1]]


def export_mesh(output):
    depsgraph=bpy.context.evaluated_depsgraph_get()
    vertices=[]; triangles=[]; ids=[]; colors=[]; objects=[]; offset=0
    # Include all visible render geometry, with evaluated modifiers and font meshes.
    for obj in bpy.context.scene.objects:
        if obj.hide_render or obj.type not in {"MESH","FONT","CURVE","SURFACE","META"}:
            continue
        evaluated=obj.evaluated_get(depsgraph)
        mesh=evaluated.to_mesh()
        if mesh is None:
            continue
        mesh.calc_loop_triangles()
        if not mesh.loop_triangles:
            evaluated.to_mesh_clear()
            continue
        obj_id=len(objects)+1
        coords=np.array([tuple(evaluated.matrix_world @ v.co) for v in mesh.vertices],dtype=np.float32)
        faces=np.array([tuple(t.vertices) for t in mesh.loop_triangles],dtype=np.int32)
        vertices.append(coords); triangles.append(faces+offset)
        ids.append(np.full(len(faces),obj_id,dtype=np.int32))
        mat_colors=[]
        for face in mesh.loop_triangles:
            idx=mesh.polygons[face.polygon_index].material_index
            mat=mesh.materials[idx] if idx < len(mesh.materials) else None
            mat_colors.append(tuple(mat.diffuse_color[:3]) if mat else (.5,.5,.5))
        colors.append(np.asarray(mat_colors,dtype=np.float32))
        objects.append({"id":obj_id,"name":obj.name,"semantic_class":obj.get("semantic_class","geometry")})
        offset+=len(coords)
        evaluated.to_mesh_clear()
    np.savez_compressed(output/"mesh.npz",vertices=np.concatenate(vertices),triangles=np.concatenate(triangles),face_ids=np.concatenate(ids),colors=np.concatenate(colors))
    (output/"objects.json").write_text(json.dumps(objects,indent=2),encoding="utf8")
    return {"vertices":offset,"triangles":sum(map(len,triangles)),"objects":len(objects)}


def render(path):
    bpy.context.scene.render.filepath=str(path.resolve())
    bpy.ops.render.render(write_still=True)


def cubemap(output,T_WC,size,faces=None):
    # faces: names to render (default all six); the caller chooses only those its camera can sample.
    # Direction/up pairs expressed in the base camera's OpenCV frame.
    axes={"px":((1,0,0),(0,-1,0)),"nx":((-1,0,0),(0,-1,0)),
          "py":((0,1,0),(0,0,1)),"ny":((0,-1,0),(0,0,-1)),
          "pz":((0,0,1),(0,-1,0)),"nz":((0,0,-1),(0,-1,0))}
    result={"faces":[],"camera_base_T_WC":np.asarray(T_WC).tolist(),"size":size}
    base=np.asarray(T_WC,dtype=float)
    for name,(forward,up) in axes.items():
        if faces is not None and name not in faces:
            continue
        f=np.asarray(forward,dtype=float); u=np.asarray(up,dtype=float)
        r=np.cross(f,u); down=-u
        local=np.eye(4); local[:3,:3]=np.column_stack((r,down,f))
        pose=base@local
        K=camera_at(pose,size,size,90.)
        render(output/f"cube_{name}.png")
        result["faces"].append({"name":name,"T_WC":pose.tolist(),"K":K,"image":f"cube_{name}.png"})
    (output/"cube_metadata.json").write_text(json.dumps(result,indent=2),encoding="utf8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene",choices=("warehouse","laboratory","urban","corridor"),default="warehouse")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--samples",type=int,default=32)
    parser.add_argument("--width",type=int,default=640)
    parser.add_argument("--height",type=int,default=480)
    parser.add_argument("--device",choices=("OPTIX","CUDA","CPU"),default="CPU")
    parser.add_argument("--allow-render",action="store_true",help="Explicitly enable native rendering; off after reported host crashes")
    parser.add_argument("--allow-gpu",action="store_true",help="Explicitly enable GPU device probing/rendering")
    parser.add_argument("--hdri",type=Path)
    parser.add_argument("--blend",type=Path,help="Render an existing generated scene instead of building it")
    parser.add_argument("--pose-json",type=Path,help="JSON containing T_WC, optionally width,height,fov_deg")
    parser.add_argument("--cubemap",action="store_true")
    parser.add_argument("--cube-size",type=int,default=512)
    parser.add_argument("--faces",default="",help="Comma-separated cube faces to render (px,nx,py,ny,pz,nz); default all six")
    parser.add_argument("--no-render",action="store_true")
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    if not args.no_render and not args.allow_render:
        parser.error("Rendering disabled by default after reported Windows crashes; --allow-render is required")
    if args.device != "CPU" and not args.allow_gpu:
        parser.error("GPU use requires --allow-gpu; choose --device CPU for conservative execution")
    if min(args.width,args.height,args.samples,args.cube_size)<=0:
        parser.error("Dimensions and sample count must be positive")
    faces=[f for f in args.faces.split(",") if f] or None
    if faces and not set(faces)<={"px","nx","py","ny","pz","nz"}:
        parser.error("--faces accepts only px,nx,py,ny,pz,nz")
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter()
    if args.blend:
        bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()))
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        random.seed(42)
        setup_materials()
        globals()[args.scene]()
        bpy.context.scene.unit_settings.system="METRIC"
        bpy.context.scene.unit_settings.scale_length=1.
        world=bpy.data.worlds.new("Environment")
        bpy.context.scene.world=world
        world.use_nodes=True
        world.node_tree.nodes["Background"].inputs["Color"].default_value=(.35,.44,.60,1)
        world.node_tree.nodes["Background"].inputs["Strength"].default_value=.3 if args.scene=="urban" else .08
        if args.hdri:
            texture=world.node_tree.nodes.new("ShaderNodeTexEnvironment")
            texture.image=bpy.data.images.load(str(args.hdri.resolve()))
            world.node_tree.links.new(texture.outputs["Color"],world.node_tree.nodes["Background"].inputs["Color"])
            bpy.context.scene["hdri_asset"] = args.hdri.name
            bpy.context.scene["hdri_sha256"] = hashlib.sha256(args.hdri.read_bytes()).hexdigest()
        bpy.context.scene["simulator_scene"] = args.scene
        bpy.context.scene["simulator_scene_version"] = SCENE_VERSION
    scene=bpy.context.scene
    scene.render.threads_mode="FIXED"
    scene.render.threads=1
    device=select_device(args.device)
    scene.cycles.samples=args.samples
    scene.cycles.use_denoising=True
    scene.cycles.use_adaptive_sampling=True
    scene.cycles.seed=42
    scene.render.image_settings.file_format="PNG"
    scene.view_settings.view_transform="AgX"
    pose=np.eye(4)
    pose[:3,:3]=np.array([[0,0,1],[-1,0,0],[0,-1,0]])
    pose[:3,3]=[0,0,1.6]
    spec=json.loads(args.pose_json.read_text(encoding="utf8")) if args.pose_json else {}
    pose=np.asarray(spec.get("T_WC",pose.tolist()),dtype=float)
    if pose.shape!=(4,4) or not np.isfinite(pose).all() or not np.allclose(pose[3],[0,0,0,1]):
        raise ValueError("T_WC must be a finite homogeneous 4x4 camera-to-world pose")
    K=camera_at(pose,spec.get("width",args.width),spec.get("height",args.height),spec.get("fov_deg",100.))
    metadata={"scene":scene.get("simulator_scene",args.scene),"scene_version":scene.get("simulator_scene_version",SCENE_VERSION),"blender_version":bpy.app.version_string,
              "device":device,"samples":args.samples,"world_frame":"right-handed, x forward, y left, z up; metres",
              "camera_frame":"OpenCV x right, y down, z forward","T_WC":pose.tolist(),"K":K,
              "width":scene.render.resolution_x,"height":scene.render.resolution_y,
              "fidelity":"Detailed procedural geometry and noise-based PBR; no external asset textures. Not a validated photorealistic benchmark.",
              "geometry_note":"mesh.npz contains evaluated render-visible meshes including bevels and text; shader bump does not change geometric surfaces."}
    if "hdri_asset" in scene:
        metadata["hdri"] = {"asset": scene["hdri_asset"], "sha256": scene["hdri_sha256"], "packed_in_blend": True}
    if not args.blend:
        metadata["mesh"]=export_mesh(output)
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=str(output/"scene.blend"))
    if not args.no_render:
        if args.cubemap:
            cubemap(output,pose,args.cube_size,faces)
        else:
            render(output/"preview.png")
    metadata["elapsed_seconds"]=time.perf_counter()-start
    (output/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf8")
    print("SIMLAB_RENDER_RESULT "+json.dumps(metadata))


if __name__=="__main__":
    main()
