#!/usr/bin/env python3
"""
Doraskill · generate_search_plan.py

读取 config/competitors.json（SOP v10.0 检索矩阵），为指定日期生成一份
可直接照做的舆情日报检索计划：

    1. 第一轮 —— 九家友商并行检索（每家 = 友商名 + 日期 + 主关键词 + 数据向关键词）
    2. 第二轮 —— 维度补检（业绩财报 / 数据报告 / 物流产品 / 政策监管）
    3. 第三轮 —— 行业与政策、敦煌网自身
    4. 维度覆盖核查 —— 确保五大检索维度至少各覆盖一轮

纯 Python 标准库实现，无第三方依赖，离线可运行。

用法:
    python generate_search_plan.py                 # 按今天日期生成
    python generate_search_plan.py --date 2026-09-08
    python generate_search_plan.py --out plan.md   # 输出到文件

配置格式见 config/competitors.json（字段与 skill-Dora.md §4.1 / §4.2 一一对应）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# 仓库根目录：脚本位于 <root>/scripts/，配置位于 <root>/config/
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "competitors.json"

# 五大维度中哪些需要"第二轮补检"（含必查机构/信源的维度）
DIMENSION_PRIORITY = ["earnings", "data_report", "logistics_product", "policy"]


def load_config(path: Path = CONFIG_PATH) -> dict:
    """加载检索配置；缺失或非法 JSON 时给出可读错误并退出。"""
    if not path.exists():
        sys.exit(f"[错误] 找不到配置文件: {path}\n请确认在仓库根目录下运行本脚本。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"[错误] 配置文件不是合法 JSON: {path}\n{exc}")


def parse_date(value: str) -> dt.date:
    """解析 --date 参数，格式 YYYY-MM-DD。"""
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        sys.exit(f"[错误] 日期格式应为 YYYY-MM-DD，收到: {value}")


def _strip_name(name: str, keyword: str) -> str:
    """去掉关键词开头重复的友商名，避免 query 词面冗余（"Temu … Temu 半托管"）。"""
    if keyword.startswith(name):
        rest = keyword[len(name):].strip()
        return rest or name  # 兜底：全名恰等于关键词时保留原名
    return keyword


def build_competitor_queries(cfg: dict, date: dt.date) -> list[dict]:
    """第一轮：为每家友商生成一条推荐 query 及其可用备选词。

    推荐 query 结构 = 友商名(含别名) + 日期 + 主关键词 + 数据向关键词，
    其中主词/数据词若自带友商名前缀则去重，保证词面干净。
    """
    queries = []
    for comp in cfg["competitors"]:
        name = comp["name"]
        aliases = " ".join(comp.get("aliases", []))
        primary = comp["primary_keywords"]
        data = comp["data_keywords"]

        # 组合：友商名（含别名）+ 日期 + 首个主词（去重前缀）+ 首个数据词（去重前缀）
        head = name + (f" {aliases}" if aliases else "")
        query = " ".join(
            x for x in [head, date.isoformat(), _strip_name(name, primary[0]),
                        _strip_name(name, data[0])] if x
        )

        queries.append(
            {
                "name": name,
                "query": query,
                "primary_keywords": primary,
                "data_keywords": data,
                "priority_sources": comp.get("priority_sources", []),
            }
        )
    return queries


def build_followup_queries(cfg: dict, date: dt.date) -> list[dict]:
    """第二轮：业绩财报 / 数据报告 / 物流产品 / 政策监管 四类补检建议。"""
    dims = {d["id"]: d for d in cfg["retrieval_dimensions"]}
    followups = []
    templates = {
        "earnings": "eBay OR 亚马逊 OR 速卖通 {date} Q2 营收 GMV 财报",
        "data_report": "TikTok Shop OR Shopee GMV Momentum Works Marketplace Pulse {date}",
        "logistics_product": "菜鸟 OR 速卖通 物流产品 三日达 履约 {date}",
        "policy": "跨境电商 {date} 政策 退税 增值税法 综试区 海关",
    }
    mandates = {
        "earnings": "亿邦 ebrungo/zb 快讯栏",
        "data_report": "AMZ123 / TT123",
        "logistics_product": "中国新闻网 / 央视网",
        "policy": "海关总署 / 财政部 / 商务部官网",
    }
    for dim_id in DIMENSION_PRIORITY:
        dim = dims[dim_id]
        followups.append(
            {
                "name": dim["name"],
                "query": templates[dim_id].format(date=date.isoformat()),
                "mandatory": mandates[dim_id],
                "dimension_keywords": dim["keywords"],
                "include": dim.get("include", ""),
                "exclude": dim.get("exclude", ""),
            }
        )
    return followups


def render(cfg: dict, date: dt.date) -> str:
    """把检索计划渲染为 Markdown 文本。"""
    lines: list[str] = []
    add = lines.append
    meta = cfg["meta"]

    add(f"# 舆情日报检索计划 · {date.isoformat()}")
    add("")
    add(f"> 依据：`{meta['source']}` ｜ 规则：{meta['retrieval_rule']}")
    add("> 覆盖要求：{0}。建议并行执行、够用即停。".format(meta["dimension_rule"]))
    add("")

    # ---- 第一轮：九家友商 ----
    comp_queries = build_competitor_queries(cfg, date)
    add(f"## 第一轮：九家友商并行检索（{len(comp_queries)} 次搜索）")
    add("")
    for i, q in enumerate(comp_queries, 1):
        add(f"### {i}. {q['name']}")
        add("")
        add(f"- 推荐 query：`{q['query']}`")
        add(f"- 主关键词：{' / '.join(q['primary_keywords'])}")
        add(f"- 数据向关键词：{' / '.join(q['data_keywords'])}")
        src = "、".join(q["priority_sources"]) if q["priority_sources"] else "—"
        add(f"- 信源优先：{src}")
        add("")

    # ---- 第二轮：维度补检 ----
    followups = build_followup_queries(cfg, date)
    add(f"## 第二轮：维度补检（{len(followups)} 类）")
    add("")
    add("> 命中各维度时对照过滤细化表：`include` 可纳入，`exclude` 一律排除。")
    add("")
    for f in followups:
        add(f"### {f['name']}")
        add("")
        add(f"- 补检 query：`{f['query']}`")
        add(f"- 必查：{f['mandatory']}")
        if f["include"]:
            add(f"- ✅ 纳入：{f['include']}")
        if f["exclude"]:
            add(f"- ❌ 排除：{f['exclude']}")
        add("")

    # ---- 第三轮：行业政策 + 敦煌自身 ----
    add("## 第三轮：行业与政策、敦煌网自身")
    add("")
    ind = cfg["industry_policy"]
    add("### 行业与政策")
    add("")
    add(f"- query：`{' OR '.join(ind['keywords'])} {date.isoformat()}`")
    add(f"- 信源聚焦：{'、'.join(ind['focus'])}")
    add(f"- ❌ 排除：{'；'.join(ind['exclude'])}")
    add("")
    self_m = cfg["self_monitoring"]
    add("### 敦煌网自身（无战略级动态则省略该板块）")
    add("")
    add(f"- query：`{' OR '.join(self_m['keywords'])} {date.isoformat()}`")
    add(f"- 信源优先：{'、'.join(self_m['priority_sources'])}")
    add("")

    # ---- 维度覆盖核查 ----
    add("## 维度覆盖核查（生成前逐项打勾）")
    add("")
    dim_names = [d["name"] for d in cfg["retrieval_dimensions"]]
    for name in dim_names:
        add(f"- [ ] {name} 已覆盖至少一轮")
    add("")
    add("---")
    add("")
    add("*时间窗口提示：友商战略动作/业绩快讯收当日；第三方数据报告放宽至近 2-3 日；")
    add("平台级物流产品与行业政策收当日+近 1-2 日。详见 skill-Dora.md 第六部分。*")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成舆情日报当日检索计划")
    parser.add_argument("--date", type=str, default=None,
                        help="报告日期 YYYY-MM-DD（默认今天）")
    parser.add_argument("--out", type=str, default=None,
                        help="输出文件路径（默认打印到终端）")
    args = parser.parse_args()

    cfg = load_config()
    date = parse_date(args.date) if args.date else dt.date.today()
    plan = render(cfg, date)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(plan, encoding="utf-8")
        print(f"[OK] 检索计划已写入: {out_path.resolve()}")
    else:
        print(plan)


if __name__ == "__main__":
    main()
