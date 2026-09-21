"""V1.19 regression checks for reusable source analysis caches."""

import unittest

import validate_dialogue_and_timeline as validator


class SourceAnalysisCacheTests(unittest.TestCase):
    def setUp(self):
        validator._analyse_source_dialogue_cached.cache_clear()
        validator._source_speech_candidate_index.cache_clear()

    def test_dialogue_source_is_parsed_once_and_results_are_fresh(self):
        source = '陈默：「我  不走。」'

        first_dialogues, first_diagnostics = validator.analyse_source_dialogue(source)
        first_info = validator._analyse_source_dialogue_cached.cache_info()
        self.assertEqual((first_info.misses, first_info.hits), (1, 0))

        first_dialogues.clear()
        first_diagnostics[0].message = '被调用方修改过的消息'
        second_dialogues, second_diagnostics = validator.analyse_source_dialogue(source)
        second_info = validator._analyse_source_dialogue_cached.cache_info()

        self.assertEqual((second_info.misses, second_info.hits), (1, 1))
        self.assertEqual([entry.text for entry in second_dialogues], ['我  不走。'])
        self.assertIn('多余空格', second_diagnostics[0].message)
        self.assertIsNot(first_diagnostics[0], second_diagnostics[0])

    def test_many_boundary_lookups_build_one_long_source_index(self):
        source = '\n'.join(
            f'角色{number}：「第{number}句，继续。」' for number in range(600)
        )
        text = '第599句，继续。'
        split = text.index('，') + 1

        for _ in range(40):
            self.assertTrue(validator.source_backed_speech_boundary(
                source, text, split, '角色599', '对白'
            ))

        info = validator._source_speech_candidate_index.cache_info()
        self.assertEqual(info.misses, 1)
        self.assertEqual(info.hits, 39)

    def test_boundary_index_preserves_speaker_and_display_semantics(self):
        text = '甲，乙。'
        split = 2
        labelled = '陈默：「甲，乙。」'
        self.assertTrue(validator.source_backed_speech_boundary(
            labelled, text, split, '陈默', '对白'
        ))
        self.assertFalse(validator.source_backed_speech_boundary(
            labelled, text, split, '吴天德', '对白'
        ))
        self.assertFalse(validator.source_backed_speech_boundary(
            '画面文字：「甲，乙。」', text, split, '陈默', '对白'
        ))
        self.assertFalse(validator.source_backed_speech_boundary(
            '陈默：「甲，乙。」（仅展示，不念）', text, split, '陈默', '对白'
        ))

        bare = '陈默转身\n「甲，乙。」'
        self.assertTrue(validator.source_backed_speech_boundary(
            bare, text, split, '吴天德', '对白'
        ))

    def test_boundary_index_keeps_newline_normalisation_for_unquoted_dialogue(self):
        source = '陈默：第一行\n第二行。'
        text = '第一行，第二行。'
        split = text.index('，') + 1

        self.assertTrue(validator.source_backed_speech_boundary(
            source, text, split, '陈默', '对白'
        ))
        self.assertFalse(validator.source_backed_speech_boundary(
            source, text, split, '吴天德', '对白'
        ))


if __name__ == '__main__':
    unittest.main()
