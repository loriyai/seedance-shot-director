"""V1.22 导演规则回归：声音类型、镜数弹性、机位与跨块连续性。"""

import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

import compile_plan as c
import validate_dialogue_and_timeline as v
from project_state import ProjectState, digest
from test_v119_performance_refactor import SOURCE, compact_plan


class DirectingRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(os.environ.get('SEEDANCE_TEST_TMP', tempfile.gettempdir())).resolve()
        self.project = self.temp_root / ('seedance-v121-' + uuid.uuid4().hex)
        self.project.mkdir()
        self.store = ProjectState(self.project)
        self.store.init('story')
        self.store.ingest('seg001', SOURCE)
        self.store.config({'model': '2.0', 'target_duration': 15})
        self.store.use_original('seg001')

    def tearDown(self):
        self.assertEqual(self.project.resolve().parent, self.temp_root)
        shutil.rmtree(self.project)

    def plan(self):
        return compact_plan(self.store)

    def render(self, plan):
        return c.render(plan, SOURCE, self.store.read()['config'])

    def messages(self, plan, level=None):
        return [d.message for d in c.shot_language_diagnostics(plan)
                if level is None or d.level == level]

    def test_os_voice_keeps_inner_os_wording(self):
        plan = self.plan()
        plan['blocks'][0]['voices'][0]['kind'] = 'OS'
        rendered = self.render(plan)
        self.assertIn('林舟内心OS：“明日出发。”', rendered)
        self.assertNotIn('OS的语气', rendered)
        audit = c.render(plan, SOURCE, self.store.read()['config'], audit=True)
        names = {v.canonical_speaker(x['speaker'], x['kind'])
                 for b in plan['blocks'] for x in b['voices']}
        actual, unassigned = v.extract_output_dialogue(rendered, names)
        expected, _ = v.extract_output_dialogue(audit, names)
        self.assertEqual(unassigned, 0)
        self.assertEqual([(x.speaker, x.text) for x in actual], [(x.speaker, x.text) for x in expected])
        self.assertIn('林舟OS', {x.speaker for x in actual})

    def test_tone_must_not_carry_speech_manner(self):
        plan = self.plan()
        plan['blocks'][0]['voices'][0]['tone'] = '以内心OS的语气'
        with self.assertRaisesRegex(ValueError, '语气字段'):
            self.render(plan)

    def test_fifteen_second_block_accepts_six_and_seven_shots(self):
        plan = self.plan()
        shots = plan['blocks'][0]['shots']
        tail = shots.pop()
        shots.append(dict(tail, start=12, end=13.5))
        shots.append(dict(tail, start=13.5, end=15))
        rendered = self.render(plan)
        self.assertEqual(sum(1 for line in rendered.splitlines() if line.startswith('[')), 6)
        self.assertIn('镜头以极具张力的', rendered)
        tail = shots.pop()
        shots.append(dict(tail, start=13, end=14))
        shots.append(dict(tail, start=14, end=15))
        rendered = self.render(plan)
        self.assertEqual(sum(1 for line in rendered.splitlines() if line.startswith('[')), 7)
        tail = shots.pop()
        shots.append(dict(tail, start=14.5, end=14.7))
        shots.append(dict(tail, start=14.7, end=15))
        with self.assertRaisesRegex(ValueError, '5-7镜'):
            self.render(plan)

    def test_last_shot_without_dialogue_avoids_dialogue_wording(self):
        plan = self.plan()
        rendered = self.render(plan)
        last = [line for line in rendered.splitlines() if line.startswith('声音安排：')][-1]
        self.assertNotIn('台词', last)

    def test_broadcast_style_camera_is_hard_error(self):
        plan = self.plan()
        plan['blocks'][0]['shots'][0]['camera'] = '正面平视，正对镜头，固定机位。'
        self.assertTrue(any('播报式正脸' in message for message in self.messages(plan, 'ERROR')))

    def test_frontal_shot_quota_warns(self):
        plan = self.plan()
        for shot in plan['blocks'][0]['shots'][:3]:
            shot['camera'] = '正面平视，固定机位。'
        self.assertTrue(any('正面镜' in message for message in self.messages(plan, 'WARN')))

    def test_group_entry_over_two_seconds_warns(self):
        plan = self.plan()
        block = plan['blocks'][0]
        plan['beats'][0]['evidence'] = '来了一群穿紫衣服的人'
        block['shots'][0]['beats'] = [plan['beats'][0]['id']]
        block['shots'][0]['end'] = 3.5
        block['shots'][1]['start'] = 3.5
        self.assertTrue(any('群体入场镜超过2秒' in message for message in self.messages(plan, 'WARN')))

    def test_background_reference_drift_and_state_relay_warn(self):
        plan = self.plan()
        block = plan['blocks'][0]
        block.setdefault('scene_design', {
            'lighting': '日光自院墙右上方斜射为主光',
            'tone': '暖白日光，低对比',
            'layering': '前景是木桌，中景是两人，后景是低矮山脊与疏林',
            'depth_design': '建立与推进用中等景深',
            'blocking': '林舟在桌左，沈遥在桌右',
            'composition': '三分法构图',
            'environment': '院中浮尘在日光里缓慢浮动',
        })
        block['scene_design']['layering'] = '前景是木桌，中景是两人，后景是低矮山脊与疏林'
        follower = copy.deepcopy(block)
        follower['time_id'] = block.get('time_id', 'day_continuous')
        follower['scene_design']['layering'] = '前景是木桌，中景是两人，后景是坡下疏林'
        follower['shots'] = copy.deepcopy(block['shots'])
        plan['blocks'].append(follower)
        plan['boundary_context'] = {'incoming': None, 'outgoing': None}
        messages = self.messages(plan, 'WARN')
        self.assertTrue(any('背景参照物措辞不一致' in message for message in messages))
        self.assertTrue(any('未复述上一块出口状态' in message for message in messages))
        follower['entry'] = '延续上一块：林舟仍站在桌左。'
        self.assertFalse(any('未复述上一块出口状态' in message for message in self.messages(plan, 'WARN')))


class SoundArrangementWordingTests(unittest.TestCase):
    def test_last_shot_without_dialogue_must_not_mention_dialogue(self):
        from test_validate_dialogue_and_timeline import block
        text = block().replace(
            '声音安排：14.5-15秒无口播，仅保留本镜动作或状态的连续画面，不定格。',
            '声音安排：本镜台词按来源合法标点自然连贯，不另拆分或增加停顿。')
        messages = [d.message for d in v.validate_sound_arrangement_layout(text)]
        self.assertTrue(any('不得出现“台词”字样' in message for message in messages))


if __name__ == '__main__':
    unittest.main()
