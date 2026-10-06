"""Portable setup, startup and model download commands (Python 3.11)."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
MODELS = ('tiny', 'base', 'small', 'medium', 'large-v3', 'large-v3-turbo')


def check_dependencies():
    missing = []
    for line in (ROOT / 'requirements.txt').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, version = line.split('==')
        try:
            if importlib.metadata.version(name) != version:
                missing.append(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        raise RuntimeError('Run install first. Missing or different versions: ' + ', '.join(missing))


def install():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Install Python 3.11 from python.org, then run install again.')
    if not PYTHON.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    for folder in ('models', 'temp', '.cache/pip'):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    subprocess.run([str(PYTHON), '-m', 'pip', 'install', '--cache-dir', str(ROOT / '.cache/pip'),
                    '-r', str(ROOT / 'requirements.txt')], check=True)
    subprocess.run([str(PYTHON), '-m', 'pip', 'check'], check=True)
    target = ROOT / '.env'
    if not target.exists():
        shutil.copyfile(ROOT / '.env.example', target)
        target.chmod(0o600)
    print('Installed. Run start.command (Mac) or start.bat (Windows).')


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            return json.load(response).get('application') == 'subtitle-editor'
    except (OSError, ValueError):
        return False


def start(port, open_browser=True):
    check_dependencies()
    if health(port):
        print(f'Subtitle Editor is already running: http://127.0.0.1:{port}')
        if open_browser:
            webbrowser.open(f'http://127.0.0.1:{port}')
        return
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError(f'Port {port} is occupied. Use --port with another port.') from None
    if open_browser:
        def browse_when_ready():
            for _ in range(60):
                if health(port):
                    webbrowser.open(f'http://127.0.0.1:{port}')
                    return
                time.sleep(0.5)
        threading.Thread(target=browse_when_ready, daemon=True).start()
    sys.path.insert(0, str(ROOT))
    import uvicorn
    print(f'Open http://127.0.0.1:{port}. Stop with Ctrl+C in this window.', flush=True)
    uvicorn.run('app:app', host='127.0.0.1', port=port)


def download(name):
    check_dependencies()
    if not name:
        print('Local models (larger models need more disk space and CPU time):')
        for i, model in enumerate(MODELS, 1):
            print(f'{i}. {model}')
        choice = input('Number, or Enter to cancel: ').strip()
        if not choice:
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(MODELS):
            raise RuntimeError('Invalid model number.')
        name = MODELS[int(choice) - 1]
    destination = ROOT / 'models' / name
    if (destination / 'model.bin').exists() and (destination / 'config.json').exists():
        print(f'Model already installed: {destination}')
        return
    os.environ.setdefault('HF_HOME', str(ROOT / '.cache/huggingface'))
    from faster_whisper.utils import download_model
    staging = ROOT / 'models' / '.downloads' / name
    staging.mkdir(parents=True, exist_ok=True)
    download_model(name, output_dir=str(staging))
    if not all((staging / file).exists() for file in ('config.json', 'model.bin', 'tokenizer.json')):
        raise RuntimeError('Incomplete model download. Run this command again to resume.')
    if destination.exists():
        raise RuntimeError(f'Destination exists: {destination}. Inspect it before retrying.')
    staging.rename(destination)
    print(f'Model installed: {destination}. Select it in the application settings.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'start', 'download-model', 'check'))
    parser.add_argument('--port', type=int, default=5002)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--model', choices=MODELS)
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        if args.action == 'install':
            install()
        elif args.action == 'start':
            if not 1 <= args.port <= 65535:
                raise RuntimeError('Port must be between 1 and 65535.')
            start(args.port, not args.no_browser)
        elif args.action == 'download-model':
            download(args.model)
        else:
            check_dependencies()
            print('Dependencies OK.')
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
