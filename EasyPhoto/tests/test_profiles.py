import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app


def loader(field, values):
    return {'input': {'required': {field: [values]}}}


INFO = {
    'CheckpointLoaderSimple': loader('ckpt_name', ['full.safetensors']),
    'UNETLoader': loader('unet_name', ['flux.safetensors']),
    'DualCLIPLoader': {'input': {'required': {'clip_name1': [['clip.safetensors', 't5.safetensors']], 'clip_name2': [['clip.safetensors', 't5.safetensors']]}}},
    'CLIPLoader': loader('clip_name', ['clip.safetensors']),
    'VAELoader': loader('vae_name', ['ae.safetensors']),
    'LoraLoader': loader('lora_name', ['style.safetensors']),
}


class ProfileTests(unittest.TestCase):
    def test_split_flux_connects_both_encoders_and_external_vae(self):
        graph, seed = app.workflow(dict(prompt='a cabin', family='flux-dev', model='flux.safetensors',
            clip1='clip.safetensors', clip2='t5.safetensors', vae='ae.safetensors'), INFO)
        self.assertEqual(graph['1']['class_type'], 'UNETLoader')
        self.assertEqual(graph['20']['inputs']['type'], 'flux')
        self.assertEqual(graph['4']['class_type'], 'EmptySD3LatentImage')
        self.assertEqual(graph['5']['inputs']['cfg'], 1)
        self.assertEqual(graph['6']['inputs']['vae'], ['21', 0])
        self.assertEqual(graph['22']['inputs']['guidance'], 3.5)

    def test_split_flux_requires_vae(self):
        with self.assertRaisesRegex(ValueError, 'VAE'):
            app.workflow(dict(prompt='x', family='flux-schnell', model='flux.safetensors',
                clip1='clip.safetensors', clip2='t5.safetensors'), INFO)

    def test_turbo_uses_short_sigma_schedule(self):
        graph, _ = app.workflow(dict(prompt='x', family='sd-turbo', model='full.safetensors'), INFO)
        self.assertEqual(graph['5']['class_type'], 'SamplerCustom')
        self.assertEqual(graph['22']['class_type'], 'SDTurboScheduler')
        self.assertEqual(graph['22']['inputs']['steps'], 1)

    def test_lora_chain_preserves_connections(self):
        graph, _ = app.workflow(dict(prompt='x', model='full.safetensors', vae='ae.safetensors',
            loras=[{'name': 'style.safetensors', 'strength': .5}, {'name': 'style.safetensors', 'strength': .8}]), INFO)
        self.assertEqual(graph['31']['inputs']['model'], ['30', 0])
        self.assertEqual(graph['5']['inputs']['model'], ['31', 0])
        self.assertEqual(graph['2']['inputs']['clip'], ['31', 1])

    def test_sdxl_external_encoders_use_dual_loader(self):
        graph, _ = app.workflow(dict(prompt='x', model='full.safetensors', family='sdxl',
            clip1='clip.safetensors', clip2='t5.safetensors'), INFO)
        self.assertEqual(graph['20']['inputs']['type'], 'sdxl')

    def test_custom_profile_binds_prompt_without_changing_saved_graph(self):
        profile = {'name': 'future architecture', 'workflow': {'p': {'class_type': 'FutureNode', 'inputs': {'text': 'original'}}}, 'bindings': {'prompt': [['p', 'text']]}}
        graph = app.profiles.custom_workflow(profile, {'prompt': 'my picture'}, {'FutureNode': {}}, None)
        self.assertEqual(graph['p']['inputs']['text'], 'my picture')
        self.assertEqual(profile['workflow']['p']['inputs']['text'], 'original')

    def test_custom_profile_missing_nodes_has_actionable_error(self):
        profile = {'workflow': {'p': {'class_type': 'Missing', 'inputs': {'text': 'x'}}}, 'bindings': {'prompt': [['p','text']]}}
        with self.assertRaisesRegex(ValueError, 'Missing'):
            app.profiles.custom_workflow(profile, {'prompt': 'my picture'}, {}, None)

    def test_custom_profile_rejects_invalid_binding(self):
        with self.assertRaises(ValueError):
            app.profiles.validate_profile({'workflow': {'p': {'class_type': 'x', 'inputs': {}}}, 'bindings': {'prompt': [['outside','text']]}})


if __name__ == '__main__':
    unittest.main()
