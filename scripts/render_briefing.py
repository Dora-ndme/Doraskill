#!/usr/bin/env python3
"""HTML 日报生成器：结构化条目 -> SOP §8.2 合规排版 HTML（Doraskill 渲染链路）。

读取符合 config/briefing-entry.schema.json 的条目 JSON，自动完成：
    1. 字段校验（必填/枚举/日期格式/URL 形态/时间窗口）
    2. 过滤规则自动校验（SOP 第五部分中"可确定性判定"的子集：
       XX号自媒体、合集/周报/早报词、非详情页链接、低权重域名模式）
       —— 语义级规则（§5.2 财报/物流 的纳入 vs 排除）需人工研判，脚本只提示不改判
    3. 按 SOP §2.1 固定板块顺序输出（self → competitors → industry，空板块整体省略）
    4. 渲染锁定排版 v3（760px 居中 / 4px 红色竖线 h2 / 三档情感圆角 badge / 黄底说明区）

用法:
    python scripts/render_briefing.py --entries examples/entries.sample.json --out report.html
    python scripts/render_briefing.py --entries entries.json --strict   # warn 升级为 error

纯标准库，无第三方依赖；Python 3.9+。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

SECTIONS = {
    "self": "敦煌网自身动态",
    "competitors": "友商动态",
    "industry": "行业与政策",
}
SENTIMENTS = {"Positive", "Neutral", "Negative"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SECTION_ORDER = ["self", "competitors", "industry"]
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# —— 过滤规则自动校验（SOP §5.1 / §3.3 可确定性子集）——
XXHAO_SOURCE_RE = re.compile(r"百家号|搜狐号|网易号|头条号|公众号营销号|营销号")
XXHAO_URL_RE = re.compile(r"baijiahao\.baidu\.com|sohu\.com/a/|dy\.163\.com|toutiao\.(com|org)|mp\.weixin\.qq\.com")
COMPILATION_RE = re.compile(r"周报|月报|盘点|合集|早讯|一文读懂|每日简报|今日简报|早报")
LOW_WEIGHT_SITES = ["开屏新闻", "听筒Tech", "百运网", "shuaishou.com", "cbeeexpo.com",
                    "upkuajing.com", "chaoyuexpo.com"]
# 与 config/competitors.json 的 name 对齐
KNOWN_PLATFORMS = {"Temu", "SHEIN", "速卖通", "亚马逊", "TikTok Shop",
                   "Shopee", "Lazada", "eBay", "京东Joybuy"}


# ---------- 校验 ----------

def _parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def validate(doc: dict, strict: bool = False) -> list[str]:
    """返回错误信息列表；warn 是否升级取决于 strict。"""
    errors: list[str] = []

    def err(msg: str) -> None:
        errors.append("[error] " + msg)

    def warn(msg: str) -> None:
        errors.append("[error] " + msg if strict else "[warn] " + msg)

    if not DATE_RE.match(doc.get("report_date", "")):
        err(f"report_date 缺失或格式错误（应为 YYYY-MM-DD）: {doc.get('report_date')!r}")
        return errors
    report_date = _parse_date(doc["report_date"])

    briefing = doc.get("briefing")
    if not isinstance(briefing, list) or not briefing:
        err("briefing 为空：无条目可渲染")
        return errors

    seen_urls: set[str] = set()
    for i, e in enumerate(briefing, start=1):
        tag = f"条目#{i}"
        section = e.get("section")
        if section not in SECTIONS:
            err(f"{tag} section 非法: {section!r}")
            continue

        for field in ("title", "url", "source", "summary"):
            if not isinstance(e.get(field), str) or not e[field].strip():
                err(f"{tag} 缺少必填字段: {field}")

        sentiment = e.get("sentiment")
        if sentiment not in SENTIMENTS:
            err(f"{tag} sentiment 非法: {sentiment!r}（应为 {sorted(SENTIMENTS)}）")

        date_s = e.get("date", "")
        if not DATE_RE.match(date_s):
            err(f"{tag} date 格式错误: {date_s!r}")
        else:
            d = _parse_date(date_s)
            age = (report_date - d).days
            if age < 0:
                err(f"{tag} date 晚于 report_date（未来日期）: {date_s}")
            elif age > 3:
                err(f"{tag} 超出收录时间窗口：date {date_s} 早于报告日 {age} 天（SOP §6 仅数据报告类例外放宽近 2-3 日）")
            elif 1 <= age <= 3 and not e.get("published_date"):
                warn(f"{tag} 为非当日收录（早 {age} 天），建议补 published_date 以便说明区透明标注")

        pd_s = e.get("published_date") or ""
        if pd_s and not DATE_RE.match(pd_s):
            err(f"{tag} published_date 格式错误: {pd_s!r}")

        if section == "competitors":
            platform = e.get("platform")
            if not platform:
                err(f"{tag} section=competitors 但缺少 platform")
            elif platform not in KNOWN_PLATFORMS:
                err(f"{tag} platform={platform!r} 不在九家友商名单内（见 config/competitors.json）")
        elif e.get("platform"):
            warn(f"{tag} section={section} 不应携带 platform，将被忽略")

        # —— 过滤规则自动校验 ——
        title_s = str(e.get("title", ""))
        url_s = str(e.get("url", ""))
        source_s = str(e.get("source", ""))
        summary_s = str(e.get("summary", ""))

        if not re.match(r"^https?://", url_s):
            err(f"{tag} url 必须以 http(s):// 开头")
        else:
            up = urlsplit(url_s)
            if not up.hostname or not up.path.rstrip("/"):
                err(f"{tag} url 疑似首页/频道页（无详情路径），必须指向单篇详情页: {url_s}")
            if url_s in seen_urls:
                err(f"{tag} url 与前面条目重复")
            seen_urls.add(url_s)

        if XXHAO_SOURCE_RE.search(source_s) or XXHAO_URL_RE.search(url_s):
            err(f"{tag} 命中 XX号自媒体模式，一律排除（SOP §5.1#1 / §3.3）: source={source_s} url={url_s}")
        if COMPILATION_RE.search(title_s) or COMPILATION_RE.search(summary_s):
            err(f"{tag} 标题/摘要命中合集·周报·早报类字眼，只收单篇独立报道（SOP §5.1#2/3）")
        hit = next((w for w in LOW_WEIGHT_SITES if w in url_s), None)
        if hit:
            err(f"{tag} url 命中低权重站名单: {hit}（SOP §5.1#5）")
        if "sohu.com/a/" in url_s:
            warn(f"{tag} 命中搜狐号路径模式，请人工确认是否为搜狐财经官方频道（SOP §3.3 注）")

    return errors


# ---------- 渲染 ----------

_CSS = """
  body {
    background: #ffffff;
    font-family: "Microsoft YaHei", "PingFang SC", -apple-system, "Segoe UI", sans-serif;
    color: #333;
    margin: 0;
    padding: 24px 0 48px;
  }
  .page { max-width: 760px; margin: 0 auto; padding: 0 16px; box-sizing: border-box; }
  h1 { font-size: 22px; text-align: center; margin: 16px 0 4px; }
  .date-line { text-align: center; color: #666; font-size: 13px; margin-bottom: 24px; }
  h2 {
    font-size: 18px;
    border-left: 4px solid #e74c3c;
    padding-left: 10px;
    margin: 28px 0 14px;
  }
  .item { margin-bottom: 18px; line-height: 1.7; font-size: 14px; }
  .item a { color: #1a0dab; font-weight: 700; text-decoration: none; }
  .item a:hover { text-decoration: underline; }
  .meta { font-size: 13px; color: #555; margin: 2px 0 4px; }
  .badge {
    display: inline-block;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    line-height: 1.6;
    vertical-align: 1px;
  }
  .badge-positive { background: #d4edda; color: #155724; }
  .badge-neutral  { background: #e2e3e5; color: #383d41; }
  .badge-negative { background: #f8d7da; color: #721c24; }
  .note {
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    padding: 8px 12px;
    font-size: 12px;
    color: #856404;
    line-height: 1.7;
    margin-top: 28px;
  }
"""

_SECTION_LABEL = {"self": "敦煌网自身动态", "competitors": "友商动态", "industry": "行业与政策"}


def _fmt(d: str) -> str:
    return d.replace("-", "/")


def render(doc: dict, title: str = "敦煌网跨境电商舆情日报") -> str:
    report_date = _parse_date(doc["report_date"])
    briefing = doc["briefing"]
    meta = doc.get("meta") or {}

    # 按固定板块顺序分组，空板块省略（SOP §2.1 / §2.2 宁缺毋滥）
    buckets: dict[str, list[dict]] = {k: [] for k in SECTION_ORDER}
    for e in briefing:
        buckets[e["section"]].append(e)

    date_line = f"{_fmt(doc['report_date'])} · {WEEKDAYS[report_date.weekday()]} · 内部参考"

    parts: list[str] = []
    counts: dict[str, int] = {}
    for sec in SECTION_ORDER:
        items = buckets[sec]
        if not items:
            continue
        counts[sec] = len(items)
        parts.append(f"  <h2>{_SECTION_LABEL[sec]}</h2>\n")
        for e in items:
            badge_cls = f"badge-{e['sentiment'].lower()}"
            parts.append("  <div class=\"item\">")
            parts.append(f"    <a href=\"{html.escape(e['url'])}\">{html.escape(e['title'])}</a>")
            meta_line = f"{html.escape(e['source'])} [{_fmt(e['date'])}, "
            parts.append("    <div class=\"meta\">" + meta_line +
                         f"<span class=\"badge {badge_cls}\">{html.escape(e['sentiment'])}</span>]</div>")
            parts.append(f"    {html.escape(e['summary'])}")
            parts.append("  </div>\n")

    # —— 说明区（透明标注：收录条数/日期范围/合规/排除项/特殊处理）——
    dates = sorted({_parse_date(e["date"]) for e in briefing})
    range_txt = f"{_fmt(dates[0].isoformat())}–{_fmt(dates[-1].isoformat())}" if len(dates) > 1 else _fmt(dates[0].isoformat())
    note_lines = [
        f"收录 {len(briefing)} 条（敦煌网自身动态 {counts.get('self', 0)}、友商动态 {counts.get('competitors', 0)}、"
        f"行业与政策 {counts.get('industry', 0)}），覆盖日期范围 {range_txt}。",
    ]
    note_lines.append(meta.get("compliance") or
                      "全站条目已按 skill-Dora.md（SOP v10.0）信源梯队、过滤规则与时间窗口收录。")

    exc = meta.get("exclusions") or []
    for x in exc:
        note_lines.append(f"排除项：{x}")
    special = list(meta.get("special") or [])
    for e in briefing:
        if e.get("note"):
            special.append(f"〔{e['title'][:18]}…〕{e['note']}")
        pd = e.get("published_date")
        if pd and pd != e.get("date"):
            special.append(f"〔{e['title'][:18]}…〕数据报告/政策例外，真实发布 {_fmt(pd)}")
    for s in special:
        note_lines.append(f"特殊处理：{s}")

    note_html = "<br>\n    ".join(html.escape(x) for x in note_lines)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} · {_fmt(doc['report_date'])}</title>
<!--
  {html.escape(title)} —— 由 scripts/render_briefing.py 依据
  config/briefing-entry.schema.json 结构化条目自动生成（Doraskill）。
  排版遵循 skill-Dora.md（SOP v10.0）第八部分锁定样式 v3。
  生成时间：{dt.datetime.now().isoformat(timespec='seconds')}
-->
<style>
{_CSS}
</style>
</head>
<body>
<div class="page">

  <h1>{html.escape(title)}</h1>
  <div class="date-line">{date_line}</div>

{''.join(parts)}
  <div class="note">
    <b>说明区（透明标注）</b><br>
    {note_html}
  </div>

</div>
</body>
</html>
"""


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="结构化条目 -> SOP §8.2 合规排版 HTML")
    ap.add_argument("--entries", required=True, type=Path, help="条目 JSON（符合 config/briefing-entry.schema.json）")
    ap.add_argument("--out", "-o", type=Path, help="输出 HTML 路径；缺省打印到 stdout")
    ap.add_argument("--title", default="敦煌网跨境电商舆情日报", help="页头标题（默认：敦煌网跨境电商舆情日报）")
    ap.add_argument("--strict", action="store_true", help="将 warn 级问题升级为 error（CI 用）")
    args = ap.parse_args()

    if not args.entries.exists():
        raise SystemExit(f"[error] 找不到条目文件: {args.entries}")
    doc = json.loads(args.entries.read_text(encoding="utf-8"))

    problems = validate(doc, strict=args.strict)
    fatal = [p for p in problems if p.startswith("[error]")]
    for p in problems:
        print(p, file=sys.stderr)
    if fatal:
        raise SystemExit(f"[abort] 存在 {len(fatal)} 个 error 级问题，请修正后重试（条目字段契约见 config/briefing-entry.schema.json）")

    html_out = render(doc, title=args.title)
    if args.out:
        args.out.write_text(html_out, encoding="utf-8")
        print(f"[ok] 已渲染 {len(doc['briefing'])} 条 -> {args.out}")
    else:
        sys.stdout.write(html_out)


if __name__ == "__main__":
    main()
