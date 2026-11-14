# Snack Club Haven — AI Companionship

Custom character rigs (`Rigs/DonQuixote`, `Rigs/Faust`, `Rigs/KasaneTeto.fbx`) meant to be
driven live by **motionbricks** (separate repo: `motionbricks`, real-time human-motion
generation) for a VR livestreaming setup. This file is knowledge carried over from a
motionbricks debugging session (2026-11-14) — read it before doing retargeting/livestream
work here. Full session notes: `motionbricks/docs/live_retargeting_notes.md`.

## The pipeline this project is one piece of

- Meta Quest MRUK room-scan → real-world geometry → motionbricks obstacles/targets.
- motionbricks generates human motion live, conditioned on controller pointing, avoiding
  that geometry. Output is **SOMA** skeleton pose data (`pred_global_motions`).
- SOMA's pose needs to drive one of **these** custom rigs, live, not baked.
- Character also talks via an LLM call (voice/dialogue) — separate, unaddressed piece.

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
`Don2Sketchfab.fbx` / `Faust2Sketchfab.fbx` / `KasaneTeto.fbx` before mapping — don't assume
Mixamo convention for these three.

Units: SOMA/BVH clips are Y-up, centimeters.

## How to retarget (Blender steps, validated on a test rig)

1. Import the target rig's FBX into Blender. Install/enable the Rokoko Studio Live addon.
2. Rokoko tab (N-panel) → **Retargeting** sub-panel — it's collapsed by default
   (`DEFAULT_CLOSED`) and was gated behind Rokoko account sign-in; sign in if it's not
   showing.
3. Set source = a SOMA-named armature (any SOMA BVH clip imported, or a proxy armature —
   see below), target = the custom rig's armature.
4. Run **Build Bone List** (auto-detect). This correctly resolves the thigh/calf offset
   above — trust it, but re-check its output per rig since these three haven't been tested
   yet.
5. For a one-off clip, Rokoko's "Retarget Animation" op would duplicate the source, add
   `COPY_ROTATION`/`COPY_LOCATION` constraints, bake with `nla.bake`, then delete the
   duplicate+constraints. **Don't bake for live use** — see next section.

## For live streaming (not yet built — this is the plan, not done)

Rokoko's bake step is just a one-shot wrapper around constraints that already work
frame-by-frame. For live driving:

1. Keep a permanent **proxy armature** using SOMA's native joint names/hierarchy. Build
   the bone mapping once via step 4 above (reuse it, don't redo per session).
2. Add `COPY_ROTATION` (+ `COPY_LOCATION` on the root bone) constraints from the proxy
   onto the real character rig — the same ones Rokoko's bake creates — but leave them in
   place instead of baking+deleting. Blender re-evaluates constraints every frame on its
   own.
3. Bridge: each motionbricks frame (30 Hz), send joint quaternions + root position
   (decoded from `pred_global_motions`) to Blender. Set them directly on
   `proxy_armature.pose.bones[name].rotation_quaternion` — no keyframing needed, the
   constraints propagate automatically.
4. Don't reuse Rokoko's own UDP live-data protocol — it's built for their capture
   hardware's skeleton + faces/props/trackers payload we don't need. A minimal custom
   joint-name→quaternion feed is smaller and we already have the bone mapping.

**Open question, unresolved:** is the motionbricks process the same process as the
Blender instance (e.g. driving `bpy` directly / via an MCP connection — then step 3 is
just a function call, no socket), or separate processes (then an actual local socket/IPC
is needed)? Pin this down before building the bridge — it changes how much of "the
bridge" is real work.

## Not covered by this project

MRUK room-scan ingestion, controller→target placement, and the LLM dialogue call are
separate pieces of the larger bridge project and live elsewhere (motionbricks / app
layers), not here.

## Depth-API occlusion (Unity/MRUK side, validated 2026-11-14)

If these rigs end up occluded by real-world room geometry on Quest, the Unity-side
setup is already validated (in sibling repo `Unity-MRUtilityKitSample`, not here —
these rigs have no Unity materials yet). Full notes, shader/property mapping, and
known-good values: `docs/mruk_depth_occlusion_notes.md`.
