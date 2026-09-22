"""V1.28 回归：块内长话轮应保留完整话轮 + span，片段只用于跨块。"""

import unittest

import compile_plan


SOURCE = """坟前
「贼老天，我干你娘！刚穿越就让我捡到绝世秘籍，可我却资质平庸，幸好老子会经商，不然我可怎么活啊！」
"""


def voice(vid, text, start, end):
    return {'id': vid, 'speaker': '陈默', 'kind': '对白', 'text': text, 'start': start, 'end': end}


def plan(blocks):
    return {'schema_version': 5,
            'boundary_context': {'incoming': None, 'outgoing': None},
            'defaults': {'style': '风格', 'scene': '院中', 'atmosphere': '安静'},
            'beats': [{'id': 'E01', 'evidence': '陈默磕头'}],
            'blocks': blocks}


def block(voices):
    return {'duration': 15, 'scene_id': 'chenfu', 'time_id': 'day', 'characters': [],
            'voices': voices, 'shots': [{'start': 0, 'end': 5, 'beats': ['E01'],
                                         'action': '陈默站在石阶前骂天。', 'camera': '中景，固定机位。'}]}


class FragmentSplitTests(unittest.TestCase):
    def test_two_fragments_in_one_block_warn(self):
        data = plan([block([
            voice('V01', '贼老天，我干你娘！', 0.5, 2.0),
            voice('V02', '刚穿越就让我捡到绝世秘籍，', 2.2, 5.0),
        ])])
        messages = [item.message for item in compile_plan.fragment_split_diagnostics(data, SOURCE)]
        self.assertTrue(any('同一块内把同一话轮拆成多个片段' in message for message in messages), messages)

    def test_fragments_across_blocks_do_not_warn(self):
        data = plan([block([voice('V01', '贼老天，我干你娘！', 0.5, 2.0)]),
                     block([voice('V02', '刚穿越就让我捡到绝世秘籍，', 0.5, 3.5)])])
        self.assertEqual(compile_plan.fragment_split_diagnostics(data, SOURCE), [])

    def test_complete_turn_is_not_a_fragment(self):
        full = ('贼老天，我干你娘！刚穿越就让我捡到绝世秘籍，可我却资质平庸，'
                '幸好老子会经商，不然我可怎么活啊！')
        data = plan([block([voice('V01', full, 0.5, 9.0)])])
        self.assertEqual(compile_plan.fragment_split_diagnostics(data, SOURCE), [])


if __name__ == '__main__':
    unittest.main()
