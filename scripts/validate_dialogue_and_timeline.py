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
from collections import defaultdict
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

SPEECH_VERBS = "说|说道|道|问|答|喊|低语|开口|回应|表示|呵斥|厉喝|播报|念|响起"
FIELD_HEADER = re.compile(
    r"(?m)^[ \t]*(?P<label>画面与动作|摄影机与构图|构图|表演|光线与声音|台词|衔接|画面文字|无对白尾帧|保持与风险约束)\s*[：:]"
)
QUOTED_SOURCE_LABEL = re.compile(
    r"(?:^|[；;])[ \t]*(?P<speaker>[\u4e00-\u9fffA-Za-z0-9·_-]{1,32})"
    r"\s*(?P<mode>[（(]\s*(?:OS|旁白)\s*[）)])?\s*[：:]?\s*$"
)
READING_DIRECTIVE = re.compile(r"不念|(?<![\u4e00-\u9fff])念(?![\u4e00-\u9fff])|展示")
CAMERA_MODE = re.compile(r"固定|静止机位|推近|推进|拉远|拉至|跟拍|跟随|随.*(?:上扬|移动)|横移|升降|摇摄|摇镜|环绕|上升|下降|俯冲|手持")
HIDDEN_CUT = re.compile(r"再切|随后切|切至|切到|反打|插入.{0,12}(?:特写|镜头)|蒙太奇")
MISSING_CONTEXT = re.compile(r"保持十年前.{0,8}构图|原来的位置|上一句话|沿用上一块|参考前文|同上")
EPSILON = 1e-6
AMBIGUOUS_SPEAKER = re.compile(
    r"(?<![\u4e00-\u9fff])(?:他|她|对方|某人|角色)"
    r"(?:以|用|说道|说|道|问|答|喊|低语|开口|回应|回答|转身|抬手|后退|看向)"
)
EMPTY_SHOT = re.compile(
    r"(?:纯\s*空镜|无人物镜头|无人画面|"
    r"镜头任务\s*[：:][^；。\n]{0,24}空镜|"
    r"当前画面\s*[：:][^；。\n]{0,24}无人物|"
    r"画面与动作\s*[：:][^；。\n]{0,24}无人物)"
)
ACTION_FIELD = re.compile(r"(?:^|\n)\s*画面与动作\s*[：:]")
COMPOSITION_FIELD = re.compile(r"(?:^|\n)\s*(?:摄影机与)?构图\s*[：:]")
LEGACY_FRONTEND_FIELD = re.compile(
    r"(?:^|[；;\n])\s*(?:镜头任务|唯一主目标|当前画面|动作起点|动作过程|"
    r"可见结果|开场焦点依据|切镜动机|转场方式|镜头结束状态)\s*[：:]"
)
TAIL_SILENT_SIGNAL = re.compile(r"(?:无对白|无台词).{0,24}?(?:尾帧|缓冲)|(?:尾帧|缓冲).{0,24}?(?:无对白|无台词)")
TAIL_SILENT_DURATION = re.compile(
    r"(?:最后|尾帧|结束前)[^。！？\n]{0,48}?0\.[3-8]\s*秒[^。！？\n]{0,36}?(?:无对白|无台词)|"
    r"(?:无对白|无台词)[^。！？\n]{0,36}?0\.[3-8]\s*秒"
)
VOICE_CHAIN_LINE = re.compile(r"(?m)^\s*连续口播\s*[：:].*$")
VOICE_CHAIN = re.compile(
    r"(?m)^\s*连续口播\s*[：:]\s*"
    r"(?P<speaker>[^｜|\n]+?)\s*[｜|]\s*"
    r"(?P<start>\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[-—–~～至到]\s*"
    r"(?P<end>\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[｜|]\s*"
    r"(?P<profile>[^｜|\n]+?)\s*[｜|]\s*"
    r"跨镜连续，镜头切换不停顿，仅按原标点自然换气。\s*$"
)
VOICE_PROFILES = {
    "短剧常速": (4.0, 5.2),
    "短剧快节奏": (4.5, 5.8),
    "情绪慢速": (3.3, 4.4),
}
NUMERIC_TOKEN = re.compile(r"\d+(?:\.\d+)?")

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
    "画面文字",
    "显示文字",
    "文字",
    "评分",
    "资质",
    "悟性",
    "血脉",
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


def normalise_utterance(text: str) -> str:
    """Apply only the documented newline-to-comma layout convention."""
    lines = [normalise_text(line) for line in text.splitlines() if line.strip()]
    value = ""
    for line in lines:
        separator = "，" if value and not value.endswith(("，", "。", "！", "？", "…", ",", ".", "!", "?", "；", ";", "：", ":")) else ""
        value += separator + line
    return value


def analyse_source_dialogue(source: str) -> tuple[list[Dialogue], list[Diagnostic]]:
    """Parse explicit labels; never infer a bare quote's speaker from the plot."""
    dialogues: list[Dialogue] = []
    diagnostics: list[Diagnostic] = []
    masked = list(source)
    for quote in QUOTED_TEXT.finditer(source):
        line_start = source.rfind("\n", 0, quote.start()) + 1
        label = QUOTED_SOURCE_LABEL.search(source[line_start:quote.start()])
        body = next(value for value in quote.groups() if value is not None)
        line_number = source.count("\n", 0, quote.start()) + 1
        line_end = source.find("\n", quote.end())
        suffix = source[quote.end():line_end if line_end >= 0 else len(source)]
        display_only = "不念" in suffix or "展示" in suffix
        mixed = bool(READING_DIRECTIVE.search(body))
        raw_name = label.group("speaker") if label else ""
        is_display = raw_name in SOURCE_LABELS
        if label and raw_name not in SOURCE_LABELS and raw_name != "OS" and not mixed and not display_only:
            dialogues.append(Dialogue(canonical_speaker(raw_name, label.group("mode")), normalise_utterance(body), line_number))
        elif not is_display and not display_only:
            diagnostics.append(Diagnostic("WARN", f"源文本第 {line_number} 行引号段无法可靠归属或混有朗读标注；覆盖不完整，须人工核对。"))
        # Remove quote and its label from the fallback parser, preserving lines.
        begin = line_start + label.start() if label else quote.start()
        for index in range(begin, quote.end()):
            if masked[index] != "\n":
                masked[index] = " "

    remainder = "".join(masked)
    if any(char in remainder for char in '“”「」『』"'):
        diagnostics.append(Diagnostic("WARN", "源文本存在未闭合或无法解析的引号；覆盖不完整，须人工核对。"))
    if READING_DIRECTIVE.search(source):
        diagnostics.append(Diagnostic("WARN", "源文本含念/不念/展示标注；请人工核对朗读与屏幕文字边界，不能视为全量覆盖。"))
    active_speaker: Optional[str] = None
    for line_number, line in enumerate(remainder.splitlines(), start=1):
        match = SOURCE_LINE.match(line)
        if match:
            raw_name = match.group("speaker")
            if raw_name in SOURCE_LABELS or any(char in match.group("body") for char in '“”「」『』"') or READING_DIRECTIVE.search(match.group("body")):
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
        diagnostics.append(Diagnostic("WARN", f"源文本第 {line_number} 行按无引号连续台词暂解析；须人工排除动作说明，覆盖并非确定。"))
    return sorted(dialogues, key=lambda entry: entry.line), diagnostics


def extract_source_dialogue(source: str) -> list[Dialogue]:
    return analyse_source_dialogue(source)[0]


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


def field_values(text: str, labels: set[str]) -> list[str]:
    fields = list(FIELD_HEADER.finditer(text))
    values = []
    for index, field in enumerate(fields):
        if field.group("label") not in labels:
            continue
        end = fields[index + 1].start() if index + 1 < len(fields) else len(text)
        value = text[field.end():end]
        value = re.split(r"(?m)^[ \t]*(?:\[镜头|生成块|本次未使用文案[：:])", value)[0]
        values.append(value)
    return values


def speaker_before_quote(prefix: str, source_speakers: Iterable[str]) -> Optional[str]:
    """Find a named speaker immediately before a quoted line.

    Source names anchor the parse so descriptive Chinese before a character name
    cannot accidentally become part of that name.
    """
    candidate: Optional[tuple[int, str]] = None
    for source_speaker in set(source_speakers) | {"系统", "旁白"}:
        base = source_speaker[:-2] if source_speaker.endswith("OS") else source_speaker
        if not base:
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
    return None


def extract_output_dialogue(output: str, source_speakers: Iterable[str]) -> tuple[list[Dialogue], int]:
    dialogues: list[Dialogue] = []
    unassigned = 0
    for field in field_values(output, {"台词"}):
        previous_end = 0
        for match in QUOTED_TEXT.finditer(field):
            text = normalise_utterance(next(value for value in match.groups() if value is not None))
            prefix = field[max(previous_end, match.start() - 180):match.start()]
            speaker = speaker_before_quote(prefix, source_speakers)
            if speaker:
                dialogues.append(Dialogue(speaker=speaker, text=text, line=0))
            else:
                unassigned += 1
            previous_end = match.end()
        if not QUOTED_TEXT.search(field) and field.strip() and field.strip() not in {"无", "无台词", "无对白"}:
            unassigned += 1
        elif any(char in QUOTED_TEXT.sub("", field) for char in '“”「」『』"'):
            unassigned += 1
    return dialogues, unassigned


def remove_quoted_text(value: str) -> str:
    return QUOTED_TEXT.sub("", value)


def integer_to_chinese(value: int) -> str:
    """Return a practical Mandarin reading for non-negative integers under 10000."""
    digits = "零一二三四五六七八九"
    if value == 0:
        return digits[0]
    if value >= 10000:
        # Large values are context-sensitive (year, serial number, amount). A
        # digit-by-digit reading is safer than pretending the unit structure is
        # certain; the existing manual-review warning remains in place.
        return "".join(digits[int(char)] for char in str(value))
    result = ""
    zero_pending = False
    remainder = value
    for unit_value, unit_name in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, remainder = divmod(remainder, unit_value)
        if digit:
            if zero_pending:
                result += "零"
                zero_pending = False
            result += digits[digit] + unit_name
        elif result and remainder:
            zero_pending = True
    return result[1:] if result.startswith("一十") else result


def numeric_spoken_units(token: str) -> int:
    integer, dot, fraction = token.partition(".")
    units = len(integer_to_chinese(int(integer)))
    if dot:
        units += 1 + len(fraction)  # “点” plus one spoken unit per decimal digit.
    return units


def spoken_unit_count(text: str) -> int:
    """Approximate Mandarin audible units, expanding Arabic numerals by reading."""
    total = 0
    cursor = 0
    for match in NUMERIC_TOKEN.finditer(text):
        plain = text[cursor:match.start()]
        total += len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fffA-Za-z]", plain))
        total += numeric_spoken_units(match.group())
        cursor = match.end()
    total += len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fffA-Za-z]", text[cursor:]))
    return total


def block_target_duration(block_text: str, fallback: float) -> float:
    header = next((line for line in block_text.splitlines() if line.strip()), "")
    pipe_match = re.search(r"[｜|]\s*(\d+(?:\.\d+)?)\s*秒\s*[｜|]", header)
    if pipe_match:
        return float(pipe_match.group(1))
    labelled_match = re.search(r"(?:总时长|时长)\s*[：:]\s*(\d+(?:\.\d+)?)\s*秒", header)
    return float(labelled_match.group(1)) if labelled_match else fallback


def is_pure_empty_shot(shot_text: str) -> bool:
    if not EMPTY_SHOT.search(shot_text):
        return False
    # A named character acting in an explicitly labelled establishing shot is
    # not a pure empty shot for the budget check.
    return not bool(re.search(r"(?:人物|角色|[\u4e00-\u9fff]{2,5})(?:入画|出现|走入|转身|抬手|开口|说|道)", shot_text))


def shot_risk_warnings(shot_text: str, seconds: Optional[float], block: str, shot: str) -> list[Diagnostic]:
    """Heuristics flag review needs; they do not certify video model behavior."""
    diagnostics = []
    camera = "\n".join(field_values(shot_text, {"摄影机与构图", "构图"}))
    action = "\n".join(field_values(shot_text, {"画面与动作"}))
    if camera and not CAMERA_MODE.search(camera):
        diagnostics.append(Diagnostic("WARN", "未识别到明确的固定机位或主运镜，请人工核对摄影安排。", block, shot))
    # A transition field describes entry into this shot, not an internal cut.
    for clause in re.split(r"[；;。\n]", remove_quoted_text(camera + "\n" + action)):
        if HIDDEN_CUT.search(clause) and not re.search(r"禁止|不得|不要|不切|无切|不反打", clause):
            diagnostics.append(Diagnostic("WARN", "动作或摄影字段疑似包含额外切镜；一个编号应为一个连续镜头，请人工核对。", block, shot))
            break
    spoken = "".join(
        next(value for value in quote.groups() if value is not None)
        for field in field_values(shot_text, {"台词"}) for quote in QUOTED_TEXT.finditer(field)
    )
    if spoken and seconds is not None and seconds > 0:
        units = spoken_unit_count(spoken)
        # Upper end of the guideline, without pause costs: only a risk screen.
        if units / 5 > seconds:
            diagnostics.append(Diagnostic("WARN", f"对白容量风险：约 {units} 个可发音单位按 5 单位/秒已需约 {units / 5:.1f} 秒，镜头仅 {seconds:g} 秒，尚未计停顿。", block, shot))
        if units >= 8 and units / seconds < 3.3:
            diagnostics.append(
                Diagnostic(
                    "WARN",
                    f"台词慢节奏风险：约 {units} 个可发音单位占用整镜 {seconds:g} 秒时仅约 {units / seconds:.2f} 单位/秒；若台词并非只占本镜一部分，请缩短口播区间或声明有依据的语速档。",
                    block,
                    shot,
                )
            )
        if re.search(r"[0-9A-Za-z]", spoken):
            diagnostics.append(Diagnostic("WARN", "台词含数字或字母，请按实际读法复核口播时间；原始字符数不能代替可发音字数。", block, shot))
    return diagnostics


def validate_structure(output: str, duration: float) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    blocks = parse_blocks(output)
    if not blocks:
        return [Diagnostic("ERROR", "未找到以“生成块 N”开头的生成块。")]
    block_numbers = [int(number) for number, _ in blocks]
    if len(block_numbers) != len(set(block_numbers)) or block_numbers != sorted(block_numbers):
        diagnostics.append(Diagnostic("ERROR", "生成块编号重复或顺序错误。"))

    for block_index, (block_number, block_text) in enumerate(blocks):
        shots = parse_shots(block_text)
        target = block_target_duration(block_text, duration)
        is_last = block_index == len(blocks) - 1
        if abs(duration - 15) <= EPSILON:
            if not is_last and abs(target - 15) > EPSILON:
                diagnostics.append(
                    Diagnostic("ERROR", f"非末尾生成块必须为 15 秒，当前块头为 {target:g} 秒。", block_number)
                )
            if is_last and (target < 4 or target > 15):
                diagnostics.append(
                    Diagnostic("ERROR", f"15 秒模式的末尾生成块只能为 4-15 秒，当前为 {target:g} 秒；不足 4 秒应暂存而不生成。", block_number)
                )
            if abs(target - 15) <= EPSILON and len(shots) != 5:
                diagnostics.append(
                    Diagnostic("ERROR", f"15 秒完整生成块必须有 5 个镜头，当前为 {len(shots)} 个。", block_number)
                )
            if is_last and 4 <= target < 15 and not 1 <= len(shots) <= 5:
                diagnostics.append(
                    Diagnostic("ERROR", f"4-<15 秒末尾生成块必须有 1-5 个镜头，当前为 {len(shots)} 个。", block_number)
                )
        elif abs(target - duration) > EPSILON:
            diagnostics.append(
                Diagnostic("ERROR", f"块头时长为 {target:g} 秒，与 --duration {duration:g} 秒不一致。", block_number)
            )
        if not shots:
            diagnostics.append(Diagnostic("ERROR", "生成块中没有编号镜头。", block_number))
            continue
        if [int(number) for number, _ in shots] != list(range(1, len(shots) + 1)):
            diagnostics.append(Diagnostic("ERROR", "镜头编号必须从 1 开始连续递增且不重复。", block_number))

        previous_end: Optional[float] = None
        empty_run = 0
        empty_total = 0
        for shot_number, shot_text in shots:
            if not ACTION_FIELD.search(shot_text):
                diagnostics.append(Diagnostic("ERROR", "缺少逐镜“画面与动作”字段。", block_number, shot_number))
            if not COMPOSITION_FIELD.search(shot_text):
                diagnostics.append(Diagnostic("ERROR", "缺少逐镜“摄影机与构图”字段。", block_number, shot_number))
            legacy_fields = LEGACY_FRONTEND_FIELD.findall(shot_text)
            if len(legacy_fields) >= 5:
                diagnostics.append(
                    Diagnostic(
                        "WARN",
                        "疑似把后台导演字段逐项倾倒到正文；请合并为画面与动作、摄影机与构图及必要的可选行。",
                        block_number,
                        shot_number,
                    )
                )
            # Only the declared timeline may define shot duration. Camera ranges
            # such as “2-3米” must not masquerade as time when a field is absent.
            time_line = re.search(r"(?m)^\s*时间(?:区间)?\s*[：:]\s*([^\n]+)", shot_text)
            intervals = list(INTERVAL.finditer(time_line.group(1))) if time_line else []
            shot_seconds = None
            if not intervals:
                diagnostics.append(Diagnostic("ERROR", "缺少“起点-终点秒”的时间区间。", block_number, shot_number))
            else:
                interval = intervals[0]
                start = float(interval.group("start"))
                end = float(interval.group("end"))
                shot_seconds = end - start
                if end <= start:
                    diagnostics.append(Diagnostic("ERROR", f"时间区间 {start:g}-{end:g} 秒无效。", block_number, shot_number))
                if previous_end is None:
                    if abs(start) > EPSILON:
                        diagnostics.append(Diagnostic("ERROR", f"首镜必须从 0 秒开始，当前为 {start:g} 秒。", block_number, shot_number))
                elif abs(start - previous_end) > EPSILON:
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
                    if end - start > 1.5 + EPSILON:
                        diagnostics.append(Diagnostic("ERROR", "纯空镜不得超过 1.5 秒。", block_number, shot_number))
                    if empty_run >= 2:
                        diagnostics.append(Diagnostic("ERROR", "不允许连续两个纯空镜。", block_number, shot_number))
                else:
                    empty_run = 0
            diagnostics.extend(shot_risk_warnings(shot_text, shot_seconds, block_number, shot_number))

        if previous_end is not None and abs(previous_end - target) > EPSILON:
            diagnostics.append(
                Diagnostic("ERROR", f"末镜结束于 {previous_end:g} 秒，时间轴总长应为 {target:g} 秒。", block_number)
            )
        if abs(target - 15) <= EPSILON and empty_total > 1:
            diagnostics.append(Diagnostic("ERROR", f"15 秒块通常最多一个纯空镜，当前为 {empty_total} 个。", block_number))

        last_shot_number, last_shot = shots[-1]
        if not TAIL_SILENT_SIGNAL.search(last_shot):
            diagnostics.append(Diagnostic("ERROR", "末镜缺少 0.3-0.8 秒无对白/无台词尾帧提示。", block_number, last_shot_number))
        elif not TAIL_SILENT_DURATION.search(last_shot):
            diagnostics.append(Diagnostic("ERROR", "末镜写有无台词尾帧，但未标明 0.3-0.8 秒缓冲。", block_number, last_shot_number))

    stripped_output = QUOTED_TEXT.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), output)
    if re.search(r"(?m)^\s*(?:入口状态|出口状态)\s*[：:]", stripped_output):
        diagnostics.append(Diagnostic("WARN", "入口/出口状态应留在后台，必要起点并入首镜，不再单列前台字段。"))
    if MISSING_CONTEXT.search(stripped_output):
        diagnostics.append(Diagnostic("WARN", "提示词疑似依赖未给出的上一块上下文，请将必要起点改成当前可见事实。"))
    for match in AMBIGUOUS_SPEAKER.finditer(stripped_output):
        line = output.count("\n", 0, match.start()) + 1
        diagnostics.append(Diagnostic("ERROR", f"第 {line} 行含模糊人物指代“{match.group(0)}”。请写明角色全名或身份。"))
    return diagnostics


def validate_dialogue(source: str, output: str) -> list[Diagnostic]:
    expected, diagnostics = analyse_source_dialogue(source)
    complete_parse = not diagnostics
    if not expected:
        diagnostics.append(Diagnostic("WARN", "源文本未识别到可靠的具名对白，跳过对白覆盖校验；不能据此断言无遗漏。"))
        return diagnostics

    source_speakers = {entry.speaker for entry in expected}
    actual, unassigned = extract_output_dialogue(output, source_speakers)
    streams: dict[str, str] = defaultdict(str)
    for entry in actual:
        streams[entry.speaker] += entry.text
    if unassigned:
        diagnostics.append(Diagnostic("WARN", f"台词字段中有 {unassigned} 段口播未可靠识别说话人或引号，覆盖不完整；仅展示文字不应放入台词字段。"))

    if complete_parse and not unassigned:
        def turns(entries: list[Dialogue]) -> list[tuple[str, str]]:
            result: list[tuple[str, str]] = []
            for entry in entries:
                if result and result[-1][0] == entry.speaker:
                    result[-1] = (entry.speaker, result[-1][1] + entry.text)
                else:
                    result.append((entry.speaker, entry.text))
            return result
        if turns(expected) != turns(actual):
            diagnostics.append(Diagnostic("ERROR", "已解析台词的顺序或合并全文不一致，可能存在遗漏、重复、新增、改写、错归属或跨说话人重排。"))
    else:
        # Unknown dialogue may legitimately occupy gaps. Match known chunks in
        # order, consuming each once instead of counting overlapping substrings.
        cursors: dict[str, int] = defaultdict(int)
        for entry in expected:
            position = streams[entry.speaker].find(entry.text, cursors[entry.speaker])
            if position < 0:
                diagnostics.append(Diagnostic("WARN", f"源文本第 {entry.line} 行暂解析的 {entry.speaker} 台词未匹配：{entry.text}；覆盖不完整，须人工核对。"))
            else:
                cursors[entry.speaker] = position + len(entry.text)
    return diagnostics


def validate_voice_pacing(source: str, output: str, duration: float) -> list[Diagnostic]:
    """Validate explicit cross-shot voice chains and short-drama pace bands."""
    expected, _ = analyse_source_dialogue(source)
    source_speakers = {entry.speaker for entry in expected}
    diagnostics: list[Diagnostic] = []

    for block_number, block_text in parse_blocks(output):
        target = block_target_duration(block_text, duration)
        chain_lines = list(VOICE_CHAIN_LINE.finditer(block_text))
        declarations = list(VOICE_CHAIN.finditer(block_text))
        if len(chain_lines) != len(declarations):
            diagnostics.append(
                Diagnostic(
                    "ERROR",
                    "“连续口播”格式不完整；必须写为“说话人｜起点-终点秒｜语速档｜跨镜连续，镜头切换不停顿，仅按原标点自然换气。”。",
                    block_number,
                )
            )

        runs: list[dict[str, object]] = []
        for shot_number, shot_text in parse_shots(block_text):
            entries, _ = extract_output_dialogue(shot_text, source_speakers)
            for entry in entries:
                if runs and runs[-1]["speaker"] == entry.speaker:
                    runs[-1]["text"] = str(runs[-1]["text"]) + entry.text
                    cast_shots = runs[-1]["shots"]
                    assert isinstance(cast_shots, list)
                    if shot_number not in cast_shots:
                        cast_shots.append(shot_number)
                else:
                    runs.append({"speaker": entry.speaker, "text": entry.text, "shots": [shot_number], "claimed": False})

        queues: dict[str, list[dict[str, object]]] = defaultdict(list)
        for run in runs:
            queues[str(run["speaker"])].append(run)

        for declaration in declarations:
            speaker = canonical_speaker(declaration.group("speaker"))
            start = float(declaration.group("start"))
            end = float(declaration.group("end"))
            profile = declaration.group("profile").strip()
            if end <= start or start < 0 or end > target + EPSILON:
                diagnostics.append(
                    Diagnostic(
                        "ERROR",
                        f"连续口播区间 {start:g}-{end:g} 秒无效或超出本块 {target:g} 秒边界。",
                        block_number,
                    )
                )
            if profile not in VOICE_PROFILES:
                diagnostics.append(
                    Diagnostic(
                        "ERROR",
                        f"未知连续口播语速档“{profile}”；只能使用短剧常速、短剧快节奏或情绪慢速。",
                        block_number,
                    )
                )

            matching = next((run for run in queues.get(speaker, []) if not run["claimed"]), None)
            if matching is None:
                diagnostics.append(
                    Diagnostic(
                        "ERROR",
                        f"连续口播声明的说话人“{speaker}”没有可按顺序匹配的话轮。",
                        block_number,
                    )
                )
                continue
            matching["claimed"] = True
            if end <= start or profile not in VOICE_PROFILES:
                continue
            units = spoken_unit_count(str(matching["text"]))
            rate = units / (end - start) if units else 0.0
            minimum, maximum = VOICE_PROFILES[profile]
            if rate < minimum - EPSILON or rate > maximum + EPSILON:
                direction = "过慢" if rate < minimum else "过快"
                diagnostics.append(
                    Diagnostic(
                        "ERROR",
                        f"连续口播{direction}：约 {units} 个可发音单位分配 {end - start:g} 秒，约 {rate:.2f} 单位/秒；“{profile}”应为 {minimum:g}-{maximum:g} 单位/秒。",
                        block_number,
                    )
                )

        for run in runs:
            shots = run["shots"]
            assert isinstance(shots, list)
            if len(shots) >= 2 and not run["claimed"]:
                diagnostics.append(
                    Diagnostic(
                        "ERROR",
                        f"{run['speaker']} 的同一连续话轮跨镜头 {'、'.join(shots)}，但缺少“连续口播”约束；切镜可能制造额外停顿。",
                        block_number,
                    )
                )
    return diagnostics


def validate(source: str, output: str, duration: float) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    marker = re.search(r"(?m)^本次未使用文案[：:]", output)
    if marker:
        notice = re.fullmatch(
            r"本次未使用文案：\r?\n(?P<raw>.+?)\r?\n（“(?P=raw)”不足4s，本次未使用，请合并到下一次的分段文案中）\s*",
            output[marker.start():], re.DOTALL,
        )
        generated = output[:marker.start()]
        if notice and source.rstrip().endswith(notice.group("raw")):
            raw = notice.group("raw")
            source = source.rstrip()[:-len(raw)]
            diagnostics.append(Diagnostic("WARN", "尾部原文及规定提示已核对并排除本次覆盖；自然时长是否确实不足 4 秒仍须人工复核。"))
            if not generated.strip() and not source.strip():
                return diagnostics
        else:
            diagnostics.append(Diagnostic("ERROR", "未使用文案或提示格式不匹配，或不是源文本的逐字尾部；不能从覆盖检查排除。"))
        output = generated
    return diagnostics + validate_structure(output, duration) + validate_dialogue(source, output) + validate_voice_pacing(source, output, duration)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验 Seedance 生成块的对白覆盖、时间轴和关键结构约束。"
    )
    parser.add_argument("--source", required=True, type=Path, help="原始剧本文本路径")
    parser.add_argument("--output", required=True, type=Path, help="生成块提示词文本路径")
    parser.add_argument("--duration", type=float, default=15.0, help="常规生成块目标时长，默认 15 秒；15 秒模式允许最后一块为 4-15 秒")
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
    print("此结果仅为可解析文字与结构检查；警告需人工复核，不代表全剧情覆盖或实际视频效果通过。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
