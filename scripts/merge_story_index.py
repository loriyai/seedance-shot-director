#!/usr/bin/env python3
"""Validate and deterministically concatenate lightweight story-index shards.

This helper deliberately performs no semantic entity resolution.  Records with
the same name remain separate records until the analyst completes the required
cross-segment review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys


INDEX_SCHEMA = 'lite-v1'
PART_SCHEMA = 'lite-v1-part'
LIST_KEYS = (
    'characters', 'relationships', 'scenes', 'key_props',
    'timeline', 'foreshadowing', 'unknowns',
)
ID_PREFIXES = {
    'characters': 'C',
    'relationships': 'R',
    'scenes': 'S',
    'key_props': 'P',
    'timeline': 'T',
    'foreshadowing': 'F',
    'unknowns': 'U',
}
PART_REQUIRED = {
    'index_schema', 'source_version', 'source_sha256', 'part_id', 'owned_ref', *LIST_KEYS,
}
PART_OPTIONAL = {'context_ref'}
FINAL_REQUIRED = {
    'index_schema', 'source_version', 'source_sha256', 'coverage', 'review_status', *LIST_KEYS,
}
REF_RE = re.compile(r'L([1-9]\d*)(?:-L([1-9]\d*))?\Z')
PART_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
UNKNOWN_TYPES = {'identity', 'relationship', 'speaker', 'goal', 'result', 'prop', 'space_time'}


SCHEMAS = {
    'characters': {
        'required': ('id', 'names', 'first_ref'),
        'optional': ('identity_changes', 'stable', 'merged_from'),
    },
    'relationships': {
        'required': ('id', 'parties', 'changes'),
        'optional': ('merged_from',),
    },
    'scenes': {
        'required': ('id', 'place', 'ref'),
        'optional': ('time', 'merged_from'),
    },
    'key_props': {
        'required': ('id', 'names', 'changes'),
        'optional': ('merged_from',),
    },
    'timeline': {
        'required': ('id', 'scene', 'event', 'ref'),
        'optional': ('anchor', 'cause', 'result', 'merged_from'),
    },
    'foreshadowing': {
        'required': ('id',),
        'optional': ('clue', 'clue_ref', 'payoff', 'payoff_ref', 'clue_hint',
                     'knowledge_gap', 'merged_from'),
    },
    'unknowns': {
        'required': ('id', 'scene', 'type', 'issue', 'ref', 'blocks'),
        'optional': ('merged_from',),
    },
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def source_line_count(text: str) -> int:
    """Use the same physical-line convention as str.splitlines()."""
    return len(text.splitlines())


def parse_ref(value, *, label: str, line_count: int | None = None) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError(f'{label} 必须是绝对行号引用。')
    match = REF_RE.fullmatch(value)
    if not match:
        raise ValueError(f'{label} 必须使用 Lx 或 Lx-Ly。')
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    if start > end:
        raise ValueError(f'{label} 起始行不能晚于结束行。')
    if line_count is not None and end > line_count:
        raise ValueError(f'{label} 超出完整剧本范围。')
    return start, end


def ensure_object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f'{label} 必须是对象。')
    return value


def ensure_exact_keys(value: dict, required, optional, label: str):
    keys = set(value)
    missing = set(required) - keys
    unknown = keys - set(required) - set(optional)
    if missing:
        raise ValueError(f'{label} 缺少字段：{", ".join(sorted(missing))}。')
    if unknown:
        raise ValueError(f'{label} 含未知字段：{", ".join(sorted(unknown))}。')


def ensure_text(value, label: str):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} 必须是非空文本。')


def ensure_text_list(value, label: str, *, minimum: int = 1):
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError(f'{label} 必须是至少含 {minimum} 项的文本列表。')
    for index, item in enumerate(value):
        ensure_text(item, f'{label}[{index}]')
    if len(value) != len(set(value)):
        raise ValueError(f'{label} 不能含重复项。')


def ensure_ref_within(value, *, label: str, line_count: int,
                      owned: tuple[int, int] | None) -> tuple[int, int]:
    span = parse_ref(value, label=label, line_count=line_count)
    if owned is not None and not (owned[0] <= span[0] and span[1] <= owned[1]):
        raise ValueError(f'{label} 超出分片 owned_ref。')
    return span


def validate_change(value, *, label: str, line_count: int, owned: tuple[int, int] | None,
                    fact_field: str = 'state') -> dict:
    value = ensure_object(value, label)
    required = (fact_field, 'ref') if fact_field == 'fact' else ('scene', fact_field, 'ref')
    optional = ('known',) if fact_field == 'state' else ()
    ensure_exact_keys(value, required, optional, label)
    if 'scene' in value:
        ensure_text(value['scene'], f'{label}.scene')
    ensure_text(value[fact_field], f'{label}.{fact_field}')
    ensure_ref_within(value['ref'], label=f'{label}.ref', line_count=line_count, owned=owned)
    if 'known' in value:
        ensure_text(value['known'], f'{label}.known')
    return {key: value[key] for key in (*required, *optional) if key in value}


def validate_record(category: str, value, *, label: str, line_count: int,
                    owned: tuple[int, int] | None, expected_id: re.Pattern[str],
                    coverage_parts: set[str] | None = None) -> tuple[dict, int]:
    value = ensure_object(value, label)
    schema = SCHEMAS[category]
    ensure_exact_keys(value, schema['required'], schema['optional'], label)
    if not isinstance(value['id'], str) or not expected_id.fullmatch(value['id']):
        raise ValueError(f'{label}.id 不符合 {category} 的编号规则。')

    normalized = {'id': value['id']}
    anchor = None
    if category == 'characters':
        ensure_text_list(value['names'], f'{label}.names')
        anchor = ensure_ref_within(value['first_ref'], label=f'{label}.first_ref',
                                   line_count=line_count, owned=owned)[0]
        normalized.update(names=list(value['names']), first_ref=value['first_ref'])
        if 'identity_changes' in value:
            if not isinstance(value['identity_changes'], list) or not value['identity_changes']:
                raise ValueError(f'{label}.identity_changes 必须是非空列表；无内容时省略。')
            normalized['identity_changes'] = [
                validate_change(item, label=f'{label}.identity_changes[{index}]',
                                line_count=line_count, owned=owned)
                for index, item in enumerate(value['identity_changes'])
            ]
        if 'stable' in value:
            if not isinstance(value['stable'], list) or not value['stable']:
                raise ValueError(f'{label}.stable 必须是非空列表；无内容时省略。')
            normalized['stable'] = [
                validate_change(item, label=f'{label}.stable[{index}]', line_count=line_count,
                                owned=owned, fact_field='fact')
                for index, item in enumerate(value['stable'])
            ]
    elif category == 'relationships':
        ensure_text_list(value['parties'], f'{label}.parties', minimum=2)
        if not isinstance(value['changes'], list) or not value['changes']:
            raise ValueError(f'{label}.changes 必须是非空列表。')
        changes = [
            validate_change(item, label=f'{label}.changes[{index}]', line_count=line_count, owned=owned)
            for index, item in enumerate(value['changes'])
        ]
        anchor = min(parse_ref(item['ref'], label=f'{label}.changes.ref')[0] for item in changes)
        normalized.update(parties=list(value['parties']), changes=changes)
    elif category == 'scenes':
        ensure_text(value['place'], f'{label}.place')
        anchor = ensure_ref_within(value['ref'], label=f'{label}.ref',
                                   line_count=line_count, owned=owned)[0]
        normalized.update(place=value['place'], ref=value['ref'])
        if 'time' in value:
            ensure_text(value['time'], f'{label}.time')
            normalized['time'] = value['time']
    elif category == 'key_props':
        ensure_text_list(value['names'], f'{label}.names')
        if not isinstance(value['changes'], list) or not value['changes']:
            raise ValueError(f'{label}.changes 必须是非空列表。')
        changes = [
            validate_change(item, label=f'{label}.changes[{index}]', line_count=line_count, owned=owned)
            for index, item in enumerate(value['changes'])
        ]
        anchor = min(parse_ref(item['ref'], label=f'{label}.changes.ref')[0] for item in changes)
        normalized.update(names=list(value['names']), changes=changes)
    elif category == 'timeline':
        for key in ('scene', 'event'):
            ensure_text(value[key], f'{label}.{key}')
        anchor = ensure_ref_within(value['ref'], label=f'{label}.ref',
                                   line_count=line_count, owned=owned)[0]
        normalized.update(scene=value['scene'], event=value['event'], ref=value['ref'])
        for key in ('anchor', 'cause', 'result'):
            if key in value:
                ensure_text(value[key], f'{label}.{key}')
                normalized[key] = value[key]
    elif category == 'foreshadowing':
        has_clue = 'clue' in value or 'clue_ref' in value
        if has_clue:
            if 'clue' not in value or 'clue_ref' not in value:
                raise ValueError(f'{label} 的 clue 与 clue_ref 必须同时出现。')
            if 'clue_hint' in value:
                raise ValueError(f'{label}.clue_hint 只用于分片中的单独回收候选。')
            ensure_text(value['clue'], f'{label}.clue')
            anchor = ensure_ref_within(value['clue_ref'], label=f'{label}.clue_ref',
                                       line_count=line_count, owned=owned)[0]
            normalized.update(clue=value['clue'], clue_ref=value['clue_ref'])
        else:
            if owned is None:
                raise ValueError(f'{label} 是未并回线索的分片回收候选，不能进入最终索引。')
            if not all(key in value for key in ('payoff', 'payoff_ref', 'clue_hint')):
                raise ValueError(
                    f'{label} 的单独回收候选必须包含 payoff、payoff_ref 与 clue_hint。')
            ensure_text(value['clue_hint'], f'{label}.clue_hint')
            normalized['clue_hint'] = value['clue_hint']
        if ('payoff' in value) != ('payoff_ref' in value):
            raise ValueError(f'{label} 的 payoff 与 payoff_ref 必须同时出现。')
        if 'payoff' in value:
            ensure_text(value['payoff'], f'{label}.payoff')
            payoff_span = ensure_ref_within(
                value['payoff_ref'], label=f'{label}.payoff_ref',
                line_count=line_count, owned=owned)
            if anchor is None:
                anchor = payoff_span[0]
            normalized.update(payoff=value['payoff'], payoff_ref=value['payoff_ref'])
        if 'knowledge_gap' in value:
            ensure_text(value['knowledge_gap'], f'{label}.knowledge_gap')
            normalized['knowledge_gap'] = value['knowledge_gap']
    else:
        for key in ('scene', 'type', 'issue'):
            ensure_text(value[key], f'{label}.{key}')
        if value['type'] not in UNKNOWN_TYPES:
            raise ValueError(f'{label}.type 不属于允许的 P0 类型。')
        anchor = ensure_ref_within(value['ref'], label=f'{label}.ref',
                                   line_count=line_count, owned=owned)[0]
        ensure_text(value['blocks'], f'{label}.blocks')
        normalized.update(scene=value['scene'], type=value['type'], issue=value['issue'],
                          ref=value['ref'], blocks=value['blocks'])

    if 'merged_from' in value:
        if coverage_parts is None:
            raise ValueError(f'{label}.merged_from 只允许出现在机械合并后的最终索引。')
        ensure_text_list(value['merged_from'], f'{label}.merged_from')
        prefix = ID_PREFIXES[category]
        for item in value['merged_from']:
            match = re.fullmatch(r'([A-Za-z0-9_-]{1,64}):' + prefix + r'\d+', item)
            if not match or (coverage_parts is not None and match.group(1) not in coverage_parts):
                raise ValueError(f'{label}.merged_from 含无效分片临时ID。')
        normalized['merged_from'] = list(value['merged_from'])
    return normalized, anchor


def _actual_source(text: str, version: str) -> tuple[int, str]:
    ensure_text(version, 'source_version')
    count = source_line_count(text)
    if count < 1:
        raise ValueError('完整剧本不能为空。')
    return count, digest(text)


def validate_part(part, *, source_text: str, source_version: str) -> dict:
    part = ensure_object(part, '分片')
    ensure_exact_keys(part, PART_REQUIRED, PART_OPTIONAL, '分片')
    if part['index_schema'] != PART_SCHEMA:
        raise ValueError(f'分片 index_schema 必须为 {PART_SCHEMA}。')
    line_count, source_sha256 = _actual_source(source_text, source_version)
    if part['source_version'] != source_version or part['source_sha256'] != source_sha256:
        raise ValueError('分片来源版本或摘要与真实完整剧本不一致。')
    if not PART_ID_RE.fullmatch(part.get('part_id', '')):
        raise ValueError('part_id 只能含字母、数字、下划线和短横线。')
    owned = parse_ref(part['owned_ref'], label=f"{part['part_id']}.owned_ref", line_count=line_count)
    contexts = part.get('context_ref', [])
    if not isinstance(contexts, list):
        raise ValueError(f"{part['part_id']}.context_ref 必须是绝对引用列表。")
    if 'context_ref' in part and not contexts:
        raise ValueError(f"{part['part_id']}.context_ref 为空时应省略。")
    context_sides = set()
    for index, ref in enumerate(contexts):
        context = parse_ref(ref, label=f"{part['part_id']}.context_ref[{index}]", line_count=line_count)
        if context[1] == owned[0] - 1:
            side = 'before'
        elif context[0] == owned[1] + 1:
            side = 'after'
        else:
            raise ValueError(
                f"{part['part_id']}.context_ref[{index}] 必须紧邻 owned_ref 且不得重叠。")
        if side in context_sides:
            raise ValueError(f"{part['part_id']}.context_ref 每侧最多一段。")
        context_sides.add(side)

    normalized = {
        'index_schema': PART_SCHEMA,
        'source_version': source_version,
        'source_sha256': source_sha256,
        'part_id': part['part_id'],
        'owned_ref': part['owned_ref'],
    }
    if contexts:
        normalized['context_ref'] = list(contexts)
    seen = set()
    for category in LIST_KEYS:
        records = part[category]
        if not isinstance(records, list):
            raise ValueError(f"{part['part_id']}.{category} 必须是列表。")
        prefix = ID_PREFIXES[category]
        identifier = re.compile(re.escape(part['part_id']) + ':' + prefix + r'\d+\Z')
        normalized[category] = []
        for index, record in enumerate(records):
            item, anchor = validate_record(
                category, record, label=f"{part['part_id']}.{category}[{index}]",
                line_count=line_count, owned=owned, expected_id=identifier,
            )
            if item['id'] in seen:
                raise ValueError(f"分片临时ID重复：{item['id']}。")
            seen.add(item['id'])
            normalized[category].append((item, anchor))
    return normalized


def _check_coverage(parts: list[dict], line_count: int):
    ranges = []
    seen_parts = set()
    for part in parts:
        if part['part_id'] in seen_parts:
            raise ValueError(f"part_id 重复：{part['part_id']}。")
        seen_parts.add(part['part_id'])
        start, end = parse_ref(part['owned_ref'], label=f"{part['part_id']}.owned_ref", line_count=line_count)
        ranges.append((start, end, part['part_id'], part))
    ranges.sort(key=lambda item: (item[0], item[1], item[2]))
    expected = 1
    for start, end, part_id, _ in ranges:
        if start != expected:
            kind = '重叠' if start < expected else '空洞'
            raise ValueError(f'分片 owned_ref 存在{kind}：{part_id} 从 L{start} 开始，预期 L{expected}。')
        expected = end + 1
    if expected != line_count + 1:
        raise ValueError(f'分片 owned_ref 未覆盖完整剧本末尾 L{line_count}。')
    return ranges


def _rewrite_temporary_links(records: dict[str, list[dict]], identifier_map: dict[str, str]):
    def resolve(value, prefix, label):
        if not isinstance(value, str) or not re.fullmatch(
                r'[A-Za-z0-9_-]{1,64}:' + re.escape(prefix) + r'\d+', value):
            raise ValueError(f'{label} 必须使用分片临时 {prefix} ID，不能使用名称。')
        if value not in identifier_map:
            raise ValueError(f'{label} 指向不存在的临时ID：{value}。')
        return identifier_map[value]

    for index, character in enumerate(records['characters']):
        for change_index, change in enumerate(character.get('identity_changes', [])):
            change['scene'] = resolve(
                change['scene'], 'S', f'characters[{index}].identity_changes[{change_index}].scene')
    for index, relationship in enumerate(records['relationships']):
        relationship['parties'] = [
            resolve(value, 'C', f'relationships[{index}].parties[{party_index}]')
            for party_index, value in enumerate(relationship['parties'])
        ]
        for change_index, change in enumerate(relationship['changes']):
            change['scene'] = resolve(
                change['scene'], 'S', f'relationships[{index}].changes[{change_index}].scene')
    for index, prop in enumerate(records['key_props']):
        for change_index, change in enumerate(prop['changes']):
            change['scene'] = resolve(
                change['scene'], 'S', f'key_props[{index}].changes[{change_index}].scene')
    for category in ('timeline', 'unknowns'):
        for index, record in enumerate(records[category]):
            record['scene'] = resolve(record['scene'], 'S', f'{category}[{index}].scene')


def _validate_final_links(records: dict[str, list[dict]]):
    character_ids = {item['id'] for item in records['characters']}
    scene_ids = {item['id'] for item in records['scenes']}

    def check(value, prefix, known, label):
        if not isinstance(value, str) or not re.fullmatch(re.escape(prefix) + r'\d+', value):
            raise ValueError(f'{label} 必须使用最终 {prefix} ID。')
        if value not in known:
            raise ValueError(f'{label} 指向不存在的ID：{value}。')

    for index, character in enumerate(records['characters']):
        for change_index, change in enumerate(character.get('identity_changes', [])):
            check(change['scene'], 'S', scene_ids,
                  f'characters[{index}].identity_changes[{change_index}].scene')
    for index, relationship in enumerate(records['relationships']):
        for party_index, party in enumerate(relationship['parties']):
            check(party, 'C', character_ids, f'relationships[{index}].parties[{party_index}]')
        for change_index, change in enumerate(relationship['changes']):
            check(change['scene'], 'S', scene_ids,
                  f'relationships[{index}].changes[{change_index}].scene')
    for index, prop in enumerate(records['key_props']):
        for change_index, change in enumerate(prop['changes']):
            check(change['scene'], 'S', scene_ids,
                  f'key_props[{index}].changes[{change_index}].scene')
    for category in ('timeline', 'unknowns'):
        for index, record in enumerate(records[category]):
            check(record['scene'], 'S', scene_ids, f'{category}[{index}].scene')


def merge_parts(parts, *, source_text: str, source_version: str) -> dict:
    """Return a pending-review lite-v1 index without semantic coalescing."""
    line_count, source_sha256 = _actual_source(source_text, source_version)
    normalized_parts = [validate_part(part, source_text=source_text, source_version=source_version)
                        for part in parts]
    if not normalized_parts:
        raise ValueError('至少需要一个分片。')
    ranges = _check_coverage(normalized_parts, line_count)
    ordered_parts = [item[3] for item in ranges]
    result = {
        'index_schema': INDEX_SCHEMA,
        'source_version': source_version,
        'source_sha256': source_sha256,
        'coverage': [
            {'part_id': part['part_id'], 'owned_ref': part['owned_ref']}
            for part in ordered_parts
        ],
        'review_status': 'pending',
    }
    used_temporary_ids = set()
    identifier_map = {}
    assembled = {}
    for category in LIST_KEYS:
        gathered = []
        for part_order, part in enumerate(ordered_parts):
            for record, anchor in part[category]:
                if record['id'] in used_temporary_ids:
                    raise ValueError(f"跨分片临时ID重复：{record['id']}。")
                used_temporary_ids.add(record['id'])
                gathered.append((anchor, part_order, record['id'], record))
        gathered.sort(key=lambda item: (item[0], item[1], item[2]))
        width = max(3, len(str(len(gathered))))
        assembled[category] = []
        for number, (_, _, temporary_id, record) in enumerate(gathered, 1):
            item = dict(record)
            item['id'] = f'{ID_PREFIXES[category]}{number:0{width}d}'
            item['merged_from'] = [temporary_id]
            identifier_map[temporary_id] = item['id']
            assembled[category].append(item)
    _rewrite_temporary_links(assembled, identifier_map)
    _validate_final_links(assembled)
    result.update(assembled)
    return result


def validate_final_index(data, *, source_text: str, source_version: str,
                         source_sha256: str | None = None, require_reviewed: bool = True) -> dict:
    """Strictly validate a reviewed final lite-v1 index for project storage."""
    data = ensure_object(data, '全局索引')
    ensure_exact_keys(data, FINAL_REQUIRED, (), '全局索引')
    if data['index_schema'] != INDEX_SCHEMA:
        raise ValueError(f'全局索引 index_schema 必须为 {INDEX_SCHEMA}。')
    line_count, actual_sha256 = _actual_source(source_text, source_version)
    expected_sha256 = source_sha256 or actual_sha256
    if expected_sha256 != actual_sha256:
        raise ValueError('项目记录的完整剧本摘要与实际文件不一致。')
    if data['source_version'] != source_version or data['source_sha256'] != actual_sha256:
        raise ValueError('全剧索引不属于当前原版基线。')
    if require_reviewed and data['review_status'] != 'reviewed':
        raise ValueError("全剧索引完成跨段人工审阅并设置 review_status='reviewed' 后才能登记。")
    if data['review_status'] not in ('pending', 'reviewed'):
        raise ValueError("review_status 只能为 'pending' 或 'reviewed'。")

    coverage = data['coverage']
    if not isinstance(coverage, list) or not coverage:
        raise ValueError('coverage 必须是非空列表。')
    pseudo_parts = []
    for index, item in enumerate(coverage):
        item = ensure_object(item, f'coverage[{index}]')
        ensure_exact_keys(item, ('part_id', 'owned_ref'), (), f'coverage[{index}]')
        if not PART_ID_RE.fullmatch(item.get('part_id', '')):
            raise ValueError(f'coverage[{index}].part_id 无效。')
        pseudo_parts.append({'part_id': item['part_id'], 'owned_ref': item['owned_ref']})
    ranges = _check_coverage(pseudo_parts, line_count)
    coverage_parts = {item[2] for item in ranges}

    seen = set()
    seen_origins = set()
    normalized = {
        'index_schema': INDEX_SCHEMA,
        'source_version': source_version,
        'source_sha256': actual_sha256,
        'coverage': [{'part_id': item[2], 'owned_ref': item[3]['owned_ref']} for item in ranges],
        'review_status': data['review_status'],
    }
    for category in LIST_KEYS:
        records = data[category]
        if not isinstance(records, list):
            raise ValueError(f'{category} 必须是列表。')
        prefix = ID_PREFIXES[category]
        identifier = re.compile(prefix + r'\d+\Z')
        checked = []
        prior_sort_key = None
        for index, record in enumerate(records):
            item, anchor = validate_record(
                category, record, label=f'{category}[{index}]', line_count=line_count,
                owned=None, expected_id=identifier, coverage_parts=coverage_parts,
            )
            if item['id'] in seen:
                raise ValueError(f"全局索引ID重复：{item['id']}。")
            seen.add(item['id'])
            for origin in item.get('merged_from', []):
                if origin in seen_origins:
                    raise ValueError(f'merged_from 临时ID重复归入多个最终记录：{origin}。')
                seen_origins.add(origin)
            numeric = int(item['id'][1:])
            sort_key = (anchor, numeric)
            if prior_sort_key is not None and sort_key < prior_sort_key:
                raise ValueError(f'{category} 未按来源位置稳定排序。')
            prior_sort_key = sort_key
            checked.append(item)
        normalized[category] = checked
    _validate_final_links(normalized)
    return normalized


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValueError(f'{path} 不是有效 JSON：{error.msg}。') from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--source-version', required=True)
    parser.add_argument('--part', required=True, action='append', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source_text = args.source.read_bytes().decode('utf-8')
        result = merge_parts([read_json(path) for path in args.part], source_text=source_text,
                             source_version=args.source_version)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + '.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, args.output)
        print(json.dumps({
            'output': str(args.output),
            'source_version': result['source_version'],
            'source_sha256': result['source_sha256'],
            'parts': len(result['coverage']),
            'review_status': result['review_status'],
            'counts': {key: len(result[key]) for key in LIST_KEYS},
        }, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TypeError, AttributeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
