"""Contract tests with a local ComfyUI double; no model or GPU needed."""
import base64
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib import request, error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import zlib

import app


def png(width=1024, height=1024):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x90\xa0\x80' * width) * height)) + chunk(b'IEND', b'')


INFO = {
    'CheckpointLoaderSimple': {'input': {'required': {'ckpt_name': [['sdxl.safetensors']]}}},
    'ControlNetLoader': {'input': {'required': {'control_net_name': [['openpose.safetensors']]}}},
}
JOB_ID = '12345678-abcd-1234-abcd-123456789abc'


class FakeComfy(BaseHTTPRequestHandler):
    graph = None
    completed = False
    fail = False
    uploads = []

    def log_message(self, *args):
        pass

    def send(self, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/object_info':
            return self.send(INFO)
        if self.path == '/system_stats':
            return self.send({'devices': [{'name': 'TEST DEVICE', 'vram_total': 16 * 1024**3}]})
        if self.path == '/queue':
            return self.send({'queue_running': [[1, JOB_ID]], 'queue_pending': []})
        if self.path.startswith('/history/'):
            if self.completed:
                output = {} if self.fail else {'7': {'images': [{'filename': 'test.png', 'subfolder': '', 'type': 'output'}]}}
                return self.send({JOB_ID: {'outputs': output, 'status': {'messages': [['execution_error', {'exception_message': 'out of memory'}]]}}})
            return self.send({})
        if self.path.startswith('/view?'):
            return self.send(png(64, 64))
        self.send({})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        if self.path == '/upload/image':
            type(self).uploads.append(raw)
            return self.send({'name': 'uploaded.png', 'subfolder': ''})
        type(self).graph = json.loads(raw)['prompt']
        self.send({'prompt_id': JOB_ID})


class QuietHandler(app.Handler):
    def log_message(self, *args):
        pass


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comfy = ThreadingHTTPServer(('127.0.0.1', 0), FakeComfy)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        for server in (cls.comfy, cls.server):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.comfy, cls.server):
            server.shutdown()
            server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        for name in ('jobs', 'outputs'):
            (self.data / name).mkdir()
        self.patches = [patch.object(app, 'DATA', self.data), patch.object(app, 'COMFY', f'http://127.0.0.1:{self.comfy.server_port}')]
        for p in self.patches:
            p.start()
        FakeComfy.completed = False
        FakeComfy.fail = False
        FakeComfy.uploads = []
        self.payload = {'prompt': 'A photo of a forest', 'model': 'sdxl.safetensors', 'seed': 123}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def call(self, path, payload=None, token=app.TOKEN, headers=None):
        body = json.dumps(payload).encode() if payload is not None else None
        req = request.Request(f'http://127.0.0.1:{self.server.server_port}' + path, body, {'X-EasyPhoto-Token': token, **(headers or {})})
        try:
            with request.urlopen(req) as response:
                raw = response.read()
                return json.loads(raw) if 'json' in response.headers.get('Content-Type', '') else raw
        except error.HTTPError as exc:
            exc.close()
            raise

    def test_status_and_assets(self):
        state = self.call('/api/status')
        self.assertTrue(state['connected'])
        self.assertEqual(state['models'], ['sdxl.safetensors'])
        self.assertIn(b'EasyPhoto', self.call('/'))
        self.assertIn(b'function', self.call('/app.js'))

    def test_models_are_local_only(self):
        state = self.call('/api/status')
        self.assertNotIn('download', state)
        self.assertEqual(len(state['catalog']), 2)
        self.assertTrue(all('url' not in item for item in state['catalog']))
        with self.assertRaises(error.HTTPError) as caught:
            self.call('/api/download', {'id': 'sdxl'})
        self.assertEqual(caught.exception.code, 404)

    def test_create_to_download_and_persisted_history(self):
        job = self.call('/api/generate', self.payload)
        self.assertEqual(job['seed'], 123)
        self.assertEqual(FakeComfy.graph['5']['inputs']['latent_image'], ['4', 0])
        self.assertEqual(self.call('/api/job/' + job['id'])['state'], 'running')
        FakeComfy.completed = True
        record = self.call('/api/job/' + job['id'])
        self.assertEqual(record['state'], 'done')
        self.assertEqual(self.call(record['images'][0]), png(64, 64))
        self.assertEqual(self.call('/api/history')[0]['state'], 'done')

    def test_masked_edit_uploads_and_preserves_unmasked_pixels(self):
        image = 'data:image/png;base64,' + base64.b64encode(png()).decode()
        self.call('/api/generate', self.payload | {'mode': 'edit', 'image': image, 'mask': image, 'strength': .8})
        graph = FakeComfy.graph
        self.assertEqual(len(FakeComfy.uploads), 2)
        self.assertEqual(graph['4']['class_type'], 'VAEEncodeForInpaint')
        self.assertEqual(graph['9']['inputs']['channel'], 'red')
        self.assertEqual(graph['10']['class_type'], 'ImageCompositeMasked')
        self.assertEqual(graph['7']['inputs']['images'], ['10', 0])
        self.assertEqual(graph['5']['inputs']['denoise'], .8)
        stored = json.loads(next((self.data / 'jobs').glob('*.json')).read_text())
        self.assertNotIn('image', stored)
        self.assertNotIn('mask', stored)

    def test_pose_uses_both_controlled_conditionings(self):
        image = 'data:image/png;base64,' + base64.b64encode(png()).decode()
        self.call('/api/generate', self.payload | {'mode': 'pose', 'image': image, 'controlnet': 'openpose.safetensors'})
        self.assertEqual(FakeComfy.graph['5']['inputs']['positive'], ['10', 0])
        self.assertEqual(FakeComfy.graph['5']['inputs']['negative'], ['10', 1])

    def test_engine_failure_is_reported(self):
        job = self.call('/api/generate', self.payload)
        FakeComfy.completed = True
        FakeComfy.fail = True
        result = self.call('/api/job/' + job['id'])
        self.assertEqual(result['state'], 'error')
        self.assertIn('out of memory', result['error'])

    def test_rejects_invalid_model_dimensions_and_token(self):
        for payload in (self.payload | {'model': 'missing'}, self.payload | {'width': 1000}, self.payload | {'steps': 0}, self.payload | {'cfg': float('nan')}):
            with self.assertRaises(error.HTTPError) as caught:
                self.call('/api/generate', payload)
            self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(error.HTTPError) as caught:
            self.call('/api/generate', self.payload, token='wrong')
        self.assertEqual(caught.exception.code, 403)

    def test_rejects_foreign_host_and_path_traversal(self):
        with self.assertRaises(error.HTTPError) as caught:
            self.call('/api/session', headers={'Host': 'attacker.example'})
        self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(error.HTTPError):
            self.call('/outputs/../settings.json')

    def test_invalid_image_is_rejected(self):
        with self.assertRaises(ValueError):
            app.upload_png('data:image/png;base64,aGVsbG8=', 'source')

    def test_streamed_model_import_and_duplicate_protection(self):
        root = self.data / 'ComfyUI'
        root.mkdir()
        (root / 'main.py').write_text('')
        app.save_json(self.data / 'settings.json', {'comfy_path': str(root)})
        header = json.dumps({'weight': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
        raw = struct.pack('<Q', len(header)) + header + b'\x00' * 4
        def upload(name, content):
            req = request.Request(f'http://127.0.0.1:{self.server.server_port}/api/import?name={name}', content, {'X-EasyPhoto-Token': app.TOKEN})
            return request.urlopen(req)
        with upload('custom.safetensors', raw) as response:
            self.assertTrue(json.load(response)['ok'])
        target = root / 'models' / 'checkpoints' / 'custom.safetensors'
        self.assertEqual(target.read_bytes(), raw)
        for name, content in [('custom.safetensors', raw), ('..%2Fescape.safetensors', raw), ('invalid.safetensors', b'invalid model data')]:
            with self.assertRaises(error.HTTPError) as caught:
                upload(name, content)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(list(target.parent.glob('*.part')), [])


class ShutdownTests(unittest.TestCase):
    def test_authenticated_shutdown_stops_only_its_server(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = request.Request(f'http://127.0.0.1:{server.server_port}/api/shutdown', b'{}',
                                  {'X-EasyPhoto-Token': app.TOKEN})
            with request.urlopen(req) as response:
                self.assertTrue(json.load(response)['ok'])
            thread.join(3)
            self.assertFalse(thread.is_alive(), 'Shutdown did not stop the HTTP server')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
