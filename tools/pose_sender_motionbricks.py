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
from time import perf_counter, sleep

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

HOST, PORT = "127.0.0.1", 5005  # --host overrides HOST for an on-device build (Quest over Wi-Fi)
TARGET_PORT = 5006  # inbound: Unity -> here, "walk to this spot" (step 5, stage 1)
ARRIVAL_SLOW_RADIUS = 0.25  # m; inside this the target pose lands on the character, so she settles
UPDATE_RATE = 30.0  # matches PoseReceiver.cs / PoseFrameCodec's one-datagram-per-frame design
DESIRED_SPEED = 1.9  # m/s, SOMA's jog clip speed (from motionbricks' own locomotion_loop.py)
LEAD_SECONDS = 1.0
TRANSITION_EARLY_BY = 4
TARGET_FORMAT = "<2fB"  # see decode_target
TARGET_SIZE = struct.calcsize(TARGET_FORMAT)  # 9 bytes
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
    """(x, y, z) in motionbricks' Z-up world -> (-x, z, -y) in Unity's Y-up left-handed space.

    motionbricks' apps run in Z-up world space (runtime_api.md "Pose layouts and model space"),
    not the Y-up SOMA/BVH model space CLAUDE.md originally described — found by observing a
    live frame land the character ~43 units up in Unity's Y axis.

    The Y/Z swap is the standard Z-up-RH -> Y-up-LH conversion: its determinant is -1, which is
    what keeps chirality intact when the same numbers are reinterpreted in a left-handed basis
    (verified: SOMA's rest pose triple product is +0.0073 in its RH basis, DonQuixote's is
    negative in Unity's LH basis — the sign flip is the conversion being mirror-free).

    The extra negation of x and y on top of that swap is a 180 degree yaw, which lines SOMA's
    rest pose up with Unity's humanoid convention instead of leaving it backwards: SOMA faces
    -Y with its left arm on +X, so the bare swap lands it facing -Z, while Unity rigs
    (DonQuixote measured) face +Z with the left arm on -X.
    """
    return np.array([-p[0], p[2], -p[1]], dtype=np.float32)


def yup_to_zup_pos(u: np.ndarray) -> np.ndarray:
    """Exact inverse of zup_to_yup_pos: Unity Y-up left-handed -> motionbricks Z-up.

    Needed for the inbound direction (step 5): Unity owns the room and the NavMesh, so it
    sends target points in ITS space and this is where they come back into ours. Derived,
    not guessed -- zup_to_yup_pos maps (x, y, z) -> (-x, z, -y), so inverting each component
    gives (-u.x, -u.z, u.y). self_test() asserts the round-trip.
    """
    return np.array([-u[0], -u[2], u[1]], dtype=np.float32)


def decode_target(payload: bytes) -> np.ndarray | None:
    """One inbound target datagram -> ground position in our Z-up space, or None for "idle".

    Wire format, 9 bytes: float32 x, float32 y, uint8 has_target. The two floats are ALREADY
    in motionbricks Z-up ground coordinates -- Unity does that conversion with the
    yup_to_zup_pos rule above, because for a ground target Unity's height drops out entirely
    and it collapses to (-d.x, -d.z). Sending an absolute target rather than a direction is
    deliberate: it is idempotent, so a dropped datagram just means she keeps walking to the
    last known spot instead of veering off.
    """
    x, y, has_target = struct.unpack(TARGET_FORMAT, payload)
    return None if not has_target else np.array([x, y, 0.0], dtype=np.float32)


def drain_target(sock: socket.socket, current: np.ndarray | None) -> np.ndarray | None:
    """Newest target on the socket, or `current` if nothing arrived.

    Non-blocking and drains the whole backlog every tick: the main loop is wall-clock paced
    at 30 Hz, so a blocking read would wreck the pacing and bring back the jitter that
    pacing just fixed. Malformed datagrams are dropped, matching PoseReceiver.cs.
    """
    while True:
        try:
            payload = sock.recv(64)
        except BlockingIOError:
            return current
        if len(payload) == TARGET_SIZE:
            current = decode_target(payload)


def zup_to_yup_quat(q: np.ndarray) -> np.ndarray:
    """Matching rotation conversion for the same Y/Z axis swap. x,y,z,w order.

    Derived by conjugating the rotation matrix R by the swap matrix P (R' = P R P^-1), not
    guessed: for this P, a rotation by angle theta about any axis maps to a rotation by -theta
    about the Y/Z-swapped axis, i.e. w unchanged, vector part negated and with y/z swapped.
    Conjugating that by the 180 degree yaw of zup_to_yup_pos (which negates the x and z of a
    vector part) gives the form below. Verified by --self-test to be a homomorphism
    (T(ab) == T(a)T(b)) and consistent with zup_to_yup_pos, so it is safe to apply per joint.
    """
    return np.array([q[0], -q[2], q[1], q[3]], dtype=np.float32)


def qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of two x,y,z,w quaternions."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], dtype=np.float32)


def qinv(q: np.ndarray) -> np.ndarray:
    """Inverse of a unit x,y,z,w quaternion."""
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=np.float32)


def pack_frame(world: np.ndarray, rest_world_inv: np.ndarray, joint_indices: list[int]) -> bytes:
    """Encode one pose into PoseFrameCodec's wire format: root pos (3f) + 30 quats (4f each).

    Sends WORLD-space rotation deltas from the sender's own rest pose, not raw local
    rotations. Raw locals are meaningless to Unity: they are relative to SOMA's bind pose,
    and DonQuixote's avatar has a different one, so composing them onto Unity's rest pose
    distorted every limb. delta = G_pose * G_rest^-1 cancels both bind poses out, and the
    receiver re-applies it to its own rest world rotation. Identity delta = hold rest pose,
    which also keeps tools/pose_sender_test.py's synthetic frames meaningful.

    Hips needs no special case any more: everything is world-space, which is what joint 0's
    transform already was (motionbricks/docs/runtime_api.md "Pose layouts and model space").

    Args:
        world: Per-joint world transforms of this pose, (num_joints, 7) as [x,y,z,qx,qy,qz,qw].
        rest_world_inv: Inverse world rotations of the rest pose, (30, 4), our joints only.
        joint_indices: Index of each SOMA_JOINT_ORDER joint in the full skeleton.
    """
    payload = struct.pack("<3f", *zup_to_yup_pos(world[joint_indices[0], :3]))
    for slot, idx in enumerate(joint_indices):
        delta = qmul(world[idx, 3:7], rest_world_inv[slot])
        payload += struct.pack("<4f", *zup_to_yup_quat(delta))
    return payload


def self_test() -> None:
    """Offline check of the coordinate + delta math (no GPU, no motionbricks runtime)."""
    s2 = math.sqrt(0.5)
    rx90 = np.array([s2, 0.0, 0.0, s2], dtype=np.float32)  # 90 deg about X
    ry90 = np.array([0.0, s2, 0.0, s2], dtype=np.float32)  # 90 deg about Y

    # T must be a homomorphism, or applying it per joint would break the hierarchy.
    assert np.allclose(zup_to_yup_quat(qmul(rx90, ry90)),
                       qmul(zup_to_yup_quat(rx90), zup_to_yup_quat(ry90)), atol=1e-6)

    # T on rotations must agree with T on positions: rotate-then-convert == convert-then-rotate.
    rz90 = np.array([0.0, 0.0, s2, s2], dtype=np.float32)
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    rotated = qmul(qmul(rz90, np.array([*v, 0.0], dtype=np.float32)), qinv(rz90))[:3]
    tq = zup_to_yup_quat(rz90)
    tv = zup_to_yup_pos(v)
    rotated_after = qmul(qmul(tq, np.array([*tv, 0.0], dtype=np.float32)), qinv(tq))[:3]
    assert np.allclose(zup_to_yup_pos(rotated), rotated_after, atol=1e-6), "pos/quat conversions disagree"

    # A pose equal to the rest pose must produce identity deltas (receiver holds its rest pose).
    rest = np.zeros((2, 7), dtype=np.float32)
    rest[:, 3:7] = [rx90, ry90]
    rest_inv = np.stack([qinv(rest[i, 3:7]) for i in range(2)])
    packed = pack_frame(rest, rest_inv, [0, 1])
    quats = np.array(struct.unpack("<8f", packed[12:])).reshape(2, 4)
    assert np.allclose(np.abs(quats[:, 3]), 1.0, atol=1e-6), f"rest pose should give identity, got {quats}"
    # Step 5: the inbound conversion must be the EXACT inverse of the outbound one, on a
    # vector with three distinct nonzero components (so a swapped or dropped axis is caught).
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert np.allclose(zup_to_yup_pos(v), [-1.0, 3.0, -2.0]), zup_to_yup_pos(v)
    assert np.allclose(yup_to_zup_pos(zup_to_yup_pos(v)), v), "yup_to_zup_pos is not the inverse"
    assert np.allclose(zup_to_yup_pos(yup_to_zup_pos(v)), v), "inverse does not round-trip both ways"

    # Unity's ground-target shortcut: height must drop out, leaving (-d.x, -d.z).
    d = np.array([0.5, 9.9, -2.0], dtype=np.float32)  # Unity-space offset; y is nonsense on purpose
    ground = yup_to_zup_pos(d) * np.array([1.0, 1.0, 0.0], dtype=np.float32)
    assert np.allclose(ground, [-0.5, 2.0, 0.0]), ground

    # Target datagram round-trip, including the idle flag.
    assert decode_target(struct.pack(TARGET_FORMAT, 1.5, -2.5, 1)) is not None
    assert np.allclose(decode_target(struct.pack(TARGET_FORMAT, 1.5, -2.5, 1)), [1.5, -2.5, 0.0])
    assert decode_target(struct.pack(TARGET_FORMAT, 1.5, -2.5, 0)) is None, "has_target=0 must mean idle"
    assert TARGET_SIZE == 9, TARGET_SIZE

    print("pose_sender_motionbricks self-test passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to run (default: 60)")
    parser.add_argument("--self-test", action="store_true", help="run the offline math check and exit")
    parser.add_argument("--target", type=lambda v: [float(n) for n in v.split(",")], default=None,
                        metavar="X,Y",
                        help="initial ground target in motionbricks Z-up coords, e.g. --target 2,0 . "
                             "Lets stage 1 be tested with no Unity and no headset. Without it the "
                             "character runs the original scripted jog until a target datagram lands.")
    parser.add_argument("--host", default=HOST,
                        help=f"destination IP (default: {HOST}). Use the headset's Wi-Fi IP for an "
                             "on-device build, which takes Quest Link out of the loop entirely.")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    wp.init()
    wp.set_device("cuda:0")
    rig = load_rig("soma", JOG)
    joint_indices = [rig.skeleton.joint_names.index(name) for name in SOMA_JOINT_ORDER]

    # Rest pose in world space, for the delta in pack_frame. root_tx puts it in the same Z-up
    # runtime space the sampled poses live in (reference_local_transforms are SOMA's Y-up model
    # space; only the root differs, since parent-relative locals are basis-independent).
    world = wp.empty(rig.skeleton.num_joints, dtype=wp.transform, device=rig.skeleton.device)
    rig.skeleton.compute_world_transforms(
        rig.skeleton.reference_local_transforms, world, root_tx=rig.model_to_runtime,
    )
    rest_world_inv = np.stack([qinv(world.numpy()[idx, 3:7]) for idx in joint_indices])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Sending live motionbricks frames to {args.host}:{PORT} at {UPDATE_RATE} Hz for {args.duration:.0f}s.")

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
        start = perf_counter()
        late_frames = 0

        target_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        target_sock.bind(("0.0.0.0", TARGET_PORT))
        target_sock.setblocking(False)
        target = None if args.target is None else np.array([*args.target, 0.0], dtype=np.float32)
        print(f"Listening for targets on 0.0.0.0:{TARGET_PORT}"
              + ("" if target is None else f"; starting target {args.target}"))

        for step in range(round(args.duration * UPDATE_RATE)):
            time = step * delta_time
            position = root_positions(current_pose.reshape((1, -1)))[0] * np.array([1.0, 1.0, 0.0])

            # Step 5: a target from Unity (or --target) wins; with no target at all we fall
            # back to the original scripted jog so the known-good demo still runs unchanged.
            target = drain_target(target_sock, target)
            if target is None:
                direction = steering(time)
                lead = DESIRED_SPEED * LEAD_SECONDS
            else:
                to_target = target - position
                distance = float(np.linalg.norm(to_target[:2]))
                # Clamping the lead to the remaining distance is what makes her STOP instead
                # of overshooting: as distance -> 0 the target pose lands on top of her.
                lead = min(DESIRED_SPEED * LEAD_SECONDS, distance)
                if distance > ARRIVAL_SLOW_RADIUS:
                    direction = (to_target / distance).astype(np.float32)
                elif generated_direction is not None:
                    direction = generated_direction  # arrived: hold heading, don't spin
                else:
                    direction = steering(time)
                if step % round(UPDATE_RATE) == 0:
                    print(f"    target {target[:2].round(2)}  distance {distance:5.2f} m")

            turned = generated_direction is not None and math.degrees(
                math.acos(min(1.0, float(direction @ generated_direction)))
            ) > TURN_THRESHOLD_DEG
            if generated_direction is None or turned or player.time_to_transition <= delta_time:
                ground_position = position + direction * lead
                place_target_poses(
                    wp.vec3(*ground_position), wp.vec3(*direction), jog_poses, target_poses, stream=engine.stream,
                )
                player.generate(target_poses, settings)
                generated_direction = direction

            player.sample(delta_time, current_pose, foot_contacts)
            player.record_pose(delta_time, current_pose)

            rig.skeleton.compute_world_transforms(current_pose, world, stream=engine.stream)
            sock.sendto(pack_frame(world.numpy(), rest_world_inv, joint_indices), (args.host, PORT))

            # The loop used to be unpaced: delta_time was only the SIMULATION timestep, so
            # frames went out as fast as the GPU could produce them. Sharing a GPU with Unity's
            # XR render + Link encode that collapsed to ~8-15 Hz and arrived in bursts (measured
            # 1-75 Hz within one run), which is what made the rig jitter -- and running the GPU
            # flat out starved the renderer. Clocking it to wall time makes 30 Hz mean 30 Hz and
            # leaves the GPU idle between frames.
            slack = start + (step + 1) * delta_time - perf_counter()
            if slack > 0:
                sleep(slack)
            else:
                late_frames += 1

            if step % round(UPDATE_RATE) == 0:
                engine.synchronize()
                print(f"t = {time:4.1f}s  steering {direction[:2].round(2)}  root {position[:2].round(2)}")
        engine.synchronize()
        elapsed = perf_counter() - start
        sent = round(args.duration * UPDATE_RATE)
        print(f"Done. Sent {sent} frames in {elapsed:.1f}s = {sent / elapsed:.1f} Hz achieved "
              f"({late_frames} frames late, i.e. the GPU could not keep up with {UPDATE_RATE:.0f} Hz).")


if __name__ == "__main__":
    main()
