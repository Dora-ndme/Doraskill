#!/usr/bin/env python3
"""entries.csv -> entries.json 转换器（Doraskill 录入模板链路）。

用途：非技术同事可在 Excel/WPS 中按 examples/entries.template.csv 的列手工录入，
再用本脚本转成 JSON，交给 scripts/render_briefing.py 渲染日报。

列定义与 config/briefing-entry.schema.json 对齐：
    section | platform | title | url | source | date | published_date | sentiment | summary | note

用法:
    python scripts/csv_to_entries.py examples/entries.template.csv --out out.json

说明:
    - 纯标准库；csv 文件建议 UTF-8（带 BOM 亦可，自动兼容）
    - section 取值 self/competitors/industry；sentiment 取值 Positive/Neutral/Negative
    - section=competitors 时 platform 必填（取值见 config/competitors.json 的 name）
    - meta（说明区备注）不在 CSV 列中，转出后可在 JSON 中手工补充
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

SECTIONS = {"self", "competitors", "industry"}
SENTIMENTS = {"Positive", "Neutral", "Negative"}
REQUIRED_COLS = ["section", "platform", "title", "url", "source",
                 "date", "published_date", "sentiment", "summary", "note"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 与 config/competitors.json 的 name 对齐（保持单一事实来源，勿在此维护第二份）
KNOWN_PLATFORMS = {
    "Temu", "SHEIN", "速卖通", "亚马逊", "TikTok Shop",
    "Shopee", "Lazada", "eBay", "京东Joybuy",
}


def _cell(rows_by_header: dict[str, str], key: str) -> str:
    return (rows_by_header.get(key) or "").strip()


def _warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)


def parse_csv(path: Path) -> list[dict]:
    """读 CSV（兼容 utf-8 / utf-8-sig），返回规范化条目 dict 列表。"""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise SystemExit(f"[error] {path} 没有数据行")

    entries: list[dict] = []
    for idx, row in enumerate(rows, start=2):  # 行号从 2 开始（表头占第 1 行）
        section = _cell(row, "section")
        sentiment = _cell(row, "sentiment")
        if not section and not sentiment and not _cell(row, "title"):
            _warn(f"第 {idx} 行为空行，已跳过")
            continue

        if section not in SECTIONS:
            raise SystemExit(f"[error] 第 {idx} 行 section 非法: {section!r}（应为 {sorted(SECTIONS)}）")
        if sentiment not in SENTIMENTS:
            raise SystemExit(f"[error] 第 {idx} 行 sentiment 非法: {sentiment!r}")

        entry = {
            "section": section,
            "title": _cell(row, "title"),
            "url": _cell(row, "url"),
            "source": _cell(row, "source"),
            "date": _cell(row, "date"),
            "sentiment": sentiment,
            "summary": _cell(row, "summary"),
        }
        platform = _cell(row, "platform")
        if section == "competitors":
            if not platform:
                raise SystemExit(f"[error] 第 {idx} 行 section=competitors 但 platform 为空")
            if platform not in KNOWN_PLATFORMS:
                _warn(f"第 {idx} 行 platform={platform!r} 不在九家友商名单内，请核对")
            entry["platform"] = platform
        elif platform:
            _warn(f"第 {idx} 行 section={section} 不应填 platform，已忽略")
        for col in ("published_date", "note"):
            val = _cell(row, col)
            if val:
                entry[col] = val

        missing = [c for c in ("title", "url", "source", "date", "summary") if not entry.get(c)]
        if missing:
            raise SystemExit(f"[error] 第 {idx} 行缺少必填列: {missing}")
        if not DATE_RE.match(entry["date"]):
            raise SystemExit(f"[error] 第 {idx} 行 date 格式应为 YYYY-MM-DD: {entry['date']!r}")
        if entry.get("published_date") and not DATE_RE.match(entry["published_date"]):
            raise SystemExit(f"[error] 第 {idx} 行 published_date 格式应为 YYYY-MM-DD")
        entries.append(entry)
    return entries


def main() -> None:
    ap = argparse.ArgumentParser(description="CSV 条目模板 -> JSON（Doraskill 录入链路）")
    ap.add_argument("csv", type=Path, help="输入 CSV（模板见 examples/entries.template.csv）")
    ap.add_argument("--out", "-o", type=Path, help="输出 JSON 路径；缺省打印到 stdout")
    args = ap.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"[error] 找不到文件: {args.csv}")
    entries = parse_csv(args.csv)
    if not entries:
        raise SystemExit("[error] 没有可转换的条目")
    doc = {"report_date": "", "briefing": entries}
    out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print(f"[ok] 已转换 {len(entries)} 条 -> {args.out}\n提示: 打开后请补 report_date 与 meta 说明区字段")
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
