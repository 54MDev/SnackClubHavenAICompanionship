"""Self-check for miku_client's SSE streaming, against fake_miku_server (no real Ollama/TTS
machine needed). Run: python test_miku_client.py"""
import threading

from fake_miku_server import serve
from miku_client import send_and_stream


def test_send_and_stream_round_trip():
    server = serve(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        text, audio_bytes = send_and_stream("hello world", server_url=url, play_audio=False)
        assert text.strip() == "echo: hello world", text
        assert audio_bytes > 44  # more than just a WAV header
    finally:
        server.shutdown()


if __name__ == "__main__":
    test_send_and_stream_round_trip()
    print("ok")
