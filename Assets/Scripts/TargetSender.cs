using System.Net;
using System.Net.Sockets;
using Meta.XR.MRUtilityKit;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Sends "walk to this spot" targets to the motionbricks sender on the PC.
/// The opposite direction to <see cref="PoseReceiver"/>: that receives poses on 5005, this
/// sends targets on 5006. Wire format lives in <see cref="PoseFrameCodec.EncodeTarget"/>.
/// Full plan and rationale: docs/step5_room_geometry_to_motion.md.
///
/// Stage 3 (this version): point a controller at the room, pull its index trigger, and the
/// ray is cast against the MRUK scene, snapped to the room's NavMesh, and sent as the target.
/// Stage 4 will send successive NavMesh path corners instead of the raw hit, which is what
/// makes the motion route around furniture rather than straight through it.
/// </summary>
public class TargetSender : MonoBehaviour
{
    [Tooltip("IP of the PC running pose_sender_motionbricks.py. 172.16.1.25 was this PC's " +
             "Wi-Fi address on 2026-11-14; it is DHCP, so re-check it if targets stop landing.")]
    [SerializeField] string host = "172.16.1.25";
    [SerializeField] int port = 5006;

    [Tooltip("Supplies the rig's scene origin. Auto-found on this GameObject if left empty.")]
    [SerializeField] PoseReceiver poseReceiver;

    [Tooltip("Supplies the controller poses. Auto-found in the scene if left empty.")]
    [SerializeField] OVRCameraRig cameraRig;

    [Tooltip("How far the pointing ray reaches, in metres.")]
    [SerializeField] float maxRayDistance = 10f;

    [Tooltip("How far the ray hit may be from the NavMesh and still snap to it. Too small " +
             "and pointing at a wall or a sofa seat finds nothing; too large and it snaps " +
             "somewhere surprising.")]
    [SerializeField] float navMeshSnapDistance = 1.5f;

    [Tooltip("Used only if no controller anchor can be found, so the channel stays testable.")]
    [SerializeField] Vector3 fallbackTarget = new Vector3(1.5f, 0f, 2.3f);

    UdpClient _udp;
    IPEndPoint _endPoint;

    void Awake()
    {
        if (poseReceiver == null) poseReceiver = GetComponent<PoseReceiver>();
        if (cameraRig == null) cameraRig = FindAnyObjectByType<OVRCameraRig>();
        _udp = new UdpClient();
        _endPoint = new IPEndPoint(IPAddress.Parse(host), port);
    }

    void OnDestroy()
    {
        _udp?.Close();
    }

    void Update()
    {
        // RawButton, not Primary/Secondary IndexTrigger: Primary/Secondary's mapping to
        // left/right differs by controller type, and we need to know WHICH controller is
        // pointing so we cast from the right anchor. RIndexTrigger/LIndexTrigger are
        // unambiguous.
        if (OVRInput.GetDown(OVRInput.RawButton.RIndexTrigger)) PointAndSend(right: true);
        else if (OVRInput.GetDown(OVRInput.RawButton.LIndexTrigger)) PointAndSend(right: false);
    }

    /// <summary>
    /// Casts the pointing ray, snaps the hit to the NavMesh, and sends it as the target.
    /// Does nothing when the ray misses the room or lands nowhere near walkable floor —
    /// pointing at the ceiling should not move the character.
    /// </summary>
    void PointAndSend(bool right)
    {
        var anchor = ControllerAnchor(right);
        if (anchor == null)
        {
            Debug.LogWarning($"TargetSender: no {(right ? "right" : "left")} controller anchor; " +
                             "sending fallbackTarget instead.");
            Send(fallbackTarget);
            return;
        }

        var ray = new Ray(anchor.position, anchor.forward);

        // MRUK's own raycast, not Physics.Raycast: it tests the scene anchors directly, so it
        // needs no colliders on the room geometry (this scene's EffectMesh has
        // useAnchorColliders off). MRUKRoom.Raycast is at MRUKRoom.cs:729.
        var room = MRUK.Instance != null ? MRUK.Instance.GetCurrentRoom() : null;
        if (room == null)
        {
            Debug.LogWarning("TargetSender: no MRUK room yet — is the room scanned, and is this " +
                             "running on-device? Scene data does not load over Quest Link.");
            return;
        }
        if (!room.Raycast(ray, maxRayDistance, out var hit))
        {
            Debug.Log("TargetSender: ray missed the room, ignoring.");
            return;
        }

        // Snap to the NavMesh so we never ask her to walk somewhere unreachable. The NavMesh
        // is the same one MRUK built from the scan (SceneNavigation.BuildSceneNavMesh), which
        // is also what will give us obstacle avoidance for free in stage 4.
        if (!NavMesh.SamplePosition(hit.point, out var navHit, navMeshSnapDistance, NavMesh.AllAreas))
        {
            Debug.Log($"TargetSender: hit {hit.point} has no NavMesh within {navMeshSnapDistance} m, " +
                      "ignoring (pointed at a wall or the ceiling?).");
            return;
        }

        Debug.Log($"TargetSender: ray hit {hit.point} -> navmesh {navHit.position}");
        Send(navHit.position);
    }

    Transform ControllerAnchor(bool right)
    {
        if (cameraRig == null) return null;
        // Controller anchor for controllers; hand anchor is the fallback when tracking hands.
        var anchor = right ? cameraRig.rightControllerAnchor : cameraRig.leftControllerAnchor;
        return anchor != null ? anchor : (right ? cameraRig.rightHandAnchor : cameraRig.leftHandAnchor);
    }

    /// <summary>
    /// Sends one target datagram for a Unity world-space point.
    /// ponytail: one datagram per press, no keepalive resend. The target is absolute and
    /// the sender holds it until replaced, so a single delivery is enough and a dropped
    /// one just means nothing happens — press again. Add a 2-5 Hz resend only if drops
    /// actually show up on the LAN.
    /// </summary>
    public void Send(Vector3 worldPoint)
    {
        var offset = worldPoint - poseReceiver.StartPosition;
        var payload = PoseFrameCodec.EncodeTarget(offset);
        _udp.Send(payload, payload.Length, _endPoint);
        Debug.Log($"TargetSender: {worldPoint} (offset {offset}) -> {host}:{port}");
    }

    /// <summary>Tells the character to stop heading anywhere (has_target = 0).</summary>
    public void SendIdle()
    {
        var payload = PoseFrameCodec.EncodeTarget(Vector3.zero, hasTarget: false);
        _udp.Send(payload, payload.Length, _endPoint);
        Debug.Log($"TargetSender: idle -> {host}:{port}");
    }
}
