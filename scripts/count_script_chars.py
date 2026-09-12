#!/usr/bin/env python3
"""Count approximate Chinese-script length as Han characters plus punctuation.

The gate deliberately ignores encoded byte length, whitespace, Latin letters,
digits, file metadata, and chat wrappers. Input must be extracted plain text.
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
import unicodedata
from pathlib import Path
from typing import Optional


HAN_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x30000, 0x3134F),
    (0x31350, 0x323AF),
)


def is_han(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in HAN_RANGES)


def count_script_chars(text: str) -> dict[str, int]:
    """Return deterministic counts after canonical Unicode normalization."""
    text = unicodedata.normalize("NFC", text)
    han = sum(is_han(character) for character in text)
    punctuation = sum(
        unicodedata.category(character).startswith("P") for character in text
    )
    return {
        "han": han,
        "punctuation": punctuation,
        "approximate_total": han + punctuation,
    }


def decode_plain_text(data: bytes, encoding: str) -> str:
    if encoding != "auto":
        return data.decode(encoding)
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return data.decode("utf-32")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def read_source(source: str, encoding: str) -> str:
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在：{path}")
    return decode_plain_text(path.read_bytes(), encoding)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="按汉字数量＋标点数量统计剧本近似字数。"
    )
    parser.add_argument("source", help="UTF-8/带 BOM UTF-16/UTF-32 纯文本路径；- 表示标准输入")
    parser.add_argument("--encoding", default="auto", help="文本编码，默认根据 BOM 自动识别，否则按 UTF-8")
    parser.add_argument("--threshold", type=int, default=150000, help="门禁阈值，默认 150000")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    if args.threshold < 0:
        parser.error("--threshold 不能小于 0")

    try:
        text = read_source(args.source, args.encoding)
    except (OSError, UnicodeError) as error:
        parser.error(f"无法读取纯文本剧本：{error}")

    counts = count_script_chars(text)
    result = {
        **counts,
        "threshold": args.threshold,
        "exceeds_threshold": counts["approximate_total"] > args.threshold,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"汉字数：{result['han']}")
        print(f"标点数：{result['punctuation']}")
        print(f"合计近似字数：{result['approximate_total']}")
        print(f"超过 {result['threshold']} 门禁：{'是' if result['exceeds_threshold'] else '否'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
