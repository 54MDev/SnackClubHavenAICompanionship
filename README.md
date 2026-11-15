# Snack Club Haven: AI Companionship

A VR project that bridges real-time human motion generation, room-scanned geometry, and
a custom character rig, all running live on a Quest headset.

The short version: a Python app called motionbricks generates human motion live (it's
driven by an SOMA model), that pose data gets streamed over UDP to a Unity project, and
a custom rig (currently just DonQuixote) gets retargeted and driven by it frame by
frame. The character can be steered by pointing a controller at the floor, she avoids
real furniture using the room's scanned NavMesh, and she's occluded correctly by real
world geometry via the Quest's Depth API. There's also a basic LLM voice chat path
(speech in, local Whisper transcription, a chat server, TTS audio out through the
headset speakers).

## Demo

See `docs/media/demo.mov` for a recording of her jogging around a real room, dodging
furniture, and getting occluded behind it correctly.

## How it's put together

- `Rigs/` holds the source character rigs. Only DonQuixote is actually wired up right
  now, the others are just sitting there for later.
- `Assets/`, `Packages/`, `ProjectSettings/` are the actual Unity project (uses Meta's
  MRUK sample as a base). Open this folder in Unity Hub.
- `tools/` has the Python side: the pose sender that talks to motionbricks, and the
  voice/chat scripts.
- `docs/` has notes from earlier debugging sessions, useful if something that used to
  work stops working.
- motionbricks itself lives in a separate sibling repo, this project just talks to it
  over a socket.

## Running it

You need the motionbricks repo checked out next to this one with its own venv set up,
a CUDA GPU, and a Quest headset on the same Wi-Fi network as your PC.

Build and install the APK (from Unity, or just reinstall an existing build in
`Builds/`), then launch it on the headset:

```
adb install -r Builds/SnackClubHaven-voice.apk
adb shell monkey -p com.samples.mruksample -c android.intent.category.LAUNCHER 1
```

Then kick off the pose stream from your PC, pointed at the headset's Wi-Fi IP:

```
cd ../motionbricks
uv run python ../SnackClubHavenAICompanionship/tools/pose_sender_motionbricks.py --host <headset-ip> --duration 45
```

That's it, she should start moving. Point the controller at the floor to steer her
around.

## Status

Everything up through room-geometry avoidance and depth occlusion is working on
device. The voice/dialogue piece currently talks to a local Ollama server
