"""EasyPhoto: a loopback-only, dependency-free frontend for ComfyUI."""
import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path
import secrets
import struct
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request, parse, error
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
TOKEN = secrets.token_urlsafe(32)
COMFY = 'http://127.0.0.1:8188'
LOCK = threading.Lock()
CATALOG = json.loads((ROOT / 'models' / 'manifest.json').read_text('utf-8'))



def api(path, payload=None, timeout=15):
    body = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(COMFY + path, body, {'Content-Type': 'application/json'})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except error.HTTPError as exc:
        details = exc.read().decode(errors='replace')
        raise ValueError('ComfyUI: ' + details[:1600]) from exc


def comfy_root():
    config = DATA / 'settings.json'
    if config.exists():
        path = Path(json.loads(config.read_text('utf-8'))['comfy_path']).expanduser().resolve()
        if not (path / 'main.py').is_file():
            raise ValueError('В выбранной папке нет main.py ComfyUI.')
        return path
    matches = list((ROOT / 'runtime').glob('**/ComfyUI/main.py'))
    return matches[0].parent if matches else None


def choices(info, node, field):
    try:
        return info[node]['input']['required'][field][0]
    except (KeyError, TypeError):
        return []


def integer(value, low, high, label):
    try:
        number = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(label + ': нужно целое число.') from exc
    if not low <= number <= high:
        raise ValueError(label + ': недопустимое значение.')
    return number


def workflow(p, info):
    model = p.get('model')
    if model not in choices(info, 'CheckpointLoaderSimple', 'ckpt_name'):
        raise ValueError('Выберите установленную модель.')
    mode = p.get('mode', 'create')
    if mode not in ('create', 'edit', 'pose'):
        raise ValueError('Неизвестный режим.')
    prompt = str(p.get('prompt', '')).strip()
    if not prompt or len(prompt) > 10000:
        raise ValueError('Опишите нужную фотографию (до 10 000 символов).')
    width = integer(p.get('width', 1024), 256, 1536, 'Ширина')
    height = integer(p.get('height', 1024), 256, 1536, 'Высота')
    if width % 64 or height % 64:
        raise ValueError('Размеры должны быть кратны 64.')
    seed = p.get('seed', '')
    seed = secrets.randbelow(2**53) if seed in ('', None, -1) else integer(seed, 0, 2**53 - 1, 'Seed')
    strength = float(p.get('strength', .75))
    cfg = float(p.get('cfg', 6))
    if not 0.05 <= strength <= 1 or not 1 <= cfg <= 15:
        raise ValueError('Недопустимая сила изменения или CFG.')
    graph = {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': model}},
        '2': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': prompt}},
        '3': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': str(p.get('negative', ''))[:10000]}},
        '4': {'class_type': 'EmptyLatentImage', 'inputs': {'width': width, 'height': height, 'batch_size': 1}},
        '5': {'class_type': 'KSampler', 'inputs': {'model': ['1', 0], 'positive': ['2', 0], 'negative': ['3', 0], 'latent_image': ['4', 0], 'seed': seed, 'steps': integer(p.get('steps', 25), 4, 60, 'Шаги'), 'cfg': cfg, 'sampler_name': 'dpmpp_2m', 'scheduler': 'karras', 'denoise': 1.0}},
        '6': {'class_type': 'VAEDecode', 'inputs': {'samples': ['5', 0], 'vae': ['1', 2]}},
        '7': {'class_type': 'SaveImage', 'inputs': {'images': ['6', 0], 'filename_prefix': 'EasyPhoto'}},
    }
    if mode == 'edit':
        image = upload_png(p.get('image'), 'source')
        graph['8'] = {'class_type': 'LoadImage', 'inputs': {'image': image}}
        # The browser sizes both source and mask identically, to multiples of 64.
        graph['4'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['8', 0], 'vae': ['1', 2]}}
        graph['5']['inputs']['denoise'] = strength
        if p.get('mask'):
            mask = upload_png(p['mask'], 'mask')
            graph['9'] = {'class_type': 'LoadImageMask', 'inputs': {'image': mask, 'channel': 'red'}}
            graph['4'] = {'class_type': 'VAEEncodeForInpaint', 'inputs': {'pixels': ['8', 0], 'vae': ['1', 2], 'mask': ['9', 0], 'grow_mask_by': 8}}
            # Composite unmasked pixels back, rather than allowing VAE drift everywhere.
            graph['10'] = {'class_type': 'ImageCompositeMasked', 'inputs': {'destination': ['8', 0], 'source': ['6', 0], 'x': 0, 'y': 0, 'resize_source': False, 'mask': ['9', 0]}}
            graph['7']['inputs']['images'] = ['10', 0]
    if mode == 'pose':
        control = p.get('controlnet')
        if control not in choices(info, 'ControlNetLoader', 'control_net_name'):
            raise ValueError('Добавьте совместимую с вашей моделью OpenPose ControlNet.')
        pose = upload_png(p.get('image'), 'pose')
        graph['8'] = {'class_type': 'LoadImage', 'inputs': {'image': pose}}
        graph['9'] = {'class_type': 'ControlNetLoader', 'inputs': {'control_net_name': control}}
        graph['10'] = {'class_type': 'ControlNetApplyAdvanced', 'inputs': {'positive': ['2', 0], 'negative': ['3', 0], 'control_net': ['9', 0], 'image': ['8', 0], 'strength': 1.0, 'start_percent': 0.0, 'end_percent': 1.0, 'vae': ['1', 2]}}
        graph['5']['inputs'].update(positive=['10', 0], negative=['10', 1])
    return graph, seed


def upload_png(encoded, label):
    if not isinstance(encoded, str) or not encoded.startswith('data:image/png;base64,'):
        raise ValueError('Добавьте изображение PNG.')
    try:
        content = base64.b64decode(encoded.split(',', 1)[1], validate=True)
    except ValueError as exc:
        raise ValueError('Не удалось прочитать изображение.') from exc
    if len(content) > 20 * 1024**2 or content[:8] != b'\x89PNG\r\n\x1a\n' or len(content) < 24:
        raise ValueError('Некорректный PNG или размер больше 20 МБ.')
    w, h = struct.unpack('>II', content[16:24])
    if not 64 <= w <= 2048 or not 64 <= h <= 2048:
        raise ValueError('Размер изображения должен быть от 64 до 2048 пикселей.')
    name = f'easyphoto_{label}_{secrets.token_hex(8)}.png'
    boundary = secrets.token_hex(20)
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: image/png\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    req = request.Request(COMFY + '/upload/image', body, {'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    return '/'.join(filter(None, [result.get('subfolder'), result['name']]))


def save_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
    tmp.replace(path)


def check_safetensors(path):
    with path.open('rb') as source:
        header_size = int.from_bytes(source.read(8), 'little')
        if not 2 <= header_size <= min(path.stat().st_size - 8, 100 * 1024**2):
            raise ValueError('Файл не содержит корректный заголовок safetensors.')
        header = json.loads(source.read(header_size))
        if not isinstance(header, dict):
            raise ValueError('Некорректный заголовок модели.')


class Handler(BaseHTTPRequestHandler):
    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def send(self, data, status=200, content_type='application/json; charset=utf-8'):
        raw = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.valid_host():
            return self.send({'error': 'Недопустимый адрес приложения.'}, 403)
        try:
            self.get()
        except (ValueError, OSError, error.URLError) as exc:
            self.send({'error': str(exc)}, 400)
        except Exception:
            traceback.print_exc()
            self.send({'error': 'Внутренняя ошибка. Подробности в журнале приложения.'}, 500)

    def get(self):
        url = parse.urlsplit(self.path)
        if url.path == '/api/session':
            return self.send({'token': TOKEN})
        if url.path == '/api/status':
            root = comfy_root()
            result = {'connected': False, 'comfy_path': str(root or ''), 'catalog': [{k: v for k, v in item.items() if k != 'url'} | {'id': key} for key, item in CATALOG.items()]}
            try:
                info = api('/object_info', timeout=3)
                result.update(connected=True, models=choices(info, 'CheckpointLoaderSimple', 'ckpt_name'), controlnets=choices(info, 'ControlNetLoader', 'control_net_name'))
                stats = api('/system_stats', timeout=3)
                result['devices'] = stats.get('devices', [])
            except (OSError, ValueError) as exc:
                result['connection_error'] = str(exc)
            return self.send(result)
        if url.path == '/api/history':
            records = []
            for path in (DATA / 'jobs').glob('*.json'):
                records.append(json.loads(path.read_text('utf-8')))
            return self.send(sorted(records, key=lambda r: r['created'], reverse=True)[:100])
        if url.path.startswith('/api/job/'):
            job_id = url.path.rsplit('/', 1)[-1]
            if not all(c in '0123456789abcdef-' for c in job_id) or not job_id:
                raise ValueError('Некорректный номер задания.')
            path = DATA / 'jobs' / (job_id + '.json')
            if not path.exists():
                raise ValueError('Задание не найдено.')
            with LOCK:
                record = json.loads(path.read_text('utf-8'))
                if record['state'] in ('queued', 'running'):
                    history = api('/history/' + job_id).get(job_id)
                    if history:
                        images = []
                        for output in history.get('outputs', {}).values():
                            for img in output.get('images', []):
                                if img.get('type') != 'output':
                                    continue
                                query = parse.urlencode(img)
                                with request.urlopen(COMFY + '/view?' + query, timeout=30) as response:
                                    raw = response.read()
                                filename = f'{job_id}_{len(images)}.png'
                                (DATA / 'outputs' / filename).write_bytes(raw)
                                images.append('/outputs/' + filename)
                        record.update(state='done' if images else 'error', images=images)
                        if not images:
                            messages = history.get('status', {}).get('messages', [])
                            record['error'] = 'ComfyUI не создал изображение. ' + str(messages)[-1800:]
                        save_json(path, record)
                    else:
                        queue = api('/queue')
                        active = [x[1] for x in queue.get('queue_running', [])]
                        pending = [x[1] for x in queue.get('queue_pending', [])]
                        if job_id in active:
                            record['state'] = 'running'
                        elif job_id not in pending:
                            record.update(state='error', error='Задание отсутствует в движке. Возможно, ComfyUI перезапустился или генерация была отменена.')
                            save_json(path, record)
                return self.send(record)
        if url.path.startswith('/outputs/'):
            name = url.path.removeprefix('/outputs/')
            if Path(name).name != name or not name.endswith('.png'):
                raise ValueError('Некорректный файл.')
            return self.send((DATA / 'outputs' / name).read_bytes(), content_type='image/png')
        assets = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
        if url.path in assets:
            filename = assets[url.path]
            return self.send((ROOT / 'web' / filename).read_bytes(), content_type=mimetypes.guess_type(filename)[0] + '; charset=utf-8')
        return self.send({'error': 'Не найдено'}, 404)

    def do_POST(self):
        # Non-simple header plus per-process token prevents drive-by localhost writes.
        if not self.valid_host() or self.headers.get('X-EasyPhoto-Token') != TOKEN:
            return self.send({'error': 'Обновите страницу приложения.'}, 403)
        try:
            if parse.urlsplit(self.path).path == '/api/import':
                return self.import_model()
            size = integer(self.headers.get('Content-Length', 0), 1, 60 * 1024**2, 'Размер запроса')
            p = json.loads(self.rfile.read(size))
            if self.path == '/api/shutdown':
                self.send({'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path == '/api/settings':
                root = Path(str(p.get('comfy_path', ''))).expanduser().resolve()
                if not (root / 'main.py').is_file():
                    raise ValueError('Укажите папку ComfyUI, в которой находится main.py.')
                save_json(DATA / 'settings.json', {'comfy_path': str(root)})
                return self.send({'ok': True})
            if self.path == '/api/generate':
                info = api('/object_info')
                graph, seed = workflow(p, info)
                with LOCK:
                    result = api('/prompt', {'prompt': graph, 'client_id': 'easyphoto'})
                    if 'prompt_id' not in result:
                        raise ValueError(str(result))
                    record = {k: v for k, v in p.items() if k not in ('image', 'mask')}
                    record.update(id=result['prompt_id'], seed=seed, state='queued', created=time.time(), images=[])
                    save_json(DATA / 'jobs' / (record['id'] + '.json'), record)
                return self.send(record)
            return self.send({'error': 'Не найдено'}, 404)
        except (ValueError, TypeError, OSError, error.URLError) as exc:
            self.send({'error': str(exc)}, 400)

    def import_model(self):
        query = parse.parse_qs(parse.urlsplit(self.path).query)
        name = query.get('name', [''])[0]
        if not name or '/' in name or '\\' in name or ':' in name or name.startswith('.') or not name.lower().endswith('.safetensors') or len(name) > 180:
            raise ValueError('Выберите файл модели .safetensors с обычным именем.')
        size = integer(self.headers.get('Content-Length', 0), 10, 32 * 1024**3, 'Размер модели')
        root = comfy_root()
        if root is None:
            raise ValueError('Сначала укажите папку ComfyUI в настройках.')
        folder = root / 'models' / 'checkpoints'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        if target.exists():
            raise ValueError('Модель с таким именем уже добавлена.')
        tmp = folder / (name + '.' + secrets.token_hex(6) + '.part')
        try:
            remaining = size
            self.connection.settimeout(120)
            with tmp.open('xb') as destination:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError('Копирование прервалось. Повторите добавление модели.')
                    destination.write(chunk)
                    remaining -= len(chunk)
            check_safetensors(tmp)
            # Windows rename and POSIX link publish atomically without overwriting.
            if os.name == 'nt':
                os.rename(tmp, target)
            else:
                os.link(tmp, target)
            return self.send({'ok': True, 'filename': name})
        finally:
            tmp.unlink(missing_ok=True)


def main():
    global COMFY
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--comfy-url', default=COMFY)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    parts = parse.urlsplit(args.comfy_url)
    if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('ComfyUI должен работать локально по HTTP.')
    COMFY = args.comfy_url.rstrip('/')
    for folder in ('jobs', 'outputs'):
        (DATA / folder).mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    address = f'http://127.0.0.1:{args.port}'
    print('EasyPhoto: ' + address, flush=True)
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
