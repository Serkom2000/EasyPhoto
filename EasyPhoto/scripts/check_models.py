"""Verify bundled weights before creating an offline distribution."""
import hashlib
import json
from pathlib import Path
import sys


def check_models(root):
    manifest = json.loads((root / 'models' / 'manifest.json').read_text('utf-8'))
    errors = []
    for item in manifest.values():
        path = root / 'models' / 'checkpoints' / item['filename']
        if not path.is_file():
            errors.append(f"Missing model: {item['filename']}")
            continue
        if path.stat().st_size != item['size']:
            errors.append(f"Wrong file size: {item['filename']}")
            continue
        digest = hashlib.sha256()
        with path.open('rb') as source:
            while chunk := source.read(4 * 1024**2):
                digest.update(chunk)
        if digest.hexdigest() != item['sha256']:
            errors.append(f"SHA256 mismatch: {item['filename']}")
        else:
            print(f"Verified: {item['filename']}", flush=True)
    return errors


if __name__ == '__main__':
    failures = check_models(Path(__file__).resolve().parent.parent)
    for failure in failures:
        print(failure, file=sys.stderr)
    sys.exit(1 if failures else 0)
