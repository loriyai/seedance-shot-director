"""V1.22 起草前预计算：话轮单位、合法切分点与骨架覆盖差分。"""

from pathlib import Path
import unittest

from plan_voices import plan_report, source_utterances, text_report


SOURCE = """两座坟前
陈默磕头
「爹！娘！
我捡到一本绝世秘籍《玄清功》，给我十年」
陈默站起身
系统：「凡人百世书，宿主第一世结束」
」
"""


def voice(identifier, text, start, end, **extra):
    record = {'id': identifier, 'speaker': '陈默', 'kind': '对白', 'text': text,
              'start': start, 'end': end}
    record.update(extra)
    return record


def plan_with(voices):
    return {'schema_version': 5, 'blocks': [
        {'duration': 15, 'scene_id': 's', 'time_id': 't', 'characters': [], 'voices': voices,
         'shots': []},
    ]}


class PlanVoicesTests(unittest.TestCase):
    def test_text_mode_reports_units_bands_and_legal_splits(self):
        report = text_report(SOURCE, '爹！娘！我捡到一本绝世秘籍《玄清功》，给我十年', '短剧常速', 0.5)
        self.assertGreater(report['units'], 10)
        self.assertTrue(report['source_backed_utterance'])
        band = report['pace_bands_by_profile']['短剧常速']
        self.assertLess(band[0], band[1])
        self.assertAlmostEqual(band[0], round(report['units'] / 5.2, 2), places=2)
        self.assertAlmostEqual(band[1], round(report['units'] / 4.0, 2), places=2)
        indexes = [item['index'] for item in report['legal_split_points']]
        self.assertIn(4, indexes)
        self.assertNotIn(1, indexes)
        for item in report['legal_split_points']:
            self.assertGreater(item['left_units'], 0)
            self.assertGreater(item['right_units'], 0)
        suggestions = report['pace_bands_by_profile'].keys()
        self.assertIn('情绪慢速', suggestions)

    def test_text_mode_marks_fragment_as_not_source_backed(self):
        report = text_report(SOURCE, '爹！娘！', '短剧常速', 0.5)
        self.assertFalse(report['source_backed_utterance'])
        self.assertTrue(any('不是锁定来源中的完整话轮' in note for note in report['notes']))

    def test_text_mode_marks_complete_source_utterance(self):
        report = text_report(SOURCE, '凡人百世书，宿主第一世结束', '短剧常速', 1.0)
        self.assertTrue(report['source_backed_utterance'])

    def test_plan_mode_passes_on_covering_plan(self):
        report = plan_report(SOURCE, plan_with([
            voice('V1', '爹！娘！我捡到一本绝世秘籍《玄清功》，给我十年', 0.5, 6.0),
            voice('V2', '凡人百世书，宿主第一世结束', 6.5, 9.5),
        ]))
        self.assertEqual(report['errors'], 0)
        self.assertEqual(report['units']['source'], report['units']['planned'])
        self.assertEqual(report['missing_lines'], [])

    def test_plan_mode_catches_dropped_fragment(self):
        report = plan_report(SOURCE, plan_with([
            voice('V1', '爹！娘！我捡到一本绝世秘籍《玄清功》，给我十年', 0.5, 6.0),
            voice('V2', '凡人百世书，', 6.5, 9.5),
        ]))
        self.assertEqual(report['status'], 'hard_failed')
        self.assertEqual(report['missing_lines'], [6])
        self.assertNotEqual(report['units']['source'], report['units']['planned'])
        messages = ' '.join(item['message'] for item in report['diagnostics'])
        self.assertIn('未进入规划', messages)
        self.assertIn('可发音单位总量不一致', messages)

    def test_plan_mode_flags_pacing_band_and_overflow(self):
        report = plan_report(SOURCE, plan_with([
            voice('V1', '爹！娘！我捡到一本绝世秘籍《玄清功》，给我十年', 0.5, 12.0),
            voice('V2', '凡人百世书，宿主第一世结束', 12.5, 16.0),
        ]))
        messages = ' '.join(item['message'] for item in report['diagnostics'])
        self.assertIn('净发音语速不符', messages)
        self.assertIn('超出本块', messages)

    def test_plan_mode_flags_overlapping_turns(self):
        report = plan_report(SOURCE, plan_with([
            voice('V1', '爹！娘！我捡到一本绝世秘籍《玄清功》，给我十年', 0.5, 6.0),
            voice('V2', '凡人百世书，宿主第一世结束', 5.0, 9.5),
        ]))
        messages = ' '.join(item['message'] for item in report['diagnostics'])
        self.assertIn('时间重叠', messages)

    def test_source_utterances_include_unattributed_quotes_in_order(self):
        lines = [item['line'] for item in source_utterances(SOURCE)]
        self.assertEqual(lines, sorted(lines))
        self.assertEqual(len(lines), 2)

    def test_cli_and_module_paths_exist(self):
        root = Path(__file__).resolve().parent.parent
        self.assertTrue((root / 'scripts' / 'plan_voices.py').exists())
        self.assertIn('plan_voices.py', (root / 'SKILL.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
