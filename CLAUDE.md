# Snack Club Haven — AI Companionship

## Next steps (reviewed 2026-11-14)

Plan review findings first, then ordered steps.

**Findings**
- The retargeting plan below runs through Blender, but the live rig renders in **Unity on
  Quest**. Blender is fine for one-off clip validation; for the live path it's a detour.
  Unity's Humanoid avatar retargeting does the SOMA→rig bone mapping natively (and fixes
  the thigh/calf offset trap) — drive the Unity rig directly instead.
- **Open question resolved:** motionbricks is a standalone Python app (`motionbricks/app/runtime`,
  own imgui window). It is *not* inside Blender or Unity. A local socket (UDP, 30 Hz,
  joint-name→quaternion + root pos) is required either way. Details in "Live streaming".
- `Rigs/` now holds 9 rigs, not 3 (FreddyFazbear, Master Chief, Seek, carmen, ishmael,
  joker added). Pick **one** to bring up end-to-end before touching the rest.

**Steps, in order**
1. **Done 2026-11-14** (via MCP for Unity). Imported
   `Assets/Rigs/DonQuixote/DonQuixote.fbx`, Rig → Humanoid, avatar auto-mapped
   (`avatarSetup: CreateFromThisModel`) with all 19 required `HumanBodyBones` resolved,
   no red entries — 54 bones mapped total (fingers included), 103 skeleton bones overall.
   Source rig uses **Blender/Rigify-style names**, not Mixamo — `spine`, `spine.001`..
   `spine.004`, `shoulder.L/R`, `upper_arm.L/R`, `forearm.L/R`, `hand.L/R`,
   `f_index/middle/ring/pinky.0{1,2,3}.L/R`, `thumb.0{1,2,3}.L/R`. Doesn't matter for the
   live path — PoseReceiver.cs (step 3) will target `HumanBodyBones` via the Animator's
   avatar, not raw bone names.
2. **Done 2026-11-14.** SOMA joint order comes straight from the model manifest
   (`motionbricks/motionbricks/assets/onnx/soma/soma_n1.json` → `joint_names`, 30 joints,
   index 0 = root), confirmed against `docs/soma_model.md`'s `local_poses` layout — no
   need to run inference just to see the order. `pred_global_motions` ([N,64,366]) is
   root(5) + joint positions(87=29×3) + 6D rotations(180=30×6) + joint velocities(90) +
   foot contacts(4) per frame, in that order.

   SOMA→Humanoid `HumanBodyBones` table (cross-checked against DonQuixote's actual 54
   mapped bones from step 1 — `✓` = Unity resolved it on this rig, `✗` = not present on
   this rig's avatar, so PoseReceiver.cs must skip it for DonQuixote without erroring):

   | SOMA joint | `HumanBodyBones` | On DonQuixote? |
   | --- | --- | --- |
   | `Hips` | `Hips` | ✓ |
   | `Spine1` | `Spine` | ✓ |
   | `Spine2` | `Chest` | ✓ |
   | `Chest` | `UpperChest` | ✓ |
   | `Neck1` | `Neck` | ✓ |
   | `Neck2` | *(no slot — Humanoid has one Neck bone)* | — compose into `Neck`, see below |
   | `Head` | `Head` | ✓ |
   | `Jaw` | `Jaw` | ✗ (DonQuixote has no Jaw bone — skip) |
   | `LeftEye` | `LeftEye` | ✓ |
   | `RightEye` | `RightEye` | ✓ |
   | `LeftShoulder` | `LeftShoulder` | ✓ |
   | `LeftArm` | `LeftUpperArm` | ✓ |
   | `LeftForeArm` | `LeftLowerArm` | ✓ |
   | `LeftHand` | `LeftHand` | ✓ |
   | `LeftHandThumbEnd` | *(end-effector marker, not a rotating joint)* | — position-only, skip |
   | `LeftHandMiddleEnd` | *(end-effector marker, not a rotating joint)* | — position-only, skip |
   | `RightShoulder` | `RightShoulder` | ✓ |
   | `RightArm` | `RightUpperArm` | ✓ |
   | `RightForeArm` | `RightLowerArm` | ✓ |
   | `RightHand` | `RightHand` | ✓ |
   | `RightHandThumbEnd` | *(marker)* | — skip |
   | `RightHandMiddleEnd` | *(marker)* | — skip |
   | `LeftLeg` | `LeftUpperLeg` | ✓ **(the thigh/calf offset trap — see below)** |
   | `LeftShin` | `LeftLowerLeg` | ✓ |
   | `LeftFoot` | `LeftFoot` | ✓ |
   | `LeftToeBase` | `LeftToes` | ✓ |
   | `RightLeg` | `RightUpperLeg` | ✓ |
   | `RightShin` | `RightLowerLeg` | ✓ |
   | `RightFoot` | `RightFoot` | ✓ |
   | `RightToeBase` | `RightToes` | ✓ |

   Confirms the offset trap from "Why these rigs need retargeting" above is real on the
   live data too (`LeftLeg`=thigh, `LeftShin`=calf) — irrelevant in Unity since the
   mapping here is by `HumanBodyBones` enum value, not name string, so there's no name
   collision to get wrong. `Neck2` has nowhere to go on a 1-neck-bone Humanoid rig:
   PoseReceiver.cs should either drop it or multiply it into the `Neck1`→`Neck` rotation
   — decide in step 3, not here. SOMA ships no finger joints at all (only two end
   markers per hand), so DonQuixote's finger bones (visible in step 1's 54-bone mapping)
   simply won't be driven by motionbricks — expected, not a bug.
   **Done when:** every SOMA joint name has a row above, and every row's
   `HumanBodyBones` value is checked against what Unity actually resolved in step 1
   (not just the enum's existence) — done above.
3. **Done 2026-11-14.** `Assets/Scripts/PoseFrameCodec.cs` (wire format: root position +
   30 quaternions in SOMA order, 492 bytes/frame; the step-2 SOMA→`HumanBodyBones` table;
   a `ConvertHandedness` helper) and `Assets/Scripts/PoseReceiver.cs` (background-thread
   `UdpClient` on port 5005, applies decoded rotations to `Animator.GetBoneTransform`
   bones each `Update()`, skips null-mapped joints).
   - **Self-test (non-trivial parsing logic):** `Tools/Pose Streaming/Run PoseFrameCodec
     Self-Test` Unity menu item — encode/decode round-trip + table-length asserts. Ran
     it: **passed**.
   - **BVH-clip test, done as a synthetic smoke test instead:** `tools/pose_sender_test.py`
     sends a synthetic oscillating pose (not a real SOMA BVH clip — ponytail: skip
     reimplementing motionbricks' BVH parser just for a wiring smoke test; swap in
     `motionbricks/motionbricks/io/bvh.py` output later if clip fidelity matters) over
     UDP at 30 Hz. Verified end-to-end in a new `Assets/Scenes/PoseReceiverTest.unity`
     scene with `DonQuixote.fbx` + `PoseReceiver`: rig root tracked the sent root
     position `(0,1,0)`, and `Hips` world rotation changed frame to frame
     (10.68° → 333.66°) matching the sender's sine sweep — confirms the UDP→decode→
     bone-lookup→rotation pipeline actually works, not just that it compiles.
   - **Not yet verified:** `flipHandedness` (default `true` on `PoseReceiver`) — SOMA's
     real handedness convention is still unconfirmed against actual motionbricks output;
     first thing to check once step 4 wires up the real sender.
   - **Bug found and fixed (same day):** initial version set `bone.rotation` (absolute
     world rotation) directly from the raw incoming quaternion. The synthetic sender
     sends identity for every untouched joint, and forcing a bone's *world* rotation to
     identity erases its actual rest-pose bend — every untouched limb collapsed toward
     the same world-identity orientation (hands/feet visibly clustered together while
     only the driven Hips looked right). Fixed by capturing each bone's rest **local**
     rotation once at `Awake()` and applying incoming data as a delta from rest
     (`bone.localRotation = restLocal * incoming`), so identity now means "hold rest
     pose." Re-verified: `LeftHand`/`LeftFoot` held fixed rest-pose rotation across two
     samples while `Hips` kept oscillating (61.45° → 60.01°). This delta-from-rest
     convention is still a simplification, not validated retargeting math — revisit if
     real SOMA data (true per-joint global orientation, not "mostly identity") doesn't
     look right once step 4 is wired up.
   - **New finding, not yet fixed:** `DonQuixote.fbx`'s `ModelImporter.globalScale` is
     `15.6`, not `1` — this rig isn't currently at real-world meter scale (bone world
     positions came back in the thousands during this test, not ~1-2 for a human-sized
     rig). `PoseReceiver.positionScale` assumes the sender already sends meters matching
     Unity's 1-unit-= 1-meter convention; with this rig's current import scale that
     assumption doesn't hold. Fix the FBX import scale (or compensate in
     `positionScale`) before trusting root-position placement in step 4.
4. **WORKING as of 2026-11-14 (desktop Editor); formal "done when" not fully met — needs
   the NavMesh scene over Quest Link.** Real motionbricks inference
   streams into `PoseReceiver` and the plumbing is confirmed working (see below). The
   previously-reported broken pose (character tipped on her side, limbs distorted) was
   traced to the wire format itself sending raw bind-pose-relative local rotations; all
   four rotation/coordinate issues from the earlier handoff are now addressed in one
   change. **Nobody has looked at Game view since.**

   **What changed:** the wire format now carries **world-space rotation deltas from the
   sender's own rest pose** instead of raw local rotations.
   - `tools/pose_sender_motionbricks.py`: FKs each pose with the skeleton's own
     `compute_world_transforms`, computes `delta = G_pose * G_rest^-1` per joint against
     the rest pose (`reference_local_transforms` FK'd with `root_tx=rig.model_to_runtime`
     so both are in the same Z-up runtime space), then applies the Z-up→Y-up conversion.
   - `Assets/Scripts/PoseReceiver.cs`: captures each bone's rest **world** rotation at
     `Awake()` and applies `bone.rotation = delta * restWorld`. SOMA joint order is
     parent-before-child, so writing world rotations in list order is safe.
   - `flipHandedness` / `PoseFrameCodec.ConvertHandedness` **deleted** (and the stale
     `flipHandedness: 1` dropped from `Assets/Scenes/PoseReceiverTest.unity`). Axis
     conversion now lives only in the Python sender, which owns the Z-up source data.

   **Why this is the right fix, not another guess:** raw local rotations are relative to
   SOMA's bind pose; DonQuixote's Humanoid avatar has a different one, so composing them
   onto Unity's rest pose (the old `restLocal * incoming`) distorted every limb — that was
   issue #3 in the old notes. The world-space delta cancels **both** bind poses out, and
   it also dissolves issue #4 (Hips's transform already *was* a world placement, so
   treating everything as world-space is now consistent) and issue #1 (one conversion, in
   one place). Identity delta still means "hold rest pose", so
   `tools/pose_sender_test.py`'s synthetic frames remain meaningful.

   The Z-up→Y-up quaternion `(-x, -z, -y, w)` from the old issue #2 was **verified
   correct**, not replaced: `python tools/pose_sender_motionbricks.py --self-test`
   (runnable offline, no GPU) asserts it is a homomorphism (`T(ab) == T(a)T(b)`, checked
   on a non-commuting pair — which is what makes it valid to apply per joint in a
   hierarchy), that it agrees with `zup_to_yup_pos` when rotating a vector, and that a
   pose equal to the rest pose packs to identity deltas. **Ran it: passed.**
   `Assets/Scripts/PoseFrameCodec.cs`'s editor self-test still passes unchanged.

   **What was already confirmed working (unchanged from the earlier handoff):**
   - `tools/pose_sender_motionbricks.py` runs motionbricks' actual
     `MotionBricksSOMAEngine` + `GeneratedMotionPlayer` live (adapted from
     `motionbricks/docs/examples/locomotion_loop.py`) on real hardware (RTX 4080 SUPER,
     cached TensorRT plan), 30 Hz, root tracking a real jog-with-a-turn.
   - The 30 SOMA joints are correctly located in the skeleton's full 77-joint array
     (`rig.skeleton.joint_names.index(name)` per `SOMA_JOINT_ORDER`, parent names
     verified).
   - UDP delivery and decode work; `PoseReceiver` never throws.
   - A `FollowCamera` (Camera, child of `DonQuixote`, tag `MainCamera`) exists in
     `Assets/Scenes/PoseReceiverTest.unity` — the scene originally had no camera, which
     is why the first live runs appeared to show nothing. No further scene setup needed.

   **Bone mapping verified on the live rig (2026-11-14):** dumped
   `animator.GetBoneTransform` for all 30 SOMA joints in Play mode. Every one resolves to
   the anatomically correct Rigify bone (`Hips`→`spine`, `Spine1`→`spine.001`,
   `Head`→`face`, `LeftLeg`→`thigh.L`, `LeftShin`→`shin.L`, `LeftToeBase`→`toe.L`, …) —
   the thigh/calf offset trap does not bite, as predicted. `Jaw` is the only missing bone
   and is skipped without erroring. Avatar `DonQuixoteAvatar`, `isHuman=true`, valid, no
   AnimatorController assigned. **Mapping is not a suspect for any remaining visual bug.**

   **Jitter fixed (2026-11-14, not yet re-tested visually):** the rig moved but jittered.
   Cause was frame cadence, not mapping: bones were written in `Update()` and only on
   frames a datagram actually landed on. The sender runs at 30 Hz against a much faster
   render loop, so most frames wrote nothing and the Animator's own Humanoid avatar
   evaluation (which happens *between* `Update` and `LateUpdate`) showed through — the rig
   alternated between the streamed pose and the avatar pose at the beat frequency. Fixed
   in `PoseReceiver.cs` by moving the bone writes to `LateUpdate()`, caching the last
   decoded frame and re-applying it every render frame, and setting
   `animator.applyRootMotion = false` in `Awake()` since this script owns the root
   transform.

   **Inverted limbs fixed (2026-11-14, not yet re-tested visually):** after the jitter fix
   the limbs moved but bent wrong — knees inward, elbows backwards. **It was not a mirror
   and not the bone mapping**; both were measured and cleared:
   - *Chirality is intact.* Signed triple product of (hips→LeftArm, hips→RightArm,
     hips→Head) is `+0.0073` in SOMA's RH basis and negative in Unity's LH basis. That
     sign flip is exactly what a mirror-free RH→LH conversion must produce, so the Y/Z
     swap is not reflecting the character.
   - *Two rest-pose mismatches were the actual cause.* Measured
     `animator.GetBoneTransform` rest directions against SOMA's reference pose:

     | | SOMA rest | DonQuixote bind pose |
     | --- | --- | --- |
     | `LeftArm`→`LeftForeArm` | `(+1, 0, 0)` (T-pose) | `(-0.424, -0.824, -0.375)` |
     | `LeftForeArm`→`LeftHand` | `(+1, 0, 0)` | `(-0.398, -0.265, +0.878)` |
     | `LeftLeg`→`LeftShin` | `(0, 0, -1)` = down | `(-0.029, -1.000, 0)` = down |

     SOMA's rest is a clean T-pose in metres (head at 1.61 m); DonQuixote's FBX bind pose
     has arms hanging ~55° down with elbows already bent. The world-space delta is
     measured from SOMA's T-pose, so applying it to an already-posed bind pose
     double-rotated every limb. Legs matched better, which is why they looked merely
     splayed rather than broken.
   - *The two rests were also yawed 180° apart.* SOMA faces `-Y` with its left arm on
     `+X`; Unity rigs (DonQuixote measured: `LeftUpperArm.x = -605`) face `+Z` with the
     left arm on `-X`. The bare Y/Z swap landed SOMA facing `-Z`.

   **The two fixes:**
   - `tools/pose_sender_motionbricks.py`: conversion is now `pos -> (-x, z, -y)` and
     `quat -> (x, -z, y, w)` — the same Y/Z swap (determinant -1, so chirality still
     holds) composed with a 180° yaw, which lines SOMA's rest up with Unity's humanoid
     convention. `--self-test` re-passes (homomorphism, pos/quat agreement, rest→identity),
     so the new pair is internally consistent, not a guess.
   - `Assets/Scripts/PoseReceiver.cs`: `ReferenceRotation()` builds, once at `Awake()`, a
     **T-pose-aligned reference** per bone — the bind-pose world rotation pre-swung by
     `Quaternion.FromToRotation(actualBoneDirection, somaRestDirection)` so each bone axis
     points where SOMA's T-pose points it. Deltas are applied to that instead of the raw
     bind pose. `PoseFrameCodec.SomaRestBoneDirections` (SOMA's rest directions in Unity
     space) and `SomaChildJoint` (which child defines each bone's axis) are **generated
     from `soma_base_skel_minimal_no_root.usd`**, not hand-written; the editor self-test
     asserts the two tables agree about which joints are leaves. Ran it: passed.

   **Dead end, recorded so nobody retries it:** zeroing `HumanPose.muscles` and calling
   `HumanPoseHandler.SetHumanPose` does **not** give a T-pose. Measured: it yields the
   avatar's relaxed neutral — arms ~45° down (`(-0.634, -0.646, 0.424)`), knees bent 30°.
   Unity's stored T-pose is not reachable through public runtime API, hence the
   direction-alignment approach above.

   **Visually confirmed 2026-11-14** (user, Editor Game view, `PoseReceiverTest.unity`):
   after the delta-retarget, jitter and T-pose-alignment fixes the rig jogs correctly —
   limbs bend the right way and she travels a long distance over the run. The three
   rotation/coordinate bugs are closed.

   **Still open:**
   - **Not yet tested in the NavMesh scene or over Quest Link**, which is what step 4's
     "done when" actually asks for, and no frame rate was measured. Desktop Editor only
     so far.
   - **Twist is not retargeted.** `FromToRotation` is a minimal-arc alignment, so it
     corrects each bone's *direction* but not its roll about its own axis. If wrists or
     forearms read as rolled, align a second axis (the limb's bend plane) rather than
     using `FromToRotation`. Hands specifically get no alignment at all — SOMA's
     `LeftHand`/`RightHand` child is an end marker with no `HumanBodyBones` slot, so those
     fall back to the raw bind rotation.
   **Scale fixed properly, 2026-11-14 (was: `positionScale = 3493` as a fudge).**
   `DonQuixote.fbx`'s `ModelImporter.globalScale` went `15.63624` -> `0.004476024`
   (= `15.63624 * 1.012 / 3535.252`, i.e. calibrated so the rest hips height matches
   SOMA's `1.012 m`), and `PoseReceiver.positionScale` is back to `1`. The rig is now at
   Unity's 1-unit-=-1-metre convention, which step 6's MR occlusion needs.
   - Verified after reimport: hips `1.0120 m`, head `1.6765 m`, upper arm `0.231 m`
     (SOMA's is `0.289` — different proportions, not an error). Avatar survived: all 19
     required `HumanBodyBones` resolve, `isHuman`, valid, and 24 of 30 SOMA joints bind
     (correct — 5 have no Humanoid slot, `Jaw` is absent on this rig).
   - Two things the scale change dragged with it, both fixed: `FollowCamera`'s local
     position was framed in the old units (`(0, 9167, -16111)`, i.e. 16 km out) and was
     rescaled by the same factor to `(0, 2.624, -4.612)`; and `PoseReceiver` now
     subtracts `_hipsOffsetFromRoot` from the streamed root position, because SOMA's root
     **is** its Hips joint while this script moves the GameObject root, which sits a
     hip-height below — the rig had been floating by exactly that much, invisible at
     ~3500x scale.
   - Housekeeping: an earlier `HumanPoseHandler.SetHumanPose` experiment had been
     accidentally saved into `PoseReceiverTest.unity`, leaving the relaxed pose as the
     stored rest. Reverted all 103 transform overrides on the prefab instance; bind pose
     confirmed restored (`LeftUpperArm->LeftLowerArm` back to `(-0.424, -0.824, -0.375)`).
   - **No interpolation.** Each 30 Hz pose is held until the next arrives (a stair-step,
     not a smooth blend). Fine at 30 Hz; if it reads as choppy on-device, `Slerp` toward
     the latest frame instead of snapping to it.
   - **Scale:** `DonQuixote.fbx`'s `ModelImporter.globalScale` is `15.6`, not `1`, so the
     rig is not at Unity's 1-unit-=-1-metre scale while `PoseReceiver.positionScale` is
     `1` and the sender sends metres. Expect root translation to look far too small for
     the rig's size. Fix the FBX import scale (or `positionScale`) when tuning placement.

   **How to run it:**
   ```
   # Terminal 1 — Unity: open PoseReceiverTest.unity, enter Play mode
   # Terminal 2:
   cd ../motionbricks
   uv run python ../SnackClubHavenAICompanionship/tools/pose_sender_motionbricks.py --duration 45
   ```
   Needs the `motionbricks` repo as a sibling checkout with its own `uv` venv set up, and
   a CUDA GPU (first run per process builds/loads a TensorRT plan).

   **Done when:** rig in the NavMesh scene visibly mirrors live motionbricks motion over
   Quest Link, at >=20 Hz observed (no visible stutter/snapping), for one full generated
   sequence without a dropped-frame crash. **MET 2026-11-14 — on-device, not over Link,
   which is strictly better. Quest Link is a dead end on this machine; don't retry it.**
   User in headset: "it works so well and is so smooth." Sender: `30.0 Hz achieved,
   2 frames late` out of 1350 (vs ~8/s and 1-75 Hz bursts over Link).

   **THE WORKING PATH — on-device APK, pose streamed over Wi-Fi. Use this, not Link.**
   ```
   # 1. build+install (Unity: platform already Android; ~4 min build)
   #    scene list must be ONLY Assets/MRUKSamples/NavMesh/NavMesh.unity so the APK
   #    boots into it instead of StartScene. Output: Builds/SnackClubHaven.apk
   ADB="C:/Program Files/Unity/Hub/Editor/6000.0.38f1/Editor/Data/PlaybackEngines/AndroidPlayer/SDK/platform-tools/adb.exe"
   "$ADB" install -r Builds/SnackClubHaven.apk
   "$ADB" shell monkey -p com.samples.mruksample -c android.intent.category.LAUNCHER 1
   # 2. stream from the PC (headset's Wi-Fi IP, NOT loopback)
   cd ../motionbricks
   uv run python ../SnackClubHavenAICompanionship/tools/pose_sender_motionbricks.py        --host 172.16.1.134 --duration 45
   ```
   - Package id is **`com.samples.mruksample`** (`ProjectSettings` `applicationIdentifier`),
     NOT the `com.meta.mruksample` in `Assets/Plugins/Android/AndroidManifest.xml` — that
     manifest's `package=` attribute is ignored. Using the manifest name gives
     "No activities found to run".
   - `tools/pose_sender_motionbricks.py` gained `--host` for this; default stays loopback.
   - Verified on device: `XR_FB_passthrough: Version=5` **available** (it is *Unavailable*
     over Link), `XR_META_environment_depth: Version=2`, `USE_SCENE: granted=true`,
     `android.permission.INTERNET: granted=true` (Unity's manifest merger adds INTERNET
     from the `UdpClient` even though `ForceInternetPermission: 0`), MRUK anchors load and
     persist natively. PC `172.16.1.25/23` and Quest `172.16.1.134/23` are same-subnet with
     no AP isolation (ping 0% loss, 3-20 ms).
   - Needs USB only to install. Headset must be authorized for adb (tap **Allow** in the
     headset); `adb connect <ip>:5555` fails unless wireless debugging was enabled first.
   - **Unity Editor is not needed to run the demo** — the APK runs standalone.

   **Why Link was abandoned (measured, don't re-litigate):** cable negotiates USB 2.0
   (`transmission_type: USB2_DISCO` in 53/57 streaming steps, 81
   `usbwatcher_disconnected` events). Unity submitted **2-8 app fps against 72 presented**,
   so the compositor reprojected nearly every frame; reprojection corrects head motion but
   not object motion, which is why the *moving characters* tore while the static room
   looked fine. Dropping Standalone quality Ultra->Medium changed app fps **not at all**,
   which is what proved render cost was never the bottleneck. Sender alone with Unity idle:
   `30.0 Hz, 1 frame late` — motionbricks was never the problem.

   **Unity crashed at 21:20:12** (`%LOCALAPPDATA%/Temp/Unity/Editor/Crashes/Crash_2026-11-14_212012185`)
   right after the USB cable was unplugged/replugged while it still held the Link XR
   session; `mfh264enc.dll` (Link's H.264 encoder) is in the faulting module list. No work
   lost — the scene and QualitySettings had been saved through the Editor API, everything
   else was written to disk directly. Unity also re-serialized
   `Assets/Universal Render Pipeline Asset.asset` on the Android platform switch
   (`m_PrefilteringModeAdditionalLight: 4 -> 3`, a shader-stripping hint only; MSAA still 4).
   Test plan for the remaining half: `docs/quest_link_test_plan.md`.

   **Quest Link run #1 (2026-11-14, cable Link, `NavMesh.unity`, Editor Play mode):**
   - **Passthrough blocker found and fixed — it was never in the project.** The Link
     runtime wasn't advertising `XR_FB_passthrough` (`Editor-prev.log`: `Unavailable
     OpenXR extension: XR_FB_passthrough` → `Failed to initialize Insight Passthrough
     ... Failure_NotInitialized`). Cause: *Passthrough over Meta Quest Link* and *Spatial
     Data over Meta Quest Link* were off in the Link desktop app. After toggling both
     (+ restart): `[Insight MR] Successfully initialized passthrough` and
     `XR_TYPE_EVENT_DATA_PASSTHROUGH_LAYER_RESUMED_META`. Every project-side setting was
     audited and was already correct — details in `docs/quest_link_test_plan.md` §3.
   - **Pose stream reached the rig, but the ≥20 Hz bar failed.** Sender ran its full 45 s
     (`Done.`, exit 0, no PoseReceiver exceptions). Receiver counted **359 datagrams in
     45 s ≈ 8/s delivered, 15.6 Hz avg per logged second, bursty (1→75 Hz)**, 23 log
     lines where ~45 were expected — so the receive thread sat blocked for multi-second
     stretches, then got bursts. Sender claims 30 Hz; not yet determined whether it was
     GPU-starved by Unity's XR render + Link encode on the same RTX 4080 (likely — the
     desktop-Editor run had no Link encoder competing) or whether its loop free-runs.
     **Next:** stamp each datagram with send time (or just print sender-side achieved Hz)
     to split sender-vs-receiver before touching anything.
   - **Visual result (user, in headset): passthrough fully visible, but no movement from
     DonQuixote.** Root cause found, and it is *not* the missing room scan: `PoseReceiver`
     set `transform.position` to the streamed root **absolutely**, so the rig teleported
     off its `(1.5, 0, 0.3)` scene placement to the world origin and then jogged straight
     out of the room — the sender's own log shows root reaching `[5.79, 80.14]`, i.e. 80 m,
     by t=44s. The desktop-Editor run looked fine only because a `FollowCamera` chased her;
     that camera is disabled in `NavMesh.unity` (the headset owns `MainCamera`), so from a
     fixed viewpoint she leaves frame in ~2 s and reads as "never appeared".
     **Fixed** in `PoseReceiver.cs`: streamed root is now an offset from the rig's scene
     position (`_startPosition`), plus a `followRootPosition` bool — set to `false` on the
     `NavMesh.unity` instance so she jogs in place and stays observable. Step 5 is what
     gives the two frames a shared origin; at that point place the rig at the room origin
     and the behaviour degenerates to the old absolute one. Sender `--self-test` re-passes;
     scene saved with `followRootPosition: 0`.
   - **The room-scan prompt needs no code — MRUK already does it, and it cannot work over
     Link.** `MRUK.cs:784` calls `LoadSceneFromDevice()` with its default
     `requestSceneCaptureIfNoDataFound: true`, and `MRUK.Shared.cs:271` runs
     `OVRScene.RequestSpaceSetup()` on the `NoRoomsFound` branch. That branch *did* run —
     the console warning we saw is printed at `MRUK.Shared.cs:264`, immediately above it:
     "Scene capture does not work over Link or XR Sim. If using Link please capture a scene
     with the HMD in standalone mode, then access the scene model over Link." So the fix is
     operational, not code: run **Space Setup in the headset standalone**, then reconnect
     Link. Adding another prompt call would duplicate the SDK's and still return false.
   - The 6 `NullReferenceException`s were all `OVRInputModule` (intro-canvas UI pointer),
     not `PoseReceiver` — stack traces checked, unrelated to the pose path.

   **Quest Link run #2 (2026-11-14, after the room rescan). Room data, occlusion and
   Breeze all work; jitter fixed; tearing diagnosed but NOT fixed.**
   - **Room scan came through:** `Anchor search complete with 16 anchors`, `Found 1 room
     V1 anchors` (run #1 had 0 + the JSON fallback). Breeze's NavMesh works, and the user
     confirms Depth-API occlusion works in the headset.
   - **Don's jitter root cause: `tools/pose_sender_motionbricks.py` had no pacing at all.**
     `delta_time = 1/UPDATE_RATE` was only the *simulation* timestep and `time = step *
     delta_time` a virtual clock — the loop had no `sleep`, so it emitted frames as fast
     as the GPU produced them and ran the GPU flat out. Sharing the GPU with Unity's XR
     render + Link encode, that collapsed to ~8-15 Hz in irregular bursts.
     **Fixed** by clocking the loop to wall time (`slack = start + (step+1)*delta_time -
     perf_counter()`), plus an achieved-Hz line at exit.
     Measured, same scene, Play mode, before -> after: receiver **15.6 Hz avg, range
     1-75** -> **33.2 Hz avg, range 14-48**; sender reports `29.5 Hz achieved`.
     User confirms "jitter was a lot less" in the headset. `--self-test` still passes.
     Note `381/600 frames late` — frame time sits right at 33 ms, so 30 Hz is marginal
     while sharing the GPU. Receiver-side `Slerp` (already flagged above as the planned
     next step) is the remaining lever if it still reads choppy.
   - **Tearing on both characters: NOT the pose path, and not occlusion.** DonQuixote has
     no materials at all (only the two FBXs), so she isn't even using
     `MRUKOccludedLit` — an occlusion-edge artifact cannot explain tearing on her. Two
     real causes, both from the Link app's own telemetry
     (`%LOCALAPPDATA%\Oculus\PerfLog_2026-11-14_14.54.26.json`,
     `oculus_pc_xrs_stats_event` rows):
     1. **The cable is negotiating USB 2.0.** `transmission_type` reads `USB2_DISCO` in
        53 of 57 streaming steps, plus 81 `oculus_xrs_pc_usbwatcher_disconnected` events.
        Quest Link wants USB 3.0; at USB 2 bitrate the stream glitches
        (`num_glitches` 1-9/min, flagged `num_glitches_with_high_bitrate`). The charging
        cable bundled with the headset is USB 2 — use the official Link cable or a
        certified 5 Gbps USB-C cable in a USB-3 port directly on the motherboard.
     2. **Unity submits 2-8 app fps against 72 fps presented.**
        `num_pc_presented_frames` ≈ 72/s while `num_completed_app_frames` is 2-8/s, with
        223-1090 `num_pc_app_early_reprojected_frames` and 10-83 `lost_pc_app_frames` per
        minute. The compositor is reprojecting nearly every frame, and reprojection
        corrects *head* motion only, not object motion — so moving objects (both
        characters) smear while the static room looks correct. That is exactly the
        reported symptom.
     **Applied 2026-11-14 (user's call): Standalone quality level 5 (Ultra) -> 2 (Medium),
     i.e. the same level Android/Quest builds use.** Done through the Editor
     (`SerializedObject` on the QualitySettings singleton + `SaveAssets`) so Unity's
     in-memory state matches the file, then `SetQualityLevel(2, true)`. What it buys:
     shadows soft->hard, shadow resolution 2->0, cascades 4->1, shadow distance 150->20 m,
     realtime reflection probes off, soft particles/vegetation off, realtime GI CPU
     100->25, LOD bias 2->0.7. Side benefit: the Editor-over-Link preview now matches what
     the device build actually renders. **MSAA is unchanged at 4** — it lives in
     `Assets/Universal Render Pipeline Asset.asset`, and no quality level overrides the
     URP asset (`renderPipeline` appears 0 times in QualitySettings), so the quality level
     cannot touch it. Saving also re-serialized the asset to `serializedVersion: 4`
     (new zero-valued `adaptiveVsync*` fields, a `Nintendo Switch 2` entry) — Unity's own
     format upgrade, not a settings change. **Not yet re-measured in the headset.**

     Still untried, in order of expected payoff: **USB-3 cable** (the big one — USB 2 is a
     transport ceiling no project setting can lift); drop URP `m_MSAA: 4` to 2;
     close/minimise the Scene view during Play so the Editor renders one view instead of
     two. `runInBackground` was checked and is already `1`, so Editor focus is not the
     cause.
   - Side finding: MRUK found **0 room anchors over Link** (`Anchor search complete with
     0 anchors` → fell back to the bundled JSON room); Breeze threw `Failed to create
     agent because there is no valid NavMesh` + 6 `NullReferenceException`s. That's the
     sample scene's problem, not PoseReceiver's, but it means step 5's real-room geometry
     needs the headset's Space Setup scan to come through Spatial-Data-over-Link.
   - Note: `EnvironmentDepth`'s `_systemOcclusionEnabled`/`_systemMaxEnvOcclusion`/
     `_systemMaxOpacity` fields were dropped on scene save — they don't exist in the
     installed Meta XR SDK 209. `docs/mruk_depth_occlusion_notes.md` step 1 still
     references `_systemOcclusionEnabled`; stale for step 6.
5. Feed MRUK room geometry → motionbricks, controller ray hit → target position. Same
   socket, opposite direction.
   **Premise corrected 2026-11-14: there is no "motionbricks obstacles" format to find.**
   Grepped the whole motionbricks repo — it has **no obstacle, avoidance, or pathfinding
   API at all**. The only `obstacle` hits are *motion clip filenames*
   (`soma/avoidance/neutral_avoid_obstacle_*.bvh`, `soma/jump/jump_over_obstacle_*.bvh`),
   i.e. animation data, not routing. `runtime_api.md` exposes exactly one steering
   concept: **generate toward one to four target poses**, placed in world space by moving
   the pose root (`place_target_poses()` in `motionbricks/runtime/target_pose.py`).
   So **routing is our job, not motionbricks'.** The good news is Unity already does it:
   MRUK builds a real NavMesh from the room scan and `Breeze` navigates it on-device
   today. The shape of step 5 is therefore:
   - Unity: controller ray hit → `NavMesh.CalculatePath` → waypoint list.
   - **New reverse channel Unity → Python** (does not exist yet; `PoseReceiver` is
     receive-only). Add a second UDP socket, opposite direction.
   - Sender: replace the hardcoded `steering(time)` with "direction toward next waypoint".
     `canonical_target`/`place_target_poses` already take a direction + ground position,
     so this end is a small change.
   Obstacle *avoidance* then falls out of the NavMesh for free — the path already routes
   around scanned geometry; motionbricks just walks it.
   **Full handoff doc, written for a fresh agent: `docs/step5_room_geometry_to_motion.md`**
   — exact file:line touchpoints, the Unity→motionbricks coordinate inverse, a wire-format
   proposal, 8 traps, and a 5-stage build order where each stage is independently
   verifiable. Start there, not here.
   **Done when:** moving the controller ray to a new point visibly redirects the rig's
   live motion toward it, and placing a real-world obstacle (per MRUK scan) causes the
   generated motion to route around it in the headset.
   **MET 2026-11-14 — BOTH halves, on-device.** User in headset: *"moves literally
   perfectly"* (pointing) and *"it completely works, moves around furniture"* (avoidance).
   - Pointing: 13 trigger presses -> 13 datagrams, 12 of 13 confirmed to the centimetre;
     NavMesh snap mean 0.236 m; 30.0 Hz with 1 late frame of 2250 while handling inbound.
   - Avoidance: 14 paths in 90 s — 10x 2-corner `PathComplete`, 3x 2-corner `PathPartial`,
     1x **4-corner** `PathPartial` with 2 mid-path corner advances.
   - Built: `Assets/Scripts/TargetSender.cs`, `PoseFrameCodec.EncodeTarget`,
     `PoseReceiver.StartPosition`, and the sender's inbound socket on 5006
     (`yup_to_zup_pos`, `decode_target`, `drain_target`, `--target X,Y`).
   - Reversibility kept: `useNavMeshPath = false` reverts to straight-line walking with no
     rebuild; `Builds/SnackClubHaven-stage3-KNOWN-GOOD.apk`; checkpoint commit `e15c339`.
   - Known cosmetic defect, accepted by the user: she mills ~+/-0.5 m around a reached
     target (the jog target pose carries 1.9 m/s of momentum). Fix options in
     `docs/step5_room_geometry_to_motion.md` §9.
   - Full record: `docs/step5_room_geometry_to_motion.md`.
6. Apply Depth-API occlusion material to the rig (`docs/mruk_depth_occlusion_notes.md`).
   **This is now the blocking gap — everything it depends on is verified working.**
   On-device the Depth API is live (`XR_META_environment_depth: Version=2`,
   `USE_SCENE: granted=true`) and `Breeze` is correctly occluded; DonQuixote is not,
   because she has no materials at all (only `DonQuixote.fbx` / `Don2Sketchfab.fbx`), so
   Unity gave her standard URP Lit. Extract her textures, build a material on
   `MRUKOccludedLit.shadergraph`, re-map per the property table in the notes, set
   `_EnvironmentDepthBias = 0.09`, assign, rebuild, reinstall. **Build to a separate APK
   path so the known-good `Builds/SnackClubHaven.apk` stays installable as a fallback.**
   **Done when:** on-device, the rig is correctly occluded by real-world geometry it
   walks behind (verified visually, matching the known-good values in
   `docs/mruk_depth_occlusion_notes.md`) — not just assigned the material.
7. LLM dialogue: TTS + lipsync is the hard part, not the API call.
   **Status 2026-11-14 — further along than this list implied, but PC-side only.** Already
   built in `tools/`: `miku_client.py` (456 lines; Ollama token streaming + real-time TTS
   audio over SSE from a second machine at `172.16.1.27:8765`), `voice_input.py`
   (push-to-talk → local Whisper → `miku_client.send_and_stream`), `fake_miku_server.py`
   (test double so the SSE path runs without the second machine) and
   `test_voice_input.py`. Last `whisper_test.log` run transcribed `''` — the model
   downloaded and ran, but captured no speech, so mic capture is unverified.
   **Note this uses Ollama, not the Claude API** — the "pick a Claude model via the
   `claude-api` skill" line above is superseded unless you deliberately switch back.
   **What is actually left:** all of the above plays audio on the **PC**, while the
   character now renders in an **on-device APK**. Either (a) accept PC-side audio — fine
   if the livestream mixes PC audio, and it costs nothing — or (b) stream audio to the
   Quest app, which is what on-device lipsync (OVRLipSync visemes) would need.
   **Done when:** a hardcoded line of dialogue plays as audible speech synced to the
   character on-device (lipsync can lag; audio playback cannot), via one manual run —
   record which Claude model was picked and why.

   **Partial progress, 2026-11-14 — speech-in half built and tested on desktop; still not
   the Claude-model path, and not yet wired to the character on-device.** Added
   `tools/miku_client.py`, `tools/voice_input.py` (push-to-talk: press Enter, speak, press
   Enter, local Whisper transcribes, text is handed to `send_and_stream`), plus
   `tools/fake_miku_server.py` + `tools/test_miku_client.py`/`test_voice_input.py` as the
   runnable self-checks.

   **Important deviation from the plan above, not yet resolved:** the server this talks to
   (a second machine on the LAN, `172.16.1.27:8765`) runs **Ollama**
   (`huihui_ai/qwen3.5-abliterated:2b`) + Edge-TTS/RVC for voice, **not Claude**. This is
   the text-generation+TTS path that was actually built and tested; picking a Claude model
   via the `claude-api` skill (as this step asks) is still open — either swap this server's
   LLM call for Claude, or treat Ollama as a placeholder and revisit. Don't assume "LLM
   dialogue" means Claude until that's decided.

   **Verified working, against the real second machine (not just `fake_miku_server.py`):**
   - `python tools/miku_client.py "<prompt>" --server http://172.16.1.27:8765` round-trips
     text + audio for real — e.g. one run: prompt → full reply text + 812 KB of synthesized
     audio in **9.04s** total.
   - **It's genuinely streamed, not buffered-then-dumped** (timestamped
     `MikuClient.stream_chat` callbacks, one run): text tokens arrive almost immediately
     (0.47s–0.66s after sending, word-by-word from Ollama); audio arrives as separate
     per-sentence WAV chunks only once each sentence's TTS finishes (sentence 1's audio at
     3.90s, sentence 2's at 16.17s) — audio for a later sentence doesn't block on an earlier
     one, so playback can start before the whole reply is synthesized.
   - `tools/voice_input.py`'s recording half works against the real mic (`sounddevice`
     `InputStream`, verified capturing real samples) and Whisper transcription works
     (`tiny` model; `base` model's first download hit a corrupted/truncated fetch — SHA256
     checksum mismatch — fixed by deleting the bad `~/.cache/whisper/base.pt` and letting it
     re-download, or just use `--whisper-model tiny` on a flaky connection).
   - **Not yet tried:** real speech into `voice_input.py` end-to-end (only tested with
     silence, which correctly transcribes to `''`); playback on the actual character
     on-device in Unity/Quest (everything above ran on desktop via `sounddevice`, not
     through `PoseReceiver`'s rig or any lipsync); and the Claude-model swap mentioned above.
8. ~~Repeat step 1 for the other rigs.~~ **CUT 2026-11-14 — scope is DonQuixote only.**
   The other 8 rigs in `Rigs/` stay source FBX; don't spend time on them. If one is ever
   revived, what Don needed was: import as Humanoid (all 19 required `HumanBodyBones`
   resolved), a **per-rig import scale** (Don's `globalScale` is `0.004476024`, calibrated
   so rest hips match SOMA's `1.012 m` — the default `15.6` put her at ~3500x), and her
   own `MRUKOccludedLit` material (step 6). The SOMA→`HumanBodyBones` table in step 2 and
   `PoseReceiver.cs`'s T-pose alignment are rig-agnostic and need no per-rig work.

---

**This is the bridge project**: it owns tying Meta Quest MRUK (room-scan geometry),
motionbricks (real-time human-motion generation), these custom character rigs, and the
LLM dialogue call into one live VR-livestreaming pipeline. motionbricks itself stays a
separate repo (`motionbricks`); everything else now lives in **this one repo/folder**:

- `Rigs/` — source character rigs, not yet Unity assets (see below). 9 rigs as of
  2026-11-14: `DonQuixote/`, `Faust/`, `carmen-limbus-company/`,
  `ishmael-v2-limbus-company/`, `joker-persona-5/`, `FreddyFazbear/` (Sketchfab-style
  `source/` + `textures/` layout), plus `KasaneTeto.fbx`, `Seek/Seek.fbx`,
  `Master Chief/` (fbx + dae). **DonQuixote is the only rig in scope — step 8 was cut
  2026-11-14. The other 8 are dead weight unless scope changes.**
- `Assets/`, `Packages/`, `ProjectSettings/` — the actual Unity/MRUK project. This was
  merged in 2026-11-14 from a separate `Unity-MRUtilityKitSample` repo (Meta's MRUK
  sample, history intentionally stripped — hackathon, didn't need to keep pulling
  upstream updates). Open this folder itself in Unity Hub as the project root.
- `docs/` — notes carried over from testing in that former repo, before the merge.

This file is knowledge carried over from a motionbricks debugging session (2026-11-14)
— read it before doing retargeting/livestream work here. Full session notes:
`motionbricks/docs/live_retargeting_notes.md`.

## The pipeline this project bridges

- Meta Quest MRUK room-scan → real-world geometry → motionbricks obstacles/targets.
- motionbricks generates human motion live, conditioned on controller pointing, avoiding
  that geometry. Output is **SOMA** skeleton pose data (`pred_global_motions`).
- SOMA's pose needs to drive one of **these** custom rigs, live, not baked.
- Character also talks via an LLM call (voice/dialogue) — part of this bridge, not yet
  built here.

## Why these rigs need retargeting (not a straight name match)

SOMA uses raw mocap bone names (`Hips, Spine1, Spine2, LeftLeg, LeftShin, LeftFoot, ...`).
These Fbx rigs likely use their own hierarchy/naming per DCC export (Mixamo-style rigs seen
in the test scene used `mixamorig:LeftUpLeg` etc.). **Known trap:** leg segments are
offset by one joint between naming conventions —

| Segment | Mocap/SOMA name | Mixamo-style name |
| --- | --- | --- |
| Thigh | `LeftLeg` | `mixamorig:LeftUpLeg` |
| Calf | `LeftShin` | `mixamorig:LeftLeg` |
| Foot | `LeftFoot` | `mixamorig:LeftFoot` |

A naive name match puts the thigh rotation on the knee. Verify the actual bone names in
each FBX before mapping — don't assume Mixamo convention for any of these rigs.

**In Unity this is solved for free:** import the FBX with Rig → Humanoid. Unity's avatar
mapper resolves bones to `HumanBodyBones` by hierarchy, not name, so the offset trap
disappears. The SOMA side still needs one hand-written SOMA-name → `HumanBodyBones` table
(step 2 in Next steps). The Blender/Rokoko path below is only for offline clip checks.

Units: **the live runtime path is Z-up and in metres** — `motionbricks/io/bvh.py` multiplies
the BVH's centimetre offsets by `0.01` on load, and the engine runs in MuJoCo-convention Z-up
world space. Measured 2026-11-14: SOMA's rest hips sit at `1.012`, head at `1.610`. The
"Y-up, centimetres" note that used to be here described the raw BVH files, not what comes out
of the runtime, and cost a session's debugging — see step 4.

## Offline clip check in Blender (validated on a test rig — NOT the live path)

Use this to eyeball a SOMA BVH clip on a rig before touching Unity. It is not part of the
runtime pipeline.

1. Import the target rig's FBX into Blender. Install/enable the Rokoko Studio Live addon.
2. Rokoko tab (N-panel) → **Retargeting** sub-panel — it's collapsed by default
   (`DEFAULT_CLOSED`) and was gated behind Rokoko account sign-in; sign in if it's not
   showing.
3. Set source = a SOMA-named armature (any SOMA BVH clip imported, or a proxy armature —
   see below), target = the custom rig's armature.
4. Run **Build Bone List** (auto-detect). This correctly resolves the thigh/calf offset
   above — trust it, but re-check its output per rig since these three haven't been tested
   yet.
5. For a one-off clip, Rokoko's "Retarget Animation" op duplicates the source, adds
   `COPY_ROTATION`/`COPY_LOCATION` constraints, bakes with `nla.bake`, then deletes the
   duplicate+constraints. Fine for a clip check; irrelevant for live.

## Live streaming (WORKING on-device as of 2026-11-14 — step 4 closed, NOT over Link)

Live pose goes **motionbricks → UDP → Unity**, no Blender in the loop. The rig renders in
Unity on Quest, so that's where the bones get driven.

1. **Processes:** motionbricks is its own Python app (`motionbricks/app/runtime`, imgui
   window). Unity is a separate process. **The deployment is an on-device APK, not the
   Editor over Quest Link** — Link was tried and abandoned (USB 2.0 ceiling, 2-8 app fps;
   see step 4). A socket is required either way, but it is **not** loopback on-device: the
   sender takes `--host <headset Wi-Fi IP>` and the datagrams cross the LAN.
2. **Payload, 30 Hz, one UDP datagram per frame:** root position + one quaternion per SOMA
   joint, decoded from `pred_global_motions`. Keep it tiny and ours. Don't reuse Rokoko's
   live protocol — it carries capture-hardware skeleton/face/prop/tracker data we don't
   need.
3. **Unity side — BUILT, see step 4 for what it actually does.** `PoseReceiver.cs` on the
   rig. The original plan here ("set local rotation; convert Y-up cm to m; handedness flip
   to verify") is superseded on every count: the stream carries **world-space rotation
   deltas from SOMA's T-pose**, applied to a T-pose-aligned reference built from the rig's
   own bind pose, and all axis conversion (`pos -> (-x, z, -y)`, `quat -> (x, -z, y, w)`)
   lives in the Python sender. No ÷100 anywhere — the runtime is already in metres.
4. **Bootstrap without motionbricks running:** replay a SOMA BVH clip from a 20-line
   Python sender so the receiver can be debugged in isolation.
5. **Reverse direction** (MRUK geometry → motionbricks obstacles, controller ray →
   target) uses the same socket pair. Payload format TBD against
   `motionbricks/docs/runtime_api.md`.

## Not yet built here

MRUK room-scan ingestion and controller→target placement are in scope for this bridge
project but not yet implemented in this repo. The LLM dialogue call is partially
addressed — see step 7 above (`tools/voice_input.py` + `tools/miku_client.py`: speech in
→ Whisper → a LAN Ollama+TTS server → audio out, tested working on desktop) — but it
talks to Ollama, not Claude, and isn't wired to a character on-device yet. Don't read
"not covered" as "someone else's problem" — it's this project's backlog.

## Depth-API occlusion (Unity/MRUK, validated 2026-11-14)

If these rigs end up occluded by real-world room geometry on Quest, the Unity-side
setup is already validated in this project's `Assets/MRUKSamples/NavMesh` sample scene
(`BreezeCharacter`) — not a separate repo anymore, it's right here. Full notes,
shader/property mapping, and known-good values: `docs/mruk_depth_occlusion_notes.md`.
Applying it to the `Rigs/` characters is still open — they're source FBX, not yet
imported into `Assets/` as Unity materials. **Updated 2026-11-14:** DonQuixote is now in
`NavMesh.unity` and running on-device, but still has **no materials at all** (her folder
holds only the two FBXs), so Unity gave her standard URP Lit and she is **not** occluded —
confirmed in the headset. `Breeze` in the same scene *is* occluded. This is the whole of
the remaining gap; see the step-6 section of `docs/mruk_depth_occlusion_notes.md` for the
exact swap. Also note Depth API does not work over Link at all — on-device only.
