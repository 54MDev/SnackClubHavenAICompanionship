# Step 4 Quest Link test plan — CLOSED 2026-11-14, Link ABANDONED

> **Outcome: step 4 is met, but on-device, not over Quest Link. Do not follow this plan
> to validate anything — Quest Link is a hardware dead end on this machine.**
>
> The working path (build/install/stream commands) is in `CLAUDE.md` step 4 under
> "THE WORKING PATH". On-device result: **30.0 Hz achieved, 2 late frames out of 1350**,
> user in headset: "it works so well and is so smooth." Over Link the same setup
> delivered ~8/s in 1-75 Hz bursts.
>
> **Why Link was abandoned, measured — don't re-litigate:**
> - The cable negotiates **USB 2.0** (`transmission_type: USB2_DISCO` in 53 of 57
>   streaming steps; 81 `usbwatcher_disconnected` events) in
>   `%LOCALAPPDATA%\Oculus\PerfLog_*.json`.
> - Unity submitted **2-8 app fps against 72 presented**, so the compositor reprojected
>   nearly every frame. Reprojection corrects head motion but not *object* motion, which
>   is why the moving characters tore while the static room looked fine.
> - Dropping Standalone quality Ultra -> Medium changed app fps **not at all** — that is
>   what proved render cost was never the bottleneck.
> - Sender alone with Unity idle: **30.0 Hz, 1 frame late**. motionbricks was never the
>   problem.
> - Link also cost a Unity crash: unplugging/replugging USB while the Editor held the XR
>   session took it down (`mfh264enc.dll` in the faulting module list).
>
> Sections 1-2 below still hold — the rig placement and the Hz counter are part of the
> working on-device build. Sections 3-5 are superseded.

Original intent: closes the one thing step 4 in `CLAUDE.md` still needed — "done when"
asked for the `NavMesh` scene over Quest Link at >=20 Hz, no dropped-frame crash, one full
generated sequence. Everything else in step 4 (retargeting math, jitter fix, scale) was
already visually confirmed in the desktop Editor; this was purely getting that
already-working setup into the real scene and the real headset.

## 1. Add the rig to `NavMesh.unity` — DONE 2026-11-14

`Assets/Scenes/PoseReceiverTest.unity` already had a known-good setup: the `DonQuixote`
GameObject (`DonQuixote.fbx` dragged into the scene directly, not a separate prefab asset)
carrying a `FollowCamera` child (Camera, tag `MainCamera`) and a `PoseReceiver` component
(`port: 5005`, `positionScale: 1`). Moved (not copied) into
`Assets/MRUKSamples/NavMesh/NavMesh.unity` at `(1.5, 0, 0.3)`, next to the existing `Breeze`
NPC so they don't overlap. `FollowCamera` was disabled rather than deleted — `NavMesh.unity`
already has `OVRCameraRig`'s `CenterEyeAnchor`/`LeftEyeAnchor` tagged `MainCamera` for the
headset; a third camera with that tag would compete with them. `PoseReceiver.cs` untouched.

**Check:** `NavMesh.unity`'s hierarchy has `DonQuixote` with `Animator` + `PoseReceiver`
intact, standing on the floor (not floating/buried); only `CenterEyeAnchor`/
`LeftEyeAnchor` are active and tagged `MainCamera`; Unity console has no new
errors/warnings after the move. All confirmed via MCP for Unity on 2026-11-14.

## 2. Add a frames/sec counter to `PoseReceiver.cs`

Nothing currently measures receive rate. In `ReceiveLoop()` (the background thread), count
datagrams and log once a second:

```csharp
int _frameCount;
float _lastLogTime;
...
// inside the while loop, after a successful lock/assign:
_frameCount++;
if (Time.realtimeSinceStartup - _lastLogTime >= 1f)
{
    Debug.Log($"PoseReceiver: {_frameCount} Hz");
    _frameCount = 0;
    _lastLogTime = Time.realtimeSinceStartup;
}
```

`ponytail:` this is a throwaway counter for one manual test, not instrumentation worth
keeping long-term — fine to rip out once step 4 is closed, or leave it, it's one `Debug.Log`.

**Check:** before touching Quest Link, run the existing desktop-Editor setup
(`PoseReceiverTest.unity` + `tools/pose_sender_test.py`) for a few seconds and confirm the
`Hz` log appears in the console at roughly the sender's rate. If it doesn't log at all here,
it won't over Link either — catch that now, not after wrangling the headset.

## 3. Connect Quest Link and enter Play mode — SUPERSEDED (see the banner above)

*Kept only because the passthrough prerequisite below was a real, separately-diagnosed
bug: Link's runtime does not advertise `XR_FB_passthrough` until the desktop-app toggles
are on. On-device that extension is simply present (`Version=5`), so none of this applies
to the working path.*

**Prerequisite (this is what blocked the 2026-11-14 attempt):** in the Meta Quest Link
desktop app → Settings → Beta → turn on **Passthrough over Meta Quest Link** (and
**Spatial Data over Meta Quest Link** under Developer, for MRUK room geometry / Depth API).
Both need Developer mode on the headset. Restart the Link app (and the headset's Link
session) after toggling. Proof it was off: `Editor-prev.log` from that run shows the
runtime advertising `Unavailable OpenXR extension: XR_FB_passthrough` followed by
`Failed to initialize Insight Passthrough ... Error Failure_NotInitialized`. The project
side is correct and was checked field by field (`isInsightPassthroughEnabled: 1`, CenterEye
Solid Color alpha 0, `OVRPassthroughLayer` active, `_insightPassthroughSupport: 2`,
`MetaXRFeature` enabled for Standalone, active OpenXR runtime = Oculus) — don't go
hunting in the scene again.

Headset on, Link (cable or Air Link) connected, Unity's Link status shows connected.
Open `NavMesh.unity`, enter Play mode in the Editor as usual — Link mirrors the rendered
output to the headset, it doesn't change how the Unity process runs.

**Check:** before running any sender, confirm the headset shows the Unity scene (room
passthrough/MRUK geometry, `Breeze` and the now-stationary `DonQuixote` both visible) and
Unity isn't throwing XR/Link errors in the console. If the scene doesn't show up in the
headset yet, pose data arriving later won't fix that — fix Link first.

## 4. Run the real sender, unchanged — SUPERSEDED

*The sender now takes `--host`; on-device it targets the headset's Wi-Fi IP, not loopback.
It also gained wall-clock pacing, which is what fixed the rig's jitter — the loop
previously had no `sleep` at all and emitted frames as fast as the GPU produced them.*

From the sibling `motionbricks` checkout:

```
cd ../motionbricks
uv run python ../SnackClubHavenAICompanionship/tools/pose_sender_motionbricks.py --duration 45
```

Same command as the desktop-Editor test. UDP is loopback either way — Quest Link only
forwards the rendered frame to the headset, the sender has no idea a headset is involved.

**Check:** within the first couple seconds, the Hz log should start and `DonQuixote` should
visibly leave its rest pose. If neither happens within ~5s, stop the sender rather than
waiting out the full 45s — something upstream (sender not finding a GPU/TensorRT plan,
wrong port, scene not in Play mode) is broken and the rest of the run won't tell you more.

## 5. Observe, for the full run — SUPERSEDED

- **In the headset:** rig visibly mirrors the generated motion on the real room floor —
  smooth, not snapping or frozen.
- **In the Editor console:** the Hz log from step 2 should read >=20 for the whole 45s,
  not just at the start.
- **No crash/exception** for the full duration — let it run to completion, don't stop early.

## Done when — MET, via the on-device APK

Original bar: rig in `NavMesh.unity` visibly mirrors live motionbricks motion over Quest
Link, >=20 Hz observed start-to-finish, one full generated sequence, no dropped-frame
crash.

**Met on-device instead, which clears the bar by a wide margin:** 30.0 Hz sustained
(2 late frames in 1350), smooth and visually confirmed in the headset, full 45 s sequence,
no crash. The Link half of the bar is unreachable on this hardware and was dropped
deliberately, not skipped. `CLAUDE.md` step 4 holds the full log.
