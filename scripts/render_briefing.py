#!/usr/bin/env python3
"""HTML 日报生成器：结构化条目 -> SOP §8.2 合规排版 HTML（Doraskill 渲染链路）。

读取符合 config/briefing-entry.schema.json 的条目 JSON，自动完成：
    1. 字段校验（必填/枚举/日期格式/URL 形态/时间窗口）
    2. 确定性过滤规则自动拦截（SOP §5.1：XX号自媒体、合集/周报/早报词、
       非详情页链接、低权重域名模式）
    3. 语义过滤层（SOP §5.2 细化对照表 / 维度③④）：财报条目区分
       "业绩快讯（纳入）vs 纯股价/市值/减持/增发/回购炒作（排除）"；
       物流条目区分"平台级物流产品发布（纳入）vs 友商仓储运营细节
       （排除）"。命中排除侧信号且无纳入侧要素 → 自动拦截；纳入/排除
       信号并存（边界冲突）或归类不确定 → warn（--strict 升级为 error）。
       note 注明"用户指定/用户指令/指定链接"的条目按 SOP §10.1 豁免
       自动拦截（error 降级 warn）。
    4. 按 SOP §2.1 固定板块顺序输出（self → competitors → industry，空板块整体省略）
    5. 渲染锁定排版 v5（760px 居中 / 主标题「【WorkBuddy】敦煌网舆情日报_YYYY年M月D日」分享格式 /
       板块标题「一、自身监测」「二、友商动态」「三、行业与政策」+ 4px 红色竖线 /
       深色标题 + 来源/日期/badge 元信息行 + <p.summary> 摘要，不输出底部说明区）

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

# —— 过滤规则自动校验（SOP §5.1 / §3.3 可确定性子集）——
XXHAO_SOURCE_RE = re.compile(r"百家号|搜狐号|网易号|头条号|公众号营销号|营销号")
XXHAO_URL_RE = re.compile(r"baijiahao\.baidu\.com|sohu\.com/a/|dy\.163\.com|toutiao\.(com|org)|mp\.weixin\.qq\.com")
COMPILATION_RE = re.compile(r"周报|月报|盘点|合集|早讯|一文读懂|每日简报|今日简报|早报")
LOW_WEIGHT_SITES = ["开屏新闻", "听筒Tech", "百运网", "shuaishou.com", "cbeeexpo.com",
                    "upkuajing.com", "chaoyuexpo.com"]
# 与 config/competitors.json 的 name 对齐
KNOWN_PLATFORMS = {"Temu", "SHEIN", "速卖通", "亚马逊", "TikTok Shop",
                   "Shopee", "Lazada", "eBay", "京东Joybuy"}

# —— 语义过滤层词表（SOP §5.2 细化对照表 / §4.1 维度③④ 过滤行）——
# 财报域：维度③ 关键词（季度财报/Q2/Q3/年报/净营收/净利润/活跃买家/GMV/
#         超预期/指引/财报）触发；判定"业绩快讯（纳入）vs 纯股价炒作（排除）"
EARNINGS_TRIGGER_RE = re.compile(
    r"财报|营收|净利|利润|业绩|GMV|活跃买家|超预期|指引|股价|市值|减持|增发|回购|涨停|跌停|年报|Q[1-4]")
EARNINGS_KEEP_RE = re.compile(  # 纳入侧：友商业绩快讯（营收/GMV/活跃买家超预期、季度指引）
    r"财报|季度|年报|净营收|营收|净利润|净利|利润|业绩|GMV|活跃买家|超预期|指引|同比|Q[1-4]")
EARNINGS_DROP_RE = re.compile(  # 排除侧：纯股价/市值/减持/增发/回购炒作
    r"股价|市值|减持|增发|回购|涨停|跌停|概念股|暴涨|暴跌|抄底|做空|套现|崩盘")

# 物流域：维度④ 关键词（物流产品/x日达/履约/配送/专线/包机/海外仓网络/智慧物流）
# 触发；判定"平台级物流产品发布（纳入）vs 友商仓储运营细节（排除）"
LOGISTICS_TRIGGER_RE = re.compile(
    r"物流|履约|配送|专线|包机|时效|建仓|关仓|仓储|仓库|扩容|枢纽仓|分拣|日达|平台配")
LOGISTICS_KEEP_RE = re.compile(  # 纳入侧：平台级物流产品发布（菜鸟三日达/速卖通平台配，行业基建）
    r"\d+日达|当日达|次日达|半日达|物流产品|平台配|全球.{0,8}达|智慧物流|物流网络|"
    r"履约(?:网络|体系|服务|升级)|专线|包机|时效(?:承诺|升级|提速)|上线|开通|发布|覆盖")
LOGISTICS_DROP_RE = re.compile(  # 排除侧：友商仓储运营细节（建仓/关仓/扩容/智能枢纽仓）
    r"建仓|关仓|扩容|智能枢纽仓|枢纽仓|分拣|仓储面积|库容|万平方米|平方米|新仓|仓库|"
    r"海外仓(?:启用|开仓|投产|扩建|落地)")

_SEMANTIC_CHECKS = [
    {
        "domain": "财报",
        "trigger": EARNINGS_TRIGGER_RE,
        "keep": EARNINGS_KEEP_RE,
        "drop": EARNINGS_DROP_RE,
        "sop": ("SOP §5.2/维度③：✅ 纳入友商业绩快讯（营收/GMV/活跃买家超预期、季度指引），"
                "属\"GMV 公布\"战略级；❌ 排除纯股价/市值/减持/增发/回购炒作"),
    },
    {
        "domain": "物流",
        "trigger": LOGISTICS_TRIGGER_RE,
        "keep": LOGISTICS_KEEP_RE,
        "drop": LOGISTICS_DROP_RE,
        "sop": ("SOP §5.2/维度④：✅ 纳入平台级物流产品发布（菜鸟三日达、速卖通\"平台配\"，行业基建）；"
                "❌ 排除友商仓储运营细节（建仓/关仓/扩容/智能枢纽仓）"),
    },
]

# note 命中这些字样 = SOP §10.1"用户指定链接优先"，豁免语义自动拦截
USER_PINNED_MARKERS = ("用户指定", "用户指令", "指定链接")


# ---------- 校验 ----------

def _parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def semantic_checks(e: dict) -> list[tuple[str, str]]:
    """语义过滤层（SOP §5.2 细化对照表）。仅对 competitors/industry 板块执行
    （排除表语境均为友商；self 自身动态全部视为平台动作，不套用）。

    判定逻辑（对每个命中的域）：
      - 命中排除侧信号 且 无纳入侧要素 → ("error", ...)  纯炒作/仓储细节，自动拦截
      - 纳入侧与排除侧信号并存 → ("warn", ...)           边界冲突，人工复核
      - 仅命中域触发词、两侧均无信号 → ("warn", ...)      归类不确定，人工复核
    """
    if e.get("section") == "self":
        return []
    text = f"{e.get('title', '')}\n{e.get('summary', '')}"
    out: list[tuple[str, str]] = []
    for c in _SEMANTIC_CHECKS:
        m_t = c["trigger"].search(text)
        if not m_t:
            continue
        m_k = c["keep"].search(text)
        m_d = c["drop"].search(text)
        if m_d and not m_k:
            out.append(("error", f"命中语义过滤【{c['domain']}】排除侧信号「{m_d.group(0)}」"
                                f"且无纳入侧要素——{c['sop']}"))
        elif m_d and m_k:
            out.append(("warn", f"语义边界冲突【{c['domain']}】：排除侧「{m_d.group(0)}」"
                                f"与纳入侧「{m_k.group(0)}」并存，需人工复核——{c['sop']}"))
        elif not m_k:
            out.append(("warn", f"语义归类不确定【{c['domain']}】：命中域触发词「{m_t.group(0)}」"
                                f"但未检出纳入/排除信号，需人工复核——{c['sop']}"))
    return out


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
                warn(f"{tag} 为非当日收录（早 {age} 天），建议补 published_date 字段记录真实发布日期")

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

        # —— 语义过滤层（SOP §5.2：财报 业绩快讯 vs 纯炒作 / 物流 平台级 vs 仓储细节）——
        user_pinned = any(mk in (e.get("note") or "") for mk in USER_PINNED_MARKERS)
        for level, msg in semantic_checks(e):
            if level == "error" and not user_pinned:
                err(f"{tag} {msg}")
            else:
                suffix = "（note 注明用户指定，按 SOP §10.1 收录）" \
                    if user_pinned and level == "error" else ""
                warn(f"{tag} {msg}{suffix}")

    return errors


# ---------- 渲染 ----------

_CSS = """
  body {
    background: #ffffff;
    font-family: "Microsoft YaHei", "PingFang SC", -apple-system, "Segoe UI", sans-serif;
    color: #333;
    margin: 0;
    padding: 32px 0 64px;
  }
  .page { max-width: 760px; margin: 0 auto; padding: 0 24px; box-sizing: border-box; }
  h1 {
    font-size: 22px;
    font-weight: 700;
    text-align: center;
    margin: 24px 0 28px;
    letter-spacing: 1px;
    color: #1a1a1a;
  }
  h2 {
    font-size: 20px;
    font-weight: 700;
    border-left: 4px solid #e74c3c;
    padding-left: 12px;
    margin: 36px 0 18px;
    line-height: 1.4;
    color: #1a1a1a;
  }
  .item {
    margin-bottom: 28px;
    line-height: 1.8;
    font-size: 15px;
  }
  .item a {
    color: #1a1a1a;
    font-weight: 600;
    text-decoration: none;
    display: block;
    margin-bottom: 6px;
    font-size: 16px;
  }
  .item a:hover { text-decoration: underline; }
  .meta {
    font-size: 13px;
    color: #999;
    margin: 0 0 8px;
  }
  .meta .source {
    color: #4a90e2;
    font-weight: 500;
  }
  .meta .date {
    margin-left: 6px;
  }
  .badge {
    display: inline-block;
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 12px;
    line-height: 1.6;
    margin-left: 10px;
  }
  .badge-positive { background: #d4edda; color: #155724; }
  .badge-neutral  { background: #e2e3e5; color: #383d41; }
  .badge-negative { background: #f8d7da; color: #721c24; }
  .summary {
    color: #555;
    margin: 0;
    text-align: justify;
  }
"""

_SECTION_LABEL = {"self": "一、自身监测", "competitors": "二、友商动态", "industry": "三、行业与政策"}


def _fmt(d: str) -> str:
    return d.replace("-", "/")


def _cn_date(d: str) -> str:
    """YYYY-MM-DD -> 2026年9月9日"""
    y, m, day = d.split("-")
    return f"{y}年{int(m)}月{int(day)}日"


def render(doc: dict, title: str = "敦煌网舆情日报") -> str:
    briefing = doc["briefing"]

    # 按固定板块顺序分组，空板块省略（SOP §2.1 / §2.2 宁缺毋滥）
    buckets: dict[str, list[dict]] = {k: [] for k in SECTION_ORDER}
    for e in briefing:
        buckets[e["section"]].append(e)

    # 主标题：【WorkBuddy】敦煌网舆情日报_2026年9月9日（分享标题格式，日期并入标题）
    h1_title = f"【WorkBuddy】{title}_{_cn_date(doc['report_date'])}"

    parts: list[str] = []
    for sec in SECTION_ORDER:
        items = buckets[sec]
        if not items:
            continue
        parts.append(f"  <h2>{_SECTION_LABEL[sec]}</h2>\n")
        for e in items:
            badge_cls = f"badge-{e['sentiment'].lower()}"
            parts.append("  <div class=\"item\">")
            parts.append(f"    <a href=\"{html.escape(e['url'])}\">{html.escape(e['title'])}</a>")
            meta_line = (
                f'<span class="source">{html.escape(e["source"])}</span>'
                f'  <span class="date">{_fmt(e["date"])}</span>'
                f'  <span class="badge {badge_cls}">{html.escape(e["sentiment"])}</span>'
            )
            parts.append("    <div class=\"meta\">" + meta_line + "</div>")
            parts.append(f"    <p class=\"summary\">{html.escape(e['summary'])}</p>")
            parts.append("  </div>\n")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(h1_title)}</title>
<!--
  {html.escape(title)} —— 由 scripts/render_briefing.py 依据
  config/briefing-entry.schema.json 结构化条目自动生成（Doraskill）。
  排版遵循 skill-Dora.md（SOP v10.0）第八部分锁定样式 v5。
  生成时间：{dt.datetime.now().isoformat(timespec='seconds')}
-->
<style>
{_CSS}
</style>
</head>
<body>
<div class="page">

  <h1>{html.escape(h1_title)}</h1>

{''.join(parts)}
</div>
</body>
</html>
"""


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="结构化条目 -> SOP §8.2 合规排版 HTML")
    ap.add_argument("--entries", required=True, type=Path, help="条目 JSON（符合 config/briefing-entry.schema.json）")
    ap.add_argument("--out", "-o", type=Path, help="输出 HTML 路径；缺省打印到 stdout")
    ap.add_argument("--title", default="敦煌网舆情日报", help="页头标题（默认：敦煌网舆情日报）")
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
