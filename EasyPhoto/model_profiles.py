"""Model-family recipes and portable, explicit bindings for Comfy API workflows."""
import copy
import math
import re

FAMILIES = {
    'sdxl': ('SDXL', 25, 6), 'sd15': ('SD 1.5', 25, 6),
    'sd-turbo': ('SD Turbo', 1, 1), 'sdxl-turbo': ('SDXL Turbo', 4, 1),
    'flux-dev': ('FLUX.1 Dev', 20, 1), 'flux-schnell': ('FLUX.1 Schnell', 4, 1),
}
CATEGORIES = {
    'checkpoints': ('CheckpointLoaderSimple', 'ckpt_name'),
    'diffusion_models': ('UNETLoader', 'unet_name'), 'vae': ('VAELoader', 'vae_name'),
    'loras': ('LoraLoader', 'lora_name'), 'text_encoders': ('CLIPLoader', 'clip_name'),
    'controlnet': ('ControlNetLoader', 'control_net_name'),
}


def choices(info, node, field):
    spec = info.get(node, {}).get('input', {}).get('required', {}).get(field, [[]])[0]
    return spec if isinstance(spec, list) else []


def components(info):
    result = {key: choices(info, *spec) for key, spec in CATEGORIES.items()}
    # Some engines expose dual encoders separately from CLIPLoader.
    result['text_encoders'] = sorted(set(result['text_encoders'] + choices(info, 'DualCLIPLoader', 'clip_name1')))
    return result


def selected(info, node, field, value, label):
    if value not in choices(info, node, field):
        raise ValueError('Выберите установленный ' + label + '. Проверьте категорию файла в «Моделях».')
    return value


def number(value, low, high, label):
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(label + ': нужно число.') from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(label + ': недопустимое значение.')
    return value


def adapt(graph, p, info):
    family = p.get('family', 'sdxl')
    if family not in FAMILIES:
        raise ValueError('Выберите семейство модели или импортированный профиль.')
    flux = family.startswith('flux-')
    model, clip, vae = ['1', 0], ['1', 1], ['1', 2]
    if flux and p.get('loader', 'split') == 'split':
        graph['1'] = {'class_type': 'UNETLoader', 'inputs': {
            'unet_name': selected(info, 'UNETLoader', 'unet_name', p.get('model'), 'diffusion model'), 'weight_dtype': 'default'}}
        graph['20'] = {'class_type': 'DualCLIPLoader', 'inputs': {
            'clip_name1': selected(info, 'DualCLIPLoader', 'clip_name1', p.get('clip1'), 'CLIP-L'),
            'clip_name2': selected(info, 'DualCLIPLoader', 'clip_name2', p.get('clip2'), 'T5'), 'type': 'flux'}}
        clip = ['20', 0]
        if not p.get('vae'):
            raise ValueError('Для отдельного FLUX выберите VAE (обычно ae.safetensors).')
    elif p.get('clip1'):
        dual = flux or 'sdxl' in family
        if dual:
            graph['20'] = {'class_type': 'DualCLIPLoader', 'inputs': {
                'clip_name1': selected(info, 'DualCLIPLoader', 'clip_name1', p['clip1'], 'первый текстовый энкодер'),
                'clip_name2': selected(info, 'DualCLIPLoader', 'clip_name2', p.get('clip2'), 'второй текстовый энкодер'),
                'type': 'flux' if flux else 'sdxl'}}
        else:
            graph['20'] = {'class_type': 'CLIPLoader', 'inputs': {
                'clip_name': selected(info, 'CLIPLoader', 'clip_name', p['clip1'], 'текстовый энкодер'),
                'type': 'stable_diffusion'}}
        clip = ['20', 0]
    if p.get('vae'):
        graph['21'] = {'class_type': 'VAELoader', 'inputs': {'vae_name': selected(info, 'VAELoader', 'vae_name', p['vae'], 'VAE')}}
        vae = ['21', 0]
    loras = p.get('loras', [])
    if not isinstance(loras, list) or len(loras) > 8:
        raise ValueError('Можно подключить до восьми LoRA.')
    for index, item in enumerate(loras):
        key = str(30 + index)
        graph[key] = {'class_type': 'LoraLoader', 'inputs': {
            'model': model, 'clip': clip,
            'lora_name': selected(info, 'LoraLoader', 'lora_name', item.get('name'), 'LoRA'),
            'strength_model': number(item.get('strength', 1), -2, 2, 'Сила LoRA'),
            'strength_clip': number(item.get('strength_clip', item.get('strength', 1)), -2, 2, 'Сила LoRA CLIP')}}
        model, clip = [key, 0], [key, 1]
    graph['2']['inputs']['clip'] = clip
    graph['3']['inputs']['clip'] = clip
    graph['6']['inputs']['vae'] = vae
    if 'vae' in graph['4']['inputs']:
        graph['4']['inputs']['vae'] = vae
    if p.get('mode') == 'pose':
        if flux:
            raise ValueError('Для FLUX ControlNet импортируйте профиль совместимого workflow. Встроенная «Поза» — для SD.')
        graph['10']['inputs']['vae'] = vae
    sampler = graph['5']['inputs']
    sampler['model'] = model
    if flux:
        if graph['4']['class_type'] == 'EmptyLatentImage':
            graph['4']['class_type'] = 'EmptySD3LatentImage'
        sampler.update(cfg=1.0, sampler_name='euler', scheduler='simple')
        graph['22'] = {'class_type': 'FluxGuidance', 'inputs': {'conditioning': ['2', 0],
            'guidance': number(p.get('guidance', 3.5 if family == 'flux-dev' else 0), 0, 20, 'Guidance')}}
        sampler['positive'] = ['22', 0]
    if family.endswith('turbo'):
        if not 1 <= sampler['steps'] <= 10:
            raise ValueError('Turbo: выберите от 1 до 10 шагов.')
        # SDTurboScheduler produces the noise schedule required by distilled SD models.
        graph['22'] = {'class_type': 'SDTurboScheduler', 'inputs': {'model': model, 'steps': sampler['steps'], 'denoise': sampler['denoise']}}
        graph['23'] = {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler_ancestral'}}
        graph['5'] = {'class_type': 'SamplerCustom', 'inputs': {
            'model': model, 'add_noise': True, 'noise_seed': sampler['seed'], 'cfg': 1.0,
            'positive': sampler['positive'], 'negative': sampler['negative'],
            'sampler': ['23', 0], 'sigmas': ['22', 0], 'latent_image': sampler['latent_image']}}
    # Legacy contract doubles only include loaders; real engines expose KSampler.
    if 'KSampler' in info:
        missing = sorted({n['class_type'] for n in graph.values()} - info.keys())
        if missing:
            raise ValueError('В движке отсутствуют узлы: ' + ', '.join(missing) + '. Нужен совместимый движок/профиль.')
    return graph


BINDINGS = frozenset(('prompt', 'negative', 'seed', 'steps', 'cfg', 'width', 'height', 'image',
                      'model', 'vae', 'clip1', 'clip2', 'guidance'))


def validate_profile(value):
    if not isinstance(value, dict) or not isinstance(value.get('workflow'), dict):
        raise ValueError('Нужен JSON-профиль с workflow в API-формате и bindings. Пример есть в инструкции.')
    graph = value['workflow']
    if not 1 <= len(graph) <= 200:
        raise ValueError('Профиль должен содержать от 1 до 200 узлов.')
    for key, node in graph.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key) or not isinstance(node, dict) or not isinstance(node.get('inputs'), dict) or not isinstance(node.get('class_type'), str):
            raise ValueError('Некорректный API workflow.')
    bindings = value.get('bindings', {})
    if not isinstance(bindings, dict) or set(bindings) - BINDINGS:
        raise ValueError('Неизвестное поле bindings.')
    for field, targets in bindings.items():
        if not isinstance(targets, list) or not targets:
            raise ValueError('Каждый binding — список пар [node_id, input_name].')
        for target in targets:
            if not isinstance(target, list) or len(target) != 2 or target[0] not in graph or target[1] not in graph[target[0]]['inputs']:
                raise ValueError('Binding указывает на отсутствующий вход: ' + field)
    if 'prompt' not in bindings:
        raise ValueError('Укажите binding prompt для описания кадра.')
    name = str(value.get('name', 'Мой профиль')).strip()[:80]
    return {'name': name or 'Мой профиль', 'workflow': graph, 'bindings': bindings}


def custom_workflow(profile, p, info, upload):
    profile = validate_profile(profile)
    graph = copy.deepcopy(profile['workflow'])
    missing = sorted({node['class_type'] for node in graph.values()} - info.keys())
    if missing:
        raise ValueError('Профилю нужны узлы движка: ' + ', '.join(missing))
    if p.get('mode', 'create') != 'create' and 'image' not in profile['bindings']:
        raise ValueError('Этот профиль не содержит входа image для редактирования.')
    if p.get('mask') or p.get('mode') == 'pose':
        raise ValueError('Кисть и поза в импортированном профиле настраиваются внутри самого workflow.')
    for field, targets in profile['bindings'].items():
        value = p.get(field)
        if field == 'image' and value:
            value = upload(value, 'source')
        if value in (None, ''):
            continue
        for node, input_name in targets:
            graph[node]['inputs'][input_name] = value
    for node in graph.values():
        required = info[node['class_type']].get('input', {}).get('required', {})
        for field, value in node['inputs'].items():
            spec = required.get(field)
            if spec and isinstance(spec[0], list) and not isinstance(value, list) and value not in spec[0]:
                raise ValueError('Профиль: недоступное значение ' + field + ': ' + str(value))
    return graph
