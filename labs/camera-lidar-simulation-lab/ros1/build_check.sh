#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/noetic/setup.bash
LAB="$(cd -- "$(dirname -- "$0")/.." && pwd)"
WORKSPACE="$LAB/outputs/ros_catkin_ws"
mkdir -p "$WORKSPACE/src"
if [ ! -e "$WORKSPACE/src/camera_lidar_simulation_lab" ]; then
  ln -s "$LAB/ros1" "$WORKSPACE/src/camera_lidar_simulation_lab"
fi
catkin_make -C "$WORKSPACE" -DPYTHON_EXECUTABLE=/usr/bin/python3
