#!/usr/bin/env python3
"""Validate dialogue coverage and structural invariants in Seedance shot prompts.

The validator intentionally works on plain text. It does not attempt to infer a
screenplay's plot; it verifies the explicit dialogue, block, shot, and timeline
contracts that can be checked deterministically before a prompt is delivered.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


SOURCE_LINE = re.compile(
    r"^\s*(?P<speaker>[\u4e00-\u9fffA-Za-z0-9·_-]{1,32})"
    r"\s*(?P<mode>[（(]\s*(?:OS|旁白)\s*[）)])?\s*[：:]\s*(?P<body>.+?)\s*$"
)
BLOCK_HEADER = re.compile(r"(?m)^\s*生成块\s*(?P<number>\d+)\b")
SHOT_HEADER = re.compile(r"(?m)^\s*\[镜头\s*(?P<number>\d+)\s*\]")
INTERVAL = re.compile(
    r"(?:时间(?:区间)?\s*[：:]\s*)?"
    r"(?P<start>\d+(?:\.\d+)?)\s*(?:秒|s)?\s*"
    r"(?:至|到|[-—–~～])\s*"
    r"(?P<end>\d+(?:\.\d+)?)\s*(?:秒|s)?"
)
QUOTED_TEXT = re.compile(r"“(?P<cn>[^”]+)”|「(?P<corner>[^」]+)」|『(?P<book>[^』]+)』|\"(?P<ascii>[^\"]+)\"")

SPEECH_VERBS = "说|说道|道|问|答|喊|低语|开口|回应|表示|呵斥|厉喝"
AMBIGUOUS_SPEAKER = re.compile(
    r"(?<![\u4e00-\u9fff])(?:他|她|对方|某人|角色)"
    r"(?:以|用|说道|说|道|问|答|喊|低语|开口|回应|回答|转身|抬手|后退|看向)"
)
EMPTY_SHOT = re.compile(
    r"(?:纯\s*空镜|无人物镜头|无人画面|"
    r"镜头任务\s*[：:][^；。\n]{0,24}空镜|"
    r"当前画面\s*[：:][^；。\n]{0,24}无人物)"
)
COMPOSITION_FIELD = re.compile(r"(?:^|[；;\n])\s*构图\s*[：:]")
TAIL_SILENT_SIGNAL = re.compile(r"(?:无对白|无台词).{0,24}?(?:尾帧|缓冲)|(?:尾帧|缓冲).{0,24}?(?:无对白|无台词)")
TAIL_SILENT_DURATION = re.compile(
    r"(?:最后|尾帧|结束前)[^。！？\n]{0,48}?0\.[3-8]\s*秒[^。！？\n]{0,36}?(?:无对白|无台词)|"
    r"(?:无对白|无台词)[^。！？\n]{0,36}?0\.[3-8]\s*秒"
)

SOURCE_LABELS = {
    "场景",
    "时间",
    "动作",
    "画面",
    "镜头",
    "旁白说明",
    "备注",
    "人物",
    "道具",
    "入口状态",
    "出口状态",
}


@dataclass(frozen=True)
class Dialogue:
    speaker: str
    text: str
    line: int


@dataclass
class Diagnostic:
    level: str
    message: str
    block: Optional[str] = None
    shot: Optional[str] = None

    def render(self) -> str:
        where = []
        if self.block is not None:
            where.append("生成块 " + self.block)
        if self.shot is not None:
            where.append("镜头 " + self.shot)
        prefix = " / ".join(where)
        return f"{self.level} [{prefix}] {self.message}" if prefix else f"{self.level} {self.message}"


def normalise_text(value: str) -> str:
    """Normalise layout only; dialogue punctuation and word order stay meaningful."""
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\u3000", "")
    return re.sub(r"\s+", "", value)


def canonical_speaker(name: str, mode: Optional[str] = None) -> str:
    name = unicodedata.normalize("NFKC", name).strip()
    compact_mode = unicodedata.normalize("NFKC", mode or "")
    is_os = "OS" in compact_mode or name.endswith("OS")
    is_narration = "旁白" in compact_mode or name == "旁白"
    if name.endswith("OS"):
        name = name[:-2]
    if name.startswith("系统"):
        name = "系统"
    if is_narration:
        return "旁白"
    return name + ("OS" if is_os else "")


def quoted_portion(body: str, speaker: str) -> str:
    """Prefer explicitly quoted text, including system interface brackets."""
    matches = list(QUOTED_TEXT.finditer(body))
    if matches:
        return "".join(next(value for value in match.groups() if value is not None) for match in matches)
    if speaker == "系统":
        system_match = re.search(r"【([^】]+)】|\[([^\]]+)\]", body)
        if system_match:
            return next(value for value in system_match.groups() if value is not None)
    body = re.sub(r"^[（(][^）)]{0,80}[）)]\s*", "", body)
    return body


def extract_source_dialogue(source: str) -> list[Dialogue]:
    dialogues: list[Dialogue] = []
    active_speaker: Optional[str] = None
    for line_number, line in enumerate(source.splitlines(), start=1):
        match = SOURCE_LINE.match(line)
        if match:
            raw_name = match.group("speaker")
            if raw_name in SOURCE_LABELS:
                active_speaker = None
                continue
            speaker = canonical_speaker(raw_name, match.group("mode"))
            body = normalise_text(quoted_portion(match.group("body"), speaker))
            if body:
                dialogues.append(Dialogue(speaker=speaker, text=body, line=line_number))
                active_speaker = speaker
            continue

        # A screenplay often wraps one continuous utterance onto the next line.
        # Preserve the rule's permitted layout change by treating that newline as
        # a Chinese comma, unless the new line looks like a direction or heading.
        plain_line = line.strip()
        if not active_speaker or not plain_line or not is_dialogue_continuation(plain_line):
            active_speaker = None
            continue
        text = normalise_text(quoted_portion(plain_line, active_speaker))
        if not text or not dialogues:
            continue
        previous = dialogues[-1]
        separator = "" if previous.text.endswith(("，", "。", "！", "？", "…", ",", ".", "!", "?")) else "，"
        dialogues[-1] = Dialogue(speaker=previous.speaker, text=previous.text + separator + text, line=previous.line)
    return dialogues


def is_dialogue_continuation(line: str) -> bool:
    if line.startswith(("（", "(", "[", "【")):
        return False
    if re.match(r"^(?:场景|时间|动作|镜头|画面|转场|旁白|系统提示)\b", line):
        return False
    # A bare physical direction must not silently become dialogue.
    return not bool(
        re.match(
            r"^[\u4e00-\u9fff]{1,8}(?:转身|低下头|走向|跪下|起身|抬手|看向|后退|倒下)(?:[，。；：:！!？?]|$)",
            line,
        )
    )


def parse_blocks(output: str) -> list[tuple[str, str]]:
    headers = list(BLOCK_HEADER.finditer(output))
    if not headers:
        return []
    blocks: list[tuple[str, str]] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(output)
        blocks.append((header.group("number"), output[header.start() : end]))
    return blocks


def parse_shots(block_text: str) -> list[tuple[str, str]]:
    headers = list(SHOT_HEADER.finditer(block_text))
    shots: list[tuple[str, str]] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(block_text)
        shots.append((header.group("number"), block_text[header.start() : end]))
    return shots


def has_interface_context(prefix: str) -> bool:
    return bool(re.search(r"(?:系统|界面|古书|书页|卷宗)[^“”\"「」『』\n]{0,64}(?:文字|显示|浮现|写着|内容)", prefix))


def speaker_before_quote(prefix: str, source_speakers: Iterable[str]) -> Optional[str]:
    """Find a named speaker immediately before a quoted line.

    Source names anchor the parse so descriptive Chinese before a character name
    cannot accidentally become part of that name.
    """
    candidate: Optional[tuple[int, str]] = None
    for source_speaker in source_speakers:
        base = source_speaker[:-2] if source_speaker.endswith("OS") else source_speaker
        if not base or base in {"系统", "旁白"}:
            continue
        pattern = re.compile(
            re.escape(base)
            + r"\s*(?P<mode>[（(]\s*(?:OS|旁白)\s*[）)]|OS|旁白)?"
            + r"[^“”\"「」『』\n]{0,72}?"
            + r"(?:" + SPEECH_VERBS + r")\s*[：:]?\s*$"
        )
        for match in pattern.finditer(prefix):
            mode = match.group("mode")
            key = canonical_speaker(base, mode)
            if candidate is None or match.start() > candidate[0]:
                candidate = (match.start(), key)
    if candidate:
        return candidate[1]
    if has_interface_context(prefix):
        return "系统"
    return None


def extract_output_dialogue(output: str, source_speakers: Iterable[str]) -> tuple[list[Dialogue], int]:
    dialogues: list[Dialogue] = []
    unassigned = 0
    previous_end = 0
    for match in QUOTED_TEXT.finditer(output):
        text = normalise_text(next(value for value in match.groups() if value is not None))
        if not text:
            previous_end = match.end()
            continue
        prefix = output[max(previous_end, match.start() - 180) : match.start()]
        speaker = speaker_before_quote(prefix, source_speakers)
        line = output.count("\n", 0, match.start()) + 1
        if speaker:
            dialogues.append(Dialogue(speaker=speaker, text=text, line=line))
        else:
            unassigned += 1
        previous_end = match.end()
    return dialogues, unassigned


def remove_quoted_text(value: str) -> str:
    return QUOTED_TEXT.sub("", value)


def block_target_duration(block_text: str, fallback: float) -> float:
    header = block_text.split("\n", 1)[0]
    match = re.search(r"(?:总时长|时长)\s*[：:]\s*(\d+(?:\.\d+)?)\s*秒", header)
    return float(match.group(1)) if match else fallback


def is_pure_empty_shot(shot_text: str) -> bool:
    if not EMPTY_SHOT.search(shot_text):
        return False
    # A named character acting in an explicitly labelled establishing shot is
    # not a pure empty shot for the budget check.
    return not bool(re.search(r"(?:人物|角色|[\u4e00-\u9fff]{2,5})(?:入画|出现|走入|转身|抬手|开口|说|道)", shot_text))


def validate_structure(output: str, duration: float) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    blocks = parse_blocks(output)
    if not blocks:
        return [Diagnostic("ERROR", "未找到以“生成块 N”开头的生成块。")]

    for block_number, block_text in blocks:
        shots = parse_shots(block_text)
        target = block_target_duration(block_text, duration)
        if abs(target - duration) > 0.05:
            diagnostics.append(
                Diagnostic("ERROR", f"块头时长为 {target:g} 秒，与 --duration {duration:g} 秒不一致。", block_number)
            )
        if abs(target - 15) <= 0.05 and len(shots) != 5:
            diagnostics.append(
                Diagnostic("ERROR", f"15 秒生成块必须有 5 个镜头，当前为 {len(shots)} 个。", block_number)
            )
        if not shots:
            continue

        previous_end: Optional[float] = None
        empty_run = 0
        empty_total = 0
        for shot_number, shot_text in shots:
            if not COMPOSITION_FIELD.search(shot_text):
                diagnostics.append(Diagnostic("ERROR", "缺少逐镜“构图”字段。", block_number, shot_number))
            intervals = list(INTERVAL.finditer(shot_text))
            if not intervals:
                diagnostics.append(Diagnostic("ERROR", "缺少“起点-终点秒”的时间区间。", block_number, shot_number))
            else:
                interval = intervals[0]
                start = float(interval.group("start"))
                end = float(interval.group("end"))
                if end <= start:
                    diagnostics.append(Diagnostic("ERROR", f"时间区间 {start:g}-{end:g} 秒无效。", block_number, shot_number))
                if previous_end is None:
                    if abs(start) > 0.05:
                        diagnostics.append(Diagnostic("ERROR", f"首镜必须从 0 秒开始，当前为 {start:g} 秒。", block_number, shot_number))
                elif abs(start - previous_end) > 0.05:
                    diagnostics.append(
                        Diagnostic(
                            "ERROR",
                            f"时间轴不连续：上一镜结束于 {previous_end:g} 秒，当前从 {start:g} 秒开始。",
                            block_number,
                            shot_number,
                        )
                    )
                previous_end = end

                if is_pure_empty_shot(shot_text):
                    empty_run += 1
                    empty_total += 1
                    if end - start > 1.5 + 0.05:
                        diagnostics.append(Diagnostic("ERROR", "纯空镜不得超过 1.5 秒。", block_number, shot_number))
                    if empty_run >= 2:
                        diagnostics.append(Diagnostic("ERROR", "不允许连续两个纯空镜。", block_number, shot_number))
                else:
                    empty_run = 0

        if previous_end is not None and abs(previous_end - target) > 0.05:
            diagnostics.append(
                Diagnostic("ERROR", f"末镜结束于 {previous_end:g} 秒，时间轴总长应为 {target:g} 秒。", block_number)
            )
        if abs(target - 15) <= 0.05 and empty_total > 1:
            diagnostics.append(Diagnostic("ERROR", f"15 秒块通常最多一个纯空镜，当前为 {empty_total} 个。", block_number))

        last_shot_number, last_shot = shots[-1]
        if not TAIL_SILENT_SIGNAL.search(last_shot):
            diagnostics.append(Diagnostic("ERROR", "末镜缺少 0.3-0.8 秒无对白/无台词尾帧提示。", block_number, last_shot_number))
        elif not TAIL_SILENT_DURATION.search(last_shot):
            diagnostics.append(Diagnostic("ERROR", "末镜写有无台词尾帧，但未标明 0.3-0.8 秒缓冲。", block_number, last_shot_number))

    stripped_output = remove_quoted_text(output)
    for match in AMBIGUOUS_SPEAKER.finditer(stripped_output):
        line = output.count("\n", 0, match.start()) + 1
        diagnostics.append(Diagnostic("ERROR", f"第 {line} 行含模糊人物指代“{match.group(0)}”。请写明角色全名或身份。"))
    return diagnostics


def count_non_overlapping(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    count = 0
    position = 0
    while True:
        position = haystack.find(needle, position)
        if position < 0:
            return count
        count += 1
        position += len(needle)


def validate_dialogue(source: str, output: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    expected = extract_source_dialogue(source)
    if not expected:
        diagnostics.append(Diagnostic("WARN", "源文本未识别到“说话人：台词”格式的对白，跳过对白覆盖校验。"))
        return diagnostics

    source_speakers = {entry.speaker for entry in expected}
    actual, unassigned = extract_output_dialogue(output, source_speakers)
    streams: dict[str, str] = defaultdict(str)
    for entry in actual:
        streams[entry.speaker] += entry.text
    if unassigned:
        diagnostics.append(Diagnostic("WARN", f"输出中有 {unassigned} 段引号文本未找到明确说话人；系统界面文字应标明“系统”。"))

    required_counts = Counter((entry.speaker, entry.text) for entry in expected)
    for (speaker, text), expected_count in required_counts.items():
        actual_count = count_non_overlapping(streams[speaker], text)
        if actual_count < expected_count:
            other_speakers = [
                name for name, stream in streams.items() if name != speaker and count_non_overlapping(stream, text)
            ]
            wrong_speaker = f"；疑似被归为 {', '.join(other_speakers)}" if other_speakers else ""
            diagnostics.append(
                Diagnostic(
                    "ERROR",
                    f"源文本第 {next(item.line for item in expected if item.speaker == speaker and item.text == text)} 行的 {speaker} 台词缺失：{text}{wrong_speaker}",
                )
            )
        elif actual_count > expected_count:
            diagnostics.append(
                Diagnostic("ERROR", f"{speaker} 台词重复 {actual_count - expected_count} 次：{text}")
            )
    return diagnostics


def validate(source: str, output: str, duration: float) -> list[Diagnostic]:
    return validate_structure(output, duration) + validate_dialogue(source, output)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验 Seedance 生成块的对白覆盖、时间轴和关键结构约束。"
    )
    parser.add_argument("--source", required=True, type=Path, help="原始剧本文本路径")
    parser.add_argument("--output", required=True, type=Path, help="生成块提示词文本路径")
    parser.add_argument("--duration", type=float, default=15.0, help="每个生成块目标时长，默认 15 秒")
    args = parser.parse_args(argv)

    if args.duration <= 0:
        parser.error("--duration 必须大于 0")
    for path in (args.source, args.output):
        if not path.is_file():
            parser.error(f"文件不存在：{path}")

    source = args.source.read_text(encoding="utf-8")
    output = args.output.read_text(encoding="utf-8")
    diagnostics = validate(source, output, args.duration)
    for diagnostic in diagnostics:
        print(diagnostic.render())
    errors = sum(diagnostic.level == "ERROR" for diagnostic in diagnostics)
    warnings = sum(diagnostic.level == "WARN" for diagnostic in diagnostics)
    print(f"校验完成：{errors} 个错误，{warnings} 个警告。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
