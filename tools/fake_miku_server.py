"""Fake Miku server: stands in for the real Ollama+TTS machine so miku_client's SSE
streaming (text tokens + base64 WAV audio chunks) can be tested without it.

Usage:
    python fake_miku_server.py             # serves on 127.0.0.1:8765
    python miku_client.py "hi" --server http://127.0.0.1:8765 --no-play
"""
import argparse
import base64
import io
import json
import struct
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer


def silent_wav(seconds: float = 0.2, sample_rate: int = 16000) -> bytes:
    """A tiny valid mono 16-bit WAV, silent, so soundfile/sounddevice can actually play it."""
    n = int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # no Content-Length needed; client reads until connection close

    def _sse(self, event: str, data: dict):
        self.wfile.write(f"event: {event}\n".encode())
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        prompt = body.get("prompt", "")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        reply = f"echo: {prompt}"
        for word in reply.split(" "):
            self._sse("text", {"token": word + " "})
        self._sse("audio", {
            "audio": base64.b64encode(silent_wav()).decode(),
            "duration": 0.2,
            "sentence": reply,
        })
        self._sse("done", {})

    def log_message(self, fmt, *args):
        print("[fake_miku_server]", fmt % args)


def serve(host: str = "127.0.0.1", port: int = 8765) -> HTTPServer:
    server = HTTPServer((host, port), Handler)
    print(f"fake_miku_server listening on http://{host}:{server.server_port}")
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port).serve_forever()
