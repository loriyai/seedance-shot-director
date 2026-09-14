import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

import compile_plan as c
from project_state import ProjectState, digest


EXAMPLES = Path(__file__).resolve().parent.parent / 'references'
SOURCE = (EXAMPLES / 'plan-example-source.txt').read_bytes().decode('utf-8')


def example_plan(store):
    plan = json.loads((EXAMPLES / 'plan-example.json').read_text(encoding='utf-8'))
    source = store.source('seg001')
    plan.update(source_version=source['version'], source_sha256=source['sha256'],
                config_sha256=digest(c.canonical(store.read()['config'])))
    return plan


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(os.environ.get('SEEDANCE_TEST_TMP', tempfile.gettempdir())).resolve()
        self.project = self.temp_root / ('seedance-v113-' + uuid.uuid4().hex)
        self.project.mkdir()
        self.store = ProjectState(self.project)
        self.store.init('story')
        self.store.ingest('seg001', SOURCE)
        self.store.config({'model': '2.0', 'target_duration': 15})
        self.store.use_original('seg001')

    def tearDown(self):
        self.assertEqual(self.project.resolve().parent, self.temp_root)
        shutil.rmtree(self.project)

    def review_result(self, result, passed=True):
        return {'plan_sha256': result['plan_sha256'], 'prompt_sha256': result['prompt_sha256'],
                'passed': passed, 'note': '已核对来源动作、台词身份、出门过程与观看重点。',
                'warnings_reviewed': [i for i, d in enumerate(result['diagnostics']) if d['level'] == 'WARN']}

    def test_compilation_and_finalization_share_plan_and_check_once(self):
        plan = example_plan(self.store)
        with patch.object(c, 'validate', wraps=c.validate) as validator:
            result = c.compile_project(self.project, 'seg001', plan)
            self.assertEqual(result['diagnostics'], [])
            self.assertEqual(result['status'], 'needs_semantic_review')
            self.assertIsNone(self.store.read()['segments']['seg001']['ledger'])
            text = Path(result['prompt']).read_text(encoding='utf-8')
            self.assertEqual(text.count('明日出发。'), 1)
            self.assertEqual(text.count('[镜头'), 5)
            c.finalize(self.project, 'seg001', result['build'], self.review_result(result))
            self.assertEqual(validator.call_count, 1)
        ledger = self.store.read()['segments']['seg001']['ledger']
        self.assertEqual(ledger['plan'], plan)
        self.assertEqual(ledger['status'], 'passed')

    def test_changed_dialogue_and_missing_shots_cannot_be_finalized(self):
        for mutation in ('dialogue', 'shots'):
            plan = example_plan(self.store)
            if mutation == 'dialogue':
                plan['blocks'][0]['voices'][0]['text'] = '今日出发。'
            else:
                plan['blocks'][0]['shots'].pop()
            result = c.compile_project(self.project, 'seg001', plan)
            self.assertGreater(result['errors'], 0)
            with self.assertRaises(ValueError):
                c.finalize(self.project, 'seg001', result['build'], self.review_result(result))

    def test_span_split_keeps_source_once_and_rejects_duplicate(self):
        plan = example_plan(self.store)
        voice = plan['blocks'][0]['voices'][0]
        voice.update(start=2.4, end=3.5)
        shots = plan['blocks'][0]['shots']
        shots[0]['speech'] = [{'voice': 'V1', 'span': [0, 2]}]
        shots[1]['speech'].insert(0, {'voice': 'V1', 'span': [2, 5]})
        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        self.assertIn('：“明日”', rendered)
        self.assertIn('：“出发。”', rendered)
        shots[1]['speech'][0]['span'] = [0, 5]
        with self.assertRaises(ValueError): c.render(plan, SOURCE, self.store.read()['config'])

    def test_unknown_field_and_unmapped_beat_are_rejected(self):
        for mutation in ('unknown', 'unmapped', 'foreign_evidence'):
            plan = example_plan(self.store)
            if mutation == 'unknown': plan['blocks'][0]['shots'][0]['dialog'] = '静默丢失的台词'
            elif mutation == 'unmapped': plan['beats'].append({'id': 'E5', 'evidence': '林舟把信放在桌上。'})
            else: plan['beats'][0]['evidence'] = '林舟拔剑攻击。'
            with self.assertRaises(ValueError): c.compile_project(self.project, 'seg001', plan)

    def test_warning_requires_review_without_rerunning_checks(self):
        plan = example_plan(self.store)
        plan['blocks'][0]['voices'][0]['pause'] = None
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertEqual(result['errors'], 0)
        self.assertGreater(result['warnings'], 0)
        review = self.review_result(result)
        review['warnings_reviewed'] = []
        with self.assertRaises(ValueError): c.finalize(self.project, 'seg001', result['build'], review)
        result = c.finalize(self.project, 'seg001', result['build'], self.review_result(result))
        self.assertEqual(result['status'], 'passed')

    def test_semantic_problem_is_not_automatically_marked_passed(self):
        result = c.compile_project(self.project, 'seg001', example_plan(self.store))
        review = self.review_result(result, False)
        review['note'] = '动作路径仍需修正。'
        self.assertEqual(c.finalize(self.project, 'seg001', result['build'], review)['status'], 'semantic_blocked')

    def test_source_config_and_review_hash_invalidate_candidate(self):
        result = c.compile_project(self.project, 'seg001', example_plan(self.store))
        bad_review = self.review_result(result)
        bad_review['prompt_sha256'] = 'wrong'
        with self.assertRaises(ValueError): c.finalize(self.project, 'seg001', result['build'], bad_review)
        self.store.config({'music': 'source'})
        with self.assertRaises(ValueError): c.finalize(self.project, 'seg001', result['build'], self.review_result(result))
        self.store.config({'music': 'none'})
        self.store.revise('seg001', SOURCE + '\n天色渐暗。', '用户补充结尾')
        self.store.use_original('seg001')
        with self.assertRaises(ValueError): c.finalize(self.project, 'seg001', result['build'], self.review_result(result))

    def test_tampered_prompt_and_diagnostics_are_rejected(self):
        result = c.compile_project(self.project, 'seg001', example_plan(self.store))
        prompt = Path(result['prompt'])
        old = prompt.read_bytes()
        prompt.write_bytes(old + '篡改'.encode())
        with self.assertRaises(ValueError): c.finalize(self.project, 'seg001', result['build'], self.review_result(result))
        prompt.write_bytes(old)
        ledger_path = Path(result['ledger'])
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
        ledger['diagnostics'] = [{'level': 'WARN', 'message': '伪造'}]
        ledger_path.write_text(c.canonical(ledger), encoding='utf-8')
        with self.assertRaises(ValueError): c.finalize(self.project, 'seg001', result['build'], self.review_result(result))

    def test_stale_plan_cannot_compile(self):
        plan = example_plan(self.store)
        self.store.config({'music': 'source'})
        with self.assertRaises(ValueError): c.compile_project(self.project, 'seg001', plan)

    def test_rebalanced_short_tail_expands_each_block_header(self):
        revised = '林舟把信放在桌上。\n林舟：「明日出发。」\n两人走出院门。\n沈遥：「我在南门等你。」'
        self.store.revise('seg001', revised, '用户调整回应顺序')
        self.store.use_original('seg001')
        plan = example_plan(self.store)
        first = plan['blocks'][0]
        second_voice = first['voices'].pop()
        second_voice.update(start=0.5, end=2.2)
        first['duration'], first['ending'] = 13, '连续剪辑'
        first['shots'].pop(1)
        for index, shot in enumerate(first['shots']):
            shot['start'], shot['end'] = index * 3, (index + 1) * 3 if index < 3 else 13
        plan['blocks'].append({'duration': 4, 'entry': first['exit'], 'exit': '沈遥站在门外，林舟在旁。',
            'header': {'scene': '院门外道路，院门在人物身后', 'atmosphere': '日光平稳，沈遥在林舟右侧'},
            'voices': [second_voice], 'shots': [{'start': 0, 'end': 4, 'beats': ['E3'],
                'action': '沈遥停在院门外，朝身旁林舟说话。', 'camera': '双人中景，门外侧面平视，固定机位。',
                'speech': [{'voice': 'V2'}]}]})
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertEqual(result['diagnostics'], [])
        prompt = Path(result['prompt']).read_text(encoding='utf-8')
        self.assertEqual(prompt.count('人物：'), 2)
        self.assertEqual(prompt.count('国风二维动画，线条清晰'), 2)
        self.assertIn('生成块 02｜4秒', prompt)
        self.assertIn('场景：院门外道路', prompt)

    def test_thirty_second_plan_and_model_cap(self):
        self.store.config({'model': '2.5', 'target_duration': 30})
        plan = example_plan(self.store)
        block = plan['blocks'][0]
        block['duration'] = 30
        template = copy.deepcopy(block['shots'][-1])
        for i in range(5, 10):
            shot = copy.deepcopy(template)
            shot.update(start=i * 3, end=(i + 1) * 3)
            block['shots'].append(shot)
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertEqual(result['diagnostics'], [])
        self.store.config({'model': '2.0'})
        plan['config_sha256'] = digest(c.canonical(self.store.read()['config']))
        self.assertGreater(c.compile_project(self.project, 'seg001', plan)['errors'], 0)

    def patch_payload(self, edits):
        segment = self.store.read()['segments']['seg001']
        version = segment['review']
        return {'review_version': version, 'review_sha256': segment['versions'][version]['sha256'], 'edits': edits}

    def test_review_patch_preserves_complete_versions_and_exact_newlines(self):
        original = '第一段\r\n林舟放下书信。\r\n末段保持。'
        self.store.review('seg001', original)
        payload = self.patch_payload([{'old': '林舟放下书信。', 'new': '🟦【细节增强：原“林舟放下书信。”】林舟将书信平放桌面，手掌离开信纸。'}])
        result = self.store.review_patch('seg001', payload)
        self.assertEqual(result['version'], 'R2')
        context = ProjectState(self.project).review_context('seg001')
        self.assertEqual(context['sha256'], result['sha256'])
        self.assertEqual(context['version'], 'R2')
        text = Path(result['path']).read_bytes().decode('utf-8')
        self.assertTrue(text.startswith('第一段\r\n'))
        self.assertTrue(text.endswith('\r\n末段保持。'))
        segment = self.store.read()['segments']['seg001']
        self.assertEqual(self.store.verified_text(segment['versions']['R1']), original)
        with self.assertRaises(ValueError): self.store.source('seg001')

    def test_ambiguous_overlapping_and_stale_review_patches_rejected(self):
        self.store.review('seg001', '甲乙丙。甲乙丙。唯一段落。')
        bad_edits = [[{'old': '甲乙丙', 'new': '新'}],
                     [{'old': '唯一段落', 'new': '新'}, {'old': '段落', 'new': '旧'}]]
        for edits in bad_edits:
            with self.assertRaises(ValueError): self.store.review_patch('seg001', self.patch_payload(edits))
        payload = self.patch_payload([{'old': '唯一段落', 'new': '更新段落'}])
        self.store.review_patch('seg001', payload)
        with self.assertRaises(ValueError): self.store.review_patch('seg001', payload)

    def test_noop_patch_does_not_create_new_version(self):
        self.store.review('seg001', '原稿。')
        result = self.store.review_patch('seg001', self.patch_payload([{'old': '原稿。', 'new': '原稿。'}]))
        self.assertFalse(result['changed'])
        self.assertEqual(result['version'], 'R1')

    def test_global_index_is_validated_against_baseline_and_invalidated_by_revision(self):
        segment = self.store.read()['segments']['seg001']
        data = {'source_version': 'V0', 'source_sha256': segment['versions']['V0']['sha256'],
                'characters': ['林舟', '沈遥'], 'relationships': [], 'scenes': ['院内'], 'key_props': ['书信'],
                'timeline': ['约定明日出发'], 'foreshadowing': [], 'unknowns': []}
        self.store.story_index('seg001', data)
        self.store.revise('seg001', SOURCE + '\n书信随后被烧毁。', '用户修订')
        self.assertEqual(self.store.read()['segments']['seg001']['index_status'], 'stale')
        with self.assertRaises(ValueError): self.store.story_index('seg001', data)


if __name__ == '__main__':
    unittest.main()
