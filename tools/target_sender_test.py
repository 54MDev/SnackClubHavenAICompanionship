"""Send step-5 target datagrams to pose_sender_motionbricks.py, standing in for Unity.

Stage 1 of docs/step5_room_geometry_to_motion.md: proves the Python half of the reverse
channel with no Unity, no APK and no headset. Coordinates are motionbricks Z-up ground
coords, the same thing Unity will send once TargetSender.cs exists.

Usage:
    python target_sender_test.py 2,0                 # walk to (2, 0) and stop
    python target_sender_test.py 2,0 0,2 --hold 8    # redirect every 8s, proves re-steering
    python target_sender_test.py idle                # has_target=0, falls back to scripted jog
"""
import argparse
import socket
import struct
from time import sleep

TARGET_FORMAT = "<2fB"  # must match pose_sender_motionbricks.TARGET_FORMAT


def pack(spec: str) -> bytes:
    if spec == "idle":
        return struct.pack(TARGET_FORMAT, 0.0, 0.0, 0)
    x, y = (float(n) for n in spec.split(","))
    return struct.pack(TARGET_FORMAT, x, y, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="+", metavar="X,Y|idle")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5006)
    parser.add_argument("--hold", type=float, default=0.0,
                        help="seconds between targets (default 0: send all once and exit)")
    parser.add_argument("--repeat", type=float, default=0.0,
                        help="resend the current target every N seconds, like Unity's keepalive")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for spec in args.targets:
        payload = pack(spec)
        sock.sendto(payload, (args.host, args.port))
        print(f"sent {spec} -> {args.host}:{args.port} ({len(payload)} bytes)")
        if args.hold <= 0:
            continue
        # Resend while holding, so a dropped datagram cannot strand the character.
        elapsed = 0.0
        while elapsed < args.hold:
            step = args.repeat if args.repeat > 0 else args.hold
            sleep(min(step, args.hold - elapsed))
            elapsed += step
            if args.repeat > 0 and elapsed < args.hold:
                sock.sendto(payload, (args.host, args.port))


def demo() -> None:
    """assert-based self-check of the only logic here (the packing). No socket needed."""
    assert len(pack("2,0")) == 9
    assert struct.unpack(TARGET_FORMAT, pack("2,-3.5")) == (2.0, -3.5, 1)
    assert struct.unpack(TARGET_FORMAT, pack("idle"))[2] == 0
    print("target_sender_test self-check passed.")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        demo()
    else:
        main()
