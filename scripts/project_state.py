#!/usr/bin/env python3
"""Recoverable per-project sources. No project data is stored in the skill."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Optional


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class ProjectState:
    def __init__(self, project: Path):
        project = project.resolve()
        skill = Path(__file__).resolve().parent.parent
        if project == skill or skill in project.parents:
            raise ValueError('项目状态不得写入技能安装目录。')
        self.root = project / 'seedance_state'
        if self.root.resolve().parent != project:
            raise ValueError('项目状态目录不能通过链接指向其他目录。')

    def path(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if self.root.resolve() not in target.parents:
            raise ValueError('状态路径必须留在项目状态目录。')
        return target

    @contextmanager
    def transaction(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / '.write-lock'
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ValueError('另一个状态写入正在进行；请确认完成后再重试。')
        os.close(fd)
        try:
            yield
        finally:
            lock.unlink()

    def read(self):
        state = json.loads(self.path('state.json').read_text(encoding='utf-8'))
        if state.get('schema_version') != 1:
            raise ValueError('不支持的项目状态版本。')
        return state

    def commit(self, state):
        target = self.path('state.json')
        temp = self.path('state.json.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, target)

    def init(self, project_id: str):
        with self.transaction():
            if self.path('state.json').exists():
                state = self.read()
                if state['project_id'] != project_id:
                    raise ValueError('项目已存在，不能静默改名。')
                return state
            state = {'schema_version': 1, 'project_id': project_id, 'config': {'enhancement_policy': 'ask_each', 'enhancement_level': 'light', 'output_detail': 'execution', 'delivery': 'standalone', 'music': 'none', 'aspect_ratio': '16:9'}, 'segments': {}}
            self.commit(state)
            return state

    def segment(self, state, identifier):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identifier):
            raise ValueError('片段ID只能含字母、数字、下划线和短横线。')
        return state['segments'].get(identifier)

    def save_version(self, identifier, segment, version, text, **metadata):
        relative = f'segments/{identifier}/{version}.txt'
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Retry after an interrupted state commit can reuse an identical orphan.
        if target.exists():
            if target.read_bytes().decode('utf-8') != text:
                raise ValueError(f'{version} 文件已存在且内容不同，不覆盖。')
        else:
            with target.open('x', encoding='utf-8', newline='') as stream:
                stream.write(text)
        record = {'path': relative, 'sha256': digest(text), **metadata}
        segment['versions'][version] = record
        return record

    def verified_text(self, record):
        text = self.path(record['path']).read_bytes().decode('utf-8')
        if digest(text) != record['sha256']:
            raise ValueError('来源文件摘要不一致，停止恢复，不能把改动后的文件当作原版。')
        return text

    def ingest(self, identifier, text):
        with self.transaction():
            state = self.read()
            current = self.segment(state, identifier)
            if current:
                if self.verified_text(current['versions']['V0']) != text:
                    raise ValueError('该片段V0已存在；更改请使用显式修订或新的片段ID。')
                return current
            segment = {'baseline': 'V0', 'source': None, 'review': None, 'versions': {}, 'ledger_status': 'missing', 'ledger': None}
            self.save_version(identifier, segment, 'V0', text, kind='original')
            state['segments'][identifier] = segment
            self.commit(state)
            return segment

    def revise_in_state(self, identifier, segment, text, reason):
        if not reason.strip():
            raise ValueError('来源修订必须记录用户接受的具体修订依据。')
        if text == self.verified_text(segment['versions'][segment['baseline']]):
            return segment['baseline']
        numbers = [int(v[3:]) for v in segment['versions'] if re.fullmatch(r'V0\.\d+', v)]
        version = f'V0.{max(numbers, default=0)+1}'
        self.save_version(identifier, segment, version, text, kind='revision', reason=reason, parent=segment['baseline'])
        segment['baseline'] = version
        segment['source'] = None
        segment['ledger_status'] = 'stale'
        return version

    def revise(self, identifier, text, reason):
        with self.transaction():
            state = self.read()
            segment = self.require_segment(state, identifier)
            version = self.revise_in_state(identifier, segment, text, reason)
            self.commit(state)
            return version

    def require_segment(self, state, identifier):
        segment = self.segment(state, identifier)
        if segment is None:
            raise ValueError('片段不存在，请先保存V0。')
        for record in segment['versions'].values():
            self.verified_text(record)
        return segment

    def review(self, identifier, text, initial=False):
        with self.transaction():
            state = self.read()
            segment = self.require_segment(state, identifier)
            number = max((int(v[1:]) for v in segment['versions'] if re.fullmatch(r'R\d+', v)), default=0)+1
            version = f'R{number}'
            baseline = 'V0' if initial else segment['baseline']
            self.save_version(identifier, segment, version, text, kind='review', baseline=baseline, baseline_at_review=segment['baseline'])
            segment['review'] = version
            segment['source'] = None
            segment['ledger_status'] = 'stale'
            self.commit(state)
            return version

    def confirm(self, identifier, clean_text, baseline_text=None, reason=''):
        with self.transaction():
            state = self.read()
            segment = self.require_segment(state, identifier)
            review = segment['review']
            if not review:
                raise ValueError('没有可确认的审阅稿。')
            base = segment['versions'][review]['baseline']
            if segment['versions'][review].get('baseline_at_review', base) != segment['baseline']:
                raise ValueError('审阅稿基线已变化；重新审阅后再确认。')
            if re.search(r'🟩|🟦|🟨|🟥|【(?:新增动作|细节增强|文字修正|逻辑疑点)', clean_text):
                raise ValueError('确认稿仍含审阅标记。')
            if baseline_text is not None:
                self.revise_in_state(identifier, segment, baseline_text, reason)
                base = segment['baseline']
            number = max((int(v[1:]) for v in segment['versions'] if re.fullmatch(r'C\d+', v)), default=0)+1
            version = f'C{number}'
            self.save_version(identifier, segment, version, clean_text, kind='confirmed', review=review, baseline=base)
            segment['source'] = version
            segment['ledger_status'] = 'stale'
            self.commit(state)
            return version

    def use_original(self, identifier, initial=False):
        with self.transaction():
            state = self.read()
            segment = self.require_segment(state, identifier)
            source = 'V0' if initial else segment['baseline']
            if segment['source'] != source:
                segment['ledger_status'] = 'stale'
            segment['source'] = source
            segment['review'] = None
            self.commit(state)
            return source

    def source(self, identifier):
        segment = self.require_segment(self.read(), identifier)
        version = segment['source']
        if not version:
            raise ValueError('当前分镜来源尚未锁定。')
        record = segment['versions'][version]
        return {'version': version, 'path': str(self.path(record['path'])), 'sha256': record['sha256']}

    def config(self, changes):
        if not isinstance(changes, dict):
            raise ValueError('配置必须为JSON对象。')
        choices = {'enhancement_level': {'light', 'standard'}, 'enhancement_policy': {'ask_each', 'always_enhance', 'always_original'}, 'output_detail': {'execution', 'director'}, 'delivery': {'standalone', 'continuous'}, 'music': {'none', 'source', 'custom'}}
        for key, allowed in choices.items():
            if key in changes and changes[key] not in allowed:
                raise ValueError(f'无效配置：{key}')
        with self.transaction():
            state = self.read()
            updated = {**state['config'], **changes}
            if updated.get('target_duration', 15) not in (15, 30):
                raise ValueError('目标时长只能为15或30秒。')
            cap = 15 if updated.get('model') == '2.0' else 30
            if updated.get('max_duration', cap) > cap or updated.get('min_duration', 4) <= 0 or updated.get('min_duration', 4) > updated.get('max_duration', cap):
                raise ValueError('实际时长范围超出模型上限或最小值无效。')
            if updated.get('duration_step') is not None and updated['duration_step'] <= 0:
                raise ValueError('入口步长必须为正。')
            if updated != state['config']:
                for segment in state['segments'].values():
                    segment['ledger_status'] = 'stale'
            state['config'] = updated
            self.commit(state)
            return updated

    def ledger(self, identifier, data):
        with self.transaction():
            state = self.read()
            segment = self.require_segment(state, identifier)
            source = segment['source']
            if not source:
                raise ValueError('未锁定来源，不能登记分镜台账。')
            if data.get('source_version') != source or data.get('source_sha256') != segment['versions'][source]['sha256']:
                raise ValueError('台账来源版本或摘要不匹配。')
            segment['ledger'] = data
            segment['ledger_status'] = 'recorded'
            self.commit(state)
            return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('command', choices=['init','ingest','revise','review','confirm','use-original','source','config','ledger'])
    parser.add_argument('--id', default='story')
    parser.add_argument('--segment')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--baseline-input', type=Path)
    parser.add_argument('--reason', default='')
    parser.add_argument('--initial', action='store_true')
    args = parser.parse_args(argv)
    try:
        store = ProjectState(args.project)
        if args.command == 'init':
            result = store.init(args.id)
        elif args.command == 'config':
            result = store.config(json.loads(args.input.read_text(encoding='utf-8')))
        else:
            if not args.segment:
                raise ValueError('该操作需要 --segment。')
            if args.command == 'source':
                result = store.source(args.segment)
            elif args.command == 'use-original':
                result = store.use_original(args.segment, args.initial)
            else:
                if args.input is None:
                    raise ValueError('该操作需要 --input。')
                text = args.input.read_bytes().decode('utf-8')
                if args.command == 'ingest': result = store.ingest(args.segment, text)
                elif args.command == 'revise': result = store.revise(args.segment, text, args.reason)
                elif args.command == 'review': result = store.review(args.segment, text, args.initial)
                elif args.command == 'confirm': result = store.confirm(args.segment, text, args.baseline_input.read_bytes().decode('utf-8') if args.baseline_input else None, args.reason)
                elif args.command == 'ledger': result = store.ledger(args.segment, json.loads(text))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TypeError, AttributeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
