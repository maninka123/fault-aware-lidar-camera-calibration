"""Cubemap sampling regression uses existing synthetic images; no native renderer."""
import cv2
import numpy as np
import pytest
from simulator.camera import Camera
from simulator.io import json_write
from simulator.render import cubemap_rgb


def test_cubemap_seams_and_large_remap_are_covered(tmp_path):
    axes={"px":((1,0,0),(0,-1,0)),"nx":((-1,0,0),(0,-1,0)),
          "py":((0,1,0),(0,0,1)),"ny":((0,-1,0),(0,0,-1)),
          "pz":((0,0,1),(0,-1,0)),"nz":((0,0,-1),(0,-1,0))}
    faces=[]
    n=32
    # Equal colors make every edge deterministic; focus on floating ties and remap size.
    for name,(forward,up) in axes.items():
        f,u=np.array(forward),np.array(up)
        pose=np.eye(4)
        pose[:3,:3]=np.column_stack((np.cross(f,u),-u,f))
        image=np.full((n,n,3),[20,70,150],np.uint8)
        cv2.imwrite(str(tmp_path/(name+".png")),image)
        faces.append(dict(T_WC=pose.tolist(),K=[[16.000000000000004,0,15.5],[0,16.000000000000004,15.5],[0,0,1]],image=name+".png"))
    json_write(tmp_path/"cube_metadata.json",dict(faces=faces))
    cam=Camera.from_dict(dict(model="fisheye",width=484,height=366,focal_px=200,D=[.02,-.005,0,0]))
    rgb=cubemap_rgb(cam,np.eye(4),tmp_path)
    assert rgb.shape == (366,484,3)
    np.testing.assert_array_equal(rgb,np.tile([150,70,20],(366,484,1)))
    moved=np.eye(4)
    moved[0,3]=.1
    with pytest.raises(ValueError,match="origin differs"):
        cubemap_rgb(cam,moved,tmp_path)
