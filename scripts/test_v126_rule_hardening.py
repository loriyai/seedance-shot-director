"""V1.26 回归：块内无口播填空、语气缺漏与跨块片段单镜容量。"""

import unittest

import compile_plan
import plan_voices


SOURCE = """坟前
陈默磕头
「贼老天，我干你娘！刚穿越就让我捡到绝世秘籍，可我却资质平庸，幸好老子会经商，不然我可怎么活啊！」
"""


def block(**overrides):
    value = {
        'duration': 15,
        'scene_id': 'fenqian',
        'time_id': 'day',
        'voices': [
            {'id': 'V01', 'start': 0.5, 'end': 7.5, 'text': '爹！娘！', 'tone': None},
            {'id': 'V02', 'start': 11.5, 'end': 13.4, 'text': '江湖，我他娘的来了！', 'tone': None},
        ],
        'shots': [],
    }
    value.update(overrides)
    return value


class BlockGapTests(unittest.TestCase):
    def test_four_second_interior_gap_is_flagged(self):
        diagnostics = compile_plan.dialogue_gap_diagnostics(block(), head=0, tail=1.0, label='01')
        messages = [item.message for item in diagnostics]
        self.assertTrue(any('中间无口播' in message and '疑似填秒' in message for message in messages),
                        messages)

    def test_narrow_gaps_are_not_flagged(self):
        tight = block(voices=[
            {'id': 'V01', 'start': 1.0, 'end': 7.5, 'text': '爹！娘！'},
            {'id': 'V02', 'start': 8.5, 'end': 14.0, 'text': '江湖，我他娘的来了！'},
        ])
        self.assertEqual(compile_plan.dialogue_gap_diagnostics(tight, head=1.0, tail=1.0, label='01'), [])

    def test_required_cross_time_head_and_tail_are_excused(self):
        spaced = block(voices=[
            {'id': 'V01', 'start': 1.0, 'end': 13.0, 'text': '爹！娘！'},
        ])
        self.assertEqual(compile_plan.dialogue_gap_diagnostics(spaced, head=1.0, tail=1.0, label='01'), [])

    def test_tone_gap_and_coverage_report(self):
        one = block(voices=[
            {'id': 'V01', 'start': 0.5, 'end': 3.0, 'text': '我干你娘！', 'tone': '怒骂'},
            {'id': 'V02', 'start': 3.0, 'end': 6.0, 'text': '我恨呐！哈哈哈哈！'},
        ])
        self.assertEqual(compile_plan.tone_gaps(one), ['V02'])
        self.assertEqual(compile_plan.tone_report(one),
                         {'voices': 2, 'with_tone': 1, 'signal_without_tone': ['V02']})


class PlanVoiceGateTests(unittest.TestCase):
    def report(self, voices):
        plan = {'schema_version': 5, 'blocks': [
            {'duration': 15, 'scene_id': 'fenqian', 'time_id': 'day', 'voices': voices, 'shots': []},
        ]}
        return plan_voices.plan_report(SOURCE, plan)

    def test_over_long_cross_block_fragment_is_an_error(self):
        fragment = '刚穿越就让我捡到绝世秘籍，可我却资质平庸，幸好老子会经商，不然我可怎么活啊！'
        report = self.report([
            {'id': 'V01', 'speaker': '陈默', 'kind': '对白', 'text': fragment,
             'start': 0.5, 'end': 8.0, 'profile': '短剧快节奏', 'tone': '怒骂'},
        ])
        self.assertTrue(any('跨块片段无法用 span 拆分' in item['message']
                            for item in report['diagnostics']), report['diagnostics'])

    def test_single_shot_sized_fragment_passes_and_missing_tone_warns(self):
        fragment = '贼老天，我干你娘！'
        report = self.report([
            {'id': 'V01', 'speaker': '陈默', 'kind': '对白', 'text': fragment,
             'start': 0.5, 'end': 2.2, 'profile': '短剧快节奏'},
        ])
        messages = [item['message'] for item in report['diagnostics']]
        self.assertFalse(any('跨块片段' in message for message in messages), messages)
        self.assertTrue(any('未填 tone' in message for message in messages), messages)


if __name__ == '__main__':
    unittest.main()
