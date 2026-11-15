Real-time AI voice conversation and TTS system that turns text into vocaloid style speech using Edge TTS, RVC neural voice conversion, and local Ollama LLMs. Models remain resident in GPU VRAM for real-time sub-second generation and gapless audio streaming.

Windows Command Prompt:

```bat
run.bat
```

Open **http://127.0.0.1:8765** in your browser.

---

## API Reference

### 1. Raw Audio Stream (`/api/stream`)
Stream live converted audio directly into any audio player or script:

```bash
# Stream Miku AI response from Ollama
curl -N "http://127.0.0.1:8765/api/stream?prompt=Hello+Miku" | ffplay -nodisp -autoexit -

# Speak custom text without Ollama
curl -N "http://127.0.0.1:8765/api/stream?prompt=Welcome+to+the+concert!&ollama=false" | mpv -
```

**Query Params:**
- `prompt` (string, required): The prompt or text.
- `ollama` (bool, default `true`): Set to `false` to convert the prompt text directly without calling Ollama.
- `ollama_url` (string, default `http://172.16.1.52:11434`): The Ollama server endpoint.
- `ollama_model` (string, default `huihui_ai/qwen3.5-abliterated:2b`): The Ollama model to use.
- `voice` (string, default `en-US-AnaNeural`): Edge TTS voice.
- `pitch` (int, default `2`): Pitch shift in semitones.
- `method` (string, default `rmvpe`): `rmvpe` or `pm`.
- `index_rate` (float, default `0.70`): Feature retrieval strength.

### 2. Realtime SSE Chat Stream (`/api/chat_stream`)
Send a JSON payload to receive an SSE event stream of tokens and audio chunks:

```bash
curl -N -X POST http://127.0.0.1:8765/api/chat_stream \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Tell me a joke!"}'
```

**Events received:**
- `event: text`: `{"token": "Why "}`
- `event: audio`: `{"audio": "<base64_wav>", "duration": 2.1, "sentence": "..."}`
- `event: done`: `{"text": "..."}`

## Setup on Windows

Install **64-bit Python 3.12** and FFmpeg. Make sure `git` and `ffmpeg` are available on PATH; reopen your terminal after installation. Alternatively, an existing RVC installation can have `ffmpeg.exe` in its root folder.

In Command Prompt:

```bat
setup.bat
run.bat
```

Setup uses an existing project `.venv` when present. Its CUDA Torch installation is
preserved: the CUDA requirements file intentionally excludes `torch` and `torchaudio`,
so setup does not replace or download another Torch build. The app checks every Python
module required by Edge TTS and RVC before starting a generation and reports all missing
or unloadable dependencies together. Setup also downloads and verifies the local HuBERT
and RMVPE model assets required by inference; generation stops immediately with an asset
error if either asset is missing.

If setup reports a TLS certificate error while downloading from Hugging Face, fix the
machine or corporate proxy certificate trust and run `setup.bat` again. Do not start
inference until setup confirms both model assets.

RVC models (.pth files) and corresponding index files must be added to the models dir.