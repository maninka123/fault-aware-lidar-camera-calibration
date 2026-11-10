#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/noetic/setup.bash
set -u
python3 - <<'PY'
import sys
import numpy
import cv2
import rospy
import rosbag
print('Python:', sys.version)
print('NumPy:', numpy.__version__)
print('OpenCV:', cv2.__version__)
print('rospy:', rospy.__file__)
print('rosbag:', rosbag.__file__)
PY
command -v roscore
command -v rosbag
