"""Push-to-talk voice input -> Whisper transcription -> Miku TTS client.

Button is the Quest controller's A/X (OVRInput.Button.One) via Assets/Scripts/VoicePTT.cs,
which sends a 1-byte UDP signal here (1 = held down, 0 = released) on --controller-port.
The clip is transcribed locally with Whisper, and the resulting text is handed to
miku_client.send_and_stream, which sends it to the second machine for the LLM response +
synced TTS playback (CLAUDE.md step 7: LLM dialogue input half).

Needs: pip install openai-whisper sounddevice soundfile  (+ ffmpeg on PATH, for Whisper)

Usage:
    python voice_input.py
    python voice_input.py --server http://172.16.1.27:8765 --whisper-model base
"""
import argparse
import socket

import numpy as np
import sounddevice as sd
import whisper

from miku_client import DEFAULT_HEADSET_HOST, DEFAULT_SERVER_URL, send_and_stream

SAMPLE_RATE = 16000  # Whisper's native input rate
CONTROLLER_PORT = 5007


def frames_to_audio(frames: list) -> np.ndarray:
    """Concatenate recorded mic chunks into one mono float32 array."""
    if not frames:
        return np.zeros(0, dtype="float32")
    return np.concatenate(frames, axis=0).flatten()


def wait_for_byte(sock: socket.socket, expected: int) -> None:
    """Block until a VoicePTT datagram carrying `expected` (0 or 1) arrives.

    Polls with a timeout (rather than a bare blocking recv) so Ctrl+C still works on
    Windows, where a blocking socket call can swallow SIGINT until it next returns.
    """
    while True:
        try:
            data, _ = sock.recvfrom(1)
        except socket.timeout:
            continue
        if data and data[0] == expected:
            return


def find_oculus_mic():
    """Pick the Quest headset's mic by name, so recording doesn't silently fall back to
    whatever sounddevice's system default input happens to be (on this machine: a SteelSeries
    Sonar virtual device, not the headset -- the actual cause of "nothing was heard")."""
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and "oculus" in d["name"].lower():
            return i
    return None


def record_until_button_release(sock: socket.socket, sample_rate: int = SAMPLE_RATE,
                                 mic_device=None) -> np.ndarray:
    """Record mic audio from one controller button-press to the release (the "button")."""
    frames = []

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    print("Hold A/X on the controller to start recording...")
    wait_for_byte(sock, 1)
    print("Recording... release A/X to stop.")
    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32",
                         device=mic_device, callback=callback):
        wait_for_byte(sock, 0)
    print("Recording stopped.")
    return frames_to_audio(frames)


def transcribe(audio: np.ndarray, model) -> str:
    return model.transcribe(audio, fp16=False)["text"].strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", default=DEFAULT_SERVER_URL, help="Miku server URL")
    parser.add_argument("--whisper-model", default="base", help="Whisper model size (default: base)")
    parser.add_argument("--device", default="cpu",
                         help="Device for Whisper (default: cpu, since the GPU is usually busy "
                              "running motionbricks' pose inference at the same time)")
    parser.add_argument("--voice", default="en-US-AnaNeural")
    parser.add_argument("--controller-port", type=int, default=CONTROLLER_PORT,
                         help="UDP port VoicePTT.cs sends button state to (default: %(default)s)")
    parser.add_argument("--headset", metavar="IP", default=DEFAULT_HEADSET_HOST,
                         help="Send the reply audio to the Quest headset instead of playing it "
                              "on this PC. Defaults to $MIKU_HEADSET_HOST.")
    parser.add_argument("--mic-device", default=None,
                         help="sounddevice input device name/index to record from (default: "
                              "auto-pick the Oculus headset mic; run `python -m sounddevice` "
                              "to list devices if auto-pick guesses wrong)")
    args = parser.parse_args()

    mic_device = args.mic_device
    if mic_device is None:
        mic_device = find_oculus_mic()
        if mic_device is None:
            print("WARNING: no Oculus mic found; falling back to the system default input "
                  "device, which is probably NOT the headset.")
    print(f"Recording from: {sd.query_devices(mic_device)['name'] if mic_device is not None else '(system default)'}")

    print(f"Loading Whisper model '{args.whisper_model}'...")
    model = whisper.load_model(args.whisper_model, device=args.device)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.controller_port))
    sock.settimeout(1.0)
    print(f"Listening for controller button on UDP :{args.controller_port}")

    while True:
        try:
            audio = record_until_button_release(sock, mic_device=mic_device)
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        if audio.size == 0:
            continue

        text = transcribe(audio, model)
        if not text:
            print("(heard nothing, try again)")
            continue
        print(f"You said: {text}")
        send_and_stream(text, server_url=args.server, voice=args.voice, headset_host=args.headset)


if __name__ == "__main__":
    main()
