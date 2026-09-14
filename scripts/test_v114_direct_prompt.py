import copy
import unittest

import compile_plan as c
import validate_dialogue_and_timeline as v
import test_v113_workflow as workflow
from test_v113_workflow import example_plan, SOURCE


class DirectPromptTests(unittest.TestCase):
    setUp = workflow.WorkflowTests.setUp
    tearDown = workflow.WorkflowTests.tearDown
    def new_plan(self):
        plan = example_plan(self.store)
        plan['schema_version'] = 2
        plan['defaults']['characters'] = '林舟；沈遥'
        plan['defaults']['sound'] = '无背景配乐'
        for block in plan['blocks']:
            block['scene_id'] = 'courtyard_day'
            for shot in block['shots']:
                shot['effects'] = ['院中轻微环境底声', '衣料摩擦声']
        return plan

    def test_internal_voice_metadata_does_not_leak(self):
        plan = self.new_plan()
        plan['blocks'][0]['voices'][0]['tone'] = '压低声音'
        result = c.compile_project(self.project, 'seg001', plan)
        self.assertEqual(result['errors'], 0)
        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        for label in ('口播段：', '收尾方式：', 'V1｜', '短剧常速', '停顿0.2秒'):
            self.assertNotIn(label, rendered)
        self.assertIn('林舟压低声音说：“明日出发。”', rendered)
        self.assertEqual(rendered.count('环境音效：'), 5)
        self.assertIn('院中轻微环境底声；衣料摩擦声', rendered)
        self.assertLess(rendered.index('台词：'), rendered.index('环境音效：'))

    def test_os_shouting_stays_os_and_legacy_os_is_preserved(self):
        for label in ('林舟以内心呐喊的语气内心OS', '林舟OS说', '林舟内心OS'):
            self.assertEqual(v.extract_output_dialogue(f'台词：{label}：“走吧。”', {'林舟OS'})[0][0].speaker, '林舟OS')

    def test_different_scene_ids_reserve_both_sides(self):
        plan = self.new_plan()
        plan['blocks'].append(copy.deepcopy(plan['blocks'][0]))
        plan['blocks'][1]['scene_id'] = 'courtyard_ten_years_later'
        self.assertEqual(c.block_handles(plan, 0, {})[:2], (0, 1))
        self.assertEqual(c.block_handles(plan, 1, {})[:2], (1, 0.5))
        self.assertTrue(any(d.level == 'ERROR' and '无口播' in d.message for d in c.validate_plan_timing(plan, {})))
        plan['blocks'][1]['voices'][0].update(start=1, end=2.1)
        self.assertEqual(c.validate_plan_timing(plan, {}), [])

    def test_same_scene_does_not_add_leading_handle(self):
        plan = self.new_plan()
        plan['blocks'].append(copy.deepcopy(plan['blocks'][0]))
        self.assertEqual(c.block_handles(plan, 1, {})[0], 0)

    def test_any_voice_type_cannot_occupy_scene_handles(self):
        for kind in ('对白', 'OS', '旁白'):
            plan = self.new_plan()
            plan['blocks'][0]['silent_head'] = 1
            plan['blocks'][0]['voices'][0]['kind'] = kind
            self.assertTrue(any(d.level == 'ERROR' for d in c.validate_plan_timing(plan, {})))

    def test_fragment_capacity_fails_even_when_whole_turn_fits(self):
        plan = self.new_plan()
        voice = plan['blocks'][0]['voices'][0]
        voice.update(start=2.9, end=4, pause=0.2)
        shots = plan['blocks'][0]['shots']
        shots[0]['speech'] = [{'voice': 'V1', 'span': [0, 2]}]
        shots[1]['speech'] = [{'voice': 'V1', 'span': [2, 5]}]
        self.assertTrue(any('片段容量不足' in d.message for d in c.validate_plan_timing(plan, {})))

    def test_fragment_gaps_and_pause_mismatch_fail(self):
        for fragment in ({'voice':'V1','start':0.6}, {'voice':'V1','pause':0.1}):
            plan = self.new_plan()
            plan['blocks'][0]['shots'][0]['speech'] = [fragment]
            self.assertTrue(any(d.level == 'ERROR' for d in c.validate_plan_timing(plan, {})))

    def test_new_plan_requires_scene_identity_and_per_shot_sound(self):
        for field in ('scene_id', 'effects'):
            plan = self.new_plan()
            if field == 'scene_id': del plan['blocks'][0][field]
            else: del plan['blocks'][0]['shots'][0][field]
            with self.assertRaises(ValueError): c.render(plan, SOURCE, {})

    def test_longer_leading_handle_must_fit_first_shot(self):
        plan = self.new_plan()
        plan['blocks'][0]['silent_head'] = 4
        self.assertTrue(any('首镜和末镜' in d.message for d in c.validate_plan_timing(plan, {})))

    def test_direct_text_timing_does_not_allow_speech_in_handle(self):
        text = '[镜头1]\n时间区间：0-15秒。\n声音安排：0.5-1.6秒，开始发声。\n台词：林舟说：“明日出发。”\n声音安排：0-1秒无口播。'
        self.assertTrue(any('无口播' in d.message for d in v.validate_natural_voice_timing(text, '01', 15, {'林舟'})))

    def test_direct_text_needs_actual_voice_interval(self):
        text = '[镜头1]\n时间区间：0-15秒。\n台词：林舟说：“明日出发。”\n声音安排：14-15秒无口播。'
        self.assertTrue(any('缺少' in d.message for d in v.validate_natural_voice_timing(text, '01', 15, {'林舟'})))


if __name__ == '__main__':
    unittest.main()
