# Step 5 — MRUK room geometry → motionbricks motion (handoff)

**Status: stages 1-3 of 5 DONE (2026-11-14). Behaviour (1) of step 5 — point a controller
and she walks there — WORKS on-device, verified numerically and visually ("moves literally
perfectly"). Next up is stage 4 (NavMesh path corners), which delivers behaviour (2),
routing around real furniture.** Steps 1-4 of
`CLAUDE.md` are done and working on-device. See §8 for the staged plan and what stage 1
measured, including one known defect (she paces around an arrived-at target).
Written 2026-11-14 for a fresh agent. Read `CLAUDE.md` steps 1-4 first for the retargeting
history — this doc assumes that pipeline works and only covers the new direction of data.

---

## 1. What step 5 actually is

Two behaviours, both driven by the real room:

1. **Controller ray → target.** Point a controller at a spot in the room, pull the trigger,
   and the character walks there.
2. **Room geometry → avoidance.** A real obstacle (per the MRUK scan) makes the generated
   motion route *around* it instead of through it.

**Done when:** moving the controller ray to a new point visibly redirects the rig's live
motion toward it, and placing a real-world obstacle causes the generated motion to route
around it in the headset.

## 2. The premise in the old plan was WRONG — read this before designing anything

`CLAUDE.md` used to say: "Feed MRUK room geometry → motionbricks obstacles (format TBD from
`runtime_api.md`)". **There is no such format.** Verified 2026-11-14 by grepping the entire
motionbricks repo:

- **No obstacle, avoidance, collision-avoidance or pathfinding API exists.**
- The only `obstacle` matches are *motion clip filenames* — `assets/motions/README.md`
  lists `soma/avoidance/neutral_avoid_obstacle_bend_down_jog_*.bvh` and
  `soma/jump/jump_over_obstacle_*.bvh`. Those are animation data, not a routing system.
- `docs/runtime_api.md` exposes exactly **one** steering concept: generate toward **one to
  four target poses**, placed in world space by moving the pose root.

**So routing is our job, not motionbricks'.** Do not spend time looking for an obstacle API.

The good news: **Unity already does the routing, today, on-device.** MRUK builds a real
NavMesh from the room scan and the sample character `Breeze` navigates it. A NavMesh path
already routes around scanned geometry, so behaviour (2) above falls out of behaviour (1)
for free — we only ever send motionbricks a *direction to walk next*, and the NavMesh is
what makes that direction avoid furniture.

### Resulting architecture

```
                   EXISTS AND WORKS                         TO BUILD (this step)
   +-------------------------------------+      +------------------------------------+
   | motionbricks (PC, Python, CUDA)     |      | Unity (Quest APK)                  |
   |  generates SOMA poses @30 Hz        |      |  controller ray -> hit point       |
   |                                     |      |  NavMesh.CalculatePath -> corners  |
   |  pose_sender_motionbricks.py        |      |                                    |
   +---------------+---------------------+      +--------------+---------------------+
                   | UDP :5005  492 B/frame                    | UDP :5006 (NEW)
                   | root pos + 30 quats                       | next waypoint
                   v                                           v
   +-------------------------------------+      +------------------------------------+
   | PoseReceiver.cs (Unity)             |      | new socket in the sender           |
   |  drives DonQuixote's bones          |      |  replaces steering(time)           |
   +-------------------------------------+      +------------------------------------+
```

One new UDP channel, opposite direction. Keep it as small and ours as the existing one.

## 3. Prerequisite: how to run what already works

**Quest Link is a dead end on this machine — do not try to use it.** (USB 2.0 ceiling,
2-8 app fps; full measurements in `CLAUDE.md` step 4 and `docs/quest_link_test_plan.md`.)
Everything is done with an on-device APK.

```bash
ADB="C:/Program Files/Unity/Hub/Editor/6000.0.38f1/Editor/Data/PlaybackEngines/AndroidPlayer/SDK/platform-tools/adb.exe"

# build: Unity -> Android, scene list must be ONLY Assets/MRUKSamples/NavMesh/NavMesh.unity
#        output Builds/SnackClubHaven.apk   (~4 min once Android assets are imported)
"$ADB" install -r Builds/SnackClubHaven.apk
"$ADB" shell monkey -p com.samples.mruksample -c android.intent.category.LAUNCHER 1

# stream poses from the PC (headset Wi-Fi IP, NOT loopback)
cd ../motionbricks
uv run python ../SnackClubHavenAICompanionship/tools/pose_sender_motionbricks.py \
    --host 172.16.1.134 --duration 45

# watch on-device logs (Debug.Log lands here; it is a development build)
"$ADB" logcat -v brief Unity:D "*:S"
```

- Package id is **`com.samples.mruksample`** (from `ProjectSettings` `applicationIdentifier`).
  The `package="com.meta.mruksample"` in `Assets/Plugins/Android/AndroidManifest.xml` is
  **ignored** — using it gives "No activities found to run".
- Headset must be adb-authorized (tap **Allow** in the headset). `adb connect <ip>:5555`
  only works if wireless debugging was enabled from a USB session first.
- Known-good baseline: **30.0 Hz achieved, 2 late frames of 1350.** If you see worse,
  suspect your change, not the pipeline.
- **The Unity Editor is not needed to run the demo.** It is needed to rebuild.
- Iteration tax: every Unity-side change is a ~4 min APK rebuild. **Air Link was never
  tested** — if it works it restores the instant Editor loop and is worth 2 minutes of
  trying before you start.

## 4. Exact code touchpoints

### Python sender — `tools/pose_sender_motionbricks.py`

| Line | Thing | Note for step 5 |
| --- | --- | --- |
| 39 | `HOST, PORT = "127.0.0.1", 5005` | add a second port for the inbound channel |
| 41 | `DESIRED_SPEED = 1.9` | m/s, SOMA's jog clip speed |
| 42 | `LEAD_SECONDS = 1.0` | target is placed this far ahead |
| 44 | `TURN_THRESHOLD_DEG = 15.0` | re-generates when the direction changes this much |
| **59** | **`def steering(time)`** | **THIS IS THE STUB TO REPLACE.** Its own docstring says "stands in for real controller input (step 5)". Returns a unit `[x, y, 0]` ground direction in Z-up space. |
| 66 | `canonical_target(rig, poses)` | builds the jog target window; leave alone |
| 78 | `zup_to_yup_pos` | motionbricks Z-up → Unity Y-up, see §5 |
| 98 | `zup_to_yup_quat` | rotation counterpart |
| 128 | `pack_frame` | outbound wire format |
| ~221 | `for step in range(...)` | the main loop |
| 234 | `TURN_THRESHOLD_DEG` check | regenerate when heading changes |
| **236** | **`ground_position = position + direction * DESIRED_SPEED * LEAD_SECONDS`** | already does exactly what we need — just needs a real `direction` |
| 247 | `sock.sendto(..., (args.host, PORT))` | outbound send |
| ~252 | `slack = start + (step+1)*delta_time - perf_counter()` | **wall-clock pacing. Do not remove.** The loop had no pacing before and ran the GPU flat out, which is what made the rig jitter. |

The engine call the sender already uses:

```python
# motionbricks/runtime/target_pose.py:477
place_target_poses(ground_position: wp.vec3, facing_direction: wp.vec3,
                   blended_poses: wp.array, target_poses: wp.array,
                   stream: wp.Stream | None = None) -> None
```

**So the Python half of step 5 is small**: feed `direction` (and optionally
`ground_position`) from a received waypoint instead of from `steering(time)`.

### Unity side

| File | Role |
| --- | --- |
| `Assets/Scripts/PoseReceiver.cs` | receive-only today, port 5005, writes bones in `LateUpdate` |
| `Assets/Scripts/PoseFrameCodec.cs` | wire format: root pos + 30 quats, 492 B/frame, SOMA joint order |
| `Assets/MRUKSamples/NavMesh/NavMesh.unity` | the live scene; `DonQuixote` at `(1.5, 0, 0.3)`, `Breeze`, `MRUK`, `EnvironmentDepth`, `OVRCameraRig` |
| `SceneNavigation.cs:375` `BuildSceneNavMesh()` | MRUK builds the room NavMesh (already wired to `SceneLoadedEvent`) |
| `SceneNavigation.cs:351` `ToggleGlobalMeshNavigation(bool, int)` | global-mesh vs per-anchor navigation |
| `Assets/MRUKSamples/NavMesh/Scripts/NavMeshSampleController.cs:29` | **the input pattern to copy**: `OVRInput.GetDown(OVRInput.Button.SecondaryIndexTrigger)`, `PrimaryIndexTrigger`, `HandInputManager.Instance.ThumbTapDown` |

**There is no existing controller-ray-to-point code to copy.** `NavMeshSampleController`'s
trigger only toggles global mesh and calls `SetNewTargetObjectAndPostion()`, which picks a
*random* target. You are writing the ray cast yourself. Controller pose comes from
`OVRCameraRig`'s `RightHandAnchor` / `RightControllerAnchor` transforms.

## 5. Coordinate conversion — get this right or nothing will work

The sender owns all axis conversion (Unity never converts). Forward, verified in
`pose_sender_motionbricks.py:78`:

```python
def zup_to_yup_pos(p):           # motionbricks Z-up RH  ->  Unity Y-up LH
    return np.array([-p[0], p[2], -p[1]])
```

It is a Y/Z swap (determinant -1, which is what keeps chirality correct when reinterpreted
in a left-handed basis) composed with a 180-degree yaw (SOMA faces -Y with left arm on +X;
Unity rigs face +Z with left arm on -X).

**The inverse you need for the new inbound channel** (derive it, don't guess):

```python
def yup_to_zup_pos(u):           # Unity Y-up LH  ->  motionbricks Z-up RH
    return np.array([-u[0], -u[2], u[1]])
```

Check: `zup_to_yup_pos([1,2,3]) == [-1,3,-2]`, and `yup_to_zup_pos([-1,3,-2]) == [1,2,3]`.

### Ground-target shortcut (do this, it is much simpler)

motionbricks' ground plane is XY with **Z up**. `canonical_target` builds its origin as
`wp.vec3(x, y, 0.0)`, and the main loop zeroes the third component
(`root_positions(...)[0] * [1.0, 1.0, 0.0]`). So a *ground* target only needs two numbers.

`PoseReceiver.cs` places the rig at `_startPosition + RootPosition*scale - _hipsOffsetFromRoot`,
so the stream's origin is Don's **scene placement**, not the room origin. Therefore, for a
Unity world point `P`:

```
d = P - _startPosition                       // Unity-space offset from the rig's scene origin
ground_position_motionbricks = (-d.x, -d.z, 0)
```

Unity's **height (`d.y`) drops out entirely**, which is correct for a ground target. Send
`d` (or just `-d.x, -d.z`) and the Python side needs no quaternion maths at all.

## 6. Suggested wire format for the inbound channel

Mirror the existing codec's style: fixed-size, little-endian, one datagram per update, no
versioning ceremony. Smallest thing that works:

```
port 5006, little-endian, 13 bytes:
  float32  target_x      // motionbricks Z-up ground X  (= -d.x)
  float32  target_y      // motionbricks Z-up ground Y  (= -d.z)
  uint8    has_target    // 0 = idle/stop, 1 = walk to target
  float32  seq           // optional: monotonic counter, lets the sender drop stale packets
```

Rationale: the sender needs a *direction*, and it can compute that itself from
`target - current_root`, so Unity does not need to send a direction at all. Sending the
**absolute target** rather than a direction is strictly better — it is idempotent, so a
dropped datagram just means the character keeps heading to the last known target instead of
veering off.

**Send policy:** Unity sends on trigger-press (new target) and then at a low rate (2-5 Hz)
as a keepalive/correction. Do not send at 30 Hz; there is no need.

**Waypoints vs single target — recommendation:** send only the **next NavMesh corner**, not
the whole path. Unity recomputes `NavMesh.CalculatePath` each time the character advances,
pops the corner it has reached, and sends the new one. This keeps the Python side free of
path state entirely, which matters because the Python loop is GPU-paced and should stay dumb.

## 7. Traps — each of these cost real time already

1. **`followRootPosition`** — **RESOLVED in stage 2, now `1`.** Original note: `NavMesh.unity` has
   `followRootPosition: 0` so Don jogs *in place* (that was deliberate, to keep her visible
   from a fixed viewpoint during the Link tests). Step 5 requires her to actually travel.
   **Consequence now that it is `1`: always run the sender with `--target X,Y` for headset
   tests** (e.g. `--target 0,0` parks her near her start). With no target she falls back to
   the scripted jog and trap #2 below re-arms — she will leave the room in about 2 seconds.
2. **The 80-metre runaway.** With `followRootPosition: 1` and the stock `steering()`, the
   generated jog travels ~1.9 m/s in a straight line and reached **80 m** in 45 s — out of
   any room in ~2 s. Step 5's targets are what keep her in the room. If she vanishes, that
   is why. Do not "fix" it by rescaling.
3. **`time` is shadowed in the sender's main loop.** The loop uses a local variable named
   `time` (`time = step * delta_time`), so `import time` is broken in that scope. The file
   uses `from time import perf_counter, sleep` for exactly this reason. Keep that pattern.
4. **Do not block the sender's loop on a socket read.** It is wall-clock paced at 30 Hz and
   GPU-bound; a blocking `recv` would wreck the pacing and bring the jitter back. Use a
   non-blocking socket (`sock.setblocking(False)`) or `select` with a zero timeout, and
   drain to the newest datagram each iteration.
5. **MRUK scene data over Link is a lie.** Over Link you get 0 anchors and a JSON-fallback
   room, so NavMesh paths will not match the real room. Test on-device only.
6. **Scene capture cannot be prompted over Link** (`MRUK.Shared.cs:264`). MRUK already calls
   `OVRScene.RequestSpaceSetup()` itself (`MRUK.cs:784` → `MRUK.Shared.cs:271`), so do not
   add another prompt. On-device it just works; the room must be scanned via Space Setup.
7. **The Y/Z conversion already composes a 180-degree yaw.** If your targets come out
   mirrored or behind the character, re-derive from §5 rather than adding sign flips until
   it looks right. `python tools/pose_sender_motionbricks.py --self-test` asserts the
   conversion is a homomorphism and runs offline with no GPU.
8. **Unity crashes if USB is unplugged while it holds a Link XR session**
   (`mfh264enc.dll` in the faulting module list; crash at 21:20:12 on 2026-11-14). Close
   Play mode before touching the cable.

## 8. Build order (each step independently verifiable)

1. ~~**Reverse channel, hardcoded target.**~~ **DONE 2026-11-14.** The Python half is
   proven with no Unity, no APK and no headset.
   - `tools/pose_sender_motionbricks.py`: `TARGET_PORT = 5006`, non-blocking inbound socket,
     `yup_to_zup_pos()`, `decode_target()`, `drain_target()`, and a `--target X,Y` CLI.
     `steering(time)` is **kept as the no-target fallback**, so the original scripted-jog
     demo still runs byte-identically when nothing is streaming targets.
   - `tools/target_sender_test.py`: injects targets, standing in for Unity.
     `--self-test` on both files passes offline.
   - **Measured, `--target 2,0` then live-injected `0,3`:** walked 0.19 -> 2.06 and arrived
     (distance 0.06 m); on the injected datagram, heading flipped to `[-0.5, 0.87]` within
     one second and she reached `(0.02, 3.01)` — distance **0.02 m** — in ~3 s. Pacing held
     **30.0 Hz, 1 late frame of 480.** Live re-steering through the socket works.
   - **KNOWN DEFECT — she does not settle.** After arriving she paces around the target:
     distances went `0.06 -> 0.20 -> 0.50 -> 0.12 -> 0.51 -> 0.04 -> 0.49`, i.e. roughly
     +/-0.5 m oscillation, at both targets. Cause: the target pose window is a **jog**
     (`canonical_target` calls `adjust_target_pose_speed(poses, DESIRED_SPEED)` with
     1.9 m/s), so even with the lead clamped to zero distance the generated motion still
     carries jog momentum and overshoots, then comes back. Clamping `lead` is enough to
     stop *overshooting the approach*, but not enough to stand still. This is open
     decision #3 below. Reads as "milling about near the target" in practice — cosmetic,
     not blocking stages 2-4.
2. ~~**Unity sends a fixed target.**~~ **DONE 2026-11-14.** Headset trigger -> UDP across
   the LAN -> live re-steering, proven on-device.
   - `Assets/Scripts/TargetSender.cs`: sends on `OVRInput.GetDown` of either index trigger
     (same input as `NavMeshSampleController.cs:31`), plus `SendIdle()` for `has_target=0`.
   - `PoseFrameCodec.EncodeTarget()`: the Unity->motionbricks conversion lives with the rest
     of the wire format, not in the sender script. `TargetPayloadSize = 9`.
   - `PoseReceiver.StartPosition`: new public getter. Needed because the streamed root is an
     offset from the rig's **scene placement**, not the room origin.
   - **`followRootPosition` set back to `1`** on the scene instance (trap #1 below is now
     resolved — but see the warning in that entry, it re-arms the runaway).
   - **Measured end to end:** `testTarget (1.5, 0, 2.3)` minus `StartPosition (1.5, 0, 0.3)`
     = offset `(0, 0, 2.0)`, encoded `(-d.x, -d.z)` = `(-0.0, -2.0)`, and the sender received
     exactly **`[-0. -2.]`**. She then walked toward it (root `(0.26, -1.59)`, distance
     `0.48` and closing). **30.0 Hz for a full 60 s, 2 late frames of 1800**, streaming to
     the headset over Wi-Fi. The §5 conversion is confirmed correct against live data, not
     just against the self-tests.
   - Both self-tests assert the **same** pair from opposite directions:
     `(0.5, 9.9, -2.0) -> (-0.5, 2.0)`. Python's `--self-test` and the Unity menu item
     `Tools/Pose Streaming/Run PoseFrameCodec Self-Test` both pass.
   - APK built to **`Builds/SnackClubHaven-step5.apk`**, keeping the step-4 known-good
     `Builds/SnackClubHaven.apk` installable as a fallback.
   - Noise to ignore: `Oculus.Interaction.GrabInteractor` NREs at startup are pre-existing
     (interaction rig), not from this code. Also note the app spews XR logs fast enough to
     roll the logcat buffer, so `Debug.Log` lines can vanish — trust the sender's stdout.
3. ~~**Controller ray → hit point.**~~ **DONE 2026-11-14. Behaviour (1) works.**
   User in headset: *"moves literally perfectly."* Point a controller at the floor, pull
   that controller's index trigger, she walks there.
   - **`OVRInput.RawButton.RIndexTrigger` / `LIndexTrigger`, NOT `Primary`/`Secondary`.**
     Primary/Secondary's mapping to left/right varies by controller type, and we must know
     *which* controller is pointing to cast from the right anchor. Raw is unambiguous.
   - **`room.Raycast()` (MRUK's own), NOT `Physics.Raycast`.** MRUK tests scene anchors
     directly and needs no colliders — and this scene has `useAnchorColliders` **off**, so a
     physics raycast would have hit nothing and looked like "the trigger is broken".
     Signature at `MRUKRoom.cs:729`.
   - **`NavMesh.SamplePosition` snap, misses ignored** (`navMeshSnapDistance = 1.5`), so
     pointing at a wall or the ceiling sends nothing instead of asking for an unreachable
     spot. Same NavMesh MRUK built from the scan.
   - Anchors come from `OVRCameraRig.rightControllerAnchor`/`leftControllerAnchor`, falling
     back to `rightHandAnchor`/`leftHandAnchor`.
   - **Verified numerically, 13 trigger presses in one 75 s run:** 13 datagrams sent, 13
     distinct targets received (1:1), and **12 of 13 confirmed to the centimetre** against
     the expected `(-offset.x, -offset.z)`. The 13th was only absent from the sender's
     once-per-second print because it was replaced within that second — the 13/13 count
     proves delivery. Worked example: ray hit `(1.95, -0.01, -0.29)` -> navmesh
     `(1.95, 0.04, -0.29)` -> offset `(0.45, 0.04, -0.59)` -> sent `(-0.45, 0.59)`.
   - **Snap distance measured: min 0.040 m, mean 0.236 m, max 1.262 m** over 13 presses.
     Mostly tiny, i.e. the NavMesh really is where you point. The 1.26 m outlier was close
     to the 1.5 m limit, so if a press ever sends her somewhere surprising, *lower*
     `navMeshSnapDistance` rather than raising it.
   - **30.0 Hz for the full 75 s, 1 late frame of 2250**, streaming to the headset while
     13 inbound targets were processed. The inbound channel costs the pose rate nothing.
4. **NavMesh path corners.** Replace "send hit point" with `NavMesh.CalculatePath` and send
   the next corner, advancing as the character reaches each. Behaviour (2) now works, because
   the path already routes around scanned furniture.
5. Optionally draw the path with a LineRenderer for debugging — `AnimateLineRenderer.cs`
   already exists in the NavMesh sample.

**Leave one runnable check behind** (project convention): extend
`pose_sender_motionbricks.py --self-test` with an assert that `yup_to_zup_pos` is the exact
inverse of `zup_to_yup_pos` on a non-trivial vector, and that a decoded target datagram
round-trips. It must stay runnable offline with no GPU and no headset.

## 9. Decisions deliberately left open

- **Who owns "has the character arrived?"** Recommendation above puts it in Unity (it has
  the NavMesh and the character's world transform). The alternative — Python tracking
  distance to target — duplicates state.
- **Facing direction at the target.** `place_target_poses` takes `facing_direction`
  separately from `ground_position`. Currently it is the travel direction. Whether the
  character should turn to face the user on arrival is a design call, not a technical one.
- **Idle behaviour / arrival (NOW MEASURED, see stage 1).** motionbricks must keep
  generating *something* — it is a continuous loop, and `player.time_to_transition` forces a
  new generation regardless, so you cannot simply stop calling `place_target_poses`. The jog
  target pose carries 1.9 m/s of momentum, which is what makes her pace +/-0.5 m around an
  arrived-at target. Likely fixes, cheapest first: (a) build a **second, slow target window**
  once at startup (another `canonical_target`-style call with a low
  `adjust_target_pose_speed`) and switch to it inside the arrival radius — do NOT re-run
  `adjust_target_pose_speed` on `jog_poses` per frame, it would compound; (b) find an
  idle/stand clip in motionbricks' `assets/motions` and blend to it; (c) accept the pacing as
  idle behaviour. Note `ARRIVAL_SLOW_RADIUS = 0.25` already exists as the switch point.
- **Obstacle height.** The NavMesh is 2D-ish; the `jump_over_obstacle` / `avoid_obstacle`
  clips in motionbricks' asset list hint at richer behaviour, but nothing wires them up.
  Out of scope unless asked.
