"""PoseReceiver.cs smoke test — synthetic pose, not a real SOMA BVH clip.

ponytail: sends a synthetic oscillating pose instead of parsing a real BVH clip, to test
the receiver's wire format/bone-lookup wiring without reimplementing motionbricks' BVH
loader. Swap in a real clip (motionbricks/motionbricks/io/bvh.py) when testing motion
fidelity, not just the pipe.

Wire format: 30 Hz UDP datagrams to 127.0.0.1:5005, little-endian floats:
  root position (x,y,z, meters) + 30 quaternions (x,y,z,w) in SOMA joint order.
Order must match Assets/Scripts/PoseFrameCodec.cs SomaJointOrder.

Run this, then press Play in Unity with PoseReceiver on the DonQuixote rig: the hips
should rock side to side.
"""
import math
import socket
import struct
import time

HOST, PORT = "127.0.0.1", 5005
JOINT_COUNT = 30
HZ = 30.0


def euler_to_quat(rx_deg, ry_deg, rz_deg):
    rx, ry, rz = (math.radians(a) for a in (rx_deg, ry_deg, rz_deg))
    cy, sy = math.cos(ry * 0.5), math.sin(ry * 0.5)
    cx, sx = math.cos(rx * 0.5), math.sin(rx * 0.5)
    cz, sz = math.cos(rz * 0.5), math.sin(rz * 0.5)
    return (
        cy * sx * cz - sy * cx * sz,
        sy * cx * cz + cy * sx * sz,
        cy * cx * sz - sy * sx * cz,
        cy * cx * cz + sy * sx * sz,
    )


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Sending synthetic test frames to {HOST}:{PORT} at {HZ} Hz. Ctrl+C to stop.")
    t = 0.0
    try:
        while True:
            swing_deg = 30.0 * math.sin(t * 2.0)
            payload = struct.pack("<3f", 0.0, 1.0, 0.0)  # root position
            for i in range(JOINT_COUNT):
                x, y, z, w = euler_to_quat(swing_deg if i == 0 else 0.0, 0.0, 0.0)
                payload += struct.pack("<4f", x, y, z, w)
            sock.sendto(payload, (HOST, PORT))
            t += 1.0 / HZ
            time.sleep(1.0 / HZ)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
