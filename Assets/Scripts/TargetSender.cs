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
/// Stage 4 (this version): the controller ray picks a destination, Unity computes a NavMesh
/// path to it, and we feed motionbricks the path's corners one at a time. motionbricks walks
/// straight at whatever target it is given, so following corners is what makes the motion
/// route AROUND real furniture instead of through it — the avoidance comes from the NavMesh
/// MRUK built off the room scan, because motionbricks itself has no obstacle concept at all.
///
/// Set <see cref="useNavMeshPath"/> false to revert to stage-3 behaviour (send the raw hit,
/// walk straight at it) with no rebuild.
/// </summary>
public class TargetSender : MonoBehaviour
{
    [Tooltip("IP of the PC running pose_sender_motionbricks.py. 172.16.1.25 was this PC's " +
             "Wi-Fi address on 2026-11-14; it is DHCP, so re-check it if targets stop landing.")]
    [SerializeField] string host = "172.16.1.25";
    [SerializeField] int port = 5006;

    [Tooltip("Supplies the rig's scene origin and current world position. Auto-found on this " +
             "GameObject if left empty.")]
    [SerializeField] PoseReceiver poseReceiver;

    [Tooltip("Supplies the controller poses. Auto-found in the scene if left empty.")]
    [SerializeField] OVRCameraRig cameraRig;

    [Tooltip("How far the pointing ray reaches, in metres.")]
    [SerializeField] float maxRayDistance = 10f;

    [Tooltip("How far the ray hit may be from the NavMesh and still snap to it. If a press " +
             "ever sends her somewhere surprising, LOWER this rather than raising it.")]
    [SerializeField] float navMeshSnapDistance = 1.5f;

    [Tooltip("OFF reverts to stage-3 behaviour: send the ray hit directly and walk straight " +
             "at it, ignoring furniture. Kept as a no-rebuild escape hatch.")]
    [SerializeField] bool useNavMeshPath = true;

    [Tooltip("How close she must get (horizontally) before we send the next path corner. " +
             "Too small and she never advances, because the generated gait overshoots.")]
    [SerializeField] float cornerReachedRadius = 0.5f;

    [Tooltip("Used only if no controller anchor can be found, so the channel stays testable.")]
    [SerializeField] Vector3 fallbackTarget = new Vector3(1.5f, 0f, 2.3f);

    UdpClient _udp;
    IPEndPoint _endPoint;

    // Created in Awake, not as a field initializer: Unity throws
    // "InitializeNavMeshPath is not allowed to be called from a MonoBehaviour constructor".
    NavMeshPath _path;
    Vector3[] _corners;
    int _cornerIndex;

    void Awake()
    {
        if (poseReceiver == null) poseReceiver = GetComponent<PoseReceiver>();
        if (cameraRig == null) cameraRig = FindAnyObjectByType<OVRCameraRig>();
        _path = new NavMeshPath();
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

        AdvanceAlongPath();
    }

    /// <summary>
    /// Casts the pointing ray, snaps the hit to the NavMesh, and either sends it directly or
    /// starts walking a NavMesh path to it. Does nothing when the ray misses the room or
    /// lands nowhere near walkable floor — pointing at the ceiling should not move her.
    /// </summary>
    void PointAndSend(bool right)
    {
        var anchor = ControllerAnchor(right);
        if (anchor == null)
        {
            Debug.LogWarning($"TargetSender: no {(right ? "right" : "left")} controller anchor; " +
                             "sending fallbackTarget instead.");
            SendDestination(fallbackTarget);
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

        // Snap to the NavMesh so we never ask her to walk somewhere unreachable.
        if (!NavMesh.SamplePosition(hit.point, out var navHit, navMeshSnapDistance, NavMesh.AllAreas))
        {
            Debug.Log($"TargetSender: hit {hit.point} has no NavMesh within {navMeshSnapDistance} m, " +
                      "ignoring (pointed at a wall or the ceiling?).");
            return;
        }

        Debug.Log($"TargetSender: ray hit {hit.point} -> navmesh {navHit.position}");
        SendDestination(navHit.position);
    }

    /// <summary>
    /// Either walks a NavMesh path to the destination (stage 4) or heads straight at it
    /// (stage 3, when <see cref="useNavMeshPath"/> is off).
    /// </summary>
    void SendDestination(Vector3 destination)
    {
        _corners = null;
        _cornerIndex = 0;

        if (!useNavMeshPath)
        {
            Send(destination);
            return;
        }

        // CalculatePath needs BOTH ends on the NavMesh. The rig's root is driven by streamed
        // poses and drifts off the mesh, so snap the start too or the call just fails.
        var from = poseReceiver != null ? poseReceiver.transform.position : transform.position;
        if (!NavMesh.SamplePosition(from, out var fromHit, navMeshSnapDistance, NavMesh.AllAreas))
        {
            Debug.LogWarning($"TargetSender: she is {navMeshSnapDistance} m or more off the NavMesh " +
                             $"at {from}; walking straight at the destination instead.");
            Send(destination);
            return;
        }

        if (!NavMesh.CalculatePath(fromHit.position, destination, NavMesh.AllAreas, _path)
            || _path.status == NavMeshPathStatus.PathInvalid || _path.corners.Length == 0)
        {
            Debug.LogWarning($"TargetSender: no NavMesh path {fromHit.position} -> {destination} " +
                             $"(status {_path.status}); walking straight at it instead.");
            Send(destination);
            return;
        }

        // A partial path means the destination is unreachable but we can still get closer.
        // Following it is better than refusing to move.
        if (_path.status == NavMeshPathStatus.PathPartial)
            Debug.Log("TargetSender: partial path — destination not fully reachable, going as far as possible.");

        _corners = _path.corners;
        // corners[0] is where she already stands, so the first thing worth walking to is [1].
        _cornerIndex = _corners.Length > 1 ? 1 : 0;
        Debug.Log($"TargetSender: path has {_corners.Length} corners to {destination} " +
                  $"(status {_path.status})");
        Send(_corners[_cornerIndex]);
    }

    /// <summary>
    /// Sends the next corner once she reaches the current one. This is the whole of stage 4:
    /// motionbricks only ever knows about one target at a time, so the path lives here and
    /// the Python side stays stateless.
    /// </summary>
    void AdvanceAlongPath()
    {
        if (_corners == null || _cornerIndex >= _corners.Length) return;

        var here = poseReceiver != null ? poseReceiver.transform.position : transform.position;
        // Horizontal distance only: the streamed root's height is not meaningful for "has she
        // arrived", and comparing in 3D would stall the path if she sits above or below the mesh.
        var flat = new Vector2(here.x - _corners[_cornerIndex].x, here.z - _corners[_cornerIndex].z);
        if (flat.magnitude > cornerReachedRadius) return;

        _cornerIndex++;
        if (_cornerIndex < _corners.Length)
        {
            Debug.Log($"TargetSender: corner {_cornerIndex}/{_corners.Length - 1}");
            Send(_corners[_cornerIndex]);
        }
        else
        {
            Debug.Log("TargetSender: path complete.");
            _corners = null;
        }
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
    /// ponytail: one datagram per corner, no keepalive resend. The target is absolute and
    /// the sender holds it until replaced, so a single delivery is enough. A dropped corner
    /// would stall the path, though — if that shows up on the LAN, resend the current corner
    /// at 2-5 Hz from AdvanceAlongPath rather than adding sequence numbers.
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
        _corners = null;
        var payload = PoseFrameCodec.EncodeTarget(Vector3.zero, hasTarget: false);
        _udp.Send(payload, payload.Length, _endPoint);
        Debug.Log($"TargetSender: idle -> {host}:{port}");
    }
}
