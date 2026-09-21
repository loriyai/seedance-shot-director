"""V1.23 regression checks for the mechanical strip and coverage gates.

The review pass only fixes grammar and normalises dialogue line breaks, so the
fixtures use text-correction and point-of-concern markers only.
"""

import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

import check_source_coverage as coverage
import strip_markers


REVIEW = """审阅稿 R1（基于原版 V0）

坟前
🟨【文字修正：原“陈默嗑头”】陈默磕头
「爹！娘！
我回来了」
🟥【文字疑点：这里有空格；未擅自修改】
说完，🟨【表达调整：原“陈默转身甩开衣摆离开潇洒”】说完，陈默潇洒转身离开
「这就走」

——————

变化摘要：文字修正 2 处（🟨）；疑点 1 处（🟥）

可执行操作：
1. 指定段落做局部修改。
2. 发送“确认剧本”，清理当前稿并立即继续分镜。
"""

SOURCE = """坟前
陈默磕头
「爹！娘！
我回来了」
说完，陈默潇洒转身离开
「这就走」
"""


class EnhancementGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(os.environ.get("SEEDANCE_TEST_TMP", tempfile.gettempdir())).resolve()
        self.root = self.temp / ("seedance-gates-" + uuid.uuid4().hex)
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_strip_removes_markers_title_and_operations_but_keeps_dialogue(self):
        review = self.write("R1.txt", REVIEW)
        output = self.root / "clean.txt"
        self.assertEqual(strip_markers.main(["--review", str(review), "--output", str(output)]), 0)
        cleaned = output.read_text(encoding="utf-8")
        for token in ("🟦", "🟥", "优化剧本", "审阅稿 R1", "变化摘要", "可执行操作", "确认剧本"):
            self.assertNotIn(token, cleaned)
        for token in ("🟨", "🟩", "🟦", "细节增强", "新增动作"):
            self.assertNotIn(token, cleaned)
        self.assertIn("陈默磕头", cleaned)
        self.assertIn("说完，陈默潇洒转身离开", cleaned)
        self.assertEqual(strip_markers.quoted_turns(cleaned), strip_markers.quoted_turns(SOURCE))

    def test_strip_refuses_marker_that_swallows_dialogue_and_existing_output(self):
        broken = self.write("R1.txt", REVIEW.replace(
            "】陈默磕头", "「爹！娘！我回来了」】陈默磕头"))
        with self.assertRaises(SystemExit):
            strip_markers.main(["--review", str(broken), "--output", str(self.root / "c.txt")])
        self.assertFalse((self.root / "c.txt").exists())
        review = self.write("R2.txt", REVIEW)
        output = self.write("clean.txt", "已存在")
        with self.assertRaises(SystemExit):
            strip_markers.main(["--review", str(review), "--output", str(output)])

    def test_coverage_gate_flags_missing_turn_and_ignores_marker_quotes(self):
        source = self.write("V0.txt", SOURCE)
        review = self.write("R1.txt", REVIEW)
        self.assertEqual(coverage.main(["--source", str(source), "--draft", str(review)]), 0)
        dropped = self.write("R2.txt", REVIEW.replace("「这就走」\n", ""))
        self.assertEqual(coverage.main(["--source", str(source), "--draft", str(dropped)]), 1)
        same = coverage.compare(coverage.quoted_turns("「爹！娘！\n我回来了」"),
                               coverage.quoted_turns("「爹！娘！我回来了」"))
        self.assertTrue(same["clean"])

    def test_coverage_gate_detects_rewrite_and_reorder(self):
        rewrote = coverage.compare(["甲：一", "乙：二"], ["甲：一", "乙：三"])
        self.assertFalse(rewrote["clean"])
        self.assertEqual(rewrote["missing"][0]["text"], "乙：二")
        reordered = coverage.compare(["甲：一", "乙：二"], ["乙：二", "甲：一"])
        self.assertFalse(reordered["clean"])
        self.assertIsNotNone(reordered["reordered"])


if __name__ == "__main__":
    unittest.main()
