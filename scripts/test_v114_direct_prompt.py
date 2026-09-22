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
            block.pop('characters', None)
            block.pop('time_id', None)
            block['scene_id'] = 'courtyard_day'
            for shot in block['shots']:
                shot.pop('action_basis', None)
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
        self.assertEqual(rendered.count('声音安排：'), 1)
        self.assertIn('院中轻微环境底声；衣料摩擦声', rendered)
        self.assertLess(rendered.index('台词：'), rendered.index('环境音效：'))

    def test_os_shouting_stays_os_and_legacy_os_is_preserved(self):
        for label in ('林舟以内心呐喊的语气内心OS', '林舟OS说', '林舟内心OS'):
            self.assertEqual(v.extract_output_dialogue(f'台词：{label}：“走吧。”', {'林舟OS'})[0][0].speaker, '林舟OS')

    def test_same_place_cross_time_reserves_both_sides(self):
        plan = example_plan(self.store)
        plan['blocks'][0]['time_id'] = 'day_one'
        plan['blocks'][0]['scene_id'] = 'courtyard'
        plan['blocks'][0]['header'] = {'scene': '同一庭院', 'atmosphere': '日光平稳，人物站位明确'}
        plan['blocks'].append(copy.deepcopy(plan['blocks'][0]))
        plan['blocks'][1]['time_id'] = 'ten_years_later'
        self.assertEqual(c.block_handles(plan, 0, {})[:2], (0, 1))
        self.assertEqual(c.block_handles(plan, 1, {})[:2], (1, 0.5))
        self.assertTrue(any(d.level == 'ERROR' and '无口播' in d.message for d in c.validate_plan_timing(plan, {})))
        plan['blocks'][1]['voices'][0].update(start=1, end=2.1)
        self.assertEqual(c.validate_plan_timing(plan, {}), [])
        rendered = c.render(plan, SOURCE, {})
        blocks = v.parse_blocks(rendered)
        first_counts = [shot.count('声音安排：') for _, shot in v.parse_shots(blocks[0][1])]
        second_counts = [shot.count('声音安排：') for _, shot in v.parse_shots(blocks[1][1])]
        self.assertEqual(first_counts, [0, 0, 0, 0, 1])
        self.assertEqual(second_counts, [1, 0, 0, 0, 1])
        self.assertIn('声音安排：0-1秒无口播', blocks[1][1])

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

    def test_non_boundary_silent_head_does_not_emit_first_shot_sound_arrangement(self):
        plan = self.new_plan()
        plan['blocks'][0]['silent_head'] = 1
        rendered = c.render(plan, SOURCE, {})
        counts = [shot.count('声音安排：') for _, shot in v.parse_shots(v.parse_blocks(rendered)[0][1])]
        self.assertEqual(counts, [0, 0, 0, 0, 1])

    def test_non_punctuation_fragment_split_fails(self):
        plan = self.new_plan()
        shots = plan['blocks'][0]['shots']
        shots[0]['speech'] = [{'voice': 'V1', 'span': [0, 2]}]
        shots[1]['speech'] = [{'voice': 'V1', 'span': [2, 5]}]
        with self.assertRaisesRegex(ValueError, '已有标点'):
            c.render(plan, SOURCE, {})

    def test_per_shot_voice_timing_fields_are_rejected(self):
        for fragment in ({'voice':'V1','start':0.6}, {'voice':'V1','pause':0.1}):
            plan = self.new_plan()
            plan['blocks'][0]['shots'][0]['speech'] = [fragment]
            with self.assertRaises(ValueError):
                c.render(plan, SOURCE, {})

    def test_new_plan_requires_scene_identity_and_per_shot_sound(self):
        for field in ('scene_id', 'time_id', 'effects'):
            plan = example_plan(self.store)
            if field in ('scene_id', 'time_id'):
                del plan['blocks'][0][field]
            else:
                del plan['blocks'][0]['shots'][0][field]
            with self.assertRaises(ValueError): c.render(plan, SOURCE, {})

    def test_longer_leading_handle_must_fit_first_shot(self):
        plan = self.new_plan()
        plan['blocks'][0]['silent_head'] = 4
        self.assertTrue(any('首镜和末镜' in d.message for d in c.validate_plan_timing(plan, {})))

    def test_direct_text_does_not_need_per_dialogue_voice_interval(self):
        rendered = c.render(self.new_plan(), SOURCE, {})
        result = v.validate_voice_pacing(SOURCE, rendered, 15)
        self.assertFalse(any(d.level == 'ERROR' and '声音' in d.message for d in result))

    def test_sound_arrangement_is_rejected_in_middle_shot(self):
        rendered = c.render(self.new_plan(), SOURCE, {})
        rendered = rendered.replace('[镜头2]', '[镜头2]\n声音安排：3-4秒无口播。')
        self.assertTrue(any(d.level == 'ERROR' and '其他镜头不得' in d.message
                            for d in v.validate_structure(rendered, 15)))

    def test_last_shot_sound_arrangement_is_optional_but_never_duplicated(self):
        rendered = c.render(self.new_plan(), SOURCE, {})
        stripped = '\n'.join(line for line in rendered.splitlines() if not line.startswith('声音安排：'))
        self.assertFalse(any(d.level == 'ERROR' for d in v.validate_structure(stripped, 15)))
        doubled = rendered + '\n声音安排：本镜无口播，仅保留环境与动作声与连续画面。'
        self.assertTrue(any(d.level == 'ERROR' and '最多输出一次' in d.message
                            for d in v.validate_structure(doubled, 15)))


if __name__ == '__main__':
    unittest.main()
