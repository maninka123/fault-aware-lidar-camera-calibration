#!/usr/bin/env bash
# Source the existing ROS installation only in this child shell.
set -eo pipefail
source /opt/ros/noetic/setup.bash
exec python3 "$@"
