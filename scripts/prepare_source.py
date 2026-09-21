#!/usr/bin/env python3
"""Build one reusable deterministic dialogue preflight for a locked source."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

from validate_dialogue_and_timeline import analyse_source_preflight, speaker_parts


SUMMARY_DIAGNOSTIC_LIMIT = 8


def prepare(source: str) -> dict:
    dialogues, diagnostics, unresolved = analyse_source_preflight(source)
    dialogue_payload = []
    for item in dialogues:
        record = asdict(item)
        _, voice_type = speaker_parts(item.speaker)
        record['voice_type'] = voice_type
        dialogue_payload.append(record)
    return {
        'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
        'dialogues': dialogue_payload,
        'unresolved_utterances': [asdict(item) for item in unresolved],
        'diagnostics': [asdict(item) for item in diagnostics],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--full-stdout', action='store_true',
                        help='显式要求时才把完整话轮JSON写入终端。')
    args = parser.parse_args(argv)
    try:
        payload = prepare(args.source.read_bytes().decode('utf-8'))
        if args.output:
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
        if args.full_stdout:
            result = payload
        else:
            diagnostic_levels = {}
            for diagnostic in payload['diagnostics']:
                level = diagnostic['level']
                diagnostic_levels[level] = diagnostic_levels.get(level, 0) + 1
            result = {
                'source_sha256': payload['source_sha256'],
                'dialogue_count': len(payload['dialogues']),
                'unresolved_utterance_count': len(payload['unresolved_utterances']),
                'diagnostic_count': len(payload['diagnostics']),
                'diagnostic_levels': diagnostic_levels,
                'diagnostic_sample': payload['diagnostics'][:SUMMARY_DIAGNOSTIC_LIMIT],
                'diagnostics_truncated': max(
                    0, len(payload['diagnostics']) - SUMMARY_DIAGNOSTIC_LIMIT
                ),
            }
            if args.output:
                result['analysis_path'] = str(args.output.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
