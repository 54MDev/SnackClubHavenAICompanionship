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
4. Add a UDP sender to motionbricks' runtime loop emitting the frame payload from step 2.
   Verify end-to-end on PC (Quest Link) with the rig in the NavMesh sample scene.
   **Done when:** rig in the NavMesh scene visibly mirrors live motionbricks motion over
   Quest Link, at >=20 Hz observed (no visible stutter/snapping), for one full generated
   sequence without a dropped-frame crash.
5. Feed MRUK room geometry → motionbricks obstacles (format TBD from `runtime_api.md`),
   controller ray hit → target position. Same socket, opposite direction.
   **Done when:** moving the controller ray to a new point visibly redirects the rig's
   live motion toward it, and placing a real-world obstacle (per MRUK scan) causes the
   generated motion to route around it in the headset.
6. Apply Depth-API occlusion material to the rig (`docs/mruk_depth_occlusion_notes.md`).
   **Done when:** on-device, the rig is correctly occluded by real-world geometry it
   walks behind (verified visually, matching the known-good values in
   `docs/mruk_depth_occlusion_notes.md`) — not just assigned the material.
7. LLM dialogue: TTS + lipsync is the hard part, not the API call. Prototype text→speech
   playback on the character first; pick a Claude model via the `claude-api` skill.
   **Done when:** a hardcoded line of dialogue plays as audible speech synced to the
   character on-device (lipsync can lag; audio playback cannot), via one manual run —
   record which Claude model was picked and why.
8. Only after 1–7 work on one rig: repeat step 1 for the other rigs.
   **Done when:** each of the other 8 rigs individually passes step 1's check (all 19
   required `HumanBodyBones` resolved, no red entries) — log any rig that doesn't and
   what's wrong (multiple roots, extra prop bones, etc.) rather than silently skipping it.

---

**This is the bridge project**: it owns tying Meta Quest MRUK (room-scan geometry),
motionbricks (real-time human-motion generation), these custom character rigs, and the
LLM dialogue call into one live VR-livestreaming pipeline. motionbricks itself stays a
separate repo (`motionbricks`); everything else now lives in **this one repo/folder**:

- `Rigs/` — source character rigs, not yet Unity assets (see below). 9 rigs as of
  2026-11-14: `DonQuixote/`, `Faust/`, `carmen-limbus-company/`,
  `ishmael-v2-limbus-company/`, `joker-persona-5/`, `FreddyFazbear/` (Sketchfab-style
  `source/` + `textures/` layout), plus `KasaneTeto.fbx`, `Seek/Seek.fbx`,
  `Master Chief/` (fbx + dae). Only DonQuixote is the bring-up target; the rest wait.
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

Units: SOMA/BVH clips are Y-up, centimeters.

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

## Live streaming (not yet built — this is the plan, not done)

Live pose goes **motionbricks → UDP → Unity**, no Blender in the loop. The rig renders in
Unity on Quest, so that's where the bones get driven.

1. **Processes:** motionbricks is its own Python app (`motionbricks/app/runtime`, imgui
   window). Unity is a separate process (Editor over Quest Link on PC first, then on-device
   build). A local socket is required — resolved 2026-11-14, previously an open question.
2. **Payload, 30 Hz, one UDP datagram per frame:** root position + one quaternion per SOMA
   joint, decoded from `pred_global_motions`. Keep it tiny and ours. Don't reuse Rokoko's
   live protocol — it carries capture-hardware skeleton/face/prop/tracker data we don't
   need.
3. **Unity side:** `PoseReceiver.cs` on the rig. Reads the datagram, looks each SOMA joint
   up in the SOMA→`HumanBodyBones` table, sets the mapped bone's local rotation via the
   Animator's avatar (`animator.GetBoneTransform`). Convert SOMA's Y-up cm to Unity's Y-up
   m (÷100; handedness flip to verify on first frame).
4. **Bootstrap without motionbricks running:** replay a SOMA BVH clip from a 20-line
   Python sender so the receiver can be debugged in isolation.
5. **Reverse direction** (MRUK geometry → motionbricks obstacles, controller ray →
   target) uses the same socket pair. Payload format TBD against
   `motionbricks/docs/runtime_api.md`.

## Not yet built here

MRUK room-scan ingestion, controller→target placement, and the LLM dialogue call are
all in scope for this bridge project but not yet implemented in this repo — motionbricks
produces the obstacle/target and pose data this project needs to consume, and the LLM
dialogue call is unaddressed. Don't read "not covered" as "someone else's problem" —
it's this project's backlog.

## Depth-API occlusion (Unity/MRUK, validated 2026-11-14)

If these rigs end up occluded by real-world room geometry on Quest, the Unity-side
setup is already validated in this project's `Assets/MRUKSamples/NavMesh` sample scene
(`BreezeCharacter`) — not a separate repo anymore, it's right here. Full notes,
shader/property mapping, and known-good values: `docs/mruk_depth_occlusion_notes.md`.
Applying it to the `Rigs/` characters is still open — they're source FBX, not yet
imported into `Assets/` as Unity materials, so there's nothing to swap onto until
DonQuixote is brought into a scene (Next steps 1 → 6).
