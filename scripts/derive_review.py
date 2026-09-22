#!/usr/bin/env python3
"""Derive a full review draft (R) from a locked source without hand-typing.

用法：

    python -B scripts/derive_review.py --source <锁定来源> --edits <编辑清单.json> \
        --output <审阅稿.md>

编辑清单（JSON）：

    {
      "title": "审阅稿 R1（基于原版 V0）",
      "line_edits": [{"old": "原样整行", "new": "修正后整行",
                      "marker": "🟨【文字修正：原“……”】"}],
      "space_notes": [{"line": "原样整行",
                       "note": "🟥【文字疑点：……；未经确认未删除】"}],
      "summary": "可选；省略时按实际计数生成",
      "operations": ["可选；省略时使用标准四项"]
    }

正文按来源顺序逐行派生：只做清单里的原位替换，不重写相邻行、不跳行。同一话轮内部的
排版换行按 dialogue-normalization 规则替换为标点，其余字符原样保留。写出前对锁定来源
跑一次覆盖差分闸门，出现缺失、新增或调序即报错且不写文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_source_coverage as coverage  # noqa: E402
from strip_markers import strip as strip_review_markers  # noqa: E402
from validate_dialogue_and_timeline import QUOTED_TEXT, normalise_utterance  # noqa: E402

DEFAULT_OPERATIONS = [
    "可执行操作：",
    "1. 指定段落做局部修改。",
    "2. 发送“确认剧本”，清理当前稿并立即继续分镜。",
    "3. 发送“重新优化剧本”，从当前原版基线重做。",
    "4. 发送“使用原版剧本”，忽略审阅稿并直接分镜。",
]


class EditError(ValueError):
    """编辑清单与锁定来源不一致。"""


def normalise_turns(text: str) -> tuple[str, int]:
    """同一话轮内部的排版换行替换为规范化标点，其余字符不动。"""
    parts: list[str] = []
    cursor = 0
    joined = 0
    for match in QUOTED_TEXT.finditer(text):
        body = next(value for value in match.groups() if value is not None)
        if "\n" not in body:
            continue
        joined += 1
        parts.append(text[cursor:match.start()])
        parts.append(match.group(0)[0] + normalise_utterance(body) + match.group(0)[-1])
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts), joined


def _locate(lines: list[str], wanted: str, label: str) -> int:
    hits = [index for index, line in enumerate(lines) if line.strip() == wanted.strip()]
    if not hits:
        raise EditError(f"{label} 在来源中找不到唯一整行：{wanted!r}")
    if len(hits) > 1:
        raise EditError(f"{label} 在来源中匹配到 {len(hits)} 行，需扩大上下文：{wanted!r}")
    return hits[0]


def build_draft(source_text: str, config: dict) -> tuple[str, dict]:
    body, joined = normalise_turns(source_text)
    lines = body.split("\n")
    touched: dict[int, str] = {}
    applied: list[dict] = []

    for edit in config.get("line_edits", []):
        for key in ("old", "new"):
            if not edit.get(key):
                raise EditError(f"line_edits 缺少 {key}：{edit!r}")
        index = _locate(lines, edit["old"], "line_edits.old")
        if index in touched:
            raise EditError(f"同一行被多处编辑命中：{lines[index]!r}")
        marker = edit.get("marker", "")
        touched[index] = f"{edit['new']} {marker}".rstrip()
        applied.append({"kind": "line_edit", "line_number": index + 1,
                        "old": edit["old"], "new": edit["new"]})

    for note in config.get("space_notes", []):
        if not note.get("line") or not note.get("note"):
            raise EditError(f"space_notes 缺少 line 或 note：{note!r}")
        index = _locate(lines, note["line"], "space_notes.line")
        if index in touched:
            raise EditError(f"同一行被多处编辑命中：{lines[index]!r}")
        touched[index] = f"{lines[index].rstrip()} {note['note']}"
        applied.append({"kind": "space_note", "line_number": index + 1,
                        "line": note["line"]})

    for index, value in touched.items():
        lines[index] = value
    body = "\n".join(lines)

    title = config.get("title") or "审阅稿 R1（基于原版 V0）"
    line_edit_count = sum(1 for item in applied if item["kind"] == "line_edit")
    space_note_count = sum(1 for item in applied if item["kind"] == "space_note")
    summary = config.get("summary") or (
        f"变化摘要：动作说明 {line_edit_count} 处最小文字修正、"
        f"{space_note_count} 处疑点只标记未删除、"
        f"{joined} 段话轮内部换行按规范化合并为单行（无标记，不新增词句）。"
    )
    operations = "\n".join(config.get("operations") or DEFAULT_OPERATIONS)
    draft = f"{title}\n\n{summary}\n\n{body}\n\n{operations}\n"
    receipt = {"joined_turns": joined, "line_edits": line_edit_count,
               "space_notes": space_note_count, "summary": summary}
    return draft, receipt


def gate(source_text: str, draft: str) -> dict:
    cleaned, _ = strip_review_markers(draft)
    source_turns = coverage.quoted_turns(source_text)
    draft_turns = coverage.quoted_turns(cleaned)
    report = coverage.compare(source_turns, draft_turns)
    report["source_turns"] = len(source_turns)
    report["draft_turns"] = len(draft_turns)
    report["narration_missing"] = [
        line for line in coverage.narration_lines(source_text)
        if line not in QUOTED_TEXT.sub("", cleaned) and line not in cleaned
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="锁定的来源稿（V0/V0.x/C）")
    parser.add_argument("--edits", required=True, type=Path, help="编辑清单 JSON")
    parser.add_argument("--output", required=True, type=Path, help="写出的审阅稿（R）")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")
    args = parser.parse_args(argv)
    try:
        if not args.source.is_file():
            parser.error(f"来源不存在：{args.source}")
        if args.output.exists() and not args.force:
            parser.error(f"输出已存在，不覆盖：{args.output}（如确要覆盖请加 --force）")
        source_text = args.source.read_text(encoding="utf-8")
        config = json.loads(args.edits.read_text(encoding="utf-8"))
        draft, receipt = build_draft(source_text, config)
        report = gate(source_text, draft)
        if not report["clean"]:
            raise EditError(
                f"覆盖差分未通过：缺失 {len(report['missing'])} 段、"
                f"多出 {len(report['extra'])} 段、调序={report['reordered']}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(draft, encoding="utf-8", newline="")
        print(json.dumps({
            "output": str(args.output),
            "output_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
            "source_turns": report["source_turns"],
            "draft_turns": report["draft_turns"],
            "coverage": "clean",
            "joined_turns": receipt["joined_turns"],
            "line_edits": receipt["line_edits"],
            "space_notes": receipt["space_notes"],
            "narration_missing": report["narration_missing"],
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
