#!/usr/bin/env python3
"""Mechanically derive a clean draft from a review draft.

The confirmation draft is never hand-typed: this tool removes the version title,
every review marker (text corrections and point-of-concern notes) and the trailing operation list, then
proves the locked dialogue text survived unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_dialogue_and_timeline import QUOTED_TEXT, normalise_utterance  # noqa: E402

MARKER = re.compile(r"[🟨🟥]【[^】]*】")
TITLE = re.compile(r"^\s*(?:优化剧本|剧本审阅稿|审阅稿)\s*(?:R\d+)?\s*[（(][^）)]*(?:审阅稿|基于原版)[^）)]*[）)]\s*$")
TRAILER = re.compile(r"^\s*(?:[—\-]{3,}|变化摘要\s*[：:]|可执行操作\s*[：:]|本稿操作\s*[：:])")
OPERATION = re.compile(r"^\s*(?:\d+[\.、]|[-*])\s*(?:指定段落|发送|重新优化|使用原版)")


CORNER_QUOTE = re.compile(r"「([^」]*)」")


def quoted_turns(text: str) -> list[str]:
    """Corner-bracket dialogue only: review markers use “ ” and must not count."""
    return [normalise_utterance(match.group(1)) for match in CORNER_QUOTE.finditer(text)]


def strip(text: str) -> tuple[str, dict]:
    kept: list[str] = []
    dropped_lines = 0
    inline_markers = 0
    for line in text.split("\n"):
        if TITLE.match(line) or TRAILER.match(line) or OPERATION.match(line):
            dropped_lines += 1
            continue
        cleaned, count = MARKER.subn("", line)
        inline_markers += count
        if count and not cleaned.strip():
            dropped_lines += 1
            continue
        kept.append(cleaned)
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip("\n") + "\n"
    return cleaned, {"dropped_lines": dropped_lines, "stripped_markers": inline_markers}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, type=Path, help="当前审阅稿（R 稿）")
    parser.add_argument("--output", required=True, type=Path, help="写出的干净确认稿")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")
    args = parser.parse_args(argv)
    try:
        if not args.review.is_file():
            parser.error(f"审阅稿不存在：{args.review}")
        if args.output.exists() and not args.force:
            parser.error(f"输出已存在，不覆盖：{args.output}（如确要覆盖请加 --force）")
        raw = args.review.read_text(encoding="utf-8")
        cleaned, receipt = strip(raw)
        residual = MARKER.findall(cleaned)
        if residual:
            raise ValueError(f"仍有未清理的标记：{residual[:3]}")
        before, after = quoted_turns(raw), quoted_turns(cleaned)
        if before != after:
            raise ValueError("清理后对白发生变化，拒绝写出；请检查标记是否被写进了台词。")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(cleaned, encoding="utf-8", newline="")
        print(json.dumps({
            "review": str(args.review),
            "output": str(args.output),
            "output_sha256": hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
            "lines": len(cleaned.splitlines()),
            "stripped_markers": receipt["stripped_markers"],
            "dropped_lines": receipt["dropped_lines"],
            "dialogue_turns": len(after),
            "dialogue_unchanged": True,
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
