# Overview — motionbricks bridge

## 1. Larger scope (full pipeline)

```mermaid
flowchart LR
    MRUK[Meta Quest MRUK<br/>room-scan geometry] --> OBS[Obstacles / targets]
    CTRL[Controller pointing] --> OBS
    OBS --> MB[motionbricks<br/>live motion generation]
    MB --> SOMA[SOMA pose<br/>pred_global_motions]
    SOMA --> RIG[Custom rig in Unity<br/>Quest, Humanoid retarget]
    LLM[LLM dialogue call] --> VOICE[TTS + lipsync]
    VOICE --> RIG
    RIG --> STREAM[Live VR stream]
```

## 2. Backend (live retargeting data flow)

```mermaid
flowchart LR
    subgraph Python process
        MB2[motionbricks runtime<br/>app/runtime, imgui]
        MB2 --> ENC[Encode frame:<br/>root pos + per-joint quat]
    end
    ENC -- UDP 30Hz --> RECV[PoseReceiver.cs]
    subgraph Unity process
        RECV --> MAP[SOMA joint name →<br/>HumanBodyBones table]
        MAP --> BONE[animator.GetBoneTransform<br/>set local rotation]
        BONE --> RIG2[Rig renders<br/>cm→m, Y-up]
    end
    RECV -- UDP, reverse --> ENC2[MRUK geometry + controller target]
    ENC2 --> MB2
```

Notes:
- Two separate OS processes, one socket pair, no Blender in the live loop.
- Blender/Rokoko retargeting is offline-only (clip validation before Unity wiring).
