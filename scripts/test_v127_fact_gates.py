"""V1.27 回归：场景名查表、人物可见性、设计段在场人物与事实自检表。"""

import unittest

import compile_plan


def shot(action, reaction=None, transition=None):
    value = {'start': 0, 'end': 3, 'action': action, 'camera': '侧前方中景，固定机位。',
             'shot_size': '陈默的中景', 'movement': '固定机位'}
    if reaction:
        value['reaction'] = reaction
    if transition:
        value['transition'] = transition
    return value


def block(scene_id, scene_name, characters, action, design=None, duration=12):
    return {
        'duration': duration,
        'scene_id': scene_id,
        'time_id': f'{scene_id}_day',
        'header': {'scene_name': scene_name} if scene_name else {},
        'characters': [{'name': name} for name in characters],
        'voices': [],
        'shots': [shot(action)],
        'scene_design': design or {},
    }


def plan(blocks, scenes=None, cast=None, aliases=None):
    value = {
        'schema_version': 5,
        'boundary_context': {'incoming': None, 'outgoing': None},
        'defaults': {'style': '风格', 'scene': '院中', 'atmosphere': '安静'},
        'beats': [{'id': 'E01', 'evidence': '陈默磕头'}],
        'blocks': blocks,
    }
    if scenes is not None:
        value['scenes'] = scenes
    if cast is not None:
        value['cast'] = cast
    if aliases is not None:
        value['aliases'] = aliases
    return value


class SceneNameTests(unittest.TestCase):
    def test_scene_name_comes_from_scene_id_map(self):
        data = plan([block('chenfu', None, ['陈默'], '陈默站在石阶前')],
                    scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默']})
        self.assertEqual(compile_plan.resolved_scene_name(data, data['blocks'][0]), '陈府')
        self.assertEqual(compile_plan.scene_diagnostics(data), [])

    def test_block_header_contradicting_map_is_an_error(self):
        data = plan([block('chenfu', '坟前', ['陈默'], '陈默站在石阶前')],
                    scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默']})
        messages = [item.message for item in compile_plan.scene_diagnostics(data)]
        self.assertTrue(any('与 scene_id' in message for message in messages), messages)

    def test_two_scene_ids_sharing_one_name_warns(self):
        data = plan([block('fenqian', '坟前', ['陈默'], '陈默跪在碑前'),
                     block('chenfu', '坟前', ['陈默'], '陈默站在院中')],
                    scenes={'fenqian': '坟前', 'chenfu': '坟前'})
        messages = [item.message for item in compile_plan.scene_diagnostics(data)]
        self.assertTrue(any('同一个场景名' in message for message in messages), messages)


class CharacterVisibilityTests(unittest.TestCase):
    def test_listed_character_must_appear_in_a_shot(self):
        data = plan([block('chenfu', '陈府', ['陈默', '老伴'], '陈默站在石阶前骂天')],
                    scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默', '老伴']})
        messages = [item.message for item in compile_plan.character_visibility_diagnostics(data)]
        self.assertTrue(any('老伴' in message and '没有任何镜头' in message for message in messages),
                        messages)

    def test_offscreen_character_is_exempt(self):
        data = plan([{
            **block('chenfu', '陈府', ['陈默'], '陈默站在石阶前骂天'),
            'characters': [{'name': '陈默'}, {'name': '老伴', 'offscreen': True, 'note': '在屋内'}],
        }], scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默', '老伴']})
        self.assertEqual(compile_plan.character_visibility_diagnostics(data), [])

    def test_cast_member_visible_but_unlisted_warns(self):
        data = plan([block('chenfu', '陈府', ['陈默'], '陈默把小孙女抱起来')],
                    scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默', '小孙女']})
        messages = [item.message for item in compile_plan.character_visibility_diagnostics(data)]
        self.assertTrue(any('未列' in message for message in messages), messages)


class DesignEntityTests(unittest.TestCase):
    def test_design_segment_may_not_name_absent_characters(self):
        design = {'lighting': '斜光', 'tone': '暖色', 'layering': '前景石阶',
                  'depth_design': '中等景深', 'blocking': '紫衣门众人停在石阶下',
                  'composition': '对称门楼', 'environment': '灯笼轻晃'}
        data = plan([block('chenfu', '陈府', ['陈默'], '陈默站在石阶前骂天', design=design)],
                    scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默', '紫衣门弟子']})
        messages = [item.message for item in compile_plan.design_entity_diagnostics(data)]
        self.assertTrue(any('未登场角色' in message for message in messages), messages)

    def test_present_character_in_design_is_fine(self):
        design = {'lighting': '斜光', 'tone': '暖色', 'layering': '前景石阶',
                  'depth_design': '中等景深', 'blocking': '陈默站在石阶前',
                  'composition': '对称门楼', 'environment': '灯笼轻晃'}
        data = plan([block('chenfu', '陈府', ['陈默'], '陈默站在石阶前骂天', design=design)],
                    scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默']})
        self.assertEqual(compile_plan.design_entity_diagnostics(data), [])


class FactsSheetTests(unittest.TestCase):
    def test_facts_sheet_reports_derived_scene_and_cast(self):
        data = plan([{
            **block('chenfu', None, ['陈默'], '陈默站在石阶前骂天'),
            'time_label': '白天',
            'voices': [{'id': 'V01', 'speaker': '陈默', 'kind': '对白', 'text': '我干你娘！',
                        'start': 0.5, 'end': 2.0, 'tone': '怒骂'}],
        }], scenes={'chenfu': '陈府'}, cast={'chenfu': ['陈默']})
        rows = compile_plan.facts_sheet(data, {})
        self.assertEqual(rows[0]['scene_name'], '陈府')
        self.assertEqual(rows[0]['visible_characters'], ['陈默'])
        self.assertEqual(rows[0]['tone']['with_tone'], 1)
        text = compile_plan.facts_text(rows)
        self.assertIn('陈府(chenfu)', text)
        self.assertIn('陈默（对白）', text)


if __name__ == '__main__':
    unittest.main()
