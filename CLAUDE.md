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
1. Pick one rig (suggest `Rigs/DonQuixote/source/Don2Sketchfab.fbx`). Import into
   `Assets/`, set Rig → Humanoid, confirm Unity's auto-map resolves every bone with no
   red entries. Record actual bone names here.
2. Dump SOMA joint order/names from one `pred_global_motions` frame (motionbricks) and
   write the SOMA→Humanoid `HumanBodyBones` mapping table in this file.
3. Write a Unity `PoseReceiver.cs` (UDP listener → set bone rotations each frame). Test
   with a canned BVH clip replayed from Python before wiring live motionbricks.
4. Add a UDP sender to motionbricks' runtime loop emitting the frame payload from step 2.
   Verify end-to-end on PC (Quest Link) with the rig in the NavMesh sample scene.
5. Feed MRUK room geometry → motionbricks obstacles (format TBD from `runtime_api.md`),
   controller ray hit → target position. Same socket, opposite direction.
6. Apply Depth-API occlusion material to the rig (`docs/mruk_depth_occlusion_notes.md`).
7. LLM dialogue: TTS + lipsync is the hard part, not the API call. Prototype text→speech
   playback on the character first; pick a Claude model via the `claude-api` skill.
8. Only after 1–7 work on one rig: repeat step 1 for the other rigs.

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
