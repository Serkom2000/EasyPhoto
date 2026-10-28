"""Small transactional application updates. Model weights and user data are protected."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import time
from urllib import parse, request
import uuid

CHANNEL = 'https://github.com/Serkom2000/EasyPhoto/releases/latest/download/update-manifest.json'
MANAGED = frozenset(('app.py', 'README.md', 'model_profiles.py', 'app-version.json', 'models/manifest.json',
    'web/index.html', 'web/app.js', 'web/style.css', 'scripts/start.ps1', 'scripts/launch.ps1',
    'scripts/update.ps1', 'scripts/update_core.py', 'installer/worker.ps1',
    'installer/http-download.ps1', 'installer/install.ps1', 'profiles/examples/basic.json'))
SHA = re.compile(r'^[a-f0-9]{64}$')


def no_link(path):
    try:
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
        attributes = 0
    if path.is_symlink() or attributes & 0x400:
        raise ValueError('Ссылки и reparse points не допускаются: ' + str(path))


def receipt_valid(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not re.fullmatch(r'\d+\.\d+\.\d+', str(value.get('version', ''))):
        raise ValueError('Повреждены сведения об установленной версии.')
    files = value.get('files')
    if not isinstance(files, dict) or any(k not in MANAGED or not SHA.fullmatch(str(v)) for k, v in files.items()):
        raise ValueError('Повреждены контрольные суммы установленной версии.')
    return value


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024**2), b''):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    no_link(path)
    no_link(temp)
    with temp.open('w', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def safe_path(root, relative):
    if relative not in MANAGED or '\\' in relative or ':' in relative:
        raise ValueError('Обновление пытается изменить запрещённый файл: ' + str(relative))
    path = root.joinpath(*PurePosixPath(relative).parts)
    check = path
    while check != root.parent:
        no_link(check)
        if check == root:
            break
        check = check.parent
    return path


def validate_manifest(value):
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise ValueError('Нужна новая версия загрузчика обновлений.')
    if not re.fullmatch(r'\d+\.\d+\.\d+', str(value.get('version', ''))):
        raise ValueError('Некорректная версия обновления.')
    files = value.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= len(MANAGED):
        raise ValueError('Некорректный список файлов обновления.')
    seen = set()
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('Некорректная запись файла.')
        name = item.get('path')
        if name not in MANAGED or name in seen:
            raise ValueError('Запрещённый или повторяющийся путь: ' + str(name))
        seen.add(name)
        size = item.get('size')
        if type(size) is not int or not 1 <= size <= 8 * 1024**2 or not SHA.fullmatch(str(item.get('sha256', ''))):
            raise ValueError('Некорректный размер или SHA-256: ' + name)
        if not isinstance(item.get('previous_sha256', []), list) or not all(SHA.fullmatch(str(x)) for x in item.get('previous_sha256', [])):
            raise ValueError('Некорректные сведения о предыдущей версии.')
        url = parse.urlsplit(item.get('url', ''))
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            raise ValueError('Для обновлений требуется HTTPS.')
        allowed = (url.hostname == 'raw.githubusercontent.com' and url.path.startswith('/Serkom2000/EasyPhoto/')) or (
            url.hostname == 'github.com' and url.path.startswith('/Serkom2000/EasyPhoto/releases/download/'))
        if not allowed:
            raise ValueError('Неизвестный источник обновлений.')
        total += size
    if total > 32 * 1024**2:
        raise ValueError('Слишком большой пакет приложения.')
    return value


def fetch_manifest():
    with request.urlopen(request.Request(CHANNEL, headers={'User-Agent': 'EasyPhoto-Updater'}), timeout=30) as response:
        raw = response.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2:
        raise ValueError('Слишком большой манифест обновления.')
    return validate_manifest(json.loads(raw))


def download(item, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with request.urlopen(request.Request(item['url'], headers={'User-Agent': 'EasyPhoto-Updater'}), timeout=45) as response:
        host = parse.urlsplit(response.url)
        if host.scheme != 'https' or host.hostname not in ('github.com', 'raw.githubusercontent.com',
                'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
            raise ValueError('Небезопасное перенаправление обновления.')
        done = 0
        with target.open('wb') as output:
            while chunk := response.read(256 * 1024):
                done += len(chunk)
                if done > item['size']:
                    raise ValueError('Сервер вернул слишком большой файл.')
                output.write(chunk)
    if done != item['size'] or digest(target) != item['sha256']:
        raise ValueError('Файл обновления повреждён: ' + item['path'])


@contextmanager
def install_lock(root):
    lock = root / '.easyphoto-lock'
    no_link(lock)
    with lock.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Закройте EasyPhoto и другие окна обновления.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class Updater:
    def __init__(self, root, fetch=download, report=lambda *args: None):
        self.root = Path(root).absolute()
        self.folder = self.root / 'data' / 'updates'
        self.receipt = self.root / 'data' / 'update-receipt.json'
        self.fetch = fetch
        self.report = report

    def _metadata_safe(self):
        for path in [self.root, self.root / 'data', self.folder, self.receipt]:
            no_link(path)

    def recover(self):
        self._metadata_safe()
        if not self.folder.exists():
            return
        for transaction in self.folder.iterdir():
            if not re.fullmatch(r'[a-f0-9]{32}', transaction.name):
                continue
            no_link(transaction)
            journal = transaction / 'journal.json'
            no_link(journal)
            if not journal.exists():
                continue
            value = json.loads(journal.read_text('utf-8'))
            old_receipt = receipt_valid(value.get('old_receipt'))
            if value.get('committed') or value.get('rolled_back'):
                continue
            entries = value.get('entries', [])
            if not isinstance(entries, list) or len(entries) > len(MANAGED):
                raise ValueError('Повреждён журнал отката. Резервные копии сохранены.')
            for entry in reversed(entries):
                name = entry['path']
                target = safe_path(self.root, name)
                backup = safe_path(transaction / 'backup', name)
                current = digest(target) if target.is_file() else None
                old = entry.get('old_sha256')
                if old is not None and not SHA.fullmatch(str(old)):
                    raise ValueError('Повреждён журнал резервной копии.')
                if not SHA.fullmatch(str(entry.get('new_sha256', ''))):
                    raise ValueError('Повреждён журнал обновления.')
                if entry.get('started', True) is False:
                    continue
                if current == old:
                    continue
                if current not in (None, entry['new_sha256']):
                    raise ValueError('Файл изменён после прерывания обновления: ' + name)
                if old is None:
                    target.unlink(missing_ok=True)
                else:
                    if not backup.is_file() or digest(backup) != old:
                        raise ValueError('Резервная копия повреждена: ' + name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    restore = target.with_name(target.name + '.restore')
                    no_link(restore)
                    shutil.copy2(backup, restore)
                    os.replace(restore, target)
            if old_receipt is None:
                self.receipt.unlink(missing_ok=True)
            else:
                write_json(self.receipt, old_receipt)
            value['rolled_back'] = True
            write_json(journal, value)

    def apply(self, manifest):
        manifest = validate_manifest(manifest)
        self._metadata_safe()
        if any((parent / '.git').exists() for parent in [self.root, *list(self.root.parents)[:2]]):
            raise ValueError('Исходники Git обновляйте через Git. Выберите установленную EasyPhoto.')
        with install_lock(self.root):
            self.recover()
            old_receipt = receipt_valid(json.loads(self.receipt.read_text('utf-8'))) if self.receipt.exists() else None
            previous = (old_receipt or {}).get('files', {})
            if old_receipt and tuple(map(int, manifest['version'].split('.'))) < tuple(map(int, old_receipt['version'].split('.'))):
                raise ValueError('Понижение версии запрещено.')
            changed = []
            for item in manifest['files']:
                target = safe_path(self.root, item['path'])
                current = digest(target) if target.is_file() else None
                if current == item['sha256']:
                    continue
                accepted = set(item.get('previous_sha256', []))
                if previous.get(item['path']):
                    accepted.add(previous[item['path']])
                if current is not None and current not in accepted:
                    raise ValueError('Файл изменён вручную: ' + item['path'] + '. Обновление остановлено; модели не затронуты.')
                changed.append((item, current))
            if not changed:
                return {'changed': 0, 'downloaded': 0, 'version': manifest['version']}
            required = sum(item['size'] for item, _ in changed)
            if shutil.disk_usage(self.root).free < required * 3 + 8 * 1024**2:
                raise ValueError('Недостаточно места для обновления и резервной копии.')
            transaction = self.folder / uuid.uuid4().hex
            transaction.mkdir(parents=True)
            for index, (item, _) in enumerate(changed):
                self.report('Скачиваем изменения', item['path'], int(index / len(changed) * 70))
                target = safe_path(transaction / 'staged', item['path'])
                self.fetch(item, target)
                if not target.is_file() or target.stat().st_size != item['size'] or digest(target) != item['sha256']:
                    raise ValueError('SHA-256 обновления не совпала: ' + item['path'])
            entries = []
            for item, current in changed:
                if current:
                    backup = safe_path(transaction / 'backup', item['path'])
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    source = safe_path(self.root, item['path'])
                    if digest(source) != current:
                        raise ValueError('Файл изменился во время обновления.')
                    shutil.copy2(source, backup)
                    if digest(backup) != current:
                        raise ValueError('Не удалось проверить резервную копию.')
                entries.append({'path': item['path'], 'old_sha256': current, 'new_sha256': item['sha256'], 'started': False})
            # Includes absent destinations: never overwrite a file created during download.
            for item, current in changed:
                target = safe_path(self.root, item['path'])
                actual = digest(target) if target.is_file() else None
                if actual != current or (target.exists() and not target.is_file()):
                    raise ValueError('Файл изменился во время обновления: ' + item['path'])
                staged = safe_path(transaction / 'staged', item['path'])
                if digest(staged) != item['sha256']:
                    raise ValueError('Подготовленный файл повреждён: ' + item['path'])
            journal = transaction / 'journal.json'
            record = {'entries': entries, 'old_receipt': old_receipt, 'committed': False}
            write_json(journal, record)
            try:
                self.report('Применяем обновление', 'Модели и фотографии остаются на месте.', 80)
                for item, current in sorted(changed, key=lambda pair: pair[0]['path'] == 'app-version.json'):
                    target = safe_path(self.root, item['path'])
                    actual = digest(target) if target.is_file() else None
                    if actual != current or (target.exists() and not target.is_file()):
                        raise ValueError('Файл изменился перед заменой: ' + item['path'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    next(entry for entry in entries if entry['path'] == item['path'])['started'] = True
                    write_json(journal, record)
                    os.replace(safe_path(transaction / 'staged', item['path']), target)
                write_json(self.receipt, {'version': manifest['version'], 'files': {item['path']: item['sha256'] for item in manifest['files']}})
                record['committed'] = True
                write_json(journal, record)
            except BaseException:
                self.recover()
                raise
            return {'changed': len(changed), 'downloaded': required, 'version': manifest['version']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--state')
    parser.add_argument('--recover-only', action='store_true')
    args = parser.parse_args()
    def report(phase, detail='', percent=0, status='working'):
        if args.state:
            write_json(Path(args.state), dict(phase=phase, detail=detail, percent=percent, status=status))
    updater = Updater(args.root, report=report)
    try:
        if args.recover_only:
            with install_lock(updater.root):
                updater.recover()
            return
        if not (updater.root / 'app.py').is_file() or not (updater.root / 'runtime/ComfyUI_windows_portable/python_embeded/python.exe').is_file():
            raise ValueError('Выберите папку установленной EasyPhoto с готовым runtime.')
        report('Проверяем версию', 'Получаем список файлов приложения с GitHub.', 2)
        result = updater.apply(fetch_manifest())
        report('Обновление готово', f"Версия {result['version']}. Изменено файлов: {result['changed']}. Модели не скачивались.", 100, 'done')
    except Exception as exc:
        report('Обновление остановлено', str(exc), 0, 'error')
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
