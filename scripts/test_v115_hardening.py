import copy
import unittest

import compile_plan as c
import test_v113_workflow as workflow
from test_v113_workflow import example_plan, SOURCE


class V115HardeningTests(unittest.TestCase):
    setUp = workflow.WorkflowTests.setUp
    tearDown = workflow.WorkflowTests.tearDown

    def plan(self):
        return example_plan(self.store)

    def test_v3_rejects_free_form_character_and_sound_headers(self):
        for field, value in (
            ('characters', '青年陈默：黑发高束、青灰粗布短打'),
            ('sound', '保留对白、OS、系统声音与环境声'),
        ):
            plan = self.plan()
            plan['defaults'][field] = value
            with self.assertRaises(ValueError):
                c.render(plan, SOURCE, self.store.read()['config'])

    def test_character_metadata_is_validated_but_not_rendered(self):
        plan = self.plan()
        first, second = plan['blocks'][0]['characters']
        first.update(stage='白衣', asset='@林舟参考', first_visible_shot=2, last_visible_shot=4)
        second['offscreen'] = True
        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        self.assertEqual([line for line in rendered.splitlines() if line.startswith('人物：')],
                         ['人物：林舟；沈遥'])

    def test_sound_header_is_compiled_only_from_project_music(self):
        plan = self.plan()
        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        self.assertIn('国风二维动画，线条清晰；无背景配乐', rendered)
        self.assertNotIn('保留对白', rendered)
        self.assertNotIn('系统声音', rendered)

    def test_three_shot_fifteen_second_template_is_rejected(self):
        plan = self.plan()
        plan['blocks'][0]['shots'] = plan['blocks'][0]['shots'][:3]
        with self.assertRaisesRegex(ValueError, '5-7镜'):
            c.render(plan, SOURCE, self.store.read()['config'])

    def test_four_shots_cannot_be_unlocked_by_basis(self):
        plan = self.plan()
        shots = plan['blocks'][0]['shots']
        shots[3]['end'] = 15
        shots.pop()
        with self.assertRaises(ValueError):
            c.render(plan, SOURCE, self.store.read()['config'])
        plan['blocks'][0]['shot_count_basis'] = '末段两次跨门动作需保持同一连续跟拍，避免无意义拆切。'
        with self.assertRaises(ValueError):
            c.render(plan, SOURCE, self.store.read()['config'])

    def test_shot_over_five_seconds_and_hidden_cut_are_rejected(self):
        plan = self.plan()
        plan['blocks'][0]['shots'][0]['end'] = 5
        plan['blocks'][0]['shots'][1]['start'] = 5
        c.render(plan, SOURCE, self.store.read()['config'])

        plan = self.plan()
        shot = plan['blocks'][0]['shots'][0]
        shot['end'] = 5.0000001
        plan['blocks'][0]['shots'][1]['start'] = 5.0000001
        with self.assertRaisesRegex(ValueError, '5秒'):
            c.render(plan, SOURCE, self.store.read()['config'])
        plan = self.plan()
        plan['blocks'][0]['shots'][0]['camera'] = '近景切古书特写，再切回人物。'
        with self.assertRaisesRegex(ValueError, '隐藏切镜'):
            c.render(plan, SOURCE, self.store.read()['config'])

    def test_dialogue_boundary_uses_complete_speech_punctuation(self):
        text = '真的吗？！我不信。'
        self.assertTrue(c.dialogue_split_boundary(text, 5))
        self.assertFalse(c.dialogue_split_boundary(text, 4))
        decimal = 'Seedance 2.5现在可用。'
        self.assertFalse(c.dialogue_split_boundary(decimal, decimal.index('.') + 1))
        normalised = '第一行，第二行。'
        self.assertTrue(c.boundary_exists_in_source('陈默：「第一行\n第二行。」', normalised, 4, '陈默', '对白'))
        self.assertFalse(c.boundary_exists_in_source('陈默：「第一行第二行。」', normalised, 4, '陈默', '对白'))
        multiple = '甲行，乙行，丙行。'
        multiline = '陈默：「甲行\n乙行\n丙行。」'
        self.assertTrue(c.boundary_exists_in_source(multiline, multiple, multiple.index('，') + 1, '陈默', '对白'))
        self.assertTrue(c.boundary_exists_in_source(multiline, multiple, multiple.rindex('，') + 1, '陈默', '对白'))
        self.assertFalse(c.boundary_exists_in_source(multiline, multiple, multiple.index('，') + 1, '吴天德', '对白'))
        bare_source = '陈默磕头\n「爹！娘！\n我捡到一本秘籍\n给我十年」'
        bare_text = '爹！娘！我捡到一本秘籍，给我十年'
        self.assertTrue(c.boundary_exists_in_source(
            bare_source, bare_text, bare_text.index('，') + 1, '陈默', '对白'
        ))
        display_source = '画面文字：\n「前句\n后句」'
        display_text = '前句，后句'
        self.assertFalse(c.boundary_exists_in_source(
            display_source, display_text, display_text.index('，') + 1, '吴天德', 'OS'
        ))
        self.assertFalse(c.boundary_exists_in_source(
            '「前句\n后句」不念', display_text, display_text.index('，') + 1, '吴天德', '对白'
        ))
        self.assertTrue(c.boundary_exists_in_source(
            '系统：\n「前句\n后句」', display_text, display_text.index('，') + 1, '系统', '对白'
        ))
        self.assertFalse(c.boundary_exists_in_source(
            '系统：\n「前句\n后句」', display_text, display_text.index('，') + 1, '吴天德', '对白'
        ))
        self.assertFalse(c.boundary_exists_in_source(
            '画面文字：石碑显示「前句\n后句」', display_text,
            display_text.index('，') + 1, '吴天德', 'OS'
        ))
        self.assertTrue(c.boundary_exists_in_source(
            '画面文字：第一章\n陈默：「前句，后句。」', '前句，后句。',
            len('前句，'), '陈默', '对白'
        ))
        spoken_display_word = '我展示给你看，别走。'
        self.assertTrue(c.boundary_exists_in_source(
            f'陈默：「{spoken_display_word}」', spoken_display_word,
            spoken_display_word.index('，') + 1, '陈默', '对白'
        ))
        suffix_action = '前句，后句。'
        self.assertTrue(c.boundary_exists_in_source(
            f'陈默：「{suffix_action}」他向众人展示令牌', suffix_action,
            suffix_action.index('，') + 1, '陈默', '对白'
        ))
        narration = '旁白：「前句，后句。」'
        narration_text = '前句，后句。'
        self.assertTrue(c.boundary_exists_in_source(
            narration, narration_text, narration_text.index('，') + 1, '旁白', '旁白'
        ))
        self.assertFalse(c.boundary_exists_in_source(
            narration, narration_text, narration_text.index('，') + 1, '旁白', '对白'
        ))
        spaced = 'Seedance 2.5 可以用，明天试试。'
        self.assertTrue(c.boundary_exists_in_source(
            f'陈默：「{spaced}」', spaced, spaced.index('，') + 1, '陈默', '对白'
        ))
        self.assertFalse(c.boundary_exists_in_source(
            '陈默：「now here，continue。」', 'nowhere，continue。',
            len('nowhere，'), '陈默', '对白'
        ))
        unquoted_spaced = 'now here，continue。'
        self.assertTrue(c.boundary_exists_in_source(
            f'陈默：{unquoted_spaced}', unquoted_spaced,
            unquoted_spaced.index('，') + 1, '陈默', '对白'
        ))
        quoted = '他说：“好。”然后走。'
        self.assertFalse(c.dialogue_split_boundary(quoted, quoted.index('”')))

    def test_action_field_is_rendered_before_corresponding_dialogue(self):
        rendered = c.render(self.plan(), SOURCE, self.store.read()['config'])
        first_shot = rendered.split('[镜头1]', 1)[1].split('[镜头2]', 1)[0]
        self.assertLess(first_shot.index('画面与动作：'), first_shot.index('台词：'))

    def test_effects_require_structured_provenance(self):
        plan = self.plan()
        plan['blocks'][0]['shots'][0]['effects'] = ['风声', '衣料声']
        with self.assertRaises(ValueError):
            c.render(plan, SOURCE, self.store.read()['config'])

    def test_v3_review_requires_all_semantic_checks(self):
        result = c.compile_project(self.project, 'seg001', self.plan())
        review = workflow.WorkflowTests.review_result(self, result)
        review['checks']['character_headers'] = False
        with self.assertRaises(ValueError):
            c.finalize(self.project, 'seg001', result['build'], review)


if __name__ == '__main__':
    unittest.main()
