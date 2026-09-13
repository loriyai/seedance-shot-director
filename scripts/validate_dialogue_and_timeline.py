#!/usr/bin/env python3
"""Validate dialogue coverage and structural invariants in Seedance shot prompts.

The validator intentionally works on plain text. It does not attempt to infer a
screenplay's plot; it verifies the explicit dialogue, block, shot, and timeline
contracts that can be checked deterministically before a prompt is delivered.
"""

from __future__ import annotations

import argparse
import sys
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


SOURCE_LINE = re.compile(
    r"^\s*(?P<speaker>[\u4e00-\u9fffA-Za-z0-9·_-]{1,32})"
    r"\s*(?P<mode>[（(]\s*(?:OS|旁白|对白|画外对白)\s*[）)])?\s*[：:]\s*(?P<body>.+?)\s*$"
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
    r"\s*(?P<mode>[（(]\s*(?:OS|旁白|对白|画外对白)\s*[）)])?\s*[：:]?\s*$"
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
    chain_id: Optional[str] = None
    reliable: bool = True


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


def speaker_parts(name: str, mode: Optional[str] = None) -> tuple[str, str]:
    name = unicodedata.normalize("NFKC", name).strip()
    embedded = re.fullmatch(r"(.+?)\s*\((OS|旁白|对白|画外对白)\)", name)
    if embedded:
        name, embedded_mode = embedded.groups()
        mode = mode or embedded_mode
    elif name.endswith("OS"):
        name, mode = name[:-2], mode or "OS"
    kind = unicodedata.normalize("NFKC", mode or "").strip(" ()")
    if name == "旁白" and not kind:
        kind = "旁白"
    return name.strip(), "OS" if kind == "OS" else "旁白" if kind == "旁白" else "对白"


def canonical_speaker(name: str, mode: Optional[str] = None) -> str:
    name, kind = speaker_parts(name, mode)
    if kind == "OS":
        return name + "OS"
    if kind == "旁白" and name != "旁白":
        return name + "（旁白）"
    return name


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
        prefix = source[line_start:quote.start()]
        narrative_label = re.search(
            r'(?:^|[。！？；;])[ \t]*(?P<speaker>[\u3400-\u9fffA-Za-z0-9·_-]{1,32}?)'
            r'\s*(?P<mode>[（(]\s*(?:OS|旁白|对白|画外对白)\s*[）)])?'
            r'(?:轻声|低声|大声)?(?:说道|问道|答道|说|问|答|喊|播报)[：:]?\s*$', prefix)
        label = narrative_label or QUOTED_SOURCE_LABEL.search(prefix)
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
        dialogues[-1] = Dialogue(speaker=previous.speaker, text=previous.text + separator + text, line=previous.line, reliable=False)
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
    """Parse explicit names/types; never collapse systems or named narrators."""
    typed = re.search(r"(?:^|[\n；;])\s*[A-Za-z][\w-]*\s*[｜|]\s*([^｜|\n]+)\s*[｜|]\s*(对白|画外对白|OS|旁白)\s*[：:]?\s*$", prefix)
    if typed:
        return canonical_speaker(typed.group(1), typed.group(2))
    label = re.search(r"(?:^|[\n；;])\s*([\u3400-\u9fffA-Za-z0-9·_-]{1,32})\s*(?:[（(]\s*(OS|旁白|对白|画外对白)\s*[）)])?\s*[：:]\s*$", prefix)
    if label and (label.group(2) or label.group(1) in set(source_speakers) or not re.search(r'(?:' + SPEECH_VERBS + r')$', label.group(1))):
        return canonical_speaker(label.group(1), label.group(2))
    names = sorted({speaker_parts(x)[0] for x in source_speakers} | {"系统", "旁白"}, key=len, reverse=True)
    for name in names:
        pattern = re.compile(re.escape(name) + r"\s*(?P<mode>[（(]\s*(?:OS|旁白|对白|画外对白)\s*[）)]|OS|旁白)?(?:声音)?\s*(?:以[^“”\"「」『』\n]{0,60}?|用[^“”\"「」『』\n]{0,60}?)?(?:" + SPEECH_VERBS + r")\s*[：:]?\s*$")
        match = pattern.search(prefix)
        if match:
            return canonical_speaker(name, match.group('mode'))
    # An explicit new speaker is still parsed so additions remain hard errors.
    generic = re.search(r"(?:^|[\n；;])\s*([\u3400-\u9fffA-Za-z0-9·_-]{1,32}?)(?:[（(](OS|旁白|对白|画外对白)[）)])?(?:以[^“”\n]{0,60}?的语气)?(?:" + SPEECH_VERBS + r")\s*[：:]?\s*$", prefix)
    return canonical_speaker(generic.group(1), generic.group(2)) if generic else None


def extract_output_dialogue(output: str, source_speakers: Iterable[str]) -> tuple[list[Dialogue], int]:
    dialogues: list[Dialogue] = []
    unassigned = 0
    for field in field_values(output, {"台词"}):
        previous_end = 0
        for match in QUOTED_TEXT.finditer(field):
            text = normalise_utterance(next(value for value in match.groups() if value is not None))
            prefix = field[max(previous_end, match.start()-180):match.start()]
            speaker = speaker_before_quote(prefix, source_speakers)
            identifier = re.search(r"(?:^|[\n；;])\s*([A-Za-z][\w-]*)\s*[｜|]", prefix)
            if speaker:
                dialogues.append(Dialogue(speaker, text, 0, identifier.group(1) if identifier else None))
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
    has_voice_id = bool(re.search(r'(?m)^\s*台词[：:]\s*[A-Za-z][\w-]*\s*[｜|]', shot_text))
    if spoken and seconds is not None and seconds > 0 and not has_voice_id:
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


def tail_buffer(block_text: str) -> Optional[float]:
    fields = field_values(block_text, {'无对白尾帧'})
    if not fields:
        return None
    match = re.search(r'最后\s*(\d+(?:\.\d+)?)\s*秒', fields[-1])
    return float(match.group(1)) if match else None


def ending_mode(block_text: str) -> str:
    match = re.search(r'(?m)^\s*收尾方式[：:]\s*(独立收束|连续剪辑|剧情硬切)\s*$', block_text)
    return match.group(1) if match else '独立收束'


def validate_structure(output: str, duration: float, min_duration: float = 4.0, model: Optional[str] = None, duration_step: Optional[float] = None) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    blocks = parse_blocks(output)
    if not blocks:
        return [Diagnostic('ERROR', '未找到以“生成块 N”开头的生成块。')]
    maximum = 15.0 if model == '2.0' else duration
    if duration not in (15, 30) or duration > maximum:
        diagnostics.append(Diagnostic('ERROR', '编译后 --duration 必须为15/30秒且不超过模型上限；2.0的30秒目标应编译为15秒以内块。'))
    nums = [int(x[0]) for x in blocks]
    if len(nums) != len(set(nums)) or nums != sorted(nums):
        diagnostics.append(Diagnostic('ERROR', '生成块编号重复或顺序错误。'))
    for index, (number, text) in enumerate(blocks):
        header = next((line.strip() for line in text.splitlines() if line.strip()), '')
        match = re.fullmatch(r'生成块\s*\d+\s*[｜|]\s*(\d+(?:\.\d+)?)秒\s*[｜|]\s*\d+:\d+', header)
        if not match:
            diagnostics.append(Diagnostic('ERROR', '块标题必须明确实际时长与画幅：生成块 01｜15秒｜16:9。', number))
        target = block_target_duration(text, duration)
        if target < min_duration-EPSILON or target > maximum+EPSILON:
            diagnostics.append(Diagnostic('ERROR', f'块时长只能为 {min_duration:g}-{maximum:g} 秒，当前为 {target:g} 秒。', number))
        if duration_step and abs(target/duration_step-round(target/duration_step)) > EPSILON:
            diagnostics.append(Diagnostic('ERROR', '时长不符合已配置入口步长。', number))
        if index < len(blocks)-2 and abs(target-duration)>EPSILON:
            diagnostics.append(Diagnostic('ERROR', '非末尾两块必须为完整目标时长；仅最后两块可联合调整。', number))
        shots = parse_shots(text)
        preamble = text[:SHOT_HEADER.search(text).start()] if SHOT_HEADER.search(text) else text
        nonempty = [line.strip() for line in preamble.splitlines() if line.strip()]
        if len(nonempty)<2 or re.match(r'^(人物|场景|本块氛围与站位|收尾方式|口播段|连续口播)[：:]', nonempty[1]):
            diagnostics.append(Diagnostic('ERROR', '标题后缺少实际风格与声音方案。', number))
        for label in ('人物','场景','本块氛围与站位','收尾方式'):
            if not re.search(r'(?m)^\s*'+label+r'[：:]\s*\S[^\n]*$', preamble):
                diagnostics.append(Diagnostic('ERROR', f'缺少块头“{label}”字段。', number))
        if not re.search(r'(?m)^\s*收尾方式[：:]\s*(独立收束|连续剪辑|剧情硬切)\s*$', preamble):
            diagnostics.append(Diagnostic('ERROR', '收尾方式只能为独立收束、连续剪辑或剧情硬切。', number))
        if re.search(r'<[^<>\n]+>', remove_quoted_text(text)) or re.search(r'🟩|🟦|🟨|🟥|【(?:细节增强|新增动作|文字修正|用户修订)', text):
            diagnostics.append(Diagnostic('ERROR', '正文仍含模板占位符或剧本审阅标记。', number))
        if not shots:
            diagnostics.append(Diagnostic('ERROR', '生成块中没有编号镜头。', number))
            continue
        if [int(n) for n,_ in shots] != list(range(1,len(shots)+1)):
            diagnostics.append(Diagnostic('ERROR','镜头编号必须从 1 开始连续递增且不重复。',number))
        if abs(target-15)<=EPSILON and len(shots)!=5:
            diagnostics.append(Diagnostic('ERROR',f'15 秒完整生成块必须有 5 个镜头，当前为 {len(shots)} 个。',number))
        elif target<15 and not 1<=len(shots)<=5:
            diagnostics.append(Diagnostic('ERROR','短于15秒的收尾块必须有1-5个镜头。',number))
        elif abs(target-30)<=EPSILON and not 8<=len(shots)<=12:
            diagnostics.append(Diagnostic('WARN','30秒通常8-12镜；当前偏离，请复核导演依据和观看时间。',number))
        previous_end = None
        empty_run = empty_total = 0
        for shot_number, shot in shots:
            for label in ('画面与动作','摄影机与构图'):
                if not re.search(r'(?m)^\s*'+label+r'[：:]\s*\S[^\n]*$', shot):
                    diagnostics.append(Diagnostic('ERROR',f'缺少逐镜“{label}”字段。',number,shot_number))
            time_line = re.search(r'(?m)^\s*时间(?:区间)?[：:]\s*([^\n]+)',shot)
            interval = INTERVAL.search(time_line.group(1)) if time_line else None
            seconds = None
            if not interval:
                diagnostics.append(Diagnostic('ERROR','缺少“起点-终点秒”的时间区间。',number,shot_number))
            else:
                start,end = float(interval.group('start')),float(interval.group('end'))
                seconds=end-start
                if end<=start or start<0 or end>target+EPSILON:
                    diagnostics.append(Diagnostic('ERROR','时间区间无效或超出本块边界。',number,shot_number))
                if previous_end is None and abs(start)>EPSILON:
                    diagnostics.append(Diagnostic('ERROR','首镜必须从0秒开始。',number,shot_number))
                elif previous_end is not None and abs(start-previous_end)>EPSILON:
                    diagnostics.append(Diagnostic('ERROR','时间轴不连续。',number,shot_number))
                previous_end=end
                if is_pure_empty_shot(shot):
                    empty_run+=1
                    empty_total+=1
                    if seconds>1.5+EPSILON:
                        diagnostics.append(Diagnostic('ERROR','纯空镜不得超过1.5秒。',number,shot_number))
                    if empty_run>=2:
                        diagnostics.append(Diagnostic('ERROR','不允许连续两个纯空镜。',number,shot_number))
                else:
                    empty_run=0
            diagnostics.extend(shot_risk_warnings(shot,seconds,number,shot_number))
        if previous_end is not None and abs(previous_end-target)>EPSILON:
            diagnostics.append(Diagnostic('ERROR',f'时间轴总长应为 {target:g} 秒。',number))
        if target<=15 and empty_total>1:
            diagnostics.append(Diagnostic('ERROR','15秒以内块通常最多一个纯空镜。',number))
        buffer=tail_buffer(shots[-1][1])
        if ending_mode(text)=='独立收束' and (buffer is None or not 0.3<=buffer<=0.8):
            diagnostics.append(Diagnostic('ERROR','独立收束末镜须明确最后0.3-0.8秒无对白尾帧。',number,shots[-1][0]))
        if buffer is not None and not 0.3<=buffer<=0.8:
            diagnostics.append(Diagnostic('ERROR','声明的无对白缓冲须为0.3-0.8秒。',number))
    stripped = remove_quoted_text(output)
    if re.search(r'(?m)^\s*(?:入口状态|出口状态)[：:]',stripped):
        diagnostics.append(Diagnostic('WARN','入口/出口状态应留在后台，必要起点并入首镜。'))
    if MISSING_CONTEXT.search(stripped):
        diagnostics.append(Diagnostic('WARN','提示词疑似依赖上一块上下文，请写成当前可见事实。'))
    for match in AMBIGUOUS_SPEAKER.finditer(stripped):
        diagnostics.append(Diagnostic('ERROR',f'含模糊人物指代“{match.group()}”，请写明全名或身份。'))
    return diagnostics


def validate_dialogue(source: str, output: str) -> list[Diagnostic]:
    expected, diagnostics = analyse_source_dialogue(source)
    complete_parse = not diagnostics
    if not expected:
        diagnostics.append(Diagnostic("WARN", "源文本未识别到可靠的具名对白，不能据此断言无遗漏；动作与画面文字须另核对。"))
        return diagnostics
    actual, unassigned = extract_output_dialogue(output, {entry.speaker for entry in expected})
    if unassigned:
        diagnostics.append(Diagnostic("WARN", f"台词字段中有 {unassigned} 段未可靠解析，覆盖不完整；请按共同台词格式人工核对。"))
    def turns(entries):
        merged = []
        for entry in entries:
            if merged and merged[-1][0] == entry.speaker:
                merged[-1] = (entry.speaker, merged[-1][1] + entry.text)
            else:
                merged.append((entry.speaker, entry.text))
        return merged
    if complete_parse and not unassigned:
        if turns(expected) != turns(actual):
            diagnostics.append(Diagnostic("ERROR", "已解析台词的顺序或合并全文不一致，可能存在遗漏、重复、新增、改写、错归属或跨说话人重排。"))
        return diagnostics
    # Unknown portions do not downgrade definite mismatches in known portions.
    streams = defaultdict(str)
    for entry in actual:
        streams[entry.speaker] += entry.text
    cursors = defaultdict(int)
    for entry in expected:
        pos = streams[entry.speaker].find(entry.text, cursors[entry.speaker])
        if pos < 0:
            level = 'ERROR' if entry.reliable and streams[entry.speaker] else 'WARN'
            diagnostics.append(Diagnostic(level, f"源文本第 {entry.line} 行 {entry.speaker} 台词未匹配：{entry.text}；已知正文不一致，未解析部分仍须人工核对。"))
        else:
            cursors[entry.speaker] = pos + len(entry.text)
    return diagnostics


def validate_voice_pacing(source: str, output: str, duration: float) -> list[Diagnostic]:
    expected,_ = analyse_source_dialogue(source)
    speakers={entry.speaker for entry in expected}
    diagnostics=[]
    declaration_pattern=re.compile(r'^口播段[：:]\s*(?P<id>[A-Za-z][\w-]*)\s*[｜|]\s*(?P<speaker>[^｜|]+)\s*[｜|]\s*(?P<kind>对白|画外对白|OS|旁白)\s*[｜|]\s*(?P<start>\d+(?:\.\d+)?)-(?P<end>\d+(?:\.\d+)?)秒\s*[｜|]\s*(?P<profile>[^｜|]+)\s*[｜|]\s*停顿(?P<pause>\d+(?:\.\d+)?秒|待核)\s*[｜|]\s*(?P<concurrency>连续|重叠[：:]\S.*)$')
    for block_number,block in parse_blocks(output):
        target=block_target_duration(block,duration)
        shot_rows=[]
        all_entries=[]
        for n,shot in parse_shots(block):
            time_line=re.search(r'(?m)^\s*时间(?:区间)?[：:]\s*([^\n]+)',shot)
            iv=INTERVAL.search(time_line.group(1)) if time_line else None
            entries,_=extract_output_dialogue(shot,speakers)
            bounds=(float(iv.group('start')),float(iv.group('end'))) if iv else None
            row={'number':n,'bounds':bounds,'entries':entries}
            shot_rows.append(row)
            all_entries += [(entry,row) for entry in entries]
        declarations=[]
        seen=set()
        for line in block.splitlines():
            if not line.strip().startswith(('口播段：','口播段:')):
                continue
            match=declaration_pattern.fullmatch(line.strip())
            if not match:
                diagnostics.append(Diagnostic('ERROR','口播段格式不完整，须按ID、人物、类型、区间、语速档、停顿和连续/重叠依据填写。',block_number))
                continue
            d=match.groupdict()
            if d['id'] in seen:
                diagnostics.append(Diagnostic('ERROR','口播段ID重复。',block_number))
                continue
            seen.add(d['id'])
            selected=[(e,r) for e,r in all_entries if e.chain_id==d['id']]
            declarations.append({'id':d['id'],'speaker':canonical_speaker(d['speaker'],d['kind']),'start':float(d['start']),'end':float(d['end']),'profile':d['profile'].strip(),'pause':None if d['pause']=='待核' else float(d['pause'][:-1]),'overlap':d['concurrency'].startswith('重叠'),'selected':selected,'legacy':False})
        for entry,row in all_entries:
            if entry.chain_id and entry.chain_id not in seen:
                diagnostics.append(Diagnostic('ERROR',f'台词话轮 {entry.chain_id} 缺少口播段声明。',block_number,row['number']))
            if seen and not entry.chain_id:
                diagnostics.append(Diagnostic('ERROR','使用口播段格式时，每段台词必须标话轮ID。',block_number,row['number']))
        # Legacy compatibility: do not join same-person speech across silent shots.
        runs=[]
        for row in shot_rows:
            for entry in row['entries']:
                if entry.chain_id:
                    continue
                adjacent = runs and int(row['number'])-int(runs[-1]['selected'][-1][1]['number'])<=1
                if adjacent and runs[-1]['speaker']==entry.speaker:
                    runs[-1]['selected'].append((entry,row))
                else:
                    runs.append({'speaker':entry.speaker,'selected':[(entry,row)],'claimed':False})
        legacy_lines=list(VOICE_CHAIN_LINE.finditer(block))
        legacy_matches=list(VOICE_CHAIN.finditer(block))
        if len(legacy_lines)!=len(legacy_matches):
            diagnostics.append(Diagnostic('ERROR','“连续口播”格式不完整；新输出请使用口播段共同格式。',block_number))
        for i,match in enumerate(legacy_matches):
            key=canonical_speaker(match.group('speaker'))
            run=next((r for r in runs if r['speaker']==key and not r['claimed']),None)
            if run is None:
                diagnostics.append(Diagnostic('ERROR',f'连续口播说话人“{key}”没有可匹配的话轮。',block_number))
                continue
            run['claimed']=True
            declarations.append({'id':f'legacy-{i}','speaker':key,'start':float(match.group('start')),'end':float(match.group('end')),'profile':match.group('profile').strip(),'pause':None,'overlap':False,'selected':run['selected'],'legacy':True})
        for run in runs:
            fragments=''.join(e.text for e,_ in run['selected'])
            crosses=len({r['number'] for _,r in run['selected']})>=2
            is_one_source_turn=any(e.speaker==run['speaker'] and fragments in e.text for e in expected)
            if crosses and is_one_source_turn and not run['claimed']:
                diagnostics.append(Diagnostic('ERROR',f'{run["speaker"]} 的同一话轮跨镜，缺少“连续口播”或口播段约束。',block_number))
        for d in declarations:
            start,end=d['start'],d['end']
            selected=d['selected']
            if not selected:
                diagnostics.append(Diagnostic('ERROR',f'口播段 {d["id"]} 没有对应台词。',block_number))
                continue
            if any(e.speaker!=d['speaker'] for e,_ in selected):
                diagnostics.append(Diagnostic('ERROR',f'口播段 {d["id"]} 与台词的人物或类型错归属。',block_number))
            valid_time=end>start and start>=0 and end<=target+EPSILON
            if not valid_time:
                diagnostics.append(Diagnostic('ERROR','连续口播区间无效或超出本块边界。',block_number))
            bounds=[r['bounds'] for _,r in selected if r['bounds']]
            if bounds and (start<bounds[0][0]-EPSILON or start>=bounds[0][1]-EPSILON or end<=bounds[-1][0]+EPSILON or end>bounds[-1][1]+EPSILON or any(end<=a+EPSILON or start>=b-EPSILON for a,b in bounds)):
                diagnostics.append(Diagnostic('ERROR',f'口播段 {d["id"]} 的声音时间与台词所在镜头不匹配。',block_number))
            buffer=tail_buffer(block)
            if buffer is not None and end>target-buffer+EPSILON:
                diagnostics.append(Diagnostic('ERROR',f'口播段 {d["id"]} 占用了无对白尾帧。',block_number))
            if d['profile'] not in VOICE_PROFILES:
                diagnostics.append(Diagnostic('ERROR','未知连续口播语速档。',block_number))
                continue
            if not valid_time:
                continue
            words=''.join(e.text for e,_ in selected)
            units=spoken_unit_count(words)
            if d['pause'] is None:
                if not d['legacy']:
                    diagnostics.append(Diagnostic('WARN',f'口播段 {d["id"]} 停顿待核，仅作估时复核。',block_number))
                # Legacy intervals have no declared pause budget: only risk hints.
                elif units/(end-start)<VOICE_PROFILES[d['profile']][0]:
                    diagnostics.append(Diagnostic('WARN',f'连续口播估时偏慢：约 {units} 个可发音单位；旧格式未分离停顿，请人工复核或迁移口播段。',block_number))
                continue
            voiced=end-start-d['pause']
            if voiced<=0 or d['pause']<0:
                diagnostics.append(Diagnostic('ERROR','停顿不能占满口播区间，净发音时间必须为正。',block_number))
                continue
            rate=units/voiced
            uncertain=bool(re.search(r'[^\u3400-\u4dbf\u4e00-\u9fff\s，。！？、；：…“”「」『』,.!?;:\-—]',words))
            lo,hi=VOICE_PROFILES[d['profile']]
            if uncertain:
                diagnostics.append(Diagnostic('WARN',f'口播段 {d["id"]} 含数字、外语或不确定发音，请按实际读法复核语速。',block_number))
            elif rate<lo-EPSILON or rate>hi+EPSILON:
                diagnostics.append(Diagnostic('ERROR',f'连续口播净发音语速不符：约{units}单位/{voiced:g}秒={rate:.2f}，{d["profile"]}应为{lo:g}-{hi:g}。',block_number))
            if rate>5.2 and voiced>3:
                diagnostics.append(Diagnostic('WARN','高于5.2单位/秒的连续净发音超过3秒，请复核表演依据。',block_number))
        # Compare dialogue order, independent of declaration order.
        rank={d['id']:min((all_entries.index(pair) for pair in d['selected']),default=len(all_entries)) for d in declarations}
        ordered=sorted(declarations,key=lambda d:rank[d['id']])
        for i,current in enumerate(ordered):
            for previous in ordered[:i]:
                overlaps=max(previous['start'],current['start'])<min(previous['end'],current['end'])-EPSILON
                if overlaps and not (previous['overlap'] and current['overlap']):
                    diagnostics.append(Diagnostic('ERROR','话轮时间重叠；只有来源明确并发且双方声明重叠依据才允许。',block_number))
            if i and current['start']<ordered[i-1]['start']-EPSILON and not (current['overlap'] and ordered[i-1]['overlap']):
                diagnostics.append(Diagnostic('ERROR','声音话轮时间与原文发言顺序相反。',block_number))
    return diagnostics


def validate(source: str, output: str, duration: float, min_duration: float = 4.0, model: Optional[str] = None, duration_step: Optional[float] = None, allow_deferred: bool = False) -> list[Diagnostic]:
    diagnostics=[]
    marker=re.search(r'(?m)^本次未使用文案[：:]',output)
    if marker:
        if not allow_deferred:
            diagnostics.append(Diagnostic('ERROR','默认优先完整收尾；暂存未完稿须用户明确同意并使用 --allow-deferred。'))
        notice=re.fullmatch(r'本次未使用文案：\r?\n(?P<raw>.+?)\r?\n（“(?P=raw)”不足4s，本次未使用，请合并到下一次的分段文案中）\s*',output[marker.start():],re.DOTALL)
        generated=output[:marker.start()]
        if allow_deferred and notice and source.rstrip().endswith(notice.group('raw')):
            source=source.rstrip()[:-len(notice.group('raw'))]
            diagnostics.append(Diagnostic('WARN','暂存尾部已逐字核对；不足 4 秒仍须人工复核，且不计为已完成。'))
            if not generated.strip() and not source.strip():
                return diagnostics
        elif not notice or not source.rstrip().endswith(notice.group('raw')):
            diagnostics.append(Diagnostic('ERROR','未使用文案不是源文本逐字尾部或格式不匹配，不能从覆盖检查排除。'))
        output=generated
    return diagnostics+validate_structure(output,duration,min_duration,model,duration_step)+validate_dialogue(source,output)+validate_voice_pacing(source,output,duration)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验 Seedance 生成块的对白覆盖、时间轴和关键结构约束。"
    )
    parser.add_argument("--source", required=True, type=Path, help="原始剧本文本路径")
    parser.add_argument("--output", required=True, type=Path, help="生成块提示词文本路径")
    parser.add_argument("--duration", type=float, default=15.0, help="常规生成块目标时长，默认 15 秒；最后两块可按实际时长联合收尾")
    parser.add_argument("--model", choices=["2.0", "2.5"], help="实际模型；未知时不假填")
    parser.add_argument("--min-duration", type=float, default=4.0, help="入口最小时长；默认4为工作流规划下限")
    parser.add_argument("--duration-step", type=float, help="已核实入口的时长步长")
    parser.add_argument("--allow-deferred", action="store_true", help="仅用户明确同意暂存未完稿时启用")
    args = parser.parse_args(argv)
    if args.min_duration <= 0 or (args.duration_step is not None and args.duration_step <= 0):
        parser.error("最小时长和步长必须为正")

    if args.duration <= 0:
        parser.error("--duration 必须大于 0")
    for path in (args.source, args.output):
        if not path.is_file():
            parser.error(f"文件不存在：{path}")

    source = args.source.read_text(encoding="utf-8")
    output = args.output.read_text(encoding="utf-8")
    diagnostics = validate(source, output, args.duration, args.min_duration, args.model, args.duration_step, args.allow_deferred)
    for diagnostic in diagnostics:
        print(diagnostic.render())
    errors = sum(diagnostic.level == "ERROR" for diagnostic in diagnostics)
    warnings = sum(diagnostic.level == "WARN" for diagnostic in diagnostics)
    print(f"校验完成：{errors} 个错误，{warnings} 个警告。")
    print("此结果仅为可解析文字与结构检查；警告需人工复核，不代表全剧情覆盖或实际视频效果通过。")
    return 1 if errors else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
