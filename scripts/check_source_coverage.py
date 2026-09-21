#!/usr/bin/env python3
"""Gate every review or clean draft against the locked source.

Hard check: the ordered list of quoted turns must match the locked source
verbatim, so a dropped or reworded line cannot leave the enhancement stage.
Optional narration audit lists source action lines that no longer appear in any
form; refinements legitimately rewrite those, so it reports instead of failing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_dialogue_and_timeline import QUOTED_TEXT, normalise_utterance  # noqa: E402
from strip_markers import strip as strip_review_markers  # noqa: E402


def quoted_turns(text: str) -> list[str]:
    return [normalise_utterance("".join(value for value in match.groups() if value is not None))
            for match in QUOTED_TEXT.finditer(text)]


def narration_lines(text: str) -> list[str]:
    stripped = QUOTED_TEXT.sub("\n", text)
    lines = []
    for raw in stripped.split("\n"):
        line = raw.strip()
        if not line or line.startswith(("优化剧本", "变化摘要", "可执行操作")):
            continue
        if re.fullmatch(r"[—\-]{3,}", line):
            continue
        lines.append(line)
    return lines


def compare(source_turns: list[str], draft_turns: list[str]) -> dict:
    report = {"missing": [], "extra": [], "reordered": None}
    remaining = list(draft_turns)
    for index, turn in enumerate(source_turns, 1):
        if turn in remaining:
            remaining.remove(turn)
        else:
            report["missing"].append({"turn": index, "text": turn})
    source_set = set(source_turns)
    for index, turn in enumerate(draft_turns, 1):
        if turn not in source_set:
            report["extra"].append({"turn": index, "text": turn})
    if not report["missing"] and not report["extra"] and source_turns != draft_turns:
        for index, (left, right) in enumerate(zip(source_turns, draft_turns)):
            if left != right:
                report["reordered"] = {"index": index + 1, "source": left, "draft": right}
                break
        if report["reordered"] is None and len(source_turns) != len(draft_turns):
            report["reordered"] = {"index": min(len(source_turns), len(draft_turns)) + 1,
                                   "source": "<长度不同>", "draft": "<长度不同>"}
    report["clean"] = not report["missing"] and not report["extra"] and report["reordered"] is None
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="锁定的来源稿（V0/V0.x/C）")
    parser.add_argument("--draft", required=True, type=Path, help="待交付的审阅稿或确认稿")
    parser.add_argument("--narration", action="store_true",
                        help="额外审计动作说明是否被整段吞掉（审阅稿阶段建议开启）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args(argv)
    try:
        for path in (args.source, args.draft):
            if not path.is_file():
                parser.error(f"文件不存在：{path}")
        source = args.source.read_text(encoding="utf-8")
        draft, _receipt = strip_review_markers(args.draft.read_text(encoding="utf-8"))
        source_turns, draft_turns = quoted_turns(source), quoted_turns(draft)
        report = compare(source_turns, draft_turns)
        report.update({"source": str(args.source), "draft": str(args.draft),
                       "source_turns": len(source_turns), "draft_turns": len(draft_turns)})
        if args.narration:
            draft_flat = QUOTED_TEXT.sub("", draft)
            report["narration_missing"] = [line for line in narration_lines(source)
                                           if line not in draft_flat and line not in draft]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"来源话轮 {report['source_turns']} 段 / 稿件话轮 {report['draft_turns']} 段")
            if report["clean"]:
                print("对白覆盖：逐段一致，未发现遗漏、新增或调序。")
            else:
                for item in report["missing"]:
                    print(f"缺失 第{item['turn']}段：{item['text']}")
                for item in report["extra"]:
                    print(f"多出 第{item['turn']}段：{item['text']}")
                if report["reordered"]:
                    print(f"顺序不一致 第{report['reordered']['index']}段："
                          f"来源“{report['reordered']['source']}” / 稿件“{report['reordered']['draft']}”")
            if args.narration:
                missing = report.get("narration_missing", [])
                print(f"动作说明审计：{len(missing)} 条原句在稿件中找不到对应文字（细化改写属正常，逐条人工确认）。")
                for line in missing[:40]:
                    print(f"  待确认：{line}")
        return 0 if report["clean"] else 1
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
