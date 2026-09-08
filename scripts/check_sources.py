#!/usr/bin/env python3
"""信源可访问性批量预检脚本（Doraskill Step 5 辅助工具）。

对应 skill-Dora.md（SOP v10.0）：核心原则 8「收录前必须验证可访问：
无法验证或 404/403 的直接排除」与 §5.1#7/#9（非详情页/链接失效一律排除）。

在 WebFetch 逐条核验前，先用本脚本批量预检候选链接，快速筛出：
    404 / 403 / 超时 / DNS 失败 / 跳转首页 等问题链接。

输入两种格式任选其一：
    --entries entries.json   读取日报条目 JSON（复用 config/briefing-entry.schema.json 的 url 字段）
    --urls    urls.txt       每行一个 URL 的纯文本清单

用法:
    python scripts/check_sources.py --entries examples/entries.sample.json
    python scripts/check_sources.py --urls links.txt --out report.md --timeout 8

说明:
    - 纯标准库（urllib + concurrent.futures），Python 3.9+
    - 默认并发 4 线程；HEAD 失败自动回退 GET（部分站点不支持 HEAD）
    - 结果分级：OK(200) / REDIRECT(跳转后仍可达) / BLOCKED(403) / GONE(404) / TIMEOUT / DNS / ERROR
    - --no-verify 可跳过 TLS 证书校验（个别站点证书链不全时使用）
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

UA = "Mozilla/5.0 (Doraskill-check_sources/1.0; +https://github.com/Dora-ndme/Doraskill)"


def _urls_from_entries(path: Path) -> list[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    urls = [e["url"] for e in doc.get("briefing", []) if e.get("url")]
    if not urls:
        raise SystemExit(f"[error] {path} 中没有可检查的 url")
    return urls


def _urls_from_list(path: Path) -> list[str]:
    urls = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        raise SystemExit(f"[error] {path} 为空或没有有效 URL")
    return urls


def _opener(no_verify: bool):
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def check(url: str, opener, timeout: int) -> dict:
    """单链接预检，返回 {url, status, http, final, note}。"""
    methods = ["HEAD", "GET"]
    last_code = 0
    final_url = url
    for m in methods:
        req = urllib.request.Request(url, method=m, headers={"User-Agent": UA})
        try:
            with opener.open(req, timeout=timeout) as resp:
                final_url = resp.geturl() or url
                code = resp.status
                # 跳转后回到站点根路径 -> 疑似"跳首页"
                if url != final_url and _is_home(final_url):
                    return {"url": url, "status": "REDIRECT-HOME", "http": code,
                            "final": final_url, "note": "跳转至站点根路径，疑似首页兜底"}
                if code < 400:
                    return {"url": url, "status": "OK" if m == "HEAD" else "OK(GET-fallback)",
                            "http": code, "final": final_url if url != final_url else "",
                            "note": ""}
                last_code = code  # 4xx/5xx 时继续尝试 GET（有的站 HEAD 返回 405）
        except urllib.error.HTTPError as e:
            if m == "GET":
                return {"url": url, "status": "BLOCKED" if e.code == 403 else
                        ("GONE" if e.code == 404 else f"HTTP-{e.code}"),
                        "http": e.code, "final": url, "note": ""}
            last_code = e.code
        except urllib.error.URLError as e:
            reason = str(e.reason)
            if "timed out" in reason.lower():
                return {"url": url, "status": "TIMEOUT", "http": 0, "final": url,
                        "note": f"超过 {timeout}s 无响应"}
            if "getaddrinfo" in reason or "Name or service" in reason:
                return {"url": url, "status": "DNS", "http": 0, "final": url,
                        "note": "域名无法解析"}
            if "CERTIFICATE_VERIFY_FAILED" in reason or "certificate verify" in reason.lower():
                return {"url": url, "status": "ERROR", "http": 0, "final": url,
                        "note": "TLS 证书校验失败（可尝试 --no-verify）"}
            return {"url": url, "status": "ERROR", "http": 0, "final": url, "note": reason[:120]}
        except Exception as e:  # noqa: BLE001 —— 尽力返回可读结论
            return {"url": url, "status": "ERROR", "http": 0, "final": url, "note": str(e)[:120]}
    # HEAD 收到非 2xx 且 GET 未执行（如 405 且 GET 也失败）兜底
    return {"url": url, "status": f"HTTP-{last_code}", "http": last_code,
            "final": url, "note": ""}


def _is_home(u: str) -> bool:
    try:
        return not urlsplit(u).path.rstrip("/")
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="信源链接批量可访问性预检")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--entries", type=Path, help="条目 JSON（取 url 字段）")
    g.add_argument("--urls", type=Path, help="每行一个 URL 的文本清单")
    ap.add_argument("--out", "-o", type=Path, help="输出 Markdown 报告路径；缺省仅打印控制台")
    ap.add_argument("--timeout", type=float, default=8.0, help="单链接超时秒数（默认 8）")
    ap.add_argument("--threads", type=int, default=4, help="并发线程数（默认 4）")
    ap.add_argument("--no-verify", action="store_true", help="跳过 TLS 证书校验")
    args = ap.parse_args()

    urls = _urls_from_entries(args.entries) if args.entries else _urls_from_list(args.urls)
    if len(urls) > 200:
        raise SystemExit(f"[error] 单次最多预检 200 个链接（当前 {len(urls)}），请分批")
    print(f"[precheck] 共 {len(urls)} 个链接，并发 {args.threads}，单链接超时 {args.timeout}s ...")

    opener = _opener(args.no_verify)
    results = []
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = {pool.submit(check, u, opener, args.timeout): u for u in urls}
        for fut in as_completed(futs):
            results.append(fut.result())

    order = {"OK": 0, "OK(GET-fallback)": 1, "REDIRECT-HOME": 2, "TIMEOUT": 3,
             "GONE": 3, "BLOCKED": 3, "DNS": 4, "ERROR": 4}
    results.sort(key=lambda r: (order.get(r["status"], 5), r["url"]))
    ok = sum(1 for r in results if r["status"].startswith("OK"))
    bad = [r for r in results if not r["status"].startswith("OK")]

    lines = [f"# 信源可访问性预检报告", "",
             f"- 检查时间：{__import__('datetime').datetime.now().isoformat(timespec='seconds')}",
             f"- 链接总数：{len(results)} ｜ 可达：{ok} ｜ 异常：{len(bad)}", ""]
    for r in results:
        extra = f" → {r['final']}" if r.get("final") and r["final"] != r["url"] else ""
        note = f" ｜ {r['note']}" if r.get("note") else ""
        lines.append(f"- `{r['status']}` {r['url']}{extra}{note}")
    if bad:
        lines.insert(1, f"\n> ⚠️ {len(bad)} 个链接异常，按 SOP §5.1#7/#9 应在收录前剔除或替换为权威来源。")
    report = "\n".join(lines) + "\n"

    # 控制台
    for r in results:
        icon = "✅" if r["status"].startswith("OK") else "❌"
        extra = f" -> {r['final']}" if r.get("final") and r["final"] != r["url"] else ""
        note = f" ({r['note']})" if r.get("note") else ""
        print(f"{icon} {r['status']:<16} {r['url']}{extra}{note}")
    print(f"\n结论：{ok}/{len(results)} 可达，{len(bad)} 个异常（SOP：异常链接收录前剔除）")

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"[ok] 报告已写入 {args.out}")


if __name__ == "__main__":
    main()
