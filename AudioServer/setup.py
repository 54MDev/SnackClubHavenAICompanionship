#!/usr/bin/env python3
"""Install the RVC pipeline without replacing an existing CUDA Torch install."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
RVC = ROOT / 'RVC'
WINDOWS = os.name == 'nt'


def run(*args, cwd=ROOT):
    print('> ' + subprocess.list2cmdline([str(arg) for arg in args]), flush=True)
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True, env=env)


def main():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('RVC requires Python 3.12. Run this setup with Python 3.12.')
    if not shutil.which('git'):
        raise RuntimeError('Git was not found on PATH. Install Git and reopen your terminal.')
    local_ffmpeg = RVC / ('ffmpeg.exe' if WINDOWS else 'ffmpeg')
    if not shutil.which('ffmpeg') and not local_ffmpeg.is_file():
        raise RuntimeError('FFmpeg was not found. Install FFmpeg and add it to PATH, or put ffmpeg.exe in the RVC folder on Windows.')
    if not RVC.exists():
        run('git', 'clone', 'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git', RVC)
    if not (RVC / 'infer' / 'cli.py').is_file():
        raise RuntimeError('RVC exists but infer/cli.py is missing. Check the RVC installation.')
    env_dir = ROOT / '.venv'
    python = env_dir / ('Scripts/python.exe' if WINDOWS else 'bin/python')
    hf = env_dir / ('Scripts/hf.exe' if WINDOWS else 'bin/hf')
    if not python.is_file():
        run(sys.executable, '-m', 'venv', env_dir)
    run(python, '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel', cwd=RVC)
    # This file deliberately excludes torch/torchaudio. Keep the existing
    # CUDA build (for example torch 2.12.x+cu126) selected by this environment.
    run(python, '-m', 'pip', 'install', '-r', 'requirments_cu128_py312.txt', cwd=RVC)
    run(python, '-m', 'pip', 'install', 'edge-tts', 'huggingface_hub', cwd=RVC)
    run(hf, 'download', 'lj1995/VoiceConversionWebUI', '--revision', 'main', '--include', 'hubert_base/*', '--local-dir', RVC / 'assets')
    run(hf, 'download', 'lj1995/VoiceConversionWebUI', 'rmvpe.pt', '--revision', 'hf down', '--local-dir', RVC / 'assets' / 'rmvpe')
    if not (RVC / 'assets' / 'hubert_base' / 'config.json').is_file():
        raise RuntimeError('HuBERT download completed without assets/hubert_base/config.json.')
    if not (RVC / 'assets' / 'rmvpe' / 'rmvpe.pt').is_file():
        raise RuntimeError('RMVPE download completed without assets/rmvpe/rmvpe.pt.')
    downloads = ROOT / 'downloads'
    models = ROOT / 'models' / 'miku'
    downloads.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    run(hf, 'download', 'M5-Dev/Miku_RVC_Model', 'MikuDiva.zip', '--local-dir', downloads)
    with zipfile.ZipFile(downloads / 'MikuDiva.zip') as archive:
        # Extract only inference assets, and discard archive directory names.
        for member in archive.infolist():
            name = member.filename.replace('\\', '/').split('/')[-1]
            if not member.is_dir() and Path(name).suffix.lower() in ('.pth', '.index'):
                target = models / name
                if target.exists():
                    print(f'Keeping existing {target}', flush=True)
                    continue
                with archive.open(member) as source, target.open('wb') as dest:
                    shutil.copyfileobj(source, dest)
    if not any(path.is_file() and path.suffix.lower() == '.pth' for path in models.rglob('*')):
        raise RuntimeError('The model archive did not contain a .pth file. Check the downloaded archive.')
    print('\nSetup complete. Run ' + ('py -3.12 app.py' if WINDOWS else 'python3 app.py'))
    print('Open http://127.0.0.1:8765')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print(f'\nSetup failed: {exc}', file=sys.stderr)
        sys.exit(1)
