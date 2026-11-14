"""motionbricks runtime -> UDP sender, the live SOMA pose source for Unity's PoseReceiver.

Wraps motionbricks' own continuous-locomotion-loop example (docs/examples/locomotion_loop.py)
and sends each sampled pose over UDP in PoseFrameCodec's wire format instead of collecting it
into a list. Bootstrap/debug this pipe first with tools/pose_sender_test.py (synthetic data);
this script is the real thing (CLAUDE.md "Live streaming" step 4).

Needs the motionbricks repo as a sibling checkout (../motionbricks) with its own `uv` venv set
up, and a CUDA GPU (builds a TensorRT plan on first run, which takes a few minutes).

Run from the motionbricks repo so its own venv/deps resolve, pointing at this file:
    cd ../motionbricks
    uv run python ../SnackClubHavenAICompanionship/tools/pose_sender_motionbricks.py
"""
import argparse
import math
import socket
import struct
import sys
from pathlib import Path

import numpy as np

MOTIONBRICKS_ROOT = Path(__file__).resolve().parents[2] / "motionbricks"
sys.path.insert(0, str(MOTIONBRICKS_ROOT / "docs" / "examples"))

import warp as wp  # noqa: E402  (after sys.path setup, to find motionbricks' examples helpers)
from motionbricks.model.contract import MODEL_POSES_PER_TOKEN  # noqa: E402
from motionbricks.runtime.motion_player import GeneratedMotionPlayer  # noqa: E402
from motionbricks.runtime.target_pose import (  # noqa: E402
    TargetPoseInferenceParams,
    adjust_target_pose_speed,
    place_target_poses,
)

from _rig import JOG, load_rig, root_positions, sample_window  # noqa: E402

HOST, PORT = "127.0.0.1", 5005
UPDATE_RATE = 30.0  # matches PoseReceiver.cs / PoseFrameCodec's one-datagram-per-frame design
DESIRED_SPEED = 1.9  # m/s, SOMA's jog clip speed (from motionbricks' own locomotion_loop.py)
LEAD_SECONDS = 1.0
TRANSITION_EARLY_BY = 4
TURN_THRESHOLD_DEG = 15.0
TARGET_TIME = 1.8
TURN_START, TURN_END = 2.0, 4.0

# The 30 SOMA joints in soma_n1.json order, looked up by name in the skeleton's full 77-joint
# layout (it also carries the fingers the model doesn't predict). Mirrors
# Assets/Scripts/PoseFrameCodec.cs SomaJointOrder — keep both lists in sync.
SOMA_JOINT_ORDER = [
    "Hips", "Spine1", "Spine2", "Chest", "Neck1", "Neck2", "Head", "Jaw", "LeftEye", "RightEye",
    "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "LeftHandThumbEnd", "LeftHandMiddleEnd",
    "RightShoulder", "RightArm", "RightForeArm", "RightHand", "RightHandThumbEnd", "RightHandMiddleEnd",
    "LeftLeg", "LeftShin", "LeftFoot", "LeftToeBase", "RightLeg", "RightShin", "RightFoot", "RightToeBase",
]


def steering(time: float) -> np.ndarray:
    """Desired ground direction at a time — stands in for real controller input (step 5)."""
    blend = min(max((time - TURN_START) / (TURN_END - TURN_START), 0.0), 1.0)
    angle = 0.5 * math.pi * blend
    return np.array([math.cos(angle), math.sin(angle), 0.0], dtype=np.float32)


def canonical_target(rig, poses: wp.array) -> None:
    sample_window(rig, TARGET_TIME, poses)
    roots = root_positions(poses)
    offset = roots[-1, :2] - roots[0, :2]
    heading = math.atan2(offset[1], offset[0])
    origin = wp.transform(
        wp.vec3(roots[0, 0], roots[0, 1], 0.0), wp.quat_from_axis_angle(wp.vec3(0.0, 0.0, 1.0), heading),
    )
    sample_window(rig, TARGET_TIME, poses, root_offset=wp.transform_inverse(origin))
    adjust_target_pose_speed(poses, DESIRED_SPEED, stream=rig.engine.stream)


def zup_to_yup_pos(p: np.ndarray) -> np.ndarray:
    """(x, y, z) in motionbricks' Z-up world -> (x, z, y) in the wire format's Y-up convention.

    motionbricks' apps run in Z-up world space (runtime_api.md "Pose layouts and model space"),
    not the Y-up SOMA/BVH model space CLAUDE.md originally described — found by observing a
    live frame land the character ~43 units up in Unity's Y axis. Swapping Y/Z is the standard
    Z-up-RH -> Y-up-LH conversion and also flips handedness, which Unity (left-handed) needs.
    """
    return np.array([p[0], p[2], p[1]], dtype=np.float32)


def zup_to_yup_quat(q: np.ndarray) -> np.ndarray:
    """Matching rotation conversion for the same Y/Z swap+handedness flip. x,y,z,w order.

    ponytail: standard swap-axis quaternion formula, not yet visually confirmed against this
    rig's actual limb orientation in Play mode — check hands/feet point the right way on the
    rig, same as flipHandedness in PoseReceiver.cs.
    """
    return np.array([q[0], q[2], q[1], -q[3]], dtype=np.float32)


def pack_frame(pose_row: np.ndarray, joint_indices: list[int]) -> bytes:
    """Encode one pose into PoseFrameCodec's wire format: root pos (3f) + 30 quats (4f each).

    pose_row is the skeleton's full (77, 7) array: [x, y, z, qx, qy, qz, qw] per joint, local
    transforms relative to each joint's parent except joint 0 (Hips), whose transform is the
    world root placement — see motionbricks/docs/runtime_api.md "Pose layouts and model space".
    """
    root_pos = zup_to_yup_pos(pose_row[0, :3])
    payload = struct.pack("<3f", *root_pos)
    for idx in joint_indices:
        quat = zup_to_yup_quat(pose_row[idx, 3:7])
        payload += struct.pack("<4f", *quat)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to run (default: 60)")
    args = parser.parse_args()

    wp.init()
    wp.set_device("cuda:0")
    rig = load_rig("soma", JOG)
    joint_indices = [rig.skeleton.joint_names.index(name) for name in SOMA_JOINT_ORDER]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Sending live motionbricks frames to {HOST}:{PORT} at {UPDATE_RATE} Hz for {args.duration:.0f}s.")

    with rig.engine as engine, wp.ScopedStream(engine.stream):
        player = GeneratedMotionPlayer(engine, rig.skeleton)
        jog_poses = wp.empty((MODEL_POSES_PER_TOKEN, *rig.reference_pose.shape), dtype=rig.reference_pose.dtype)
        canonical_target(rig, jog_poses)
        target_poses = wp.empty_like(jog_poses)
        settings = TargetPoseInferenceParams(transition_early_by_frames=TRANSITION_EARLY_BY, num_poses_to_use=4)

        current_pose = wp.clone(jog_poses[MODEL_POSES_PER_TOKEN - 1])
        player.seed_history_from_pose(current_pose)
        foot_contacts = wp.zeros(4, dtype=wp.float32)
        generated_direction = None
        delta_time = 1.0 / UPDATE_RATE

        for step in range(round(args.duration * UPDATE_RATE)):
            time = step * delta_time
            direction = steering(time)
            position = root_positions(current_pose.reshape((1, -1)))[0] * np.array([1.0, 1.0, 0.0])

            turned = generated_direction is not None and math.degrees(
                math.acos(min(1.0, float(direction @ generated_direction)))
            ) > TURN_THRESHOLD_DEG
            if generated_direction is None or turned or player.time_to_transition <= delta_time:
                ground_position = position + direction * DESIRED_SPEED * LEAD_SECONDS
                place_target_poses(
                    wp.vec3(*ground_position), wp.vec3(*direction), jog_poses, target_poses, stream=engine.stream,
                )
                player.generate(target_poses, settings)
                generated_direction = direction

            player.sample(delta_time, current_pose, foot_contacts)
            player.record_pose(delta_time, current_pose)

            sock.sendto(pack_frame(current_pose.numpy(), joint_indices), (HOST, PORT))

            if step % round(UPDATE_RATE) == 0:
                engine.synchronize()
                print(f"t = {time:4.1f}s  steering {direction[:2].round(2)}  root {position[:2].round(2)}")
        engine.synchronize()
    print("Done.")


if __name__ == "__main__":
    main()
