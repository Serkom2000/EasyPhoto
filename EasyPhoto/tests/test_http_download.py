"""Windows integration checks for downloading without a BITS service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest


@unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell required')
class HttpDownloadTests(unittest.TestCase):
    def test_resume_ignoring_range_and_interrupted_transfer(self):
        content = bytes(range(256)) * 8192
        ranges = []
        scenario = ['resume']

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                header = self.headers.get('Range')
                ranges.append(header)
                offset = int(header[6:-1]) if header else 0
                if scenario[0] == 'ignore':
                    offset = 0
                self.send_response(206 if offset else 200)
                self.send_header('Content-Length', str(len(content) - offset))
                if offset:
                    self.send_header('Content-Range', f'bytes {offset}-{len(content)-1}/{len(content)}')
                self.end_headers()
                if scenario[0] == 'interrupt' and len(ranges) == 1:
                    self.wfile.write(content[:65536])
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                else:
                    self.wfile.write(content[offset:])

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        helper = Path(__file__).resolve().parents[1] / 'installer' / 'http-download.ps1'
        try:
            with tempfile.TemporaryDirectory(prefix='EasyPhoto network ') as folder:
                folder = Path(folder)
                for case in ['resume', 'ignore', 'interrupt']:
                    with self.subTest(case=case):
                        scenario[0] = case
                        ranges.clear()
                        target = folder / (case + '.bin')
                        if case != 'interrupt':
                            target.with_suffix('.bin.part').write_bytes(content[:12345])
                        script = folder / 'run.ps1'
                        script.write_text(
                            "param($Helper,$Url,$Target)\n$ErrorActionPreference='Stop'\n"
                            "function Start-BitsTransfer { throw 'BITS must not be called' }\n"
                            ". $Helper\nReceive-EasyPhotoFile -Url $Url -Destination $Target\n",
                            encoding='utf-8-sig')
                        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                            '-File', str(script), str(helper), f'http://127.0.0.1:{server.server_port}/model', str(target)],
                            capture_output=True, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                        self.assertEqual(target.read_bytes(), content)
                        self.assertFalse(target.with_suffix('.bin.part').exists())
                        if case == 'resume':
                            self.assertEqual(ranges, ['bytes=12345-'])
                        if case == 'interrupt':
                            self.assertGreater(len(ranges), 1)
                            self.assertEqual(ranges[1], 'bytes=65536-')
        finally:
            server.shutdown()
            server.server_close()
