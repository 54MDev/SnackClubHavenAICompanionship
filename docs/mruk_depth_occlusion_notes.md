# MRUK Depth-API occlusion notes (2026-11-14)

Where this fits (see `CLAUDE.md`): this repo is the bridge project tying MRUK,
motionbricks, and these rigs together. The Unity/MRUK project now lives directly in
this repo's `Assets/`/`Packages`/`ProjectSettings` (merged in from a separate
`Unity-MRUtilityKitSample` repo on 2026-11-14) — occlusion was tested there, on the
`MRUKSamples/NavMesh` sample scene/character (`BreezeCharacter`), before the merge.
Recorded here so a future session working on this bridge doesn't have to re-derive it.

## What was validated

Real-world geometry (from Meta's Depth API) can occlude a virtual character — e.g.
the character walks behind a real couch and the couch correctly hides it — using
shader-based occlusion, not Unity's normal depth buffer. Confirmed working end to
end on the `Breeze` character in `NavMesh.unity`.

## How to wire it up in Unity (MRUK / Meta XR SDK)

1. **One `EnvironmentDepthManager` per scene.** Add it to any GameObject (the test
   scene used a dedicated `EnvironmentDepth` object). Key fields:
   - `_occlusionShadersMode = SoftOcclusion` (enum value `2`) — this is what makes
     the shader-based path below work.
   - ~~`_systemOcclusionEnabled = 0`~~ — **stale as of Meta XR SDK 209 (2026-11-14): this
     field no longer exists.** `EnvironmentDepthManager` now serializes only
     `_occlusionShadersMode`, `_removeHands`, `CustomTrackingSpace` and `MaskMeshFilters`
     (see `EnvironmentDepthManager.cs:109-120`). Unity silently dropped
     `_systemOcclusionEnabled`/`_systemMaxEnvOcclusion`/`_systemMaxOpacity` from
     `NavMesh.unity` the first time it re-saved the scene. Nothing to set — the shader
     path is simply what you get.
2. **Shader swap, not a toggle.** The character's material must use
   `Assets/MRUKSamples/PassthroughRelighting/Oppy/materials/MRUKOccludedLit.shadergraph`
   instead of a standard Lit/PBR shader. There's no "add occlusion to existing
   shader" checkbox — occlusion-aware sampling is baked into this shader graph.
3. **Re-map material properties onto the new shader's names** (property names
   change, not just behavior):
   | Old (Lit/Standard) | New (`MRUKOccludedLit`) |
   | --- | --- |
   | albedo texture (`_BaseMap`/`_MainTex`) | `_Albedo` |
   | normal map (`_BumpMap`) | `_Normal` |
   | metallic/smoothness map (`_MetallicGlossMap`) | `_MetallicSmoothness` |
   | smoothness value (`_Smoothness`) | `_SmoothnessMult` |
   | metallic value (`_Metallic`) | `_MetallicMult` |
   | tint (`_BaseColor`) | `_Color` |

   Everything else from the old shader (emission, detail maps, occlusion map,
   workflow mode, surface/blend settings, etc.) gets dropped — this shader graph
   doesn't expose those slots.
4. ~~**`_EnvironmentDepthBias ≈ 0.09`**~~ — **STALE as of 2026-11-14, second dead
   instruction in this doc.** `MRUKOccludedLit.shadergraph` declares
   `_EnvironmentDepthBias` **zero times**, so `Material.SetFloat` on it is a silent no-op
   and the value is dropped on serialization. The `0.09` visible in `Breeze.mat` is a
   leftover from an older shader and is doing nothing. The property does still exist, but
   in the SDK's *other* occlusion shaders — `Shaders/EnvironmentDepth/OcclusionLit.shader`,
   `OcclusionSurfaceLit.shader`, `OcclusionUnlit.shader` — which are not this shadergraph.
   **Nothing to set.** Occlusion works through the global shader keywords
   `EnvironmentDepthManager` sets from `_occlusionShadersMode`. If the real/virtual edge
   flickers, the fix is elsewhere (or switch to one of the SDK shaders above, which do
   expose a bias).
5. Reference material: `Breeze.mat` in
   `Assets/MRUKSamples/NavMesh/BreezeCharacter/` (also mirrored as `DepthOcclusion.md`
   next to it).

## Where this works: on-device only (measured 2026-11-14)

Depth API **does not work over Quest Link**, so none of this can be validated in the
Editor over a cable. Confirmed both ways:

| | Over Quest Link | On-device APK |
| --- | --- | --- |
| `XR_META_environment_depth` | — | **Version=2** |
| `XR_FB_passthrough` | `Unavailable` | **Version=5** |
| `com.oculus.permission.USE_SCENE` | n/a | **granted=true** |
| MRUK room anchors | 0 found without the Link spatial-data toggle | load and persist |

Over Link `EnvironmentDepthManager` logs `Environment Depth is not supported` and
`MRUK couldn't load any scene data. Scene capture does not work over Link or XR Sim.`
Build and deploy the APK instead — see CLAUDE.md step 4's "THE WORKING PATH" for the
build/install/stream commands. The Unity Editor is not needed to run it.

## Implication for the SOMA-driven rigs here

For these rigs to be occluded by real-world geometry when deployed through MRUK
(same room-scan→obstacle pipeline described in `CLAUDE.md`), each rig's material
needs the same treatment: swap to `MRUKOccludedLit.shadergraph`, re-map its textures
per the table above, and set `_EnvironmentDepthBias`. **Still not done — this is step 6
and it is now the blocking gap.**

Status 2026-11-14: `DonQuixote` *is* in `Assets/MRUKSamples/NavMesh/NavMesh.unity` and
runs on-device at 30 Hz (step 4 is closed), but she **has no materials at all** —
`Assets/Rigs/DonQuixote/` holds only `DonQuixote.fbx` and `Don2Sketchfab.fbx`, so Unity
auto-generated standard URP Lit for her. That is exactly why the user saw passthrough,
smooth motion and no occlusion in the headset: the Depth API is live and `Breeze` is
occluded (she carries `MRUKOccludedLit` with `_EnvironmentDepthBias: 0.09`), while Don
renders with a shader that has no occlusion sampling in it. **Not a bug, not a
regression — the material swap has simply never been done for her.**

**DONE for Don, 2026-11-14.** What it actually took, and the two things the old version of
this doc got wrong about her:

- **She was never missing materials — she was missing TEXTURES.** Her 5 materials (`DonB`,
  `DonF`, `DonH`, `DonW`, `OL`) are **embedded in `DonQuixote.fbx`** and therefore
  read-only, all default `Universal Render Pipeline/Lit` at flat grey `0.8` with no maps.
  That grey is why she looked untextured.
- **The textures were outside `Assets/`.** They sit in `Rigs/DonQuixote/textures/` (a
  Sketchfab-style `source/` + `textures/` download) and only the FBX had been copied into
  `Assets/Rigs/DonQuixote/`, so Unity had never seen them. Copied into
  `Assets/Rigs/DonQuixote/textures/`. Four base-colour maps, **no normal or metallic maps**,
  so `_Normal` and `_MetallicSmoothness` stay empty.
- Because the FBX materials are read-only, 5 new assets were created in
  `Assets/Rigs/DonQuixote/Materials/` (`<name>_Occluded.mat`) on
  `Shader Graphs/MRUKOccludedLit` — shader guid verified identical to `Breeze.mat`'s.
  `_Albedo` mapped by material name: `DonB`->body, `DonF`->face, `DonH`->hair,
  `DonW`->weapon; `OL` gets none (it is an outline material in the source, but imports as
  an ordinary cull-Back Lit material, so converting it is harmless).
  `_Color` set to white — the FBX's grey `0.8` would have darkened every texture.
  `_SmoothnessMult = 0.15` because these are flat anime base-colour maps; Breeze's `0.87`
  would read as plastic. Tune this if she looks too matte.
- Assignment is **by original material name, not slot index**, so slot order cannot be got
  wrong: `Don.002` (SkinnedMeshRenderer) has 5 slots `[DonB, DonW, DonH, DonF, OL]` and
  `Circle` (MeshRenderer) has 2 `[DonW, OL]` — 7 slots swapped in total.
- Built to `Builds/SnackClubHaven-step6.apk`, keeping earlier APKs installable. The other 8 rigs are **out of scope** (step 8
cut 2026-11-14) — only Don needs this material.

## Not covered by this doc

- System-level compositor occlusion — was "untested, deliberately left off"; now simply
  **unreachable**, the field is gone in SDK 209 (see step 1). The shader path is the only
  path.
- Hand occlusion (`_removeHands`) — left at default (`0`), not exercised.
- Everything else in the former `Unity-MRUtilityKitSample` working-tree changes
  (Android Gradle Plugin bump to 8.10.0, misc URP/ProjectSettings churn) — SDK-upgrade
  noise unrelated to occlusion, not specific to this doc's topic.
