import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('check_models', Path(__file__).resolve().parents[1] / 'scripts' / 'check_models.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'models' / 'checkpoints').mkdir(parents=True)
        self.content = b'a small test model'
        self.path = self.root / 'models' / 'checkpoints' / 'test.safetensors'
        self.manifest = {'test': {'filename': self.path.name, 'size': len(self.content),
                                'sha256': hashlib.sha256(self.content).hexdigest()}}
        (self.root / 'models' / 'manifest.json').write_text(json.dumps(self.manifest), 'utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_bundle_passes(self):
        self.path.write_bytes(self.content)
        self.assertEqual(checker.check_models(self.root), [])

    def test_missing_model_blocks_packaging(self):
        self.assertEqual(checker.check_models(self.root), ['Missing model: test.safetensors'])

    def test_truncated_model_blocks_packaging(self):
        self.path.write_bytes(self.content[:-1])
        self.assertEqual(checker.check_models(self.root), ['Wrong file size: test.safetensors'])

    def test_same_size_corrupt_model_blocks_packaging(self):
        self.path.write_bytes(b'X' + self.content[1:])
        self.assertEqual(checker.check_models(self.root), ['SHA256 mismatch: test.safetensors'])
