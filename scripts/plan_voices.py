#!/usr/bin/env python3
"""Pre-compute voice units, legal split points, and skeleton-level dialogue coverage.

Run before drafting shots so timing bands and split indices come from a script instead
of hand arithmetic:

  python -B -X utf8 scripts/plan_voices.py --source source.txt --text "台词原文" [--start 0.5]
  python -B -X utf8 scripts/plan_voices.py --source source.txt --plan plan.json

Text mode reports audible units, the (start, end) window of each pace profile, the legal
split points inside the locked source, and whether the text is a verbatim utterance.

Plan mode reports, on the skeleton before any shot exists, whether planned voices still
cover every source utterance in order and whether each voice is feasible inside its own
generation block. Both problems are cheap here and expensive after drafting.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from validate_dialogue_and_timeline import (
    EMOTION_SIGNAL,
    VOICE_PROFILES,
    _source_speech_candidate_index,
    _speech_candidate_key,
    analyse_source_preflight,
    spoken_unit_count,
    valid_speech_split_boundary,
)

DEFAULT_PAUSE = 0.2
DEFAULT_PROFILE = "短剧常速"
DIAGNOSTIC_LIMIT = 8
ALLOWED = "\u3400-\u4dbf\u4e00-\u9fff"
PUNCTUATION = r"\s，。！？、；：…“”「」『』,.!?;:\-—"
UNCERTAIN = re.compile("[^" + ALLOWED + PUNCTUATION + "]")
MAX_SHOT_SECONDS = 5.0


def pace_band(units: int, profile: str) -> tuple[float, float]:
    """Return the voiced-seconds window that keeps a turn inside its pace profile."""
    low, high = VOICE_PROFILES[profile]
    if units == 0:
        return 0.0, 0.0
    return units / high, units / low


def text_report(source: str, text: str, profile: str, start: float) -> dict:
    units = spoken_unit_count(text)
    low, high = VOICE_PROFILES[profile]
    voiced_low, voiced_high = pace_band(units, profile)
    middle_rate = (low + high) / 2
    voiced_mid = units / middle_rate if units else 0.0
    splits = []
    for index in range(1, len(text)):
        if not valid_speech_split_boundary(text, index):
            continue
        splits.append({
            'index': index,
            'left': text[max(0, index - 8):index],
            'right': text[index:index + 8],
            'left_units': spoken_unit_count(text[:index]),
            'right_units': spoken_unit_count(text[index:]),
        })
    candidates = _source_speech_candidate_index(source)
    backed = _speech_candidate_key(text) in candidates.all_texts
    notes = [
        '净发音语速＝可发音单位÷（end−start−pause），pause 缺省 0.2 秒。',
        '切分点只能取本表下标；标点归前一片段，片段顺序拼接须与话轮逐字一致。',
    ]
    if not backed:
        notes.append('该文本不是锁定来源中的完整话轮；跨块分段按每块片段独立登记，不要用 span 切分。')
    return {
        'mode': 'text',
        'units': units,
        'profile': profile,
        'uncertain_reading': bool(UNCERTAIN.search(text)),
        'voiced_seconds_band': [round(voiced_low, 2), round(voiced_high, 2)],
        'suggested': {
            'start': round(start, 2),
            'end': round(start + DEFAULT_PAUSE + voiced_mid, 2),
            'voiced': round(voiced_mid, 2),
        },
        'pace_bands_by_profile': {
            name: [round(value, 2) for value in pace_band(units, name)]
            for name in VOICE_PROFILES
        },
        'legal_split_points': splits,
        'source_backed_utterance': backed,
        'notes': notes,
    }


def source_utterances(source: str) -> list[dict]:
    """Every utterance addressable in the locked source, ordered by first line."""
    dialogues, _, unresolved = analyse_source_preflight(source)
    records = [
        {'text': item.text, 'line': item.line, 'speaker': item.speaker, 'reliable': True}
        for item in dialogues
    ]
    records += [
        {'text': item.text, 'line': item.line, 'speaker': None, 'reliable': False}
        for item in unresolved
    ]
    return sorted(records, key=lambda record: record['line'])


def plan_report(source: str, plan: dict) -> dict:
    diagnostics: list[dict] = []
    blocks = plan.get('blocks') or []
    utterances = source_utterances(source)
    full_texts = {item['text'] for item in utterances}
    planned: list[dict] = []
    for block_index, block in enumerate(blocks, 1):
        duration = block.get('duration')
        previous_end = None
        for voice in block.get('voices') or []:
            record = dict(voice)
            record['block'] = block_index
            record['duration'] = duration
            planned.append(record)
            label = {'block': block_index, 'voice': voice.get('id')}
            profile = voice.get('profile', DEFAULT_PROFILE)
            if profile not in VOICE_PROFILES:
                diagnostics.append({'level': 'ERROR', 'message': f'未知语速档 {profile}。', **label})
                continue
            pause = voice.get('pause', DEFAULT_PAUSE)
            if pause is None:
                diagnostics.append({'level': 'WARN', 'message': '停顿待核，语速只能估时复核。', **label})
                continue
            start, end = voice.get('start'), voice.get('end')
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                diagnostics.append({'level': 'ERROR', 'message': '缺少可用的 start/end。', **label})
                continue
            voice_text = voice.get('text', '')
            units = spoken_unit_count(voice_text)
            voiced = end - start - pause
            if voiced <= 0:
                diagnostics.append({'level': 'ERROR', 'message': '停顿占满口播区间，净发音时间必须为正。', **label})
                continue
            rate = units / voiced
            low, high = VOICE_PROFILES[profile]
            fragment = bool(voice_text) and voice_text not in full_texts and any(
                voice_text in item['text'] for item in utterances)
            if fragment:
                capacity = (MAX_SHOT_SECONDS - pause) * high
                if units > capacity + 1e-6:
                    diagnostics.append({
                        'level': 'ERROR',
                        'message': f'跨块片段无法用 span 拆分：约{units}单位超过单镜上限'
                                   f'（约{capacity:.0f}单位），须继续按合法标点切分。',
                        **label,
                    })
            if EMOTION_SIGNAL.search(voice_text) and not (voice.get('tone') or '').strip():
                diagnostics.append({
                    'level': 'WARN',
                    'message': '台词含明显可听情绪但未填 tone：疑似缺少语气。',
                    **label,
                })
            if UNCERTAIN.search(voice_text):
                diagnostics.append({'level': 'WARN', 'message': f'约{units}单位/{voiced:g}秒；含数字或外语，按实际读法复核。', **label})
            elif rate < low - 1e-6 or rate > high + 1e-6:
                diagnostics.append({
                    'level': 'ERROR',
                    'message': f'净发音语速不符：约{units}单位/{voiced:g}秒={rate:.2f}，{profile}应为{low:g}-{high:g}。',
                    **label,
                })
            if duration is not None and end > duration + 1e-6:
                diagnostics.append({'level': 'ERROR', 'message': f'口播结束 {end} 秒超出本块 {duration} 秒。', **label})
            if previous_end is not None and start < previous_end - 1e-6 and not voice.get('overlap'):
                diagnostics.append({'level': 'ERROR', 'message': f'与本块上一话轮时间重叠（上一段结束 {previous_end} 秒）。', **label})
            previous_end = end

    joined = ''.join(record.get('text', '') for record in planned)
    missing, out_of_order = [], []
    cursor = -1
    for utterance in utterances:
        position = joined.find(utterance['text'], cursor + 1)
        if position >= 0:
            cursor = position
        elif joined.find(utterance['text']) >= 0:
            out_of_order.append(utterance)
        else:
            missing.append(utterance)
    source_units = sum(spoken_unit_count(item['text']) for item in utterances)
    planned_units = sum(spoken_unit_count(record.get('text', '')) for record in planned)
    for utterance in missing:
        diagnostics.append({'level': 'ERROR', 'block': None, 'voice': None,
                            'message': f"来源第 {utterance['line']} 行话轮未进入规划：{utterance['text'][:24]}…"})
    for utterance in out_of_order:
        diagnostics.append({'level': 'ERROR', 'block': None, 'voice': None,
                            'message': f"来源第 {utterance['line']} 行话轮顺序被调换：{utterance['text'][:24]}…"})
    if source_units != planned_units:
        diagnostics.append({'level': 'ERROR', 'block': None, 'voice': None,
                            'message': f'可发音单位总量不一致：来源 {source_units}，规划 {planned_units}；通常意味着漏词、重词或增补。'})
    errors = sum(item['level'] == 'ERROR' for item in diagnostics)
    return {
        'mode': 'plan',
        'status': 'hard_failed' if errors else ('needs_review' if diagnostics else 'passed'),
        'errors': errors,
        'warnings': sum(item['level'] == 'WARN' for item in diagnostics),
        'blocks': len(blocks),
        'voices': len(planned),
        'source_utterances': len(utterances),
        'units': {'source': source_units, 'planned': planned_units},
        'missing_lines': [item['line'] for item in missing],
        'out_of_order_lines': [item['line'] for item in out_of_order],
        'diagnostics': diagnostics[:DIAGNOSTIC_LIMIT],
        'diagnostics_truncated': max(0, len(diagnostics) - DIAGNOSTIC_LIMIT),
        'coverage': '骨架覆盖差分只核对话轮文本与顺序，不检查镜头、摄影与时空留白。',
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='锁定来源文件。')
    parser.add_argument('--text', help='单条话轮原文，预计算单位、语速区间与切分点。')
    parser.add_argument('--plan', type=Path, help='进行中的 V5 规划，做骨架覆盖差分。')
    parser.add_argument('--profile', default=DEFAULT_PROFILE,
                        help=f'语速档，缺省 {DEFAULT_PROFILE}；可选 {"、".join(VOICE_PROFILES)}。')
    parser.add_argument('--start', type=float, default=0.5, help='文本模式建议起始秒，缺省 0.5。')
    args = parser.parse_args(argv)
    try:
        source = args.source.read_bytes().decode('utf-8')
        if args.plan:
            plan = json.loads(args.plan.read_text(encoding='utf-8'))
            report = plan_report(source, plan)
        elif args.text:
            if args.profile not in VOICE_PROFILES:
                raise ValueError(f'未知语速档 {args.profile}。')
            report = text_report(source, args.text, args.profile, args.start)
        else:
            raise ValueError('需要 --text 或 --plan 之一。')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report.get('errors') else 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
