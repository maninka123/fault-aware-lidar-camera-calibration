# LiDAR models and scientific limits

All profiles use metres and seconds, with a shared right-handed LiDAR frame:
**x forward, y left, z up**. Azimuth increases toward +y and elevation toward +z.
Directions are independent rays from the LiDAR position into the scene. All
profiles are single-origin geometric models. They omit physical beam divergence,
multiple returns, multipath, interference and internal optical-centre offsets.
These outputs are suitable for controlled geometry experiments; none is claimed
to reproduce an individual physical sensor exactly.

`generate_rays(profile, start_time, duration, options)` returns directions,
absolute per-point scheduled times, channels, global beam IDs and metadata.
Use sequence-relative nonnegative times. A capture selects the half-open interval
`[start_time, start_time + duration)`. The sensor schedule does not restart at each
capture. Adjacent accumulation windows therefore contain the same beams as their
union. `stride` retains every kth global beam and keeps its original timestamp;
metadata reports both physical and reduced nominal rate. A stride greater than
one is explicit simulation subsampling, not a different physical sensor mode.

## Livox Avia

The default schedule replays the official simulator's `avia.csv`: 960,000 ordered
azimuth/zenith entries spanning four seconds at 240,000 single-return beams/s.
Its first column agrees with this uniform schedule to CSV rounding precision.
Zenith is converted to elevation as `90 - zenith`, consistent with the reference
plugin's pitch convention. The observed pattern extends approximately ±35.31°
horizontally and ±38.59° vertically; it is preserved rather than rescaled.
Source: [official simulation reference](https://github.com/Livox-SDK/livox_laser_simulation).

The manufacturer specifies a 70.4° × 77.2° nonrepetitive field and a separate
70.4° × 4.5° repetitive line mode. Only the former has a reference pattern here;
requesting repetitive mode raises an error. Single-return rate is 240,000/s.
The 190 m default far cutoff corresponds to the stated 10% reflectivity range
at 100 klx; it does not model reflectivity-dependent detection probability.
Source: [Avia specifications](https://www.livoxtech.com/avia/specs).

The finite pattern repeats every four seconds, so it is **not indefinitely
nonrepetitive**. Unknown emitter identities are saved as channel `-1`. The 0.1 m
near cutoff is a configurable simulation default from the reference example,
not a validated Avia blind-zone claim. Validate against recordings from the
physical Avia before hardware transfer or scan-pattern benchmark claims.

## Livox Mid-360

The official `mid360.csv` contains 800,000 ordered beams. Despite its `Time/s`
header, the first column is an integer counter `1..800000`. This implementation
preserves beam order and reconstructs time at the documented 200,000 first
returns/s, yielding a four-second replay. That timing reconstruction is an
approximation; exact internal emitter timing and channel identities are unknown.
Its source angles cover 360° in azimuth, approximately −7.21° to +52.16° in
elevation; small differences from nominal manufacturer limits are retained.
Source: [official reference pattern and plugin](https://github.com/Livox-SDK/livox_laser_simulation).

The manufacturer's nominal vertical field is −7° to +52°, with 360° horizontal
coverage, a 0.1 m close blind zone and 200,000 first returns/s. Default range is
0.1–40 m; the far value is the stated 10%-reflectivity range at 100 klx.
Source: [Mid-360 specifications](https://www.livoxtech.com/mid-360/specs).

## Velodyne VLP-16

Channels follow the firing-order elevation table
`[-15,1,-13,3,-11,5,-9,7,-7,9,-5,11,-3,13,-1,15]` degrees.
Each channel fires 2.304 microseconds after the previous one, and consecutive
16-channel groups start 55.296 microseconds apart, including recharge time.
Consequently the exact single-return schedule emits about 289,352 beams/s,
rather than rounding the schedule to the marketed ~300,000/s. Rotation is
continuous at configurable 5–20 Hz (10 Hz default), including per-channel
azimuth evolution. The default range cutoff is 1–100 m.
Sources: [manufacturer manual](https://data.ouster.io/downloads/velodyne/user-manual/vlp-16-user-manual-revf.pdf),
[ROS driver calibration table](https://github.com/ros-drivers/velodyne/blob/ros2/velodyne_pointcloud/params/VLP16db.yaml).

The elevation arrangement is nominal. Unit-specific distance corrections,
optical origins, firing jitter and rotation speed variations are omitted.

## Ouster OS1-64

This is a **nominal uniform 64-beam, 45° vertical-field configuration** centered
on the horizon, with 360° horizontal rotation. Choose 512×10, 512×20, 1024×10,
1024×20 or 2048×10 modes; unsupported combinations are rejected. Default
1024×10 mode emits 655,360 scheduled rays/s. Per-channel times are uniformly
distributed within a column, a declared approximation rather than validated
hardware firing timing. Default range 0.5–100 m is a simulation cutoff, not a
claim covering all OS1 generations and reflectivities.
Sources: [OS1 Rev7 overview](https://docs.ouster.com/sensor-docs/hardware/os1-overview),
[supported resolution/rate combinations](https://docs.ouster.com/sensor-docs/firmware/sensor-performance),
[OS1 product specifications](https://ouster.com/products/hardware/os1-lidar-sensor).

The manufacturer supports several beam-spacing options and individually
calibrated angles. No serial-specific table is bundled. Supply 64 values via
`beam_elevations_deg` and optionally `beam_azimuth_offsets_deg`; metadata records
the table. A supplied table does not validate firing order or optical origins.

## Hesai AT128

This profile uses the **nominal AT128P far-field lattice** from the public manual
linked on the AT128 resource page: 128 channels, 120° horizontal field, vertical
limits −12.5° to +12.9°, 0.1° horizontal sampling at 10 Hz or 0.2° at 20 Hz.
Both modes produce 1,536,000 single-return scheduled rays/s. The scanner sweeps
from −60° up to the last sample below +60°, then resets for the next frame.
Default range cutoffs are the documented instrumented 0.5–260 m interval.
Source: [manufacturer manual A02-en-260110](https://www.hesaitech.com/wp-content/uploads/2026/01/AT128P_User_Manual_A02-en-260110.pdf).

Uniform elevation spacing and uniform sequential firing are explicit
approximations. Near-field channel selection/resolution changes, mirror-surface
corrections, firing order and each unit's calibration are not reproduced. Custom
128-element elevation and azimuth-offset tables are supported. The download page
offers an angle-correction file, but redistribution permission was not established,
so it is not incorporated. This is not a manufacturer-exact AT128 model.
Source: [official AT128 resources](https://www.hesaitech.com/product_downloads/at128/).

## Provenance and validation

The Livox reference clone is pinned in generated metadata to commit
`1cce1073633a062b92e30243a4c2920e45551bb5`; SHA-256 of each consumed CSV is also
recorded. Losslessly converted NumPy arrays are bundled under `simulator/patterns`
and included as wheel package data; no reference checkout is needed at runtime.
`provenance.json` records source CSV hashes and packaged NPZ hashes; the loader
checks the compressed bundle hashes. An explicit `pattern_path` can still select
an external CSV or equivalent NPZ archive. The reference is MIT licensed, copyright
2021 livox; its full license is included as `patterns/LIVOX_LICENSE.txt`.
No third-party simulator code is imported
into this module. Re-cloning a newer upstream revision requires reviewing and
updating the recorded reference commit; the actual content hash remains authoritative.

`tests/test_lidar.py` checks normalized directions, actual pattern extents,
known VLP-16 firing times, nominal counts, frame/window continuity, global stride,
determinism and invalid configuration rejection. These checks validate the
implemented schedules; they do not replace comparisons to real sensor recordings.
