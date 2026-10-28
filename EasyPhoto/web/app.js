'use strict';
const $ = id => document.getElementById(id);
let token, status = {}, mode = 'create', size = [1024, 1024], source = null, hasMask = false;
let job = null, running = false, refreshing = false, toastTimer, lastResult;
let formatModel = null;
const photo = $('photo-canvas'), paint = $('paint-canvas');
const ctx = photo.getContext('2d'), brush = paint.getContext('2d');

async function api(path, payload) {
  const options = payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-EasyPhoto-Token': token}, body: JSON.stringify(payload)};
  const response = await fetch('/api/' + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Не удалось выполнить запрос.');
  return result;
}
function notify(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 10000);
}
function showView(view) {
  document.querySelectorAll('.view').forEach(el => el.hidden = el.id !== view);
  document.querySelectorAll('.nav[data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  $('page-label').textContent = {studio: 'Студия', history: 'Мои фотографии', models: 'Модели', settings: 'Настройки', guide: 'Инструкция'}[view];
  window.scrollTo({top: 0, behavior: 'instant'});
  if (view === 'history') loadHistory();
  if (view === 'models' || view === 'settings') refreshStatus();
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
  if (running) return notify('Дождитесь завершения текущей фотографии.');
  setMode('create');
  $('prompt').value = 'Photograph of a cozy wooden cabin by a calm lake, pine forest, soft morning light, realistic landscape';
  $('prompt').dispatchEvent(new Event('input'));
  showView('studio'); $('prompt').focus();
  notify('Пример добавлен. Выберите модель и нажмите «Создать фотографию».');
}));
function setMode(next) {
  if (running) return notify('Дождитесь завершения текущей фотографии.');
  mode = next;
  document.querySelectorAll('[data-mode]').forEach(el => el.classList.toggle('active', el.dataset.mode === mode));
  $('upload-section').hidden = mode === 'create';
  $('controlnet-field').hidden = mode !== 'pose';
  $('pose-hint').hidden = mode !== 'pose';
  $('mask-tools').hidden = mode !== 'edit' || !source;
  $('strength-field').hidden = mode !== 'edit';
  $('format-field').hidden = mode === 'edit';
  $('upload-label').textContent = mode === 'pose' ? 'Карта позы OpenPose' : 'Исходная фотография';
  $('prompt-label').textContent = mode === 'edit' ? 'Опишите, как должен выглядеть результат' : 'Какую фотографию вы представляете?';
  $('preview-title').textContent = mode === 'edit' ? 'Ваша фотография' : mode === 'pose' ? 'Композиция по карте позы' : 'Ваш следующий удачный кадр';
  updateGenerate(); updatePreview();
}
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => setMode(button.dataset.mode)));
function updateGenerate() {
  const family = $('family').value, custom = family.startsWith('custom:');
  const split = family.startsWith('flux-') && $('loader').value === 'split';
  const missing = [];
  if (!custom && !$('model').value) missing.push('модель');
  if (split) { if (!$('vae').value) missing.push('VAE'); if (!$('clip1').value) missing.push('CLIP-L'); if (!$('clip2').value) missing.push('T5'); }
  $('component-readiness').textContent = missing.length ? 'Выберите: ' + missing.join(', ') + '.' : '';
  $('generate').disabled = running || !status.connected || missing.length > 0;
  $('generate').replaceChildren();
  const icon = document.createElement('span'); icon.textContent = '✦';
  const arrow = document.createElement('span'); arrow.textContent = '→';
  $('generate').append(icon, document.createTextNode(running ? 'Создаём фотографию…' : mode === 'edit' ? 'Изменить фотографию' : 'Создать фотографию'), arrow);
}
document.querySelectorAll('[data-size]').forEach(button => button.addEventListener('click', () => {
  size = button.dataset.size.split(',').map(Number);
  document.querySelectorAll('[data-size]').forEach(el => el.classList.toggle('active', el === button));
}));
$('prompt').addEventListener('input', () => $('prompt-count').textContent = $('prompt').value.length);
$('strength').addEventListener('input', () => $('strength-value').textContent = $('strength').value + '%');

function fillSelect(element, values, empty) {
  const previous = element.value;
  element.replaceChildren();
  if (!values?.length) element.add(new Option(empty, ''));
  else values.forEach(value => element.add(new Option(value, value)));
  if (values?.includes(previous)) element.value = previous;
}
function syncModelFormats() {
  const model = $('model').value;
  if (model === formatModel) return;
  formatModel = model;
  const item = status.catalog?.find(item => model === item.filename || model.endsWith('/' + item.filename) || model.endsWith('\\' + item.filename));
  const formats = item?.formats || [[1024, 1024], [768, 1152], [1152, 768]];
  document.querySelectorAll('[data-size]').forEach((button, index) => {
    button.dataset.size = formats[index].join(',');
    button.title = formats[index].join(' × ');
    if (button.classList.contains('active')) size = [...formats[index]];
  });
}
$('model').addEventListener('change', () => {
  const known = status.catalog?.find(item => item.filename === $('model').value);
  if (known && ['sd15','sdxl'].includes($('family').value)) $('family').value = known.id === 'sdxl' ? 'sdxl' : 'sd15';
  syncModelFormats(); updateGenerate();
});
['vae','clip1','clip2'].forEach(id => $(id).addEventListener('change', updateGenerate));
async function refreshStatus() {
  if (refreshing) return;
  refreshing = true;
  try {
    status = await api('status');
    $('connection').classList.toggle('offline', !status.connected);
    $('connection-text').textContent = status.connected ? 'Движок подключён' : 'Движок не подключён';
    $('setup-banner').hidden = status.connected && status.models?.length;
    $('setup-title').textContent = status.connected ? 'Осталось добавить первую модель' : 'Подготовим вашу мастерскую';
    $('setup-description').textContent = status.connected ? 'Откройте раздел «Модели» и добавьте файл модели из комплекта или свой.' : 'Запустите Start.bat или подключите установленный ComfyUI.';
    syncProfiles();
    syncComponents();
    $('app-version').textContent = status.version || '0.2.0';
    syncModelFormats();
    fillSelect($('controlnet'), status.controlnets, 'Нет установленных ControlNet');
    if (document.activeElement !== $('comfy-path')) $('comfy-path').value = status.comfy_path || '';
    $('device-info').textContent = status.devices?.length ? status.devices.map(d => `${d.name} · ${((d.vram_total || 0) / 1024 ** 3).toFixed(1)} ГБ памяти`).join(' / ') : 'Движок пока не подключён.';
    renderCatalog();
    $('installed-models').replaceChildren(...Object.entries(status.components || {}).flatMap(([category, files]) => files.map(name => category + ': ' + name)).map(name => {const li = document.createElement('li'); li.textContent = name; return li;}));
    updateGenerate();
  } catch (err) { $('connection-text').textContent = 'Приложение недоступно'; status.connected = false; updateGenerate(); }
  finally { refreshing = false; }
}
function renderCatalog() {
  $('catalog').replaceChildren();
  (status.catalog || []).forEach(item => {
    const card = document.createElement('div'); card.className = 'model-card';
    const detail = document.createElement('div');
    const title = document.createElement('h3'); title.textContent = item.name;
    const desc = document.createElement('p'); desc.textContent = item.description;
    const link = document.createElement('a'); link.href = item.source; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Источник и условия: ' + item.license + ' ↗';
    detail.append(title, desc, link);
    const state = document.createElement('span'); state.className = 'hint';
    const installed = status.models?.some(name => name === item.filename || name.endsWith('/' + item.filename) || name.endsWith('\\' + item.filename));
    state.textContent = !status.connected ? 'Подключите движок' : installed ? '✓ Готова к работе' : 'Файл не найден — добавьте его ниже';
    card.append(detail, state); $('catalog').append(card);
  });
}
$('settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {await api('settings', {comfy_path: $('comfy-path').value}); notify('Папка сохранена.'); await refreshStatus();} catch (e) {notify(e.message);}
});
$('import-model').addEventListener('click', () => {
  if (!status.comfy_path) return notify('Сначала укажите папку ComfyUI в настройках.');
  $('model-file').click();
});
$('model-file').addEventListener('change', () => {
  const file = $('model-file').files[0];
  if (!file) return;
  if (!/\.(safetensors|gguf)$/i.test(file.name)) return notify('Выберите файл .safetensors или .gguf.');
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/import?name=' + encodeURIComponent(file.name) + '&category=' + encodeURIComponent($('import-category').value));
  xhr.setRequestHeader('X-EasyPhoto-Token', token);
  $('import-model').disabled = true;
  $('import-status').textContent = 'Копируем модель в локальную папку движка…';
  xhr.upload.onprogress = e => {if (e.lengthComputable) $('import-status').textContent = `Копирование: ${Math.floor(e.loaded / e.total * 100)}%. Не закрывайте приложение.`;};
  xhr.onload = async () => {
    $('import-model').disabled = false; $('model-file').value = '';
    try {
      const result = JSON.parse(xhr.responseText);
      if (xhr.status !== 200) throw new Error(result.error);
      $('import-status').textContent = 'Модель добавлена. Выберите её в студии.'; await refreshStatus();
    } catch (e) {$('import-status').textContent = 'Ошибка: ' + e.message;}
  };
  xhr.onerror = () => {$('import-model').disabled = false; $('import-status').textContent = 'Соединение прервалось. Повторите добавление модели.';};
  xhr.send(file);
});

async function loadSource(file) {
  if (running) return notify('Дождитесь завершения генерации.');
  if (!file || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Выберите фотографию JPG, PNG или WEBP.');
  if (file.size > 20 * 1024 ** 2) throw new Error('Выберите фотографию меньше 20 МБ.');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image(); image.src = url; await image.decode();
    const scale = Math.min(1, 1536 / Math.max(image.width, image.height));
    photo.width = Math.max(64, Math.round(image.width * scale / 64) * 64);
    photo.height = Math.max(64, Math.round(image.height * scale / 64) * 64);
    paint.width = photo.width; paint.height = photo.height;
    ctx.drawImage(image, 0, 0, photo.width, photo.height);
    source = photo.toDataURL('image/png'); hasMask = false;
    $('upload-text').textContent = `${file.name} · ${photo.width} × ${photo.height}`;
    $('use-mask').checked = false; $('mask-tools').hidden = mode !== 'edit';
    lastResult = null; updatePreview();
  } finally {URL.revokeObjectURL(url);}
}
$('source-file').addEventListener('change', e => loadSource(e.target.files[0]).catch(e => notify(e.message)));
const dropZone = document.querySelector('.upload');
dropZone.addEventListener('dragover', e => {e.preventDefault();});
dropZone.addEventListener('drop', e => {e.preventDefault(); loadSource(e.dataTransfer.files[0]).catch(e => notify(e.message));});
function updatePreview() {
  const showSource = mode !== 'create' && source && !lastResult;
  $('canvas-wrap').hidden = !showSource;
  $('empty-preview').hidden = !!showSource || !!lastResult;
  $('result-image').hidden = !lastResult;
  $('result-actions').hidden = !lastResult;
  $('empty-footer-icon').hidden = !!lastResult;
  paint.style.pointerEvents = mode === 'edit' && $('use-mask').checked ? 'auto' : 'none';
  paint.style.visibility = mode === 'edit' && $('use-mask').checked ? 'visible' : 'hidden';
}
$('use-mask').addEventListener('change', updatePreview);
$('clear-mask').addEventListener('click', () => {brush.clearRect(0, 0, paint.width, paint.height); hasMask = false;});
let painting = false, lastPoint;
function point(event) {const rect = paint.getBoundingClientRect(); return [(event.clientX - rect.left) * paint.width / rect.width, (event.clientY - rect.top) * paint.height / rect.height];}
function stroke(event) {
  if (!painting) return;
  const next = point(event);
  brush.strokeStyle = '#ffffff'; brush.fillStyle = '#ffffff'; brush.lineWidth = Number($('brush').value); brush.lineCap = 'round'; brush.lineJoin = 'round';
  brush.beginPath(); brush.moveTo(...lastPoint); brush.lineTo(...next); brush.stroke();
  brush.beginPath(); brush.arc(...next, brush.lineWidth / 2, 0, Math.PI * 2); brush.fill();
  lastPoint = next; hasMask = true;
}
paint.addEventListener('pointerdown', e => {if (running) return; painting = true; lastPoint = point(e); paint.setPointerCapture(e.pointerId); stroke(e);});
paint.addEventListener('pointermove', stroke);
paint.addEventListener('pointerup', () => painting = false);
paint.addEventListener('pointercancel', () => painting = false);
function maskData() {
  if (!$('use-mask').checked) return null;
  if (!hasMask) throw new Error('Закрасьте область изменения или отключите выделение.');
  const canvas = document.createElement('canvas'); canvas.width = paint.width; canvas.height = paint.height;
  const context = canvas.getContext('2d'); context.fillStyle = 'black'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(paint, 0, 0);
  return canvas.toDataURL('image/png');
}
$('generate-form').addEventListener('submit', async event => {
  event.preventDefault(); if (running) return;
  try {
    if (mode !== 'create' && !source) throw new Error(mode === 'pose' ? 'Добавьте карту позы OpenPose.' : 'Добавьте исходную фотографию.');
    if (mode === 'pose' && !$('controlnet').value) throw new Error('Добавьте модель OpenPose ControlNet в разделе «Модели».');
    const payload = {...componentParameters(), mode, prompt: $('prompt').value, model: $('model').value, width: size[0], height: size[1], steps: Number($('steps').value), cfg: Number($('cfg').value), seed: $('seed').value, negative: $('negative').value, strength: Number($('strength').value) / 100};
    if (mode !== 'create') payload.image = source;
    if (mode === 'edit') {payload.mask = maskData(); payload.width = photo.width; payload.height = photo.height;}
    if (mode === 'pose') payload.controlnet = $('controlnet').value;
    running = true; updateGenerate(); $('busy').hidden = false; $('busy-title').textContent = 'Отправляем фотографию в работу';
    job = await api('generate', payload); localStorage.setItem('easyphoto-job', job.id);
    pollJob();
  } catch (e) {running = false; $('busy').hidden = true; updateGenerate(); notify(e.message);}
});
function displayResult(record) {
  lastResult = record.images[0]; $('result-image').src = lastResult;
  $('download-result').href = lastResult;
  $('result-caption').textContent = 'Seed: ' + record.seed + ' · ' + record.model;
  updatePreview();
}
async function pollJob() {
  if (!job) return;
  try {
    const record = await api('job/' + job.id);
    const secs = Math.max(0, Math.floor(Date.now() / 1000 - record.created));
    $('elapsed').textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
    if (record.state === 'done' || record.state === 'error') {
      running = false; job = null; localStorage.removeItem('easyphoto-job'); $('busy').hidden = true; updateGenerate();
      if (record.state === 'error') notify(record.error || 'Генерация не завершилась. Проверьте журнал ComfyUI.');
      else displayResult(record);
      loadHistory(false); return;
    }
    $('busy-title').textContent = record.state === 'running' ? 'Создаём вашу фотографию' : 'Фотография в очереди';
    $('busy-detail').textContent = record.state === 'running' ? 'Движок работает. Первая загрузка модели занимает больше времени.' : 'Задание отправлено. Ожидаем свободный движок.';
  } catch (e) {$('busy-title').textContent = 'Ожидаем соединения'; $('busy-detail').textContent = e.message;}
  setTimeout(pollJob, 2000);
}
$('edit-result').addEventListener('click', async () => {
  try {const response = await fetch(lastResult); const file = new File([await response.blob()], 'Моя фотография.png', {type: 'image/png'}); setMode('edit'); await loadSource(file);} catch (e) {notify(e.message);}
});
async function loadHistory(render = true) {
  try {
    const records = await api('history');
    $('history-count').textContent = records.filter(r => r.state === 'done').length;
    if (!render) return;
    records.sort((a,b) => b.created - a.created);
    $('history-grid').replaceChildren();
    if (!records.length) {const p = document.createElement('p'); p.className = 'history-empty'; p.textContent = 'Пока ни одного кадра. Самое время создать первый.'; $('history-grid').append(p);}
    records.forEach(record => {
      const card = document.createElement('article'); card.className = 'history-card';
      if (record.images?.length) {const img = document.createElement('img'); img.src = record.images[0]; img.alt = record.prompt; img.loading = 'lazy'; card.append(img);}
      const detail = document.createElement('div'), desc = document.createElement('p'), meta = document.createElement('small');
      desc.textContent = record.prompt; meta.textContent = new Date(record.created * 1000).toLocaleString('ru-RU') + ' · ' + ({done:'Готово',error:'Ошибка',queued:'В очереди',running:'В работе'}[record.state] || record.state);
      detail.append(desc, meta);
      const reuse = document.createElement('button'); reuse.className = 'secondary'; reuse.textContent = 'Повторить настройки';
      reuse.addEventListener('click', () => {
        if (running) return notify('Дождитесь завершения генерации.');
        showView('studio'); setMode(record.mode || 'create');
        restoreParameters(record);
        syncModelFormats();
        $('prompt-count').textContent = $('prompt').value.length;
        $('strength').value = (record.strength || .75) * 100; $('strength').dispatchEvent(new Event('input'));
        size = [record.width, record.height]; document.querySelectorAll('[data-size]').forEach(el => el.classList.toggle('active', el.dataset.size === size.join(',')));
        if (record.mode !== 'create') notify('Параметры восстановлены. Загрузите исходное фото или карту позы заново.');
      });
      detail.append(reuse);
      if (record.images?.length) {
        const view = document.createElement('button'); view.className = 'secondary'; view.textContent = 'Открыть';
        view.addEventListener('click', () => {if (running) return notify('Дождитесь завершения генерации.'); showView('studio'); displayResult(record);}); detail.append(' ', view);
      } else if (['queued','running'].includes(record.state)) {
        const track = document.createElement('button'); track.className = 'secondary'; track.textContent = 'Проверить'; track.addEventListener('click', () => {if (running) return; showView('studio'); job = record; running = true; $('busy').hidden = false; updateGenerate(); pollJob();}); detail.append(' ', track);
      }
      if (record.error) {const err = document.createElement('p'); err.className = 'hint'; err.textContent = record.error; detail.append(err);}
      card.append(detail); $('history-grid').append(card);
    });
  } catch (e) {notify(e.message);}
}
$('refresh-history').addEventListener('click', () => loadHistory());
function optionalSelect(element, values, label) {
  const previous = element.value;
  element.replaceChildren(new Option(label, ''), ...(values || []).map(name => new Option(name, name)));
  if ((values || []).includes(previous)) element.value = previous;
}
function syncProfiles() {
  const previous = $('family').value;
  $('family').querySelectorAll('[data-custom]').forEach(el => el.remove());
  (status.profiles || []).forEach(item => {const option = new Option(item.name, 'custom:' + item.id); option.dataset.custom = 'true'; $('family').add(option);});
  if ([...$('family').options].some(o => o.value === previous)) $('family').value = previous;
  const saved = $('preset').value;
  $('preset').replaceChildren(new Option('Новый набор', ''), ...(status.presets || []).map((item, i) => new Option(item.name, String(i))));
  $('preset').value = saved;
}
function syncComponents() {
  const family = $('family').value, flux = family.startsWith('flux-'), custom = family.startsWith('custom:');
  $('loader-field').hidden = !flux;
  const split = flux && $('loader').value === 'split';
  const initial = !formatModel;
  if (custom) optionalSelect($('model'), [...(status.models || []), ...(status.components?.diffusion_models || [])], 'Берётся из профиля');
  else {
    const eligible = (status.models || []).filter(name => {
      const known = status.catalog?.find(item => item.filename === name);
      return !known || (known.id === 'sdxl' ? family === 'sdxl' : family === 'sd15');
    });
    fillSelect($('model'), split ? status.components?.diffusion_models : eligible, 'Добавьте файл в «Моделях»');
  }
  if (initial && family === 'sdxl' && status.models?.includes('sd_xl_base_1.0.safetensors')) $('model').value = 'sd_xl_base_1.0.safetensors';
  optionalSelect($('vae'), status.components?.vae, split ? 'Выберите VAE' : 'Встроенный в checkpoint');
  optionalSelect($('clip1'), status.components?.text_encoders, split ? 'Выберите CLIP-L' : 'Встроенный в checkpoint');
  optionalSelect($('clip2'), status.components?.text_encoders, split ? 'Выберите T5' : 'Встроенный / не нужен');
  $('family-hint').textContent = custom ? 'Профиль задаёт схему. Поля компонентов заменяют только его явно заданные bindings.' : flux ? 'FLUX.1: CLIP-L + T5 + ae VAE. Dev и Schnell — разные варианты; проверьте описание файла.' : 'Семейство выбирается по описанию файла. LoRA и VAE должны с ним совпадать.';
  document.querySelector('.language-hint').textContent = family.startsWith('sd') ? 'Для SD описание на английском обычно работает лучше. Автоперевода пока нет.' : 'Язык описания зависит от модели. Автоперевода пока нет.';
  if (split) $('component-details').open = true;
  syncModelFormats(); updateGenerate();
}
function loraRow(name = '', strength = 1) {
  if ($('lora-list').children.length >= 8) return notify('Можно подключить до восьми LoRA.');
  const row = document.createElement('div'); row.className = 'lora-row';
  const select = document.createElement('select'); select.setAttribute('aria-label', 'Файл LoRA');
  optionalSelect(select, status.components?.loras, 'Выберите LoRA'); select.value = name;
  const input = document.createElement('input'); input.type = 'number'; input.min = '-2'; input.max = '2'; input.step = '0.1'; input.value = strength; input.setAttribute('aria-label', 'Сила LoRA');
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'text-button'; remove.textContent = 'Убрать'; remove.onclick = () => row.remove();
  row.append(select, input, remove); $('lora-list').append(row);
}
function componentParameters() {
  return {family: $('family').value, loader: $('loader').value, vae: $('vae').value, clip1: $('clip1').value, clip2: $('clip2').value, guidance: Number($('guidance').value),
    loras: [...$('lora-list').children].filter(row => row.querySelector('select').value).map(row => ({name: row.querySelector('select').value, strength: Number(row.querySelector('input').value)}))};
}
function restoreParameters(record) {
  $('family').value = record.family || 'sdxl'; $('loader').value = record.loader || 'split'; syncComponents();
  ['prompt','negative','steps','cfg','seed','model','controlnet','vae','clip1','clip2','guidance'].forEach(k => {if (record[k] !== undefined) $(k).value = record[k];});
  $('lora-list').replaceChildren(); (record.loras || []).forEach(item => loraRow(item.name, item.strength));
  syncModelFormats(); updateGenerate();
}
$('family').addEventListener('change', () => {
  const defaults = status.families?.[$('family').value];
  if (defaults) { $('steps').value = defaults[1]; $('cfg').value = defaults[2]; }
  $('guidance').value = $('family').value === 'flux-schnell' ? 0 : 3.5;
  if ($('family').value.startsWith('custom:')) $('model').value = '';
  syncComponents();
});
$('loader').addEventListener('change', syncComponents);
$('add-lora').addEventListener('click', () => loraRow());
$('preset').addEventListener('change', () => {const item = status.presets?.[Number($('preset').value)]; if ($('preset').value !== '' && item) restoreParameters(item.parameters);});
$('save-preset').addEventListener('click', async () => {
  const name = window.prompt('Название набора моделей и параметров'); if (!name?.trim()) return;
  try { await api('preset', {name, parameters: {...componentParameters(), model: $('model').value, steps: Number($('steps').value), cfg: Number($('cfg').value)}}); await refreshStatus(); notify('Набор сохранён. Теперь он доступен в списке «Мой набор».'); } catch (e) { notify(e.message); }
});
$('import-profile').addEventListener('click', () => $('profile-file').click());
$('profile-file').addEventListener('change', async () => {
  try {
    const file = $('profile-file').files[0]; if (!file) return;
    if (file.size > 2 * 1024 ** 2) throw new Error('Профиль должен быть меньше 2 МБ.');
    const result = await api('profile', JSON.parse(await file.text()));
    await refreshStatus(); $('family').value = 'custom:' + result.id; $('model').value = ''; syncComponents();
    $('profile-status').textContent = 'Добавлен профиль «' + result.name + '». Выбран в студии.';
  } catch (e) { $('profile-status').textContent = 'Профиль не добавлен: ' + e.message; }
  finally { $('profile-file').value = ''; }
});
$('update-app').addEventListener('click', async () => {
  try { await api('update', {}); $('update-status').textContent = 'Открыто окно обновления. Дождитесь закрытия окна запуска EasyPhoto и нажмите в обновлении «Проверить обновления».'; $('update-app').disabled = true; }
  catch (e) { $('update-status').textContent = e.message; }
});
(async () => {
  try {
    token = (await api('session')).token;
    await refreshStatus(); await loadHistory(false);
    const saved = localStorage.getItem('easyphoto-job');
    if (saved) {job = {id: saved}; running = true; $('busy').hidden = false; updateGenerate(); pollJob();}
    setInterval(refreshStatus, 6000);
  } catch (e) {notify('Не удалось подключиться к приложению: ' + e.message);}
})();
