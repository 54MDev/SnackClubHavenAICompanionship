# MRUK Depth-API occlusion notes (2026-11-14)

Where this fits in the pipeline (see `CLAUDE.md`): this is the **Quest/MRUK side** —
the piece that owns real-world room geometry. Tested in the sibling repo
`Unity-MRUtilityKitSample`, on the `MRUKSamples/NavMesh` sample scene/character
(`BreezeCharacter`), not in this repo directly — no Unity project lives here, just
rig assets. Recorded here so a future session doesn't have to re-derive it.

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
   - `_systemOcclusionEnabled = 0` — system-level (compositor) occlusion stays off;
     occlusion is instead done per-material in the shader. Don't enable both.
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
4. **`_EnvironmentDepthBias ≈ 0.09`** — pushes the occlusion boundary slightly
   so the real/virtual edge doesn't z-fight/flicker. `0.09` is the value used
   across all three sample characters (Oppy, Flame, Breeze) in this SDK sample —
   treat it as the known-good default, tune per-character only if flicker shows up.
5. Reference material: `Breeze.mat` in
   `Unity-MRUtilityKitSample/Assets/MRUKSamples/NavMesh/BreezeCharacter/` (also
   mirrored as `DepthOcclusion.md` next to it in that repo).

## Implication for the SOMA-driven rigs here

If `DonQuixote`/`Faust`/`KasaneTeto` need to be occluded by real-world geometry
when deployed through MRUK (same room-scan→obstacle pipeline described in
`CLAUDE.md`), each rig's material needs the same treatment: swap to
`MRUKOccludedLit.shadergraph`, re-map its textures per the table above, and set
`_EnvironmentDepthBias`. **Not done yet** — these rigs currently only have
source FBX/textures, no Unity materials, so there's nothing to swap until they're
actually brought into a Unity/MRUK scene.

## Not covered by this doc

- System-level compositor occlusion (`_systemOcclusionEnabled = 1` path) — untested
  here, deliberately left off in favor of the shader path.
- Hand occlusion (`_removeHands`) — left at default (`0`), not exercised.
- Everything else in `Unity-MRUtilityKitSample`'s working tree changes (Android
  Gradle Plugin bump to 8.10.0, misc URP/ProjectSettings churn) — SDK-upgrade
  noise unrelated to occlusion, not worth carrying over here.
