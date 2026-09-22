import copy
import json
from pathlib import Path
import unittest

import compile_plan as c
import validate_dialogue_and_timeline as v
import test_v113_workflow as workflow
from test_v113_workflow import example_plan, SOURCE
from test_validate_dialogue_and_timeline import block


class V118ConfirmedRulesTests(unittest.TestCase):
    setUp = workflow.WorkflowTests.setUp
    tearDown = workflow.WorkflowTests.tearDown

    def plan(self):
        return example_plan(self.store)

    @staticmethod
    def character_lines(rendered):
        return [line for line in rendered.splitlines() if line.startswith('人物：')]

    def test_character_header_only_renders_names_and_ledger_keeps_metadata(self):
        plan = self.plan()
        first, second = plan['blocks'][0]['characters']
        first.update(stage='白衣', asset='@林舟参考', first_visible_shot=2, last_visible_shot=4)
        second['offscreen'] = True

        rendered = c.render(plan, SOURCE, self.store.read()['config'])
        audited = c.render(plan, SOURCE, self.store.read()['config'], audit=True)
        self.assertEqual(self.character_lines(rendered), ['人物：林舟；沈遥'])
        self.assertEqual(self.character_lines(audited), ['人物：林舟；沈遥'])

        result = c.compile_project(self.project, 'seg001', plan)
        ledger = json.loads(Path(result['ledger']).read_text(encoding='utf-8'))
        self.assertEqual(ledger['plan']['blocks'][0]['characters'], plan['blocks'][0]['characters'])

    def test_empty_character_list_outputs_none(self):
        plan = self.plan()
        plan['blocks'][0]['characters'] = []
        self.assertEqual(self.character_lines(c.render(plan, SOURCE, self.store.read()['config'])),
                         ['人物：无'])

    def test_character_backend_constraints_remain_enforced(self):
        mutations = (
            {'first_visible_shot': 0},
            {'last_visible_shot': 6},
            {'first_visible_shot': True},
            {'first_visible_shot': 4, 'last_visible_shot': 2},
            {'offscreen': True, 'first_visible_shot': 2},
            {'asset': '林舟参考'},
            {'stage': '阶段说明过长超过十六个字符不能作为后台标识'},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                plan = self.plan()
                plan['blocks'][0]['characters'][0].update(mutation)
                with self.assertRaises(ValueError):
                    c.render(plan, SOURCE, self.store.read()['config'])

    def test_character_names_and_legacy_headers_are_structural(self):
        for name in ('无', '@林舟', '林舟（青年）', '林舟｜@参考'):
            with self.subTest(name=name):
                plan = self.plan()
                plan['blocks'][0]['characters'][0]['name'] = name
                with self.assertRaises(ValueError):
                    c.render(plan, SOURCE, self.store.read()['config'])
        self.assertEqual(c.render_legacy_characters('林舟；沈遥'), '林舟；沈遥')
        self.assertEqual(c.render_legacy_characters('无'), '无')
        for value in ('林舟（青年）', '@林舟', '林舟｜@参考'):
            with self.subTest(legacy=value), self.assertRaises(ValueError):
                c.render_legacy_characters(value)

    def test_historical_character_header_validator_uses_same_public_contract(self):
        self.assertFalse([d for d in v.validate_structure(block(), 15) if d.level == 'ERROR'])
        self.assertFalse([d for d in v.validate_structure(block().replace('人物：陈默', '人物：无'), 15)
                          if d.level == 'ERROR'])
        self.assertFalse([d for d in v.validate_structure(block().replace('人物：陈默', '人物：林舟；沈遥'), 15)
                          if d.level == 'ERROR'])
        for value in ('陈默（青年）', '@陈默', '陈默｜@参考', '陈默，青年'):
            diagnostics = v.validate_structure(block().replace('人物：陈默', '人物：' + value), 15)
            self.assertTrue(any(d.level == 'ERROR' and '只能写' in d.message for d in diagnostics), value)

    def test_v4_requires_boundary_context_and_v3_remains_readable(self):
        plan = self.plan()
        del plan['boundary_context']
        with self.assertRaisesRegex(ValueError, 'boundary_context'):
            c.render(plan, SOURCE, self.store.read()['config'])
        plan['schema_version'] = 3
        self.assertIn('人物：林舟；沈遥', c.render(plan, SOURCE, self.store.read()['config']))

    def test_auto_delivery_uses_internal_and_cross_batch_spacetime(self):
        plan = self.plan()
        self.assertEqual(c.block_handles(plan, 0, {'delivery': 'auto'}), (0, 0.5, '独立收束'))

        identity = {'scene_id': plan['blocks'][0]['scene_id'], 'time_id': plan['blocks'][0]['time_id']}
        plan['boundary_context']['outgoing'] = copy.deepcopy(identity)
        self.assertEqual(c.block_handles(plan, 0, {'delivery': 'auto'}), (0, 0, '连续剪辑'))

        plan['boundary_context']['outgoing'] = {'scene_id': identity['scene_id'], 'time_id': 'later'}
        self.assertEqual(c.block_handles(plan, 0, {'delivery': 'auto'}), (0, 1, '独立收束'))

        plan['boundary_context']['incoming'] = {'scene_id': 'outside', 'time_id': identity['time_id']}
        self.assertEqual(c.block_handles(plan, 0, {'delivery': 'auto'}), (1, 1, '独立收束'))

    def test_static_effect_forms_render_and_cannot_mix(self):
        for effects in ([], ['静默'], [{'type': '静默', 'text': '静默'}]):
            with self.subTest(effects=effects):
                plan = self.plan()
                plan['blocks'][0]['shots'][0]['effects'] = effects
                rendered = c.render(plan, SOURCE, self.store.read()['config'])
                self.assertIn('环境音效：静默。', rendered)

        plan = self.plan()
        plan['blocks'][0]['shots'][0]['effects'] = [
            {'type': '静默', 'text': '静默'},
            {'type': '环境声', 'text': '院内底声', 'provenance': 'scene_ambient', 'basis': 'scene'},
        ]
        with self.assertRaises(ValueError):
            c.render(plan, SOURCE, self.store.read()['config'])

    def test_hidden_cut_severity_depends_on_field_and_camera_context(self):
        plan = self.plan()
        plan['blocks'][0]['shots'][0]['action'] = '镜头切到门外，林舟站定。'
        with self.assertRaisesRegex(ValueError, '摄影切镜语境'):
            c.render(plan, SOURCE, self.store.read()['config'])

        plan = self.plan()
        plan['blocks'][0]['shots'][0]['action'] = '陈默反打对方一拳。'
        c.render(plan, SOURCE, self.store.read()['config'])
        diagnostics = v.shot_risk_warnings(
            '画面与动作：陈默反打对方一拳。\n摄影机与构图：固定中景。', 3, '01', '1'
        )
        self.assertTrue(any(d.level == 'WARN' and '混淆' in d.message for d in diagnostics))
        self.assertFalse(any(d.level == 'ERROR' for d in diagnostics))

    def test_meaningful_inline_spaces_are_not_equivalent(self):
        changed = v.validate_dialogue('陈默：「now here。」', '台词：陈默说：“nowhere。”')
        self.assertTrue(any(d.level == 'ERROR' for d in changed))
        unchanged = v.validate_dialogue('陈默：「Seedance 2.5 可以用。」',
                                         '台词：陈默说：“Seedance 2.5 可以用。”')
        self.assertFalse(any(d.level == 'ERROR' for d in unchanged))

    def test_any_four_to_fifteen_second_block_is_legal_but_must_be_integer(self):
        prompt = block(8, 2) + '\n' + block(number=2) + '\n' + block(number=3)
        allowed = v.validate_structure(prompt, 15)
        self.assertFalse([d.render() for d in allowed if d.level == 'ERROR'])
        fractional = block(7.5, 2) + '\n' + block(number=2) + '\n' + block(number=3)
        self.assertTrue(any(d.level == 'ERROR' and '整数' in d.message
                            for d in v.validate_structure(fractional, 15)))

        for seconds, minimum in ((5, 1), (6, 2), (10, 2), (11, 3), (14, 3)):
            with self.subTest(seconds=seconds, minimum=minimum):
                valid = v.validate_structure(block(seconds, minimum), 15)
                self.assertFalse([d.render() for d in valid if d.level == 'ERROR'])
                if minimum > 1:
                    invalid = v.validate_structure(block(seconds, minimum - 1), 15)
                    self.assertTrue(any(d.level == 'ERROR' for d in invalid))

    def test_new_project_defaults_to_auto_delivery(self):
        self.assertEqual(self.store.read()['config']['delivery'], 'auto')
        self.store.config({'delivery': 'standalone'})
        self.assertEqual(self.store.read()['config']['delivery'], 'standalone')
        self.store.config({'delivery': 'continuous'})
        self.assertEqual(self.store.read()['config']['delivery'], 'continuous')


if __name__ == '__main__':
    unittest.main()
