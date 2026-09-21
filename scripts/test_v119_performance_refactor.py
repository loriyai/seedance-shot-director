import json
import os
from pathlib import Path
import copy
import shutil
import tempfile
import unittest
import uuid

import compile_plan as c
from project_state import ProjectState, digest


REFERENCES = Path(__file__).resolve().parent.parent / 'references'
SOURCE = (REFERENCES / 'plan-example-source.txt').read_bytes().decode('utf-8')


def compact_plan(store):
    plan = json.loads((REFERENCES / 'plan-example.json').read_text(encoding='utf-8'))
    source = store.source('seg001')
    plan.update(schema_version=5, source_version=source['version'], source_sha256=source['sha256'],
                config_sha256=digest(c.canonical(store.read()['config'])))
    block = plan['blocks'][0]
    block.pop('entry')
    block.pop('exit')
    block['ambient_effects'] = [
        {'type': '环境声', 'text': '院内轻微环境底声', 'provenance': 'scene_ambient', 'basis': 'scene'}
    ]
    for voice in block['voices']:
        voice.pop('pause')
        voice.pop('profile')
    for shot in block['shots']:
        shot.pop('action_basis')
        shot.pop('effects')
    return plan


class V119PerformanceRefactorTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(os.environ.get('SEEDANCE_TEST_TMP', tempfile.gettempdir())).resolve()
        self.project = self.temp_root / ('seedance-v119-' + uuid.uuid4().hex)
        self.project.mkdir()
        self.store = ProjectState(self.project)
        self.store.init('story')
        self.store.ingest('seg001', SOURCE)
        self.store.config({'model': '2.0', 'target_duration': 15})
        self.store.use_original('seg001')

    def tearDown(self):
        self.assertEqual(self.project.resolve().parent, self.temp_root)
        shutil.rmtree(self.project)

    def semantic_review(self, result):
        return {
            'plan_sha256': result['plan_sha256'],
            'prompt_sha256': result['prompt_sha256'],
            'passed': True,
            'note': '已仅复核来源覆盖、动作因果、空间、画面可读性与声音来源。',
            'warnings_reviewed': list(result['warning_groups']),
            'checks': {name: True for name in c.V5_SEMANTIC_CHECKS},
        }

    def test_v5_compact_defaults_render_and_finalize(self):
        plan = compact_plan(self.store)
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertEqual(result['errors'], 0)
        prompt = Path(result['prompt']).read_text(encoding='utf-8')
        self.assertEqual(sum(1 for text in prompt.splitlines() if text.startswith('[')), 5)
        self.assertEqual(prompt.count('院内轻微环境底声'), 5)
        self.assertIn('禁止项：', prompt)
        self.assertEqual(result['stats']['total_shots'], 5)
        self.assertEqual(c.finalize(self.project, 'seg001', result['build'], self.semantic_review(result))['status'], 'passed')

    def test_v5_compaction_preserves_equivalent_direct_prompt(self):
        v4 = json.loads((REFERENCES / 'plan-example.json').read_text(encoding='utf-8'))
        ambient = {
            'type': '环境声', 'text': '院内轻微环境底声',
            'provenance': 'scene_ambient', 'basis': 'scene',
        }
        for shot in v4['blocks'][0]['shots']:
            local = [effect for effect in shot['effects'] if effect['provenance'] != 'scene_ambient']
            shot['effects'] = [copy.deepcopy(ambient), *local]

        v5 = copy.deepcopy(v4)
        v5['schema_version'] = 5
        block = v5['blocks'][0]
        block['ambient_effects'] = [copy.deepcopy(ambient)]
        block.pop('entry')
        block.pop('exit')
        for voice in block['voices']:
            if voice['profile'] == c.DEFAULT_VOICE_PROFILE:
                voice.pop('profile')
            if voice['pause'] == c.DEFAULT_VOICE_PAUSE:
                voice.pop('pause')
        for shot in block['shots']:
            shot.pop('action_basis')
            local = [effect for effect in shot['effects'] if effect['provenance'] != 'scene_ambient']
            if local:
                shot['effects'] = local
            else:
                shot.pop('effects')

        config = self.store.read()['config']
        # V5省略entry/exit后由首末镜动作派生，审计视图只差派生出的尾帧说明一行。
        def stable(text):
            return '\n'.join(line for line in text.splitlines() if not line.startswith('无对白尾帧：'))
        self.assertEqual(stable(c.render(v4, SOURCE, config, audit=True)),
                         stable(c.render(v5, SOURCE, config, audit=True)))
        v4_direct, v5_direct = c.render(v4, SOURCE, config), c.render(v5, SOURCE, config)
        for text in ('明日出发。', '我在南门等你。', '院内轻微环境底声'):
            self.assertEqual(v4_direct.count(text), v5_direct.count(text))

    def test_documented_v5_example_is_executable(self):
        plan = json.loads((REFERENCES / 'plan-example-v5.json').read_text(encoding='utf-8'))
        source = self.store.source('seg001')
        plan.update(source_version=source['version'], source_sha256=source['sha256'],
                    config_sha256=digest(c.canonical(self.store.read()['config'])))
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertEqual(result['errors'], 0)
        prompt = Path(result['prompt']).read_text(encoding='utf-8')
        self.assertEqual(sum(1 for text in prompt.splitlines() if text.startswith('[')), 5)
        self.assertIn('林舟的中景', prompt)

    def test_screen_text_stays_out_of_dialogue(self):
        plan = json.loads((REFERENCES / 'plan-example-v5.json').read_text(encoding='utf-8'))
        source = self.store.source('seg001')
        plan.update(source_version=source['version'], source_sha256=source['sha256'],
                    config_sha256=digest(c.canonical(self.store.read()['config'])))
        plan['blocks'][0]['shots'][0]['screen_text'] = '匾额上的“义”字'
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertEqual(result['errors'], 0)
        prompt = Path(result['prompt']).read_text(encoding='utf-8')
        self.assertIn('画面文字：【匾额上的“义”字】', prompt)

    def test_v5_still_enforces_five_shots_and_five_second_maximum(self):
        plan = compact_plan(self.store)
        plan['blocks'][0]['shots'].pop()
        with self.assertRaisesRegex(ValueError, '5镜'):
            c.render(plan, SOURCE, self.store.read()['config'])
        plan = compact_plan(self.store)
        plan['blocks'][0]['shots'][0]['end'] = 6
        with self.assertRaisesRegex(ValueError, '5秒'):
            c.render(plan, SOURCE, self.store.read()['config'])

    def test_v5_warning_categories_replace_index_bookkeeping(self):
        plan = compact_plan(self.store)
        plan['blocks'][0]['voices'][0]['pause'] = None
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertGreater(result['warnings'], 0)
        self.assertIn('dialogue_delivery', result['warning_groups'])
        bad = self.semantic_review(result)
        bad['warnings_reviewed'] = []
        with self.assertRaisesRegex(ValueError, '警告类别'):
            c.finalize(self.project, 'seg001', result['build'], bad)
        legacy_index = self.semantic_review(result)
        legacy_index['warnings_reviewed'] = [0]
        with self.assertRaisesRegex(ValueError, '类别名'):
            c.finalize(self.project, 'seg001', result['build'], legacy_index)
        self.assertEqual(c.finalize(self.project, 'seg001', result['build'], self.semantic_review(result))['status'], 'passed')

    def test_v5_explicit_silence_conflicts_with_reusable_ambience(self):
        forms = [
            ['静默'],
            [{'type': '静默', 'text': '静默'}],
            [{'type': '静默', 'text': '静默', 'provenance': 'scene_ambient', 'basis': 'scene'}],
        ]
        for effects in forms:
            with self.subTest(effects=effects):
                plan = compact_plan(self.store)
                plan['blocks'][0]['shots'][0]['effects'] = effects
                with self.assertRaisesRegex(ValueError, 'ambient_effects'):
                    c.render(plan, SOURCE, self.store.read()['config'])

    def test_identical_review_reuses_version_and_history_audit_is_explicit(self):
        self.assertEqual(self.store.review('seg001', '审阅一。'), 'R1')
        self.assertEqual(self.store.review('seg001', '审阅一。'), 'R1')
        self.assertEqual(self.store.review('seg001', '审阅二。'), 'R2')
        segment = self.store.read()['segments']['seg001']
        old_review = self.store.path(segment['versions']['R1']['path'])
        old_review.write_text('历史文件被改动。', encoding='utf-8')
        self.assertEqual(self.store.review_context('seg001')['version'], 'R2')
        with self.assertRaisesRegex(ValueError, '摘要不一致'):
            self.store.verify_history('seg001')

    def test_context_announces_compact_schema_and_semantic_checks(self):
        self.assertEqual(c.V5_SEMANTIC_CHECKS, tuple(c.V5_SEMANTIC_CHECKS))
        self.assertEqual(len(c.V5_SEMANTIC_CHECKS), 5)


if __name__ == '__main__':
    unittest.main()
