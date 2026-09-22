"""V1.24 回归：自然时长、机位配额、人物台账与场景行。"""

import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

import compile_plan as c
from project_state import ProjectState
from test_v119_performance_refactor import SOURCE, compact_plan


class DurationCameraCastTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(os.environ.get('SEEDANCE_TEST_TMP', tempfile.gettempdir())).resolve()
        self.project = self.temp_root / ('seedance-v124-' + uuid.uuid4().hex)
        self.project.mkdir()
        self.store = ProjectState(self.project)
        self.store.init('story')
        self.store.ingest('seg001', SOURCE)
        self.store.config({'model': '2.0', 'target_duration': 15})
        self.store.use_original('seg001')
        self.cast = {'courtyard': ['林舟', '沈遥']}

    def tearDown(self):
        self.assertEqual(self.project.resolve().parent, self.temp_root)
        shutil.rmtree(self.project)

    def plan(self):
        plan = compact_plan(self.store)
        plan['cast'] = copy.deepcopy(self.cast)
        return plan

    def diagnostics(self, plan):
        return (c.shot_language_diagnostics(plan) + c.cast_diagnostics(plan)
                + c.validate_plan_timing(plan, self.store.read()['config']))

    def errors(self, plan):
        return [d.message for d in self.diagnostics(plan) if d.level == 'ERROR']

    def warnings(self, plan):
        return [d.message for d in self.diagnostics(plan) if d.level == 'WARN']

    def test_natural_duration_is_integer_and_tail_gap_is_flagged(self):
        plan = self.plan()
        plan['blocks'][0]['duration'] = 7.5
        rendered_errors = [d.message for d in c.validate_structure(
            c.render(plan, SOURCE, self.store.read()['config'], audit=True), 15)]
        self.assertTrue(any('整数' in message for message in rendered_errors))
        short = self.plan()
        short['blocks'][0]['duration'] = 8
        short['blocks'][0]['shots'] = short['blocks'][0]['shots'][:4]
        for index, shot in enumerate(short['blocks'][0]['shots']):
            shot['start'], shot['end'] = index * 2, (index + 1) * 2
        short['blocks'][0]['voices'][1].update(start=5.0, end=6.6)
        self.assertEqual(self.errors(short), [])
        padded = self.plan()
        padded['blocks'][0]['voices'][1].update(start=3.2, end=4.9)
        self.assertTrue(any('疑似填秒' in message for message in self.warnings(padded)))

    def test_camera_quota_and_cut_quota_are_hard_errors(self):
        plan = self.plan()
        for shot in plan['blocks'][0]['shots']:
            shot['movement'] = '固定机位'
        messages = self.errors(plan)
        self.assertTrue(any('固定机位' in message for message in messages))
        self.assertTrue(any('没有任何移动镜头' in message for message in messages))
        plan = self.plan()
        for shot in plan['blocks'][0]['shots'][1:]:
            shot['transition'] = '硬切'
        self.assertTrue(any('连续三个镜头都写硬切' in message for message in self.errors(plan)))
        plan = self.plan()
        self.assertEqual(self.errors(plan), [])

    def test_character_ledger_continuity_and_offscreen_line(self):
        plan = self.plan()
        second = copy.deepcopy(plan['blocks'][0])
        second['time_id'] = 'following_moment'
        second['characters'] = [{'name': '林舟'}]
        second['voices'][0].update(start=8.0, end=9.1)
        second['voices'][1].update(start=12.0, end=13.6)
        plan['blocks'].append(second)
        messages = self.errors(plan)
        self.assertTrue(any('沈遥 在上一块在场、本块消失' in message for message in messages))
        plan['blocks'][1]['characters'] = [
            {'name': '林舟'},
            {'name': '沈遥', 'offscreen': True, 'note': '院门内侧未入镜'},
        ]
        self.assertEqual(self.errors(plan), [])
        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        self.assertIn('画外：沈遥（院门内侧未入镜）；', rendered)
        self.assertIn('人物：林舟；', rendered)

    def test_new_character_needs_source_basis_and_cast_membership(self):
        plan = self.plan()
        second = copy.deepcopy(plan['blocks'][0])
        second['time_id'] = 'following_moment'
        second['characters'] = [{'name': '林舟'}, {'name': '沈遥'}, {'name': '陌生人'}]
        second['voices'][0].update(start=8.0, end=9.1)
        second['voices'][1].update(start=12.0, end=13.6)
        plan['blocks'].append(second)
        messages = self.errors(plan)
        self.assertTrue(any('陌生人' in message and 'cast' in message for message in messages))
        plan['cast']['courtyard'] = ['林舟', '沈遥', '陌生人']
        messages = self.errors(plan)
        self.assertTrue(any('首次出现必须绑定来源节拍' in message for message in messages))
        plan['aliases'] = {'陌生人': ['两人']}
        self.assertEqual([message for message in self.errors(plan) if '陌生人' in message
                          and 'cast' not in message], [])

    def test_scene_line_is_name_only_and_sound_arrangement_is_conditional(self):
        plan = self.plan()
        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        self.assertIn('场景：院内；时间：', rendered)
        self.assertNotIn('场景：院内木桌位于门旁', rendered)
        self.assertEqual(rendered.count('声音安排：'), 1)
        for voice in plan['blocks'][0]['voices']:
            voice.update(start=12.0, end=13.6)
        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        self.assertEqual(rendered.count('声音安排：'), 1)
        self.assertIn('14.5-15秒无口播', rendered)


if __name__ == '__main__':
    unittest.main()
