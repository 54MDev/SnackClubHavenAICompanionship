"""Self-check for voice_input's pure logic (no mic/model required). Run: python test_voice_input.py"""
import socket

import numpy as np

from voice_input import frames_to_audio, transcribe, wait_for_byte


def test_frames_to_audio():
    assert frames_to_audio([]).size == 0
    chunks = [np.array([[1.0], [2.0]], dtype="float32"), np.array([[3.0]], dtype="float32")]
    out = frames_to_audio(chunks)
    assert out.tolist() == [1.0, 2.0, 3.0]


def test_transcribe_strips_whitespace():
    class FakeModel:
        def transcribe(self, audio, fp16=False):
            return {"text": "  hello there  "}

    assert transcribe(np.zeros(1), FakeModel()) == "hello there"


def test_wait_for_byte_ignores_wrong_value_and_timeouts():
    # socket.socketpair only supports SOCK_STREAM on Windows, so use real loopback UDP sockets.
    b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    b.bind(("127.0.0.1", 0))
    b.settimeout(0.2)
    a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    a.connect(b.getsockname())

    a.send(bytes([1]))  # wrong value: must be skipped before the right one arrives
    a.send(bytes([0]))
    wait_for_byte(b, 0)
    a.close()
    b.close()


if __name__ == "__main__":
    test_frames_to_audio()
    test_transcribe_strips_whitespace()
    test_wait_for_byte_ignores_wrong_value_and_timeouts()
    print("ok")
