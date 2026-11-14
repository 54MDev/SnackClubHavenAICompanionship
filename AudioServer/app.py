import asyncio
import base64
import io
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import av
import numpy as np
import soundfile as sf
import torch

if os.name == 'nt':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# CUDA optimize maybe
torch.set_grad_enabled(False)
if torch.cuda.is_available():
    torch.backends.cudnn.benchmark = True

ROOT = Path(__file__).resolve().parent
RVC = Path(os.environ.get('RVC_DIR', ROOT / 'RVC')).expanduser().resolve()
_PYTHON_NAME = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
_PYTHON_CANDIDATES = (
    ROOT / '.venv' / _PYTHON_NAME,
    RVC / '.venv' / _PYTHON_NAME,
)
PYTHON = Path(os.environ.get('RVC_PYTHON', next(
    (str(path) for path in _PYTHON_CANDIDATES if path.is_file()),
    str(_PYTHON_CANDIDATES[0]),
))).expanduser().resolve()

MODELS = ROOT / 'models'
OUTPUTS = ROOT / 'outputs'
OUTPUTS.mkdir(exist_ok=True)
LOCK = threading.Lock()
LOG_LOCK = threading.Lock()

DEFAULT_OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://172.16.1.52:11434')
DEFAULT_OLLAMA_MODEL = 'huihui_ai/qwen3.5-abliterated:2b'
DEFAULT_SYSTEM_PROMPT = (
    # this for hatsune miku can probably be prompt engineered for whatever
    'You are Hatsune Miku! You are cheerful, sweet, enthusiastic, and speak as the famous digital vocaloid pop star. '
    'Keep your replies concise, energetic, and natural for speech (usually 1-3 sentences).'
)

# Configure environment variables required by RVC
os.environ['weight_root'] = str(MODELS)
os.environ['rmvpe_root'] = str(RVC / 'assets' / 'rmvpe')
os.environ['index_root'] = str(RVC / 'logs')
os.environ['outside_index_root'] = str(RVC / 'assets' / 'indices')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

if str(RVC) not in sys.path:
    sys.path.insert(0, str(RVC))

_VC_ENGINE = None
_CURRENT_MODEL_FILE = None


def get_vram_str():
    if torch.cuda.is_available():
        res = torch.cuda.memory_reserved(0) / (1024 * 1024)
        total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
        return f"{res:.0f}MB / {total:.0f}MB"
    return "CPU"


def cleanup_memory():
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def log_info(ip, method, path, status=200):
    with LOG_LOCK:
        ts = time.strftime('%H:%M:%S')
        print(f"\033[90m[{ts}]\033[0m \033[36mℹ\033[0m [{ip}] {method} {path} -> \033[32m{status}\033[0m", flush=True)


def log_request_start(ip, method, path, prompt=None, config=None):
    with LOG_LOCK:
        ts = time.strftime('%H:%M:%S')
        print(f"\n\033[90m[{ts}]\033[0m \033[36;1m▶ [{ip}] {method} {path}\033[0m", flush=True)
        if prompt:
            preview = prompt.replace('\n', ' ')
            if len(preview) > 85:
                preview = preview[:82] + '...'
            print(f"  \033[90m├ Prompt: \033[0m\033[1m\"{preview}\"\033[0m", flush=True)
        if config:
            items = " | ".join(f"\033[90m{k}:\033[0m {v}" for k, v in config.items())
            print(f"  \033[90m├ Config: \033[0m{items}", flush=True)


def log_sentence_chunk(idx, text, tts_time, rvc_time, audio_sec):
    with LOG_LOCK:
        total_time = tts_time + rvc_time
        speed_x = audio_sec / max(total_time, 0.001)
        rtf = total_time / max(audio_sec, 0.001)
        preview = text.replace('\n', ' ').strip()
        if len(preview) > 60:
            preview = preview[:57] + '...'
        print(f"  \033[90m├ [Chunk {idx}]\033[0m \"{preview}\"", flush=True)
        print(f"  \033[90m│   └─ TTS:\033[0m {tts_time*1000:.0f}ms \033[90m| RVC:\033[0m {rvc_time*1000:.0f}ms \033[90m| Audio:\033[0m {audio_sec:.2f}s \033[90m| Speed:\033[0m \033[32;1m{speed_x:.1f}x\033[0m \033[90m(RTF: {rtf:.2f})\033[0m", flush=True)


def log_request_finish(total_audio, elapsed_time, chunk_count=None, tokens=None):
    with LOG_LOCK:
        speed_x = total_audio / max(elapsed_time, 0.001) if total_audio > 0 else 0
        rtf = elapsed_time / max(total_audio, 0.001) if total_audio > 0 else 0
        stats = []
        if tokens is not None:
            stats.append(f"{tokens} tokens")
        if chunk_count is not None:
            stats.append(f"{chunk_count} chunks")
        stats.append(f"Audio: \033[1m{total_audio:.2f}s\033[0m")
        stats.append(f"Time: \033[1m{elapsed_time:.2f}s\033[0m")
        stats.append(f"Speed: \033[32;1m{speed_x:.1f}x realtime\033[0m\033[90m (RTF: {rtf:.2f})\033[0m")
        stats.append(f"VRAM: \033[35m{get_vram_str()}\033[0m")
        print(f"  \033[32;1m└ [Done]\033[0m {' | '.join(stats)}\n", flush=True)


def log_request_abort(reason="Client disconnected"):
    with LOG_LOCK:
        print(f"  \033[33;1m└ [Aborted]\033[0m {reason} | VRAM: \033[35m{get_vram_str()}\033[0m\n", flush=True)



def make_wav_header(sample_rate=40000, channels=1, bits_per_sample=16, total_bytes=0x7FFFFFF0):
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    header = bytearray()
    header.extend(b'RIFF')
    header.extend((total_bytes + 36).to_bytes(4, 'little'))
    header.extend(b'WAVEfmt ')
    header.extend((16).to_bytes(4, 'little'))
    header.extend((1).to_bytes(2, 'little'))  # PCM
    header.extend(channels.to_bytes(2, 'little'))
    header.extend(sample_rate.to_bytes(4, 'little'))
    header.extend(byte_rate.to_bytes(4, 'little'))
    header.extend(block_align.to_bytes(2, 'little'))
    header.extend(bits_per_sample.to_bytes(2, 'little'))
    header.extend(b'data')
    header.extend(total_bytes.to_bytes(4, 'little'))
    return bytes(header)


def wav_bytes_from_pcm(pcm_bytes, sample_rate=40000):
    """Create a standalone complete WAV file from PCM16 bytes."""
    header = make_wav_header(sample_rate=sample_rate, channels=1, bits_per_sample=16, total_bytes=len(pcm_bytes))
    return header + pcm_bytes


def choices():
    return {
        'models': [str(p.relative_to(ROOT)) for p in sorted(MODELS.rglob('*.pth'))],
        'indexes': [str(p.relative_to(ROOT)) for p in sorted(MODELS.rglob('*.index'))],
    }


def model_path(value, suffix):
    p = (ROOT / str(value)).resolve()
    if not p.is_relative_to(MODELS.resolve()) or p.suffix.lower() != suffix or not p.is_file():
        raise ValueError(f'Select a valid {suffix} file from the models folder.')
    return p


def number(data, key, minimum, maximum, integer=False):
    value = data.get(key)
    if isinstance(value, bool):
        raise ValueError(f'Invalid {key}.')
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid {key}.')
    if not minimum <= value <= maximum or (integer and not value.is_integer()):
        raise ValueError(f'{key} must be between {minimum} and {maximum}.')
    return int(value) if integer else value


def get_vc_engine(model_target=None):
    """Keep VC, HuBERT, RMVPE, and voice model persistently resident in GPU memory."""
    global _VC_ENGINE, _CURRENT_MODEL_FILE
    orig_cwd = os.getcwd()
    try:
        os.chdir(RVC)
        if _VC_ENGINE is None:
            from configs.config import Config
            from infer.vc.modules import VC
            from infer.vc.utils import load_hubert

            print('\033[90m[RVC Engine]\033[0m Initializing PyTorch CUDA inference engine...', flush=True)
            cfg = Config()
            vc = VC(cfg)
            vc.hubert_model = load_hubert(cfg)
            _VC_ENGINE = vc
            print(f'\033[90m[RVC Engine]\033[0m Engine ready on \033[32m{cfg.device}\033[0m (fp16={cfg.is_half}) | VRAM: \033[35m{get_vram_str()}\033[0m', flush=True)

        if model_target:
            model_name = Path(model_target).name
            if model_name != _CURRENT_MODEL_FILE:
                # Release previous model if switching to prevent VRAM bloat
                if hasattr(_VC_ENGINE, 'net_g') and _VC_ENGINE.net_g is not None:
                    del _VC_ENGINE.net_g
                    _VC_ENGINE.net_g = None
                    cleanup_memory()

                print(f'\033[90m[RVC Engine]\033[0m Loading voice model: \033[1m{model_name}\033[0m...', flush=True)
                _VC_ENGINE.get_vc(model_name)
                _CURRENT_MODEL_FILE = model_name
                print(f'\033[90m[RVC Engine]\033[0m Model {model_name} cached in VRAM (\033[35m{get_vram_str()}\033[0m).', flush=True)

        # Pre-cache RMVPE pitch detection model
        if _VC_ENGINE.pipeline is not None and not hasattr(_VC_ENGINE.pipeline, 'model_rmvpe'):
            rmvpe_pt = os.path.join(os.environ['rmvpe_root'], 'rmvpe.pt')
            if os.path.isfile(rmvpe_pt):
                from infer.rmvpe import RMVPE
                _VC_ENGINE.pipeline.model_rmvpe = RMVPE(
                    rmvpe_pt,
                    is_half=_VC_ENGINE.config.is_half,
                    device=_VC_ENGINE.config.device,
                )

        return _VC_ENGINE
    finally:
        os.chdir(orig_cwd)


async def tts_to_16k_pcm(text, voice='en-US-AnaNeural', rate=0, tts_pitch=0):
    """Generate speech with EdgeTTS and resample to 16kHz mono float32 purely in-memory.

    Includes emoji and formatting stripping to eliminate artificial synthesis pauses,
    and guarantees native C PyAV container destruction to prevent leaks.
    """
    import edge_tts
    # Strip emojis, markdown symbols, and bracket tags
    clean_text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    clean_text = re.sub(r'[*#_`~>\[\]()]', '', clean_text).strip()
    if not clean_text:
        return np.array([], dtype=np.float32)

    rate_str = f'{rate:+d}%'
    pitch_str = f'{tts_pitch:+d}Hz'
    comm = edge_tts.Communicate(clean_text, voice, rate=rate_str, pitch=pitch_str)
    mp3_chunks = []
    async for chunk in comm.stream():
        if chunk['type'] == 'audio':
            mp3_chunks.append(chunk['data'])

    if not mp3_chunks:
        return np.array([], dtype=np.float32)

    mp3_bytes = b''.join(mp3_chunks)
    container = av.open(io.BytesIO(mp3_bytes))
    try:
        resampler = av.AudioResampler(format='fltp', layout='mono', rate=16000)
        frames = []
        for frame in container.decode(audio=0):
            for r_frame in resampler.resample(frame):
                frames.append(r_frame.to_ndarray())

        if not frames:
            return np.array([], dtype=np.float32)

        return np.concatenate(frames, axis=1).squeeze(0)
    finally:
        container.close()


def convert_16k_to_miku(vc, audio_16k, pitch=2, method='rmvpe', index_str='', index_rate=0.7, rms=1.0, protect=0.33):
    if len(audio_16k) == 0:
        return vc.tgt_sr, b''

    # Amplitude normalization
    audio_max = np.abs(audio_16k).max() / 0.95
    if audio_max > 1:
        audio_16k = audio_16k / audio_max

    times = [0, 0, 0]
    with LOCK:
        with torch.inference_mode():
            opt = vc.pipeline.pipeline(
                vc.hubert_model,
                vc.net_g,
                0,
                audio_16k,
                times,
                pitch,
                method,
                index_str,
                index_rate,
                vc.if_f0,
                vc.tgt_sr,
                0,
                rms,
                vc.version,
                protect,
            )

    pcm_int16 = (opt * 32767).clip(-32768, 32767).astype(np.int16)
    return vc.tgt_sr, pcm_int16.tobytes()


def stream_ollama(prompt, system_prompt=DEFAULT_SYSTEM_PROMPT, ollama_url=DEFAULT_OLLAMA_URL, ollama_model=DEFAULT_OLLAMA_MODEL):
    """Stream response tokens from Ollama with thinking explicitly disabled."""
    endpoint = f'{ollama_url.rstrip("/")}/api/generate'
    payload = {
        'model': ollama_model,
        'prompt': prompt,
        'system': system_prompt,
        'stream': True,
        'think': False,  # Explicitly disable thinking mode
        'options': {
            'temperature': 0.7,
        },
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            in_think = False
            for line in resp:
                if not line.strip():
                    continue
                data = json.loads(line.decode('utf-8'))
                chunk = data.get('response', '')
                if not chunk:
                    continue

                # Filter out any <think>...</think> tags if model leaks them
                if '<think>' in chunk:
                    in_think = True
                    chunk = chunk.split('<think>')[0]
                if '</think>' in chunk:
                    in_think = False
                    chunk = chunk.split('</think>')[-1]
                if in_think:
                    continue

                if chunk:
                    yield chunk

                if data.get('done', False):
                    break
    except Exception as exc:
        print(f'\033[31m[Ollama Stream Error] {exc}\033[0m', file=sys.stderr, flush=True)
        yield f' [Error connecting to Ollama: {exc}]'


def sentence_generator(token_gen):
    buffer = ''
    for token in token_gen:
        buffer += token
        m = re.search(r'([.!?\n]+)\s+', buffer)
        if m:
            split_point = m.end()
            sentence = buffer[:split_point].strip()
            buffer = buffer[split_point:]
            if sentence:
                yield sentence
        elif len(buffer.split()) > 14 and re.search(r'([,;:—]+)\s+', buffer):
            m = re.search(r'([,;:—]+)\s+', buffer)
            split_point = m.end()
            sentence = buffer[:split_point].strip()
            buffer = buffer[split_point:]
            if sentence:
                yield sentence

    if buffer.strip():
        yield buffer.strip()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        """Suppress default HTTP log messages to preserve structured terminal logging."""
        pass

    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_cors_headers()
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=200):
        self.send_bytes(json.dumps(obj).encode(), 'application/json; charset=utf-8', status)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        client_ip = self.client_address[0]

        if path == '/':
            log_info(client_ip, 'GET', '/')
            self.send_bytes((ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        elif path == '/api/models':
            log_info(client_ip, 'GET', '/api/models')
            self.send_json(choices())
        elif path == '/api/ollama_models':
            log_info(client_ip, 'GET', '/api/ollama_models')
            self.handle_ollama_models(url.query)
        elif path in ('/api/stream', '/api/stream_audio'):
            params = parse_qs(url.query)
            data = {k: v[0] for k, v in params.items()}
            self.handle_raw_audio_stream(data)
        elif re.fullmatch(r'/audio/miku-[0-9a-f]{32}\.wav', path):
            file = OUTPUTS / Path(path).name
            if file.is_file():
                log_info(client_ip, 'GET', path)
                self.send_bytes(file.read_bytes(), 'audio/wav')
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        if path not in ('/api/generate', '/api/chat_stream', '/api/stream', '/api/stream_audio'):
            self.send_error(404)
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
            data = json.loads(self.rfile.read(length)) if length > 0 else {}
        except Exception:
            data = {}

        if path == '/api/generate':
            self.handle_legacy_generate(data)
        elif path == '/api/chat_stream':
            self.handle_chat_sse_stream(data)
        elif path in ('/api/stream', '/api/stream_audio'):
            self.handle_raw_audio_stream(data)

    def handle_ollama_models(self, query):
        """Fetch models from the Ollama server."""
        params = parse_qs(query)
        ollama_url = params.get('url', [DEFAULT_OLLAMA_URL])[0].rstrip('/')
        endpoint = f'{ollama_url}/api/tags'
        try:
            req = urllib.request.Request(endpoint, headers={'User-Agent': 'MikuTTS/2.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                model_names = [m['name'] for m in data.get('models', [])]
                self.send_json({'models': model_names, 'url': ollama_url})
        except Exception as exc:
            self.send_json({'models': [DEFAULT_OLLAMA_MODEL], 'error': str(exc), 'url': ollama_url})

    def handle_chat_sse_stream(self, data):
        """Pipelined SSE stream delivering real-time text tokens and gapless buffered audio chunks."""
        req_start_time = time.time()
        client_ip = self.client_address[0]
        prompt = str(data.get('prompt', '')).strip()
        if not prompt:
            self.send_json({'error': 'Enter a message or prompt.'}, 400)
            return

        ollama_url = str(data.get('ollama_url', DEFAULT_OLLAMA_URL)).strip()
        ollama_model = str(data.get('ollama_model', DEFAULT_OLLAMA_MODEL)).strip()
        system_prompt = str(data.get('system_prompt', DEFAULT_SYSTEM_PROMPT)).strip()

        voice = str(data.get('voice', 'en-US-AnaNeural')).strip()
        pitch = int(data.get('pitch', 2))
        method = str(data.get('method', 'rmvpe'))
        index_rate = float(data.get('index_rate', 0.7))
        protect = float(data.get('protect', 0.33))
        rms = float(data.get('rms', 1.0))

        # Model and index resolution
        model_name = data.get('model')
        if not model_name:
            available_models = choices()['models']
            model_name = available_models[0] if available_models else 'infamous_miku_v2.pth'
        model_name = Path(model_name).name

        index_name = data.get('index')
        if not index_name:
            available_indexes = choices()['indexes']
            index_name = available_indexes[0] if available_indexes else ''
        index_path = str((ROOT / index_name).resolve()) if index_name and index_rate > 0 else ''

        log_request_start(
            client_ip, 'POST', '/api/chat_stream',
            prompt=prompt,
            config={
                'voice': voice,
                'pitch': f'{pitch:+d}',
                'method': method,
                'index': index_rate,
                'model': model_name,
                'llm': ollama_model,
            }
        )

        vc = get_vc_engine(model_name)

        # Set up SSE headers
        self.send_response(200)
        self.send_cors_headers()
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        sse_lock = threading.Lock()

        def send_sse(event, payload):
            with sse_lock:
                try:
                    msg = f'event: {event}\ndata: {json.dumps(payload)}\n\n'.encode('utf-8')
                    self.wfile.write(msg)
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError):
                    return False

        # Flow: Ollama -> sentence_q -> TTS Prefetcher -> tts_audio_q -> GPU RVC -> Client
        sentence_q = queue.Queue(maxsize=12)
        tts_audio_q = queue.Queue(maxsize=4)
        stop_event = threading.Event()
        token_count = [0]
        first_token_time = [None]

        def ollama_worker():
            try:
                tokens = stream_ollama(prompt, system_prompt, ollama_url, ollama_model)
                buffered_text = ''
                for token in tokens:
                    if stop_event.is_set():
                        break
                    token_count[0] += 1
                    if first_token_time[0] is None:
                        first_token_time[0] = time.time() - req_start_time

                    send_sse('text', {'token': token})
                    buffered_text += token

                    m = re.search(r'([.!?\n]+)\s+', buffered_text)
                    if m:
                        idx = m.end()
                        s = buffered_text[:idx].strip()
                        buffered_text = buffered_text[idx:]
                        if s:
                            sentence_q.put(s)
                    elif len(buffered_text.split()) > 14 and re.search(r'([,;:—]+)\s+', buffered_text):
                        m = re.search(r'([,;:—]+)\s+', buffered_text)
                        idx = m.end()
                        s = buffered_text[:idx].strip()
                        buffered_text = buffered_text[idx:]
                        if s:
                            sentence_q.put(s)

                if buffered_text.strip() and not stop_event.is_set():
                    sentence_q.put(buffered_text.strip())
            finally:
                sentence_q.put(None)  # Sentinel

        def tts_prefetch_worker():
            try:
                while not stop_event.is_set():
                    sentence = sentence_q.get()
                    if sentence is None:
                        break
                    t0 = time.time()
                    try:
                        audio_16k = asyncio.run(tts_to_16k_pcm(sentence, voice=voice))
                        tts_dur = time.time() - t0
                        tts_audio_q.put((sentence, audio_16k, tts_dur))
                    except Exception as err:
                        print(f'\033[31m[TTS Prefetch Error] {err}\033[0m', file=sys.stderr, flush=True)
                        tts_audio_q.put((sentence, np.array([], dtype=np.float32), 0.0))
            finally:
                tts_audio_q.put(None)

        t_ollama = threading.Thread(target=ollama_worker, daemon=True)
        t_tts = threading.Thread(target=tts_prefetch_worker, daemon=True)
        t_ollama.start()
        t_tts.start()

        full_text = []
        chunk_idx = 0
        total_audio_sec = 0.0
        aborted = False

        try:
            while True:
                item = tts_audio_q.get()
                if item is None:
                    break

                sentence, audio_16k, tts_dur = item
                if stop_event.is_set():
                    break

                full_text.append(sentence)
                chunk_idx += 1

                if len(audio_16k) == 0:
                    continue

                # Run GPU RVC Inference
                t_rvc0 = time.time()
                try:
                    tgt_sr, pcm_bytes = convert_16k_to_miku(
                        vc,
                        audio_16k,
                        pitch=pitch,
                        method=method,
                        index_str=index_path,
                        index_rate=index_rate,
                        rms=rms,
                        protect=protect,
                    )
                    rvc_dur = time.time() - t_rvc0
                    duration = (len(pcm_bytes) // 2) / tgt_sr
                    total_audio_sec += duration

                    # Send audio SSE event
                    wav_data = wav_bytes_from_pcm(pcm_bytes, tgt_sr)
                    b64_audio = base64.b64encode(wav_data).decode('ascii')
                    ok = send_sse('audio', {'audio': b64_audio, 'duration': duration, 'sentence': sentence})
                    if not ok:
                        aborted = True
                        stop_event.set()
                        break

                    log_sentence_chunk(chunk_idx, sentence, tts_dur, rvc_dur, duration)
                except Exception as exc:
                    print(f'\033[31m[Conversion error] {exc}\033[0m', file=sys.stderr, flush=True)

            if not aborted:
                send_sse('done', {'text': ' '.join(full_text)})
                elapsed = time.time() - req_start_time
                log_request_finish(total_audio_sec, elapsed, chunk_count=chunk_idx, tokens=token_count[0])
            else:
                log_request_abort('Client disconnected')
        except Exception as exc:
            stop_event.set()
            log_request_abort(f'Error: {exc}')
        finally:
            stop_event.set()
            cleanup_memory()

    def handle_raw_audio_stream(self, data):
        req_start_time = time.time()
        client_ip = self.client_address[0]
        prompt = data.get('prompt') or data.get('text', '')
        if not prompt:
            self.send_json({'error': 'Specify prompt or text.'}, 400)
            return

        use_ollama = str(data.get('ollama', 'true')).lower() in ('true', '1', 'yes')
        voice = str(data.get('voice', 'en-US-AnaNeural'))
        pitch = int(data.get('pitch', 2))
        method = str(data.get('method', 'rmvpe'))
        index_rate = float(data.get('index_rate', 0.7))

        model_name = data.get('model')
        if not model_name:
            available = choices()['models']
            model_name = available[0] if available else 'infamous_miku_v2.pth'
        model_name = Path(model_name).name

        index_name = data.get('index')
        if not index_name:
            available_idx = choices()['indexes']
            index_name = available_idx[0] if available_idx else ''
        index_path = str((ROOT / index_name).resolve()) if index_name and index_rate > 0 else ''

        log_request_start(
            client_ip, 'GET/POST', '/api/stream',
            prompt=prompt,
            config={
                'ollama': use_ollama,
                'voice': voice,
                'pitch': f'{pitch:+d}',
                'method': method,
                'model': model_name,
            }
        )

        vc = get_vc_engine(model_name)
        tgt_sr = vc.tgt_sr

        # Chunked HTTP response
        self.send_response(200)
        self.send_cors_headers()
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Transfer-Encoding', 'chunked')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()

        def write_chunk(chunk_bytes):
            if not chunk_bytes:
                return True
            try:
                self.wfile.write(f'{len(chunk_bytes):X}\r\n'.encode('ascii'))
                self.wfile.write(chunk_bytes)
                self.wfile.write(b'\r\n')
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False

        # Send initial streaming WAV header
        wav_hdr = make_wav_header(sample_rate=tgt_sr, channels=1, bits_per_sample=16, total_bytes=0x7FFFFFF0)
        if not write_chunk(wav_hdr):
            log_request_abort('Client disconnected on header')
            return

        sentence_q = queue.Queue(maxsize=10)
        audio_queue = queue.Queue(maxsize=6)
        stop_worker = threading.Event()

        def sentence_producer():
            try:
                if use_ollama:
                    ollama_url = str(data.get('ollama_url', DEFAULT_OLLAMA_URL))
                    ollama_model = str(data.get('ollama_model', DEFAULT_OLLAMA_MODEL))
                    tokens = stream_ollama(prompt, DEFAULT_SYSTEM_PROMPT, ollama_url, ollama_model)
                    for s in sentence_generator(tokens):
                        if stop_worker.is_set():
                            break
                        sentence_q.put(s)
                else:
                    sentence_q.put(prompt)
            finally:
                sentence_q.put(None)

        # TTS Prefetcher + RVC Pipeline
        def audio_synthesizer():
            chunk_num = 0
            try:
                while not stop_worker.is_set():
                    s = sentence_q.get()
                    if s is None:
                        break
                    t0 = time.time()
                    try:
                        audio_16k = asyncio.run(tts_to_16k_pcm(s, voice=voice))
                        tts_dur = time.time() - t0
                        if len(audio_16k) > 0:
                            t_rvc = time.time()
                            _, pcm_bytes = convert_16k_to_miku(
                                vc,
                                audio_16k,
                                pitch=pitch,
                                method=method,
                                index_str=index_path,
                                index_rate=index_rate,
                            )
                            rvc_dur = time.time() - t_rvc
                            if pcm_bytes:
                                chunk_num += 1
                                duration = (len(pcm_bytes) // 2) / tgt_sr
                                log_sentence_chunk(chunk_num, s, tts_dur, rvc_dur, duration)
                                audio_queue.put((pcm_bytes, duration))
                    except Exception as err:
                        print(f'\033[31m[Stream audio err] {err}\033[0m', file=sys.stderr, flush=True)
            finally:
                audio_queue.put(None)

        t_prod = threading.Thread(target=sentence_producer, daemon=True)
        t_synth = threading.Thread(target=audio_synthesizer, daemon=True)
        t_prod.start()
        t_synth.start()

        total_audio_sec = 0.0
        total_bytes = len(wav_hdr)
        aborted = False

        first_item = audio_queue.get()
        if first_item is not None:
            pcm_bytes, duration = first_item
            total_audio_sec += duration
            total_bytes += len(pcm_bytes)
            if not write_chunk(pcm_bytes):
                aborted = True
                stop_worker.set()

            while not aborted:
                item = audio_queue.get()
                if item is None:
                    break
                pcm_bytes, duration = item
                total_audio_sec += duration
                total_bytes += len(pcm_bytes)
                if not write_chunk(pcm_bytes):
                    aborted = True
                    stop_worker.set()
                    break

        # Terminate chunked stream
        try:
            self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()
        except Exception:
            pass

        stop_worker.set()
        elapsed = time.time() - req_start_time
        if not aborted:
            log_request_finish(total_audio_sec, elapsed, chunk_count=None, tokens=None)
        else:
            log_request_abort('Client disconnected')
        cleanup_memory()

    def handle_legacy_generate(self, data):
        req_start_time = time.time()
        client_ip = self.client_address[0]
        text = data.get('text', '').strip()
        if not text or len(text) > 5000:
            raise ValueError('Enter between 1 and 5,000 characters of text.')
        voice = str(data.get('voice', 'en-US-AnaNeural')).strip()
        model = model_path(data.get('model', ''), '.pth')
        index = model_path(data['index'], '.index') if data.get('index') else None
        rate = number(data, 'rate', -50, 100, True)
        tts_pitch = number(data, 'tts_pitch', -50, 50, True)
        pitch = number(data, 'pitch', -24, 24, True)
        index_rate = number(data, 'index_rate', 0, 1)
        protect = number(data, 'protect', 0, 0.5)
        rms = number(data, 'rms', 0, 1)
        method = data.get('method', 'rmvpe')

        log_request_start(
            client_ip, 'POST', '/api/generate',
            prompt=text,
            config={'voice': voice, 'pitch': f'{pitch:+d}', 'model': model.name}
        )

        vc = get_vc_engine(model.name)
        index_str = str(index) if index and index_rate > 0 else ''

        output = OUTPUTS / f'miku-{uuid.uuid4().hex}.wav'
        t_tts = time.time()
        audio_16k = asyncio.run(tts_to_16k_pcm(text, voice=voice, rate=rate, tts_pitch=tts_pitch))
        tts_dur = time.time() - t_tts

        t_rvc = time.time()
        tgt_sr, pcm_bytes = convert_16k_to_miku(
            vc,
            audio_16k,
            pitch=pitch,
            method=method,
            index_str=index_str,
            index_rate=index_rate,
            rms=rms,
            protect=protect,
        )
        rvc_dur = time.time() - t_rvc
        wav_data = wav_bytes_from_pcm(pcm_bytes, tgt_sr)
        output.write_bytes(wav_data)

        duration = (len(pcm_bytes) // 2) / tgt_sr
        elapsed = time.time() - req_start_time
        log_sentence_chunk(1, text, tts_dur, rvc_dur, duration)
        log_request_finish(duration, elapsed, chunk_count=1)

        self.send_json({'audio': '/audio/' + output.name, 'filename': output.name})
        cleanup_memory()


# Local Info
def get_local_ip():
    """Discover host's primary local network IP address."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'


def is_port_in_use(port):
    """Check if port is already bound by another process."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return False
        except OSError:
            return True


def main():
    port = int(os.environ.get('PORT', '8765'))

    # Ensure no dupes on the same port
    if is_port_in_use(port):
        print(f"\n\033[31;1m[ERROR] Port {port} is already in use by another process!\033[0m", flush=True)
        print("Please terminate any running server instances before starting.", flush=True)
        sys.exit(1)

    # Warm up default model and pitch inference on startup so the first request is instantaneous
    model_choices = choices()['models']
    if model_choices:
        try:
            default_model = Path(model_choices[0]).name
            vc = get_vc_engine(default_model)
            # Warm up RMVPE and net_g with a synthetic sine wave tone to activate the auto kernel compilation
            t = np.linspace(0, 0.5, 8000, dtype=np.float32)
            warmup_pcm = (np.sin(2 * np.pi * 440 * t) * 0.1).astype(np.float32)
            convert_16k_to_miku(vc, warmup_pcm, pitch=2, method='rmvpe')
            cleanup_memory()
            print('\033[90m[RVC Engine]\033[0m Warmup complete. Engine ready for instant response.', flush=True)
        except Exception as exc:
            print(f'\033[33m[Warmup Warning] Could not preload default model: {exc}\033[0m', flush=True)

    ThreadingHTTPServer.allow_reuse_address = True
    ThreadingHTTPServer.daemon_threads = True
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    local_ip = get_local_ip()

    print('=====================================================================', flush=True)
    print(f'🎤 \033[36;1mTTS Realtime AI Server Ready!\033[0m', flush=True)
    print(f'  - Local UI:    \033[32mhttp://127.0.0.1:{server.server_port}\033[0m', flush=True)
    print(f'  - Network UI:  \033[32mhttp://{local_ip}:{server.server_port}\033[0m', flush=True)
    print(f'  - Ollama LLM:  \033[33m{DEFAULT_OLLAMA_URL}\033[0m ({DEFAULT_OLLAMA_MODEL})', flush=True)
    print(f'  - GPU Memory:  \033[35m{get_vram_str()}\033[0m', flush=True)
    print('=====================================================================\n', flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[33mShutting down server...\033[0m", flush=True)
    finally:
        server.server_close()
        cleanup_memory()


if __name__ == '__main__':
    main()
