import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

import compile_plan as compiler
from project_state import ProjectState, digest


REFERENCES = Path(__file__).resolve().parent.parent / 'references'
SOURCE = (REFERENCES / 'plan-example-source.txt').read_text(encoding='utf-8')
EXTENDED_SOURCE = SOURCE.rstrip() + '\n林舟：「还有后话。」\n'


class IncrementalBlockCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(os.environ.get('SEEDANCE_TEST_TMP', tempfile.gettempdir())).resolve()
        self.project = self.temp_root / ('seedance-incremental-' + uuid.uuid4().hex)
        self.project.mkdir()
        self.store = ProjectState(self.project)
        self.store.init('incremental-test')
        self.store.ingest('seg001', EXTENDED_SOURCE)
        self.store.config({'model': '2.0', 'target_duration': 15})
        self.store.use_original('seg001')
        self.plan = json.loads((REFERENCES / 'plan-example-v5.json').read_text(encoding='utf-8'))
        source = self.store.source('seg001')
        self.plan.update(source_version=source['version'], source_sha256=source['sha256'],
                         config_sha256=digest(compiler.canonical(self.store.read()['config'])))

    def tearDown(self):
        self.assertEqual(self.project.resolve().parent, self.temp_root)
        shutil.rmtree(self.project)

    def test_prefix_check_is_read_only_and_does_not_claim_source_coverage(self):
        state_path = self.store.path('state.json')
        before = state_path.read_bytes()
        result = compiler.check_block(self.project, 'seg001', self.plan)
        self.assertEqual(result['status'], 'provisional')
        self.assertFalse(result['boundary_confirmed'])
        self.assertEqual(result['errors'], 0)
        self.assertEqual(result['shot_count'], 5)
        self.assertIn('未检查整段来源覆盖', result['coverage'])
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse(self.store.path('builds/seg001').exists())
        complete = compiler.compile_project(self.project, 'seg001', self.plan)
        self.assertGreater(complete['errors'], 0)

    def test_known_successor_and_declared_final_have_distinct_boundary_status(self):
        plan = copy.deepcopy(self.plan)
        plan['boundary_context']['outgoing'] = {
            'scene_id': 'courtyard', 'time_id': 'following_moment',
        }
        result = compiler.check_block(self.project, 'seg001', plan)
        self.assertEqual(result['status'], 'local_passed')
        self.assertTrue(result['boundary_confirmed'])
        with self.assertRaisesRegex(ValueError, 'final-block'):
            compiler.check_block(self.project, 'seg001', plan, final_block=True)
        final = compiler.check_block(self.project, 'seg001', self.plan, final_block=True)
        self.assertEqual(final['status'], 'local_passed')

    def test_local_check_catches_speech_pacing_before_full_plan_exists(self):
        plan = copy.deepcopy(self.plan)
        plan['blocks'][0]['voices'][0]['end'] = 0.9
        result = compiler.check_block(self.project, 'seg001', plan)
        self.assertEqual(result['status'], 'hard_failed')
        self.assertGreater(result['errors'], 0)
        self.assertTrue(any('语速' in item['message'] for item in result['diagnostics']))

    def test_known_time_jump_checks_previous_tail_buffer(self):
        plan = copy.deepcopy(self.plan)
        plan['boundary_context']['outgoing'] = {
            'scene_id': 'courtyard', 'time_id': 'following_moment',
        }
        plan['blocks'][0]['voices'][1]['start'] = 13.2
        plan['blocks'][0]['voices'][1]['end'] = 14.8
        result = compiler.check_block(self.project, 'seg001', plan)
        self.assertEqual(result['status'], 'hard_failed')
        self.assertTrue(any('无口播时段' in item['message'] for item in result['diagnostics']))

    def test_local_check_rejects_invalid_shot_and_stale_source(self):
        plan = copy.deepcopy(self.plan)
        plan['blocks'][0]['shots'][0]['end'] = 5.1
        with self.assertRaisesRegex(ValueError, '5秒'):
            compiler.check_block(self.project, 'seg001', plan)
        plan = copy.deepcopy(self.plan)
        plan['source_sha256'] = 'stale'
        with self.assertRaisesRegex(ValueError, '来源已变化'):
            compiler.check_block(self.project, 'seg001', plan)


if __name__ == '__main__':
    unittest.main()
