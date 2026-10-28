"""Build a small per-file GitHub release and a first-use updater bootstrap."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from update_core import MANAGED, validate_manifest


def main():
    output = Path(sys.argv[1]).absolute()
    output.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT / 'app-version.json').read_text('utf-8'))['version']
    files = []
    for name in sorted(MANAGED):
        source = ROOT / name
        if not source.is_file():
            raise ValueError('Missing release file: ' + name)
        content = source.read_bytes()
        previous = set()
        # Include every historical tracked revision and both newline conventions.
        path = 'EasyPhoto/' + name
        history = subprocess.run(['git', 'log', '--format=%H', '--', path], cwd=ROOT.parent, capture_output=True, text=True, check=True).stdout.splitlines()
        for revision in history:
            old = subprocess.run(['git', 'show', revision + ':' + path], cwd=ROOT.parent, capture_output=True)
            if old.returncode == 0:
                lf = old.stdout.replace(b'\r\n', b'\n')
                for variant in (old.stdout, lf, lf.replace(b'\n', b'\r\n')):
                    previous.add(hashlib.sha256(variant).hexdigest())
        asset = 'app--' + name.replace('/', '--')
        (output / asset).write_bytes(content)
        files.append(dict(path=name, size=len(content), sha256=hashlib.sha256(content).hexdigest(), previous_sha256=sorted(previous),
            url=f'https://github.com/Serkom2000/EasyPhoto/releases/download/v{version}/{asset}'))
    manifest = validate_manifest(dict(schema=1, version=version, files=files))
    (output / 'update-manifest.json').write_text(json.dumps(manifest, indent=2), 'utf-8')
    with zipfile.ZipFile(output / 'EasyPhoto-Updater.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('Updater.exe', 'scripts/update.ps1', 'scripts/update_core.py'):
            archive.write(ROOT / name, name)
        archive.writestr('НАЧАТЬ ЗДЕСЬ.txt', 'Закройте EasyPhoto. Распакуйте эти файлы в установленную папку рядом с EasyPhoto.exe, с заменой файлов. Запустите Updater.exe и нажмите «Проверить обновления». Модели, runtime, фотографии и настройки не скачиваются и не заменяются. После обновления запускайте EasyPhoto обычным ярлыком.\n')
    print(json.dumps({'version': version, 'files': len(files), 'app_bytes': sum(f['size'] for f in files),
        'bootstrap_bytes': (output / 'EasyPhoto-Updater.zip').stat().st_size, 'output': str(output)}))


if __name__ == '__main__':
    main()
