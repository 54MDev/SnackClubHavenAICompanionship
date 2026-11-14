using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

/// <summary>
/// UDP listener that drives a Humanoid Animator's bones from motionbricks' SOMA pose stream.
/// Wire format: see <see cref="PoseFrameCodec"/>. Bootstrap/debug with tools/pose_sender_test.py
/// before wiring motionbricks' real sender (CLAUDE.md "Live streaming" step 4).
///
/// Incoming rotations are world-space deltas from the SENDER's rest pose (a T-pose), so they
/// are applied to a T-pose-aligned reference built from this rig's own bind pose at Awake --
/// NOT to the bind pose itself, which on DonQuixote is an arms-down pose with bent elbows and
/// double-rotated every limb. All axis/handedness conversion lives in the sender (it owns the
/// Z-up source data).
/// </summary>
[RequireComponent(typeof(Animator))]
public class PoseReceiver : MonoBehaviour
{
    [SerializeField] int port = 5005;
    [SerializeField] float positionScale = 1f; // sender sends meters; raise it if a rig is not at 1 unit = 1 m

    Animator _animator;
    Transform[] _boneTransforms; // indexed by SOMA joint index; null where unmapped or this rig lacks the bone
    Quaternion[] _referenceWorldRotations; // per bone: its bind-pose world rotation, swung so the bone axis matches SOMA's T-pose
    Vector3 _hipsOffsetFromRoot; // rest offset of the Hips bone from this GameObject, in rig units
    UdpClient _udp;
    Thread _receiveThread;
    volatile bool _running;

    readonly object _lock = new object();
    byte[] _latestPayload;
    bool _hasFrame;
    PoseFrameCodec.Frame _frame; // last decoded frame, re-applied every render frame
    bool _hasDecoded;

    void Awake()
    {
        _animator = GetComponent<Animator>();
        _animator.applyRootMotion = false; // we own the root transform
        _boneTransforms = new Transform[PoseFrameCodec.JointCount];
        _referenceWorldRotations = new Quaternion[PoseFrameCodec.JointCount];
        for (int i = 0; i < PoseFrameCodec.JointCount; i++)
        {
            var humanBone = PoseFrameCodec.SomaToHumanBone[i];
            var bone = humanBone.HasValue ? _animator.GetBoneTransform(humanBone.Value) : null;
            _boneTransforms[i] = bone;
            if (bone != null) _referenceWorldRotations[i] = ReferenceRotation(i, bone);
        }

        // SOMA's root position is its Hips joint, but this script moves the GameObject root, and
        // the Hips bone sits a hip-height above it. Without this the rig floats by exactly that
        // much (it was invisible while the rig was ~3500x scale, obvious once it is 1 unit = 1 m).
        var hipsBone = _boneTransforms[0];
        if (hipsBone != null) _hipsOffsetFromRoot = hipsBone.position - transform.position;
    }

    /// <summary>
    /// This rig's bind-pose world rotation for one bone, pre-swung so the bone points where
    /// SOMA's T-pose rest points it. The incoming deltas are measured from SOMA's T-pose, so
    /// without this they land on whatever pose the FBX happened to be authored in -- for
    /// DonQuixote an arms-down pose with bent elbows, which is what made limbs bend inwards and
    /// backwards. Unity's own T-pose is not reachable here: zeroing HumanPose muscles gives the
    /// avatar's relaxed neutral (arms down 45 deg, knees bent 30 deg), not a T-pose.
    /// ponytail: minimal-arc alignment, so it fixes bone DIRECTION but not twist about the bone
    /// axis. Good enough for locomotion; if wrists/forearms read as rolled, align a second axis
    /// (e.g. the limb's bend plane) instead of using FromToRotation.
    /// </summary>
    Quaternion ReferenceRotation(int joint, Transform bone)
    {
        var somaDirection = PoseFrameCodec.SomaRestBoneDirections[joint];
        if (somaDirection == Vector3.zero) return bone.rotation; // leaf: no bone axis to align

        int childJoint = PoseFrameCodec.SomaChildJoint[joint];
        var childHumanBone = childJoint >= 0 ? PoseFrameCodec.SomaToHumanBone[childJoint] : null;
        var child = childHumanBone.HasValue ? _animator.GetBoneTransform(childHumanBone.Value) : null;
        if (child == null) return bone.rotation; // this rig lacks the child bone (e.g. hand end markers)

        var boneDirection = child.position - bone.position;
        if (boneDirection.sqrMagnitude < 1e-12f) return bone.rotation; // zero-length bone
        return Quaternion.FromToRotation(boneDirection, somaDirection) * bone.rotation;
    }

    void OnEnable()
    {
        _udp = new UdpClient(port);
        _running = true;
        _receiveThread = new Thread(ReceiveLoop) { IsBackground = true };
        _receiveThread.Start();
    }

    void OnDisable()
    {
        _running = false;
        _udp?.Close();
        _receiveThread?.Join(200);
    }

    void ReceiveLoop()
    {
        var remote = new IPEndPoint(IPAddress.Any, 0);
        while (_running)
        {
            try
            {
                var payload = _udp.Receive(ref remote);
                if (payload.Length != PoseFrameCodec.PayloadSize) continue; // drop malformed datagram
                lock (_lock) { _latestPayload = payload; _hasFrame = true; }
            }
            catch (SocketException)
            {
                // expected on OnDisable()'s _udp.Close()
            }
        }
    }

    // LateUpdate, not Update: the Animator evaluates its Humanoid avatar between the two and
    // would overwrite bone writes made in Update().
    void LateUpdate()
    {
        byte[] payload = null;
        lock (_lock)
        {
            if (_hasFrame) { payload = _latestPayload; _hasFrame = false; }
        }
        if (payload != null)
        {
            _frame = PoseFrameCodec.Decode(payload);
            _hasDecoded = true;
        }

        // Re-apply the last frame every render frame, not only on frames a datagram landed on:
        // the sender runs at 30 Hz and the render loop much faster, so skipping the other frames
        // let the Animator's avatar pose show through and the rig jittered at the beat frequency.
        if (!_hasDecoded) return;

        transform.position = _frame.RootPosition * positionScale - _hipsOffsetFromRoot;

        // SOMA joint order is parent-before-child, so setting world rotations in order leaves
        // each bone correct: a parent's write happens before its children's.
        for (int i = 0; i < PoseFrameCodec.JointCount; i++)
        {
            var bone = _boneTransforms[i];
            if (bone == null) continue; // unmapped SOMA joint (Neck2, hand-end markers) or rig lacks this HumanBodyBone
            bone.rotation = _frame.JointRotations[i] * _referenceWorldRotations[i];
        }
    }
}
