using UnityEngine;

/// <summary>
/// Wire format for the motionbricks -> Unity SOMA pose stream (CLAUDE.md "Live streaming").
/// One UDP datagram per frame, little-endian floats:
///   root position (3 floats, meters) + 30 quaternions (x,y,z,w) in SOMA joint order.
/// Joint order and the SOMA -> HumanBodyBones mapping mirror the table in CLAUDE.md step 2,
/// itself sourced from motionbricks/motionbricks/assets/onnx/soma/soma_n1.json.
/// </summary>
public static class PoseFrameCodec
{
    public const int JointCount = 30;
    public const int PayloadSize = sizeof(float) * (3 + JointCount * 4); // 492 bytes

    public static readonly string[] SomaJointOrder =
    {
        "Hips", "Spine1", "Spine2", "Chest", "Neck1", "Neck2", "Head", "Jaw", "LeftEye", "RightEye",
        "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "LeftHandThumbEnd", "LeftHandMiddleEnd",
        "RightShoulder", "RightArm", "RightForeArm", "RightHand", "RightHandThumbEnd", "RightHandMiddleEnd",
        "LeftLeg", "LeftShin", "LeftFoot", "LeftToeBase", "RightLeg", "RightShin", "RightFoot", "RightToeBase",
    };

    /// <summary>Null entries have no 1:1 Humanoid slot (Neck2, hand end-effector markers) — PoseReceiver skips them.</summary>
    public static readonly HumanBodyBones?[] SomaToHumanBone =
    {
        HumanBodyBones.Hips, HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest,
        HumanBodyBones.Neck, null /* Neck2 */, HumanBodyBones.Head, HumanBodyBones.Jaw,
        HumanBodyBones.LeftEye, HumanBodyBones.RightEye,
        HumanBodyBones.LeftShoulder, HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand,
        null /* LeftHandThumbEnd */, null /* LeftHandMiddleEnd */,
        HumanBodyBones.RightShoulder, HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand,
        null /* RightHandThumbEnd */, null /* RightHandMiddleEnd */,
        HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot, HumanBodyBones.LeftToes,
        HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot, HumanBodyBones.RightToes,
    };

    public struct Frame
    {
        public Vector3 RootPosition;
        public Quaternion[] JointRotations; // length JointCount, SOMA order
    }

    public static byte[] Encode(Frame frame)
    {
        var bytes = new byte[PayloadSize];
        int o = 0;
        WriteVector3(bytes, ref o, frame.RootPosition);
        for (int i = 0; i < JointCount; i++) WriteQuaternion(bytes, ref o, frame.JointRotations[i]);
        return bytes;
    }

    public static Frame Decode(byte[] bytes)
    {
        if (bytes.Length != PayloadSize)
            throw new System.ArgumentException($"Expected {PayloadSize} bytes, got {bytes.Length}");
        int o = 0;
        var frame = new Frame { JointRotations = new Quaternion[JointCount] };
        frame.RootPosition = ReadVector3(bytes, ref o);
        for (int i = 0; i < JointCount; i++) frame.JointRotations[i] = ReadQuaternion(bytes, ref o);
        return frame;
    }

    // SOMA model space is commonly right-handed Y-up; Unity is left-handed Y-up.
    // ponytail: unverified against real motionbricks output — flip PoseReceiver.flipHandedness
    // if the first live frame looks mirrored, per CLAUDE.md's "handedness flip to verify".
    public static Quaternion ConvertHandedness(Quaternion q) => new Quaternion(q.x, q.y, -q.z, -q.w);

    static void WriteVector3(byte[] b, ref int o, Vector3 v) { WriteFloat(b, ref o, v.x); WriteFloat(b, ref o, v.y); WriteFloat(b, ref o, v.z); }
    static void WriteQuaternion(byte[] b, ref int o, Quaternion q) { WriteFloat(b, ref o, q.x); WriteFloat(b, ref o, q.y); WriteFloat(b, ref o, q.z); WriteFloat(b, ref o, q.w); }
    static void WriteFloat(byte[] b, ref int o, float v) { System.BitConverter.GetBytes(v).CopyTo(b, o); o += sizeof(float); }

    static Vector3 ReadVector3(byte[] b, ref int o) => new Vector3(ReadFloat(b, ref o), ReadFloat(b, ref o), ReadFloat(b, ref o));
    static Quaternion ReadQuaternion(byte[] b, ref int o) => new Quaternion(ReadFloat(b, ref o), ReadFloat(b, ref o), ReadFloat(b, ref o), ReadFloat(b, ref o));
    static float ReadFloat(byte[] b, ref int o) { var v = System.BitConverter.ToSingle(b, o); o += sizeof(float); return v; }

#if UNITY_EDITOR
    // Runnable check for this file's non-trivial parsing logic (encode/decode round-trip + table shape).
    [UnityEditor.MenuItem("Tools/Pose Streaming/Run PoseFrameCodec Self-Test")]
    public static void SelfTest()
    {
        var frame = new Frame
        {
            RootPosition = new Vector3(1.5f, 0.9f, -2.25f),
            JointRotations = new Quaternion[JointCount],
        };
        for (int i = 0; i < JointCount; i++)
            frame.JointRotations[i] = Quaternion.Euler(i * 3f, i * 7f, i * 11f);

        var bytes = Encode(frame);
        UnityEngine.Assertions.Assert.AreEqual(PayloadSize, bytes.Length, "Encoded payload size mismatch");

        var decoded = Decode(bytes);
        UnityEngine.Assertions.Assert.IsTrue(Vector3.Distance(frame.RootPosition, decoded.RootPosition) < 1e-5f,
            "Root position round-trip mismatch");
        for (int i = 0; i < JointCount; i++)
        {
            var dot = Quaternion.Dot(frame.JointRotations[i], decoded.JointRotations[i]);
            UnityEngine.Assertions.Assert.IsTrue(Mathf.Abs(dot) > 0.9999f,
                $"Joint {i} ({SomaJointOrder[i]}) rotation round-trip mismatch");
        }

        UnityEngine.Assertions.Assert.AreEqual(JointCount, SomaJointOrder.Length, "SomaJointOrder length mismatch");
        UnityEngine.Assertions.Assert.AreEqual(JointCount, SomaToHumanBone.Length, "SomaToHumanBone length mismatch");

        Debug.Log("PoseFrameCodec self-test passed.");
    }
#endif
}
