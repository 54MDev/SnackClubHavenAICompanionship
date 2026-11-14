using UnityEngine;

/// <summary>
/// Wire format for the motionbricks -> Unity SOMA pose stream (CLAUDE.md "Live streaming").
/// One UDP datagram per frame, little-endian floats:
///   root position (3 floats, meters) + 30 quaternions (x,y,z,w) in SOMA joint order.
/// Rotations are WORLD-space deltas from the sender's rest pose (identity = hold rest pose),
/// already converted to Unity's left-handed Y-up space by the sender.
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

    /// <summary>
    /// Child joint of each SOMA joint, as an index into this same order; -1 for leaves and the
    /// unmapped markers. Used to measure a bone's direction as (child.position - bone.position).
    /// </summary>
    public static readonly int[] SomaChildJoint =
    {
        1, 2, 3, 4, 6, -1, -1, -1, -1, -1,
        11, 12, 13, 15, -1, -1,
        17, 18, 19, 21, -1, -1,
        23, 24, 25, -1, 27, 28, 29, -1,
    };

    // SOMA rest-pose bone directions in Unity space (generated, not guessed: measured from
    // soma_base_skel_minimal_no_root.usd's reference pose, converted with the sender's
    // Z-up -> Unity conversion). Vector3.zero = leaf/unmapped, no direction to align.
    // It is a clean T-pose: spine +Y, left arm -X, right arm +X, legs -Y, toes +Z.
    public static readonly Vector3[] SomaRestBoneDirections =
    {
        new Vector3(0.0000f, 1.0000f, -0.0021f), // Hips -> Spine1
        new Vector3(0.0000f, 0.9998f, -0.0219f), // Spine1 -> Spine2
        new Vector3(0.0000f, 0.9959f, -0.0900f), // Spine2 -> Chest
        new Vector3(0.0000f, 1.0000f, -0.0035f), // Chest -> Neck1
        new Vector3(0.0000f, 0.9557f, 0.2942f), // Neck1 -> Head
        Vector3.zero, // Neck2
        Vector3.zero, // Head
        Vector3.zero, // Jaw
        Vector3.zero, // LeftEye
        Vector3.zero, // RightEye
        new Vector3(-0.9382f, 0.0000f, -0.3460f), // LeftShoulder -> LeftArm
        new Vector3(-1.0000f, 0.0000f, 0.0000f), // LeftArm -> LeftForeArm
        new Vector3(-1.0000f, 0.0000f, 0.0000f), // LeftForeArm -> LeftHand
        new Vector3(-1.0000f, 0.0000f, 0.0000f), // LeftHand -> LeftHandMiddleEnd
        Vector3.zero, // LeftHandThumbEnd
        Vector3.zero, // LeftHandMiddleEnd
        new Vector3(0.9382f, 0.0000f, -0.3460f), // RightShoulder -> RightArm
        new Vector3(1.0000f, 0.0000f, 0.0000f), // RightArm -> RightForeArm
        new Vector3(1.0000f, 0.0000f, 0.0000f), // RightForeArm -> RightHand
        new Vector3(1.0000f, 0.0000f, 0.0000f), // RightHand -> RightHandMiddleEnd
        Vector3.zero, // RightHandThumbEnd
        Vector3.zero, // RightHandMiddleEnd
        new Vector3(0.0000f, -1.0000f, 0.0000f), // LeftLeg -> LeftShin
        new Vector3(0.0000f, -1.0000f, 0.0000f), // LeftShin -> LeftFoot
        new Vector3(0.0000f, -0.3572f, 0.9340f), // LeftFoot -> LeftToeBase
        Vector3.zero, // LeftToeBase
        new Vector3(0.0000f, -1.0000f, 0.0000f), // RightLeg -> RightShin
        new Vector3(0.0000f, -1.0000f, 0.0000f), // RightShin -> RightFoot
        new Vector3(0.0000f, -0.3572f, 0.9340f), // RightFoot -> RightToeBase
        Vector3.zero, // RightToeBase
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
        UnityEngine.Assertions.Assert.AreEqual(JointCount, SomaChildJoint.Length, "SomaChildJoint length mismatch");
        UnityEngine.Assertions.Assert.AreEqual(JointCount, SomaRestBoneDirections.Length, "SomaRestBoneDirections length mismatch");
        for (int i = 0; i < JointCount; i++)
        {
            int child = SomaChildJoint[i];
            UnityEngine.Assertions.Assert.IsTrue(child == -1 || (child > i && child < JointCount),
                $"SomaChildJoint[{i}] ({SomaJointOrder[i]}) must be -1 or a later joint, got {child}");
            // A joint has a rest direction exactly when it has a child to point at.
            UnityEngine.Assertions.Assert.AreEqual(child == -1, SomaRestBoneDirections[i] == Vector3.zero,
                $"Joint {i} ({SomaJointOrder[i]}): child index and rest direction disagree");
        }

        Debug.Log("PoseFrameCodec self-test passed.");
    }
#endif
}
