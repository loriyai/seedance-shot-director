import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from prepare_source import prepare


class SourcePreflightTests(unittest.TestCase):
    def test_prepare_reuses_normalised_turns_and_spacing_diagnostics(self):
        source = '陈默：「我捡到绝世秘籍  《玄清功》\n给我十年」'
        result = prepare(source)
        self.assertEqual(result['dialogues'][0]['text'], '我捡到绝世秘籍  《玄清功》，给我十年')
        self.assertEqual(result['dialogues'][0]['voice_type'], '对白')
        self.assertTrue(any('多余空格' in item['message'] for item in result['diagnostics']))
        self.assertEqual(len(result['source_sha256']), 64)

    def test_standalone_quote_is_retained_without_inventing_a_speaker(self):
        source = '两座坟前\n陈默磕头\n「爹！娘！\n给我十年」'
        result = prepare(source)
        self.assertEqual(result['dialogues'], [])
        self.assertEqual(len(result['unresolved_utterances']), 1)
        turn = result['unresolved_utterances'][0]
        self.assertEqual(turn['text'], '爹！娘！给我十年')
        self.assertEqual(turn['voice_type'], 'unknown')
        self.assertIn('陈默磕头', turn['context_before'])

    def test_named_action_line_is_not_swallowed_as_unquoted_dialogue(self):
        result = prepare('陈默：第一句\n陈默挠挠头\n第二句')
        self.assertEqual([turn['text'] for turn in result['dialogues']], ['第一句'])

    def test_other_named_actor_action_also_stops_the_turn(self):
        result = prepare('陈默：第一句\n小孙女跑过来\n第二句')
        self.assertEqual([turn['text'] for turn in result['dialogues']], ['第一句'])
        self.assertTrue(any('停止无引号连续话轮' in item['message'] for item in result['diagnostics']))

    def test_bare_action_also_stops_the_turn(self):
        result = prepare('陈默：第一句\n挠挠头\n第二句')
        self.assertEqual([turn['text'] for turn in result['dialogues']], ['第一句'])
        self.assertTrue(any('停止无引号连续话轮' in item['message'] for item in result['diagnostics']))

    def test_first_person_action_word_can_remain_spoken_text(self):
        result = prepare('陈默：第一句\n我们转身就走。')
        self.assertEqual([turn['text'] for turn in result['dialogues']], ['第一句，我们转身就走。'])

    def test_action_word_inside_spoken_sentence_is_not_a_named_direction(self):
        samples = [
            ('陈默：我记得那场雨\n也记得你转身时的背影。', '我记得那场雨，也记得你转身时的背影。'),
            ('陈默：我想问你\n陈默会转身吗？', '我想问你，陈默会转身吗？'),
            ('陈默：我不明白\n小孙女为什么跑过来？', '我不明白，小孙女为什么跑过来？'),
        ]
        for source, expected in samples:
            with self.subTest(source=source):
                result = prepare(source)
                self.assertEqual([turn['text'] for turn in result['dialogues']], [expected])

    def test_unquoted_continuation_without_action_still_normalises_newline(self):
        result = prepare('陈默：第一句\n第二句')
        self.assertEqual([turn['text'] for turn in result['dialogues']], ['第一句，第二句'])

    def test_cli_can_emit_machine_readable_json(self):
        script = Path(__file__).resolve().parent / 'prepare_source.py'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.txt'
            source.write_text('林舟：明日出发。', encoding='utf-8')
            analysis = Path(directory) / 'analysis.json'
            completed = subprocess.run(
                [sys.executable, '-B', str(script), '--source', str(source), '--output', str(analysis)],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload['dialogue_count'], 1)
            self.assertEqual(payload['unresolved_utterance_count'], 0)
            self.assertEqual(payload['diagnostics_truncated'], 0)
            self.assertNotIn('dialogues', payload)
            saved = json.loads(analysis.read_text(encoding='utf-8'))
            self.assertEqual(saved['dialogues'][0]['speaker'], '林舟')

    def test_cli_summary_caps_diagnostics_while_sidecar_keeps_all(self):
        script = Path(__file__).resolve().parent / 'prepare_source.py'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.txt'
            source.write_text(
                '\n'.join(f'角色{index}：「第  {index}句」' for index in range(30)),
                encoding='utf-8',
            )
            analysis = Path(directory) / 'analysis.json'
            completed = subprocess.run(
                [sys.executable, '-B', str(script), '--source', str(source), '--output', str(analysis)],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
            )
            summary = json.loads(completed.stdout)
            saved = json.loads(analysis.read_text(encoding='utf-8'))
            self.assertEqual(summary['diagnostic_count'], 30)
            self.assertEqual(len(summary['diagnostic_sample']), 8)
            self.assertEqual(summary['diagnostics_truncated'], 22)
            self.assertEqual(len(saved['diagnostics']), 30)
            self.assertEqual(len(saved['unresolved_utterances']), 0)

    def test_many_unresolved_quotes_share_one_summary_diagnostic(self):
        result = prepare('\n'.join(f'「第{index}句」' for index in range(30)))
        self.assertEqual(len(result['unresolved_utterances']), 30)
        self.assertEqual(len(result['diagnostics']), 1)
        self.assertIn('30 个引号段', result['diagnostics'][0]['message'])


if __name__ == '__main__':
    unittest.main()
