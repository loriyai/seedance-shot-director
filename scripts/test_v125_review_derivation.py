"""V1.25 回归：审阅稿由脚本派生、标记可剥壳、覆盖差分先于写出。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import derive_review
import strip_markers


SOURCE = """两座坟前
陈默磕头
「爹！娘！
我回来了」
陈默无奈跪下，
OS「我他娘的来了！」
"""


class ReviewDerivationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "V0.txt"
        self.source.write_text(SOURCE, encoding="utf-8")
        self.output = self.root / "R1.md"

    def tearDown(self):
        self._tmp.cleanup()

    def derive(self, config, output=None):
        edits = self.root / "edits.json"
        edits.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        argv = ["--source", str(self.source), "--edits", str(edits),
                "--output", str(output or self.output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = derive_review.main(argv)
        return code, stdout.getvalue()

    def test_same_turn_newlines_are_joined_and_still_cover(self):
        code, receipt = self.derive({"title": "审阅稿 R1（基于原版 V0）"})
        self.assertEqual(code, 0)
        report = json.loads(receipt)
        self.assertEqual(report["coverage"], "clean")
        self.assertEqual(report["joined_turns"], 1)
        draft = self.output.read_text(encoding="utf-8")
        self.assertIn("「爹！娘！我回来了」", draft)
        self.assertNotIn("「爹！娘！\n我回来了」", draft)

    def test_action_line_edit_keeps_marker_and_passes_gate(self):
        code, receipt = self.derive({
            "title": "审阅稿 R1（基于原版 V0）",
            "line_edits": [{"old": "陈默无奈跪下，", "new": "陈默无奈跪下",
                            "marker": "🟨【文字修正：原“陈默无奈跪下，”】"}],
        })
        self.assertEqual(code, 0)
        report = json.loads(receipt)
        self.assertEqual(report["line_edits"], 1)
        self.assertEqual(report["narration_missing"], ["陈默无奈跪下，"])
        draft = self.output.read_text(encoding="utf-8")
        self.assertIn("陈默无奈跪下 🟨【文字修正：原“陈默无奈跪下，”】", draft)

    def test_space_note_only_marks_without_deleting(self):
        self.source.write_text(SOURCE.replace("陈默磕头", "陈默磕头 "), encoding="utf-8")
        code, receipt = self.derive({
            "title": "审阅稿 R1（基于原版 V0）",
            "space_notes": [{"line": "陈默磕头 ",
                             "note": "🟥【文字疑点：行尾有一个半角空格；未经确认未删除】"}],
        })
        self.assertEqual(code, 0)
        report = json.loads(receipt)
        self.assertEqual(report["space_notes"], 1)
        self.assertEqual(report["line_edits"], 0)
        draft = self.output.read_text(encoding="utf-8")
        self.assertIn("陈默磕头 🟥【文字疑点：行尾有一个半角空格；未经确认未删除】", draft)

    def test_unmatched_edit_is_rejected_without_writing(self):
        with self.assertRaises(SystemExit) as caught:
            self.derive({"line_edits": [{"old": "陈默挠头", "new": "陈默挠了挠头"}]})
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_reworded_dialogue_is_blocked_by_gate(self):
        with self.assertRaises(SystemExit) as caught:
            self.derive({"line_edits": [{"old": "「爹！娘！我回来了」",
                                         "new": "「爹！娘！我这就回来了」"}]})
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_duplicate_line_target_is_rejected(self):
        self.source.write_text(SOURCE.replace("陈默磕头", "陈默磕头\n陈默磕头"),
                               encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.derive({"line_edits": [{"old": "陈默磕头", "new": "陈默躬身"}]})
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_derived_draft_survives_stripping_unchanged(self):
        self.derive({
            "title": "审阅稿 R1（基于原版 V0）",
            "line_edits": [{"old": "陈默无奈跪下，", "new": "陈默无奈跪下",
                            "marker": "🟨【文字修正：原“陈默无奈跪下，”】"}],
        })
        raw = self.output.read_text(encoding="utf-8")
        cleaned, receipt = strip_markers.strip(raw)
        self.assertEqual(receipt["stripped_markers"], 1)
        self.assertNotIn("🟨", cleaned)
        self.assertEqual(strip_markers.quoted_turns(raw), strip_markers.quoted_turns(cleaned))
        self.assertNotIn("变化摘要", cleaned)
        self.assertNotIn("可执行操作", cleaned)

    def test_existing_output_is_not_overwritten(self):
        self.output.write_text("已有稿件", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.derive({"title": "审阅稿 R1（基于原版 V0）"})
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "已有稿件")


if __name__ == "__main__":
    unittest.main()
