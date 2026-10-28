import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('update_core', Path(__file__).parents[1] / 'scripts/update_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = {'app.py': b'new application', 'web/app.js': b'new web'}
        self.downloads = []
        (self.root / 'app.py').write_bytes(b'old app')
        self.manifest = {'schema': 1, 'version': '0.2.0', 'files': [dict(path=name,
            size=len(content), sha256=hashlib.sha256(content).hexdigest(),
            previous_sha256=[hashlib.sha256(b'old app').hexdigest()],
            url='https://github.com/Serkom2000/EasyPhoto/releases/download/v0.2.0/' + name.replace('/', '--'))
            for name, content in self.payload.items()]}

    def fetch(self, item, target):
        self.downloads.append(item['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.payload[item['path']])

    def updater(self):
        return core.Updater(self.root, fetch=self.fetch)

    def test_only_changed_files_downloaded_and_user_files_preserved(self):
        for name in ('models/checkpoints/mine.safetensors', 'data/settings.json', 'data/outputs/mine.png'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'precious')
        self.assertEqual(self.updater().apply(self.manifest)['changed'], 2)
        self.assertEqual(self.updater().apply(self.manifest)['changed'], 0)
        self.assertEqual(len(self.downloads), 2)
        self.assertEqual((self.root / 'models/checkpoints/mine.safetensors').read_bytes(), b'precious')
        self.assertEqual((self.root / 'data/settings.json').read_bytes(), b'precious')
        self.assertEqual((self.root / 'data/outputs/mine.png').read_bytes(), b'precious')

    def test_bad_download_changes_nothing(self):
        self.payload['web/app.js'] = b'corruption'
        with self.assertRaises(ValueError):
            self.updater().apply(self.manifest)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old app')
        self.assertFalse((self.root / 'web/app.js').exists())

    def test_local_edits_are_not_overwritten(self):
        (self.root / 'app.py').write_bytes(b'my custom version')
        with self.assertRaisesRegex(ValueError, 'вручную'):
            self.updater().apply(self.manifest)
        self.assertEqual(self.downloads, [])

    def test_file_created_during_download_is_preserved(self):
        def fetch(item, target):
            self.fetch(item, target)
            if item['path'] == 'web/app.js':
                local = self.root / 'web/app.js'
                local.parent.mkdir(parents=True)
                local.write_bytes(b'local file created during download')
        with self.assertRaises(ValueError):
            core.Updater(self.root, fetch=fetch).apply(self.manifest)
        self.assertEqual((self.root / 'web/app.js').read_bytes(), b'local file created during download')
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old app')

    def test_conflict_mid_commit_restores_only_files_already_touched(self):
        original = core.os.replace
        def inject(source, target):
            result = original(source, target)
            if Path(target) == self.root / 'app.py' and 'staged' in Path(source).parts:
                local = self.root / 'web/app.js'
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(b'local concurrent change')
            return result
        with patch.object(core.os, 'replace', side_effect=inject):
            with self.assertRaises(ValueError):
                self.updater().apply(self.manifest)
        self.assertEqual((self.root / 'web/app.js').read_bytes(), b'local concurrent change')
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old app')

    def test_failure_during_apply_rolls_back(self):
        original = core.os.replace
        def fail(source, target):
            if Path(source).parts[-3:] == ('staged', 'web', 'app.js'):
                raise OSError('simulated disk error')
            return original(source, target)
        with patch.object(core.os, 'replace', side_effect=fail):
            with self.assertRaises(OSError):
                self.updater().apply(self.manifest)
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old app')
        self.assertFalse((self.root / 'web/app.js').exists())
        self.assertFalse((self.root / 'data/update-receipt.json').exists())

    def test_crash_recovery_restores_previous_files(self):
        transaction = self.root / 'data/updates' / ('a' * 32)
        (transaction / 'backup').mkdir(parents=True)
        (transaction / 'backup/app.py').write_bytes(b'old app')
        (self.root / 'app.py').write_bytes(b'new application')
        core.write_json(transaction / 'journal.json', {'entries': [{'path': 'app.py',
            'old_sha256': hashlib.sha256(b'old app').hexdigest(),
            'new_sha256': hashlib.sha256(b'new application').hexdigest()}], 'old_receipt': None})
        self.updater().recover()
        self.assertEqual((self.root / 'app.py').read_bytes(), b'old app')

    def test_unsafe_manifest_paths_rejected(self):
        for name in ('../app.py', 'models/checkpoints/mine.safetensors', 'data/settings.json', 'APP.PY', 'app.py:stream'):
            with self.subTest(name=name):
                self.manifest['files'][0]['path'] = name
                with self.assertRaises(ValueError):
                    self.updater().apply(self.manifest)

    def test_foreign_download_url_rejected(self):
        self.manifest['files'][0]['url'] = 'https://example.com/app.py'
        with self.assertRaises(ValueError):
            self.updater().apply(self.manifest)

    def test_second_updater_cannot_acquire_lock(self):
        with core.install_lock(self.root):
            with self.assertRaises((ValueError, OSError)):
                self.updater().apply(self.manifest)

    def test_downgrade_rejected(self):
        self.updater().apply(self.manifest)
        self.manifest['version'] = '0.1.0'
        with self.assertRaisesRegex(ValueError, 'Понижение'):
            self.updater().apply(self.manifest)

    def test_tampered_recovery_path_rejected(self):
        transaction = self.root / 'data/updates' / ('b' * 32)
        core.write_json(transaction / 'journal.json', {'entries': [{'path': '../outside', 'new_sha256': '0' * 64}]})
        with self.assertRaises(ValueError):
            self.updater().recover()

    def test_linked_application_directory_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.root / 'web'
        try:
            if core.os.name == 'nt':
                import _winapi
                _winapi.CreateJunction(str(outside), str(link))
            else:
                link.symlink_to(outside, target_is_directory=True)
        except (OSError, AttributeError):
            self.skipTest('Directory links are unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'reparse|Ссылки'):
            self.updater().apply(self.manifest)
        self.assertFalse((outside / 'app.js').exists())


if __name__ == '__main__':
    unittest.main()
