"""Miku TTS & Realtime AI Voice Client (Standalone LAN Client).

Single-file client to run on this machine or ANY OTHER DEVICE on the local network.
Exposes functions for sending prompts, streaming text tokens from Ollama,
and streaming/playing back real-time synthesized voice audio.

Usage as a Script:
    python miku_client.py "Hello Miku, what can you do?"
    python miku_client.py "Tell me a joke!" --server http://172.16.1.27:8765
    python miku_client.py --interactive

Usage as a Module:
    from miku_client import send_and_stream, stream_audio, MikuClient

    # Simple one-liner: sends text, prints tokens, and plays audio live
    send_and_stream("Hello from my laptop!")

    # Generator: yields raw audio WAV bytes as they are synthesized
    for chunk in stream_audio("Sing me a song!", use_ollama=True):
        process_audio(chunk)
"""

import argparse
import base64
import io
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Callable, Iterator, Optional, Tuple

# Default server address (LAN IP of the Miku server machine)
# Can be overridden via MIKU_SERVER_URL env var or --server CLI flag
DEFAULT_SERVER_URL = os.environ.get("MIKU_SERVER_URL", "http://172.16.1.27:8765")

# Quest headset running Assets/Scripts/AudioPlaybackReceiver.cs, listening for WAV chunks
# (CLAUDE.md step 7: "stream audio to the Quest app"). Unset = play on this PC instead.
DEFAULT_HEADSET_HOST = os.environ.get("MIKU_HEADSET_HOST") or None
HEADSET_AUDIO_PORT = 5008

# Optional audio playback libraries
_HAS_SOUNDDEVICE = False
try:
    import sounddevice as sd
    import soundfile as sf
    _HAS_SOUNDDEVICE = True
except ImportError:
    _HAS_SOUNDDEVICE = False


# ==============================================================================
# Client Class
# ==============================================================================

class MikuClient:
    """Interface to connect to the Miku TTS and Ollama server over the network."""

    def __init__(self, base_url: str = DEFAULT_SERVER_URL):
        """Initialize with the server's base URL (e.g. 'http://172.16.1.27:8765')."""
        self.base_url = base_url.rstrip("/")

    def stream_chat(
        self,
        prompt: str,
        on_text: Optional[Callable[[str], None]] = None,
        on_audio: Optional[Callable[[bytes, float, str], None]] = None,
        voice: str = "en-US-AnaNeural",
        pitch: int = 2,
        index_rate: float = 0.70,
        method: str = "rmvpe",
        ollama_model: str = "huihui_ai/qwen3.5-abliterated:2b",
        system_prompt: Optional[str] = None,
        timeout: int = 120,
    ) -> str:
        """Send prompt to Ollama with 'think: false' and stream text and audio chunks via SSE.

        Args:
            prompt: User message or question for Miku.
            on_text: Callback receiving each text token as it arrives: fn(token: str).
            on_audio: Callback receiving each converted audio sentence chunk:
                      fn(wav_bytes: bytes, duration: float, sentence: str).
            voice: Edge TTS base voice (default 'en-US-AnaNeural' for anime tone).
            pitch: Semitone pitch shift (default +2).
            index_rate: RVC feature index strength (default 0.70).
            method: Pitch detection algorithm ('rmvpe' recommended).
            ollama_model: Ollama model tag.
            system_prompt: Optional custom persona.
            timeout: Network timeout in seconds.

        Returns:
            The complete response text from Miku.
        """
        url = f"{self.base_url}/api/chat_stream"
        payload = {
            "prompt": prompt,
            "voice": voice,
            "pitch": pitch,
            "index_rate": index_rate,
            "method": method,
            "ollama_model": ollama_model,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "MikuLANClient/2.0"},
        )

        full_text = []
        with urllib.request.urlopen(req, timeout=timeout) as response:
            event_type = "message"
            data_lines = []
            for line_bytes in response:
                line = line_bytes.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        data_lines = []
                        try:
                            data = json.loads(data_str)
                            if event_type == "text":
                                token = data.get("token", "")
                                full_text.append(token)
                                if on_text:
                                    on_text(token)
                            elif event_type == "audio":
                                if on_audio:
                                    wav_bytes = base64.b64decode(data.get("audio", ""))
                                    duration = float(data.get("duration", 0.0))
                                    sentence = data.get("sentence", "")
                                    on_audio(wav_bytes, duration, sentence)
                            elif event_type == "done":
                                break
                        except Exception:
                            pass
                        event_type = "message"
                elif line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())

        return "".join(full_text)

    def stream_audio(
        self,
        prompt: str,
        use_ollama: bool = True,
        voice: str = "en-US-AnaNeural",
        pitch: int = 2,
        index_rate: float = 0.70,
        method: str = "rmvpe",
        chunk_size: int = 4096,
        timeout: int = 120,
    ) -> Iterator[bytes]:
        """Stream continuous raw audio (WAV) directly over HTTP chunk by chunk.

        Args:
            prompt: Text to send (if use_ollama=True, sent to LLM; if False, spoken directly).
            use_ollama: Whether to stream through Ollama LLM first.
            voice: Voice ID.
            pitch: Semitones pitch shift.
            index_rate: RVC index strength.
            method: Pitch algorithm ('rmvpe' or 'pm').
            chunk_size: Bytes to read per yield.
            timeout: Network timeout.

        Yields:
            WAV file bytes as they arrive from the server.
        """
        params = {
            "prompt": prompt,
            "ollama": "true" if use_ollama else "false",
            "voice": voice,
            "pitch": str(pitch),
            "index_rate": str(index_rate),
            "method": method,
        }
        url = f"{self.base_url}/api/stream?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "MikuLANClient/2.0"})

        with urllib.request.urlopen(req, timeout=timeout) as response:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def speak_to_file(
        self,
        text: str,
        output_path: str,
        use_ollama: bool = False,
        voice: str = "en-US-AnaNeural",
        pitch: int = 2,
        index_rate: float = 0.70,
    ) -> str:
        """Synthesize text and save directly to a WAV file."""
        with open(output_path, "wb") as f:
            for chunk in self.stream_audio(text, use_ollama=use_ollama, voice=voice, pitch=pitch, index_rate=index_rate):
                f.write(chunk)
        return output_path


# ==============================================================================
# Standalone Convenience Functions (Ready for direct import & use)
# ==============================================================================

def send_and_stream(
    prompt: str,
    server_url: str = DEFAULT_SERVER_URL,
    voice: str = "en-US-AnaNeural",
    pitch: int = 2,
    index_rate: float = 0.70,
    play_audio: bool = True,
    save_to: Optional[str] = None,
    on_token: Optional[Callable[[str], None]] = None,
    headset_host: Optional[str] = DEFAULT_HEADSET_HOST,
) -> Tuple[str, int]:
    """Send a line of text, stream back the LLM response tokens, and play or save the audio.

    Args:
        prompt: The text prompt to send.
        server_url: URL of the Miku TTS server on the network.
        voice: Edge TTS base voice.
        pitch: Semitone shift (+2 recommended for Miku tone).
        index_rate: Index rate (0.70 recommended).
        play_audio: If True and headset_host is not set, plays each audio chunk on this
            machine's speakers as soon as it arrives.
        save_to: Optional filepath to save the aggregated WAV audio.
        on_token: Optional callback for each streamed token (defaults to printing to stdout).
        headset_host: If set, send each audio chunk to the Quest headset's
            AudioPlaybackReceiver instead of playing it locally, so playback comes out of the
            headset speakers the character is standing in front of. Defaults to
            MIKU_HEADSET_HOST.

    Returns:
        Tuple of (complete_text_response, total_audio_bytes_received).
    """
    client = MikuClient(base_url=server_url)

    if on_token is None:
        def default_on_token(token: str):
            print(token, end="", flush=True)
        on_token = default_on_token

    audio_chunks = []
    total_audio_bytes = 0

    def handle_audio(wav_bytes: bytes, duration: float, sentence: str):
        nonlocal total_audio_bytes
        total_audio_bytes += len(wav_bytes)
        audio_chunks.append(wav_bytes)

        if headset_host:
            _send_wav_to_headset(wav_bytes, headset_host)
        elif play_audio:
            _play_wav_bytes(wav_bytes)

    text_response = client.stream_chat(
        prompt=prompt,
        on_text=on_token,
        on_audio=handle_audio,
        voice=voice,
        pitch=pitch,
        index_rate=index_rate,
    )

    if save_to and audio_chunks:
        # Combine all sentence WAVs into one audio file
        _combine_and_save_wavs(audio_chunks, save_to)

    return text_response, total_audio_bytes


def stream_audio(
    prompt: str,
    server_url: str = DEFAULT_SERVER_URL,
    use_ollama: bool = True,
    voice: str = "en-US-AnaNeural",
    pitch: int = 2,
    index_rate: float = 0.70,
) -> Iterator[bytes]:
    """Stream raw WAV audio chunks directly over HTTP.

    Example:
        for chunk in stream_audio("Hello world!"):
            process(chunk)
    """
    client = MikuClient(base_url=server_url)
    return client.stream_audio(
        prompt=prompt,
        use_ollama=use_ollama,
        voice=voice,
        pitch=pitch,
        index_rate=index_rate,
    )


# ==============================================================================
# Internal Audio Helpers
# ==============================================================================

def _send_wav_to_headset(wav_bytes: bytes, host: str, port: int = HEADSET_AUDIO_PORT):
    """Send one WAV chunk to AudioPlaybackReceiver.cs over a short-lived TCP connection.

    Length-prefixed (4-byte big-endian uint32 + payload), not UDP: a sentence clip can run
    well past UDP's 64 KB datagram limit, and a dropped chunk would garble speech.
    One connection per chunk, not a persistent socket: chunks arrive seconds apart (TTS
    pace), so reconnecting is cheap and needs no retry/keepalive logic.
    """
    try:
        with socket.create_connection((host, port), timeout=5) as s:
            s.sendall(struct.pack(">I", len(wav_bytes)) + wav_bytes)
    except OSError as e:
        print(f"[miku_client] could not reach headset at {host}:{port}: {e}", file=sys.stderr)


def _play_wav_bytes(wav_bytes: bytes):
    """Play WAV audio bytes using sounddevice, ffplay, or fallback."""
    if _HAS_SOUNDDEVICE:
        try:
            data, sr = sf.read(io.BytesIO(wav_bytes))
            sd.play(data, sr)
            sd.wait()
            return
        except Exception:
            pass

    # Fallback to ffplay subprocess if available
    if shutil.which("ffplay"):
        try:
            p = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"],
                stdin=subprocess.PIPE,
            )
            p.communicate(input=wav_bytes)
            return
        except Exception:
            pass


def _combine_and_save_wavs(wav_byte_list: list, output_path: str):
    """Combine multiple standard WAV chunks into a single valid WAV file."""
    if not wav_byte_list:
        return

    # If soundfile is available, join clean PCM samples
    if _HAS_SOUNDDEVICE:
        try:
            all_samples = []
            sr = 48000
            for b in wav_byte_list:
                data, sr = sf.read(io.BytesIO(b))
                all_samples.append(data)
            import numpy as np
            combined = np.concatenate(all_samples, axis=0)
            sf.write(output_path, combined, sr)
            return
        except Exception:
            pass

    # Fallback: extract PCM data past the 44-byte WAV header and write a valid header
    all_pcm = bytearray()
    sr = 48000
    for b in wav_byte_list:
        if len(b) > 44 and b[:4] == b"RIFF":
            all_pcm.extend(b[44:])
        else:
            all_pcm.extend(b)

    import struct
    total_data_len = len(all_pcm)
    hdr = (
        b"RIFF" +
        struct.pack("<I", total_data_len + 36) +
        b"WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00" +
        struct.pack("<II", sr, sr * 2) +
        b"\x02\x00\x10\x00data" +
        struct.pack("<I", total_data_len)
    )
    with open(output_path, "wb") as f:
        f.write(hdr)
        f.write(all_pcm)


# ==============================================================================
# Command Line Interface (Runs on this machine or any other network device)
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Miku TTS & Realtime AI Voice Client (Network Ready)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Hello! Can you hear me clearly across the network?",
        help="Text line or question to send to Miku (default: 'Hello! Can you hear me clearly across the network?')",
    )
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER_URL,
        help=f"Miku server URL (default: {DEFAULT_SERVER_URL})",
    )
    parser.add_argument(
        "--voice",
        default="en-US-AnaNeural",
        help="Edge TTS voice (default: en-US-AnaNeural)",
    )
    parser.add_argument(
        "--pitch",
        type=int,
        default=2,
        help="Pitch shift in semitones (default: 2)",
    )
    parser.add_argument(
        "--save",
        metavar="FILE.wav",
        default=None,
        help="Save the received audio response to a WAV file",
    )
    parser.add_argument(
        "--no-play",
        action="store_true",
        help="Disable live audio playback through speakers",
    )
    parser.add_argument(
        "--headset",
        metavar="IP",
        default=DEFAULT_HEADSET_HOST,
        help="Send audio to the Quest headset's AudioPlaybackReceiver (port "
             f"{HEADSET_AUDIO_PORT}) instead of playing locally. Defaults to $MIKU_HEADSET_HOST.",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Start an interactive chat loop with Miku",
    )

    args = parser.parse_args()

    print("=" * 65)
    print("Miku TTS & Realtime AI Voice Network Client")
    print(f"Server Target: {args.server}")
    if args.headset:
        print(f"Playback:      Quest headset at {args.headset}:{HEADSET_AUDIO_PORT}")
    else:
        print(f"Playback:      {'Disabled (--no-play)' if args.no_play else ('sounddevice' if _HAS_SOUNDDEVICE else ('ffplay' if shutil.which('ffplay') else 'None (install sounddevice or ffplay)'))}")
    if args.save:
        print(f"Output File:   {args.save}")
    print("=" * 65)

    def do_turn(user_text: str, out_file: Optional[str] = None):
        print(f"\nUser: {user_text}")
        print("Miku: ", end="", flush=True)
        t0 = time.time()
        _, audio_bytes = send_and_stream(
            prompt=user_text,
            server_url=args.server,
            voice=args.voice,
            pitch=args.pitch,
            play_audio=(not args.no_play),
            save_to=out_file,
            headset_host=args.headset,
        )
        elapsed = time.time() - t0
        print(f"\n[Completed in {elapsed:.2f}s | {audio_bytes / 1024:.1f} KB audio received]")

    if args.interactive:
        print("\nEntering interactive mode. Type your message and press Enter (or 'quit'/'exit' to stop).\n")
        while True:
            try:
                line = input("\nYou: ").strip()
                if not line:
                    continue
                if line.lower() in ("quit", "exit", "q"):
                    print("Goodbye!")
                    break
                do_turn(line)
            except (KeyboardInterrupt, EOFError):
                print("\nExiting.")
                break
    else:
        do_turn(args.prompt, out_file=args.save)


if __name__ == "__main__":
    main()
