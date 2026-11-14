# Adding depth occlusion to a character

Lets real-world geometry (from the Depth API) occlude a virtual character, e.g. when it walks behind furniture.

1. Make sure the scene has an `EnvironmentDepthManager` component (GameObject named `EnvironmentDepth` in `NavMesh.unity`, `_occlusionShadersMode: SoftOcclusion`). One per scene is enough.
2. Switch the character's material shader to `Assets/MRUKSamples/PassthroughRelighting/Oppy/materials/MRUKOccludedLit.shadergraph`.
3. Re-map textures/values onto that shader's exposed properties:
   - albedo texture → `_Albedo`
   - normal map → `_Normal`
   - metallic/smoothness map → `_MetallicSmoothness`
   - smoothness value → `_SmoothnessMult`
   - metallic value → `_MetallicMult`
   - tint → `_Color`
4. Set `_EnvironmentDepthBias` (~0.09, same as Oppy/Flame/Breeze) to push the occlusion boundary slightly and avoid z-fighting/flicker.

Reference implementation: `Breeze.mat` in this folder.
