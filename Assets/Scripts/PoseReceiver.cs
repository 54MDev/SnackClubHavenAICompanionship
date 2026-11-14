using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

/// <summary>
/// UDP listener that drives a Humanoid Animator's bones from motionbricks' SOMA pose stream.
/// Wire format: see <see cref="PoseFrameCodec"/>. Bootstrap/debug with tools/pose_sender_test.py
/// before wiring motionbricks' real sender (CLAUDE.md "Live streaming" step 4).
/// </summary>
[RequireComponent(typeof(Animator))]
public class PoseReceiver : MonoBehaviour
{
    [SerializeField] int port = 5005;
    [SerializeField] bool flipHandedness = true; // ponytail: verify against first live motionbricks frame, flip if mirrored
    [SerializeField] float positionScale = 1f; // sender sends meters; set 0.01 if a sender sends centimeters

    Animator _animator;
    Transform[] _boneTransforms; // indexed by SOMA joint index; null where unmapped or this rig lacks the bone
    Quaternion[] _restLocalRotations; // each bone's rest-pose local rotation, captured once at Awake
    UdpClient _udp;
    Thread _receiveThread;
    volatile bool _running;

    readonly object _lock = new object();
    byte[] _latestPayload;
    bool _hasFrame;

    void Awake()
    {
        _animator = GetComponent<Animator>();
        _boneTransforms = new Transform[PoseFrameCodec.JointCount];
        _restLocalRotations = new Quaternion[PoseFrameCodec.JointCount];
        for (int i = 0; i < PoseFrameCodec.JointCount; i++)
        {
            var humanBone = PoseFrameCodec.SomaToHumanBone[i];
            var bone = humanBone.HasValue ? _animator.GetBoneTransform(humanBone.Value) : null;
            _boneTransforms[i] = bone;
            if (bone != null) _restLocalRotations[i] = bone.localRotation;
        }
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

    void Update()
    {
        byte[] payload;
        lock (_lock)
        {
            if (!_hasFrame) return;
            payload = _latestPayload;
            _hasFrame = false;
        }

        var frame = PoseFrameCodec.Decode(payload);

        var rootPos = frame.RootPosition * positionScale;
        if (flipHandedness) rootPos.z = -rootPos.z;
        transform.position = rootPos;

        for (int i = 0; i < PoseFrameCodec.JointCount; i++)
        {
            var bone = _boneTransforms[i];
            if (bone == null) continue; // unmapped SOMA joint (Neck2, hand-end markers) or rig lacks this HumanBodyBone

            var rot = frame.JointRotations[i];
            if (flipHandedness) rot = PoseFrameCodec.ConvertHandedness(rot);
            // Delta from rest, not an absolute world rotation: an incoming identity quaternion
            // means "hold rest pose" instead of "snap this bone to world-identity orientation",
            // which otherwise collapses every untouched limb toward the same world direction.
            bone.localRotation = _restLocalRotations[i] * rot;
        }
    }
}
