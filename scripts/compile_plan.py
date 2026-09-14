#!/usr/bin/env python3
"""Compile one shot plan into a self-contained prompt, ledger and hard-check report."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys

from project_state import ProjectState, digest
from validate_dialogue_and_timeline import (validate, VOICE_PROFILES, Diagnostic,
    spoken_unit_count, extract_output_dialogue, canonical_speaker)


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def keys(data, required, optional=()):
    if not isinstance(data, dict):
        raise ValueError('规划字段必须为对象。')
    missing = set(required) - data.keys()
    unknown = data.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f'规划字段缺失 {sorted(missing)}；未知字段 {sorted(unknown)}。')


def line(value):
    if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
        raise ValueError('制作描述必须为非空单行文字。')
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('时间必须为有限数值。')
    return f'{value:g}'


def fragment_timing(voice, shot, fragment):
    start = fragment.get('start', max(voice['start'], shot['start']))
    end = fragment.get('end', min(voice['end'], shot['end']))
    span = fragment.get('span', [0, len(voice['text'])])
    units = spoken_unit_count(voice['text'][span[0]:span[1]])
    total = spoken_unit_count(voice['text'])
    pause = fragment.get('pause', None if voice['pause'] is None else voice['pause'] * units / max(total, 1))
    return start, end, pause


def block_handles(plan, index, config):
    block = plan['blocks'][index]
    changed_before = index > 0 and block.get('scene_id') != plan['blocks'][index-1].get('scene_id')
    changed_after = index + 1 < len(plan['blocks']) and block.get('scene_id') != plan['blocks'][index+1].get('scene_id')
    ending = block.get('ending', '连续剪辑' if config.get('delivery') == 'continuous' and index+1 < len(plan['blocks']) else '独立收束')
    head = max(block.get('silent_head', 0), 1 if changed_before else 0)
    tail = max(block.get('silent_tail', 0.5 if ending == '独立收束' else 0), 1 if changed_after else 0)
    return head, tail, ending


def render(plan, source, config, *, audit=False):
    keys(plan, ('schema_version', 'source_version', 'source_sha256', 'config_sha256', 'defaults', 'beats', 'blocks'))
    if plan['schema_version'] not in (1, 2):
        raise ValueError('不支持的规划版本。')
    headers = ('style', 'characters', 'scene', 'atmosphere', 'sound')
    keys(plan['defaults'], headers, ('assets',))
    for value in plan['defaults'].values():
        line(value)
    if not isinstance(plan['beats'], list) or not plan['beats']:
        raise ValueError('规划需要来源节拍。')
    beats = set()
    for beat in plan['beats']:
        keys(beat, ('id', 'evidence'), ('timing', 'basis'))
        identifier = line(beat['id'])
        if identifier in beats or line(beat['evidence']) not in source:
            raise ValueError('节拍ID重复或来源摘句不在锁定原文中。')
        if 'timing' in beat and beat['timing'] not in ('parallel', 'serial'):
            raise ValueError('动作时序只能为parallel或serial。')
        if beat.get('timing') == 'serial':
            line(beat.get('basis'))
        beats.add(identifier)
    if not isinstance(plan['blocks'], list) or not plan['blocks']:
        raise ValueError('规划需要生成块。')
    output, used_beats = [], set()
    for block_index, block in enumerate(plan['blocks'], 1):
        keys(block, ('duration', 'entry', 'exit', 'voices', 'shots'), ('header', 'ending', 'silent_tail', 'silent_head', 'scene_id', 'notes'))
        if plan['schema_version'] == 2:
            line(block.get('scene_id'))
        line(block['entry'])
        line(block['exit'])
        header = {**plan['defaults'], **block.get('header', {})}
        keys(header, headers, ('assets',))
        for value in header.values():
            line(value)
        head, tail, ending = block_handles(plan, block_index-1, config)
        for handle in (head, tail):
            number(handle)
            if handle < 0:
                raise ValueError('无口播衔接时段不能为负。')
        if head + tail >= block['duration']:
            raise ValueError('首尾衔接时段不能占满生成块。')
        if ending not in ('独立收束', '连续剪辑', '剧情硬切'):
            raise ValueError('无效收尾方式。')
        aspect = line(config.get('aspect_ratio', '16:9'))
        lines = [f'生成块 {block_index:02d}｜{number(block["duration"])}秒｜{aspect}',
                 header['style'] + '；' + header['sound'],
                 '人物：' + header['characters'], '场景：' + header['scene'],
                 '本块氛围与站位：' + header['atmosphere']]
        if audit:
            lines.append('收尾方式：' + ending)
        if 'assets' in header:
            lines.append('素材绑定：' + header['assets'])
        if not isinstance(block['voices'], list) or not isinstance(block['shots'], list):
            raise ValueError('声音和镜头必须为列表。')
        voices, consumed = {}, {}
        for voice in block['voices']:
            keys(voice, ('id', 'speaker', 'kind', 'text', 'start', 'end', 'pause', 'profile'), ('overlap', 'tone'))
            identifier = line(voice['id'])
            if identifier in voices or any(c in identifier for c in '|｜'):
                raise ValueError('话轮ID重复或包含分隔符。')
            speaker = line(voice['speaker'])
            if any(c in speaker for c in '|｜'):
                raise ValueError('说话人不能包含分隔符。')
            if voice['kind'] not in ('对白', 'OS', '旁白') or voice['profile'] not in VOICE_PROFILES:
                raise ValueError('无效声音类型或语速档。')
            line(voice['text'])
            pause = '待核' if voice['pause'] is None else number(voice['pause']) + '秒'
            overlap = '重叠：' + line(voice['overlap']) if 'overlap' in voice else '连续'
            if 'tone' in voice:
                line(voice['tone'])
            if audit:
                lines.append(f'口播段：{identifier}｜{speaker}｜{voice["kind"]}｜{number(voice["start"])}-{number(voice["end"])}秒｜{voice["profile"]}｜停顿{pause}｜{overlap}')
            voices[identifier], consumed[identifier] = voice, 0
        for shot_index, shot in enumerate(block['shots'], 1):
            keys(shot, ('start', 'end', 'beats', 'action', 'camera'), ('speech', 'performance', 'sound', 'effects', 'screen_text', 'transition', 'notes'))
            if plan['schema_version'] == 2 and (not isinstance(shot.get('effects'), list) or not shot['effects']):
                raise ValueError('每镜需要非空effects列表，逐项列出场景环境声与动作声；确无声音则明确静默。')
            if not isinstance(shot['beats'], list) or not shot['beats'] or any(b not in beats for b in shot['beats']):
                raise ValueError('镜头必须映射到已登记来源节拍。')
            used_beats.update(shot['beats'])
            lines += ['', f'[镜头{shot_index}]', f'时间区间：{number(shot["start"])}-{number(shot["end"])}秒。',
                      '画面与动作：' + line(shot['action']), '摄影机与构图：' + line(shot['camera'])]
            for field, label in (('performance', '表演'), ('screen_text', '画面文字'), ('transition', '衔接')):
                if field in shot:
                    lines.append(label + '：' + line(shot[field]))
            if not isinstance(shot.get('speech', []), list):
                raise ValueError('镜头台词必须为列表。')
            for fragment in shot.get('speech', []):
                keys(fragment, ('voice',), ('span', 'start', 'end', 'pause'))
                identifier = fragment['voice']
                if identifier not in voices:
                    raise ValueError('镜头引用了未声明话轮。')
                voice = voices[identifier]
                span = fragment.get('span', [0, len(voice['text'])])
                if not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span):
                    raise ValueError('话轮片段需提供整数[start,end]。')
                start, end = span
                if start != consumed[identifier] or not start < end <= len(voice['text']):
                    raise ValueError('话轮片段遗漏、重复、倒序或越界。')
                if audit:
                    lines.append(f'台词：{identifier}｜{voice["speaker"]}｜{voice["kind"]}：“{voice["text"][start:end]}”')
                else:
                    begin, finish, _ = fragment_timing(voice, shot, fragment)
                    verb = {'对白': '说', 'OS': '内心OS', '旁白': '旁白'}[voice['kind']]
                    delivery = voice['speaker'] + voice.get('tone', '') + verb
                    continuation = '接续本块前镜话语，语气连续' if start else '开始发声'
                    lines.append(f'声音安排：{number(begin)}-{number(finish)}秒，{continuation}；{number(finish)}秒结束本镜这部分口播。')
                    lines.append(f'台词：{delivery}：“{voice["text"][start:end]}”')
                consumed[identifier] = end
            if not audit:
                effects = shot.get('effects', [shot.get('sound', '无明确环境音效')])
                lines.append('环境音效：' + '；'.join(line(effect).rstrip('；。') for effect in effects) + '。')
                if shot_index == 1 and head:
                    lines.append(f'声音安排：0-{number(head)}秒无口播，画面自然延续当前动作或状态，环境与动作声持续。')
                if shot_index == len(block['shots']) and tail:
                    lines.append(f'声音安排：{number(block["duration"]-tail)}-{number(block["duration"])}秒无口播，画面延续本镜动作或自然状态，不定格；环境与动作声持续。')
        if any(consumed[v] != len(voices[v]['text']) for v in voices):
            raise ValueError('声明的话轮未完整分配到镜头。')
        if audit and tail:
            lines.append(f'无对白尾帧：最后{tail:g}秒无对白，' + block['exit'])
        output.append('\n'.join(lines))
    if beats != used_beats:
        raise ValueError('存在未映射到镜头的来源节拍。')
    return '\n\n'.join(output) + '\n'


def validate_plan_timing(plan, config):
    diagnostics = []
    for index, block in enumerate(plan['blocks']):
        label = f'{index+1:02d}'
        head, tail, _ = block_handles(plan, index, config)
        voices = {v['id']: v for v in block['voices']}
        segments = {key: [] for key in voices}
        if block['shots'] and (head > block['shots'][0]['end'] or tail > block['duration']-block['shots'][-1]['start']):
            diagnostics.append(Diagnostic('ERROR', '首尾无口播衔接时段必须容纳在首镜和末镜内。', label))
        for voice in voices.values():
            if voice['start'] < head-1e-6 or voice['end'] > block['duration']-tail+1e-6:
                diagnostics.append(Diagnostic('ERROR', '口播占用跨场景或收束的无口播时段。', label))
        for shot_index, shot in enumerate(block['shots'], 1):
            for fragment in shot.get('speech', []):
                voice = voices[fragment['voice']]
                start, end, pause = fragment_timing(voice, shot, fragment)
                for value in (start, end):
                    number(value)
                span = fragment.get('span', [0, len(voice['text'])])
                words = voice['text'][span[0]:span[1]]
                segments[voice['id']].append((start, end, pause))
                if start < max(shot['start'], voice['start'])-1e-6 or end > min(shot['end'], voice['end'])+1e-6 or end <= start:
                    diagnostics.append(Diagnostic('ERROR', '台词片段的实际声音区间超出对应镜头或话轮。', label, str(shot_index)))
                    continue
                if pause is None:
                    diagnostics.append(Diagnostic('WARN', '台词片段停顿待核，需人工核对局部容量。', label, str(shot_index)))
                    continue
                number(pause)
                net = end-start-pause
                units = spoken_unit_count(words)
                hi = VOICE_PROFILES[voice['profile']][1]
                if pause < 0 or net <= 0 or units / net > hi+1e-6:
                    diagnostics.append(Diagnostic('ERROR', f'台词片段容量不足：{units}个发音单位，净时间{net:g}秒；须重分片段或调整镜头边界。', label, str(shot_index)))
        for identifier, rows in segments.items():
            voice = voices[identifier]
            if rows and (abs(rows[0][0]-voice['start']) > 1e-6 or abs(rows[-1][1]-voice['end']) > 1e-6 or any(abs(a[1]-b[0]) > 1e-6 for a,b in zip(rows, rows[1:]))):
                diagnostics.append(Diagnostic('ERROR', '同一话轮片段须连续覆盖声音区间；切镜不制造空隙。', label))
            if voice['pause'] is not None and all(row[2] is not None for row in rows) and abs(sum(row[2] for row in rows)-voice['pause']) > 1e-6:
                diagnostics.append(Diagnostic('ERROR', '台词片段停顿总量与后台话轮预算不一致。', label))
    return diagnostics


def fingerprint():
    scripts = Path(__file__).resolve().parent
    return hashlib.sha256(b''.join((scripts / name).read_bytes() for name in
                                  ('compile_plan.py', 'project_state.py', 'validate_dialogue_and_timeline.py'))).hexdigest()


def compile_project(project, segment, plan):
    store = ProjectState(Path(project))
    source_record = store.source(segment)
    config = store.read()['config']
    if plan.get('source_version') != source_record['version'] or plan.get('source_sha256') != source_record['sha256']:
        raise ValueError('规划来源已变化，请更新受影响规划。')
    if plan.get('config_sha256') != digest(canonical(config)):
        raise ValueError('制作配置已变化，请复核受影响规划。')
    source = Path(source_record['path']).read_bytes().decode('utf-8')
    prompt = render(plan, source, config)
    duration = config.get('max_duration', min(config.get('target_duration', 15), 15 if config.get('model') == '2.0' else 30))
    audit_prompt = render(plan, source, config, audit=True)
    diagnostics = validate(source, audit_prompt, duration, config.get('min_duration', 4), config.get('model'), config.get('duration_step'))
    diagnostics += validate_plan_timing(plan, config)
    names = {canonical_speaker(v['speaker'], v['kind']) for b in plan['blocks'] for v in b['voices']}
    actual, unassigned = extract_output_dialogue(prompt, names)
    expected, _ = extract_output_dialogue(audit_prompt, names)
    if unassigned or [(x.speaker, x.text) for x in actual] != [(x.speaker, x.text) for x in expected]:
        diagnostics.append(Diagnostic('ERROR', '直投正文的自然语言台词与后台话轮身份或正文不一致。'))
    checks = [asdict(d) for d in diagnostics]
    plan_hash, prompt_hash = digest(canonical(plan)), digest(prompt)
    build_hash = digest(canonical({'plan': plan_hash, 'compiler': fingerprint()}))
    build_relative = f'builds/{segment}/{build_hash}'
    build = store.path(build_relative)
    build.mkdir(parents=True, exist_ok=True)
    errors = sum(d.level == 'ERROR' for d in diagnostics)
    ledger = {'source_version': source_record['version'], 'source_sha256': source_record['sha256'],
              'config_sha256': plan['config_sha256'], 'plan_sha256': plan_hash, 'prompt_sha256': prompt_hash,
              'compiler_sha256': fingerprint(), 'plan': plan, 'diagnostics': checks,
              'semantic_status': 'pending', 'status': 'hard_failed' if errors else 'needs_semantic_review'}
    # Content-addressed immutable candidates; the manifest is written last.
    for name, content in (('prompt.txt', prompt), ('ledger.json', canonical(ledger))):
        target = build / name
        if target.exists():
            if target.read_bytes().decode('utf-8') != content:
                raise ValueError('同一候选文件内容已变化，不覆盖。')
        else:
            with target.open('x', encoding='utf-8', newline='') as out:
                out.write(content)
    store.candidate(segment, build_relative, {'source_version': source_record['version'],
                    'source_sha256': source_record['sha256'], 'config_sha256': plan['config_sha256'],
                    'ledger_sha256': digest(canonical(ledger))})
    return {'build': build_relative, 'prompt': str(build / 'prompt.txt'), 'ledger': str(build / 'ledger.json'),
            'plan_sha256': plan_hash, 'prompt_sha256': prompt_hash, 'errors': errors,
            'warnings': sum(d.level == 'WARN' for d in diagnostics), 'status': ledger['status'], 'diagnostics': checks}


def finalize(project, segment, build_relative, review):
    store = ProjectState(Path(project))
    build = store.path(build_relative)
    expected_parent = store.path(f'builds/{segment}')
    if build.parent != expected_parent:
        raise ValueError('候选不属于当前片段。')
    raw_ledger = (build / 'ledger.json').read_bytes().decode('utf-8')
    receipt = store.require_segment(store.read(), segment).get('candidates', {}).get(build_relative)
    if not receipt or digest(raw_ledger) != receipt['ledger_sha256']:
        raise ValueError('候选台账未登记或已变化，请重新编译。')
    ledger = json.loads(raw_ledger)
    keys(review, ('plan_sha256', 'prompt_sha256', 'passed', 'note', 'warnings_reviewed'))
    if type(review['passed']) is not bool:
        raise ValueError('语义复核结果必须为布尔值。')
    line(review['note'])
    if review['plan_sha256'] != ledger['plan_sha256'] or review['prompt_sha256'] != ledger['prompt_sha256']:
        raise ValueError('语义复核不属于该候选。')
    if digest(canonical(ledger['plan'])) != ledger['plan_sha256'] or digest((build / 'prompt.txt').read_bytes().decode('utf-8')) != ledger['prompt_sha256']:
        raise ValueError('候选文件已变化，请重新编译并复核。')
    if ledger['compiler_sha256'] != fingerprint():
        raise ValueError('编译或检查工具已变化，请重新编译。')
    config = store.read()['config']
    if ledger['config_sha256'] != digest(canonical(config)):
        raise ValueError('制作配置已变化，请重新编译。')
    if any(d['level'] == 'ERROR' for d in ledger['diagnostics']):
        raise ValueError('存在硬错误，不可登记为已完成。')
    warnings = [i for i, d in enumerate(ledger['diagnostics']) if d['level'] == 'WARN']
    reviewed = review['warnings_reviewed']
    if not isinstance(reviewed, list) or any(type(i) is not int for i in reviewed):
        raise ValueError('已复核警告需列出诊断的零基整数索引。')
    if review['passed'] and (len(reviewed) != len(set(reviewed)) or set(reviewed) != set(warnings)):
        raise ValueError('所有警告须完成语义复核后才可交付。')
    ledger['semantic_review'] = review
    ledger['semantic_status'] = 'passed' if review['passed'] else 'blocked'
    ledger['status'] = 'passed' if review['passed'] else 'semantic_blocked'
    store.ledger(segment, ledger)
    return {'status': ledger['status'], 'prompt': str(build / 'prompt.txt')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('context', 'compile', 'finalize'))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--segment', required=True)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--build')
    parser.add_argument('--review', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'context':
            store = ProjectState(args.project)
            config = store.read()['config']
            result = {'source': store.source(args.segment), 'config': config, 'config_sha256': digest(canonical(config))}
        elif args.command == 'compile':
            if args.plan is None:
                raise ValueError('compile需要--plan。')
            result = compile_project(args.project, args.segment, json.loads(args.plan.read_text(encoding='utf-8')))
        else:
            if args.review is None or not args.build:
                raise ValueError('finalize需要--build和--review。')
            result = finalize(args.project, args.segment, args.build, json.loads(args.review.read_text(encoding='utf-8')))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('errors', 0) or result.get('status') == 'semantic_blocked' else 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
