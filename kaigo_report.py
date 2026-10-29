# -*- coding: utf-8 -*-
"""
kaigo_report.py — 原文汇总与推送正文生成

只做机械编排：分组、排序、计数。
标题、机关、日期一律原样输出，不翻译、不摘要、不改写。
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def display_title(item):
    """展示用标题：若已用 Vol 前缀单独标注，则从标题中移除重复的卷号串。
    只删「介護保険最新情報Vol.X」这一标签，括号内的正文一律保留原样。"""
    t = item["title"]
    v = item.get("doc_no")
    if v:
        t = re.sub(r"^\s*介護保険最新情報\s*[Vv][Oo][Ll]\.?\s*%s\s*" % re.escape(str(v)), "", t)
        t = re.sub(r"^[（(]\s*", "（", t) if t.startswith(("（", "(")) else t
    return t.strip() or item["title"]


def short(title, n=78):
    """仅用于表格显示的等宽截断，不改变措辞；完整标题始终附带原文链接"""
    title = re.sub(r"\s+", " ", title).strip()
    return title if len(title) <= n else title[: n - 1] + "…"


def md_link(item):
    return f"[{short(display_title(item))}]({item['url']})"


# --------------------------------------------------------------- 近10年汇总
def build_summary(items, years=10):
    now = datetime.now(JST)
    start_year = now.year - years + 1
    lines = []
    W = lines.append

    dated = [x for x in items if x.get("date")]
    W(f"# 日本介护政策原文汇总（{start_year}–{now.year}）")
    W("")
    W(f"- 归档总数：**{len(items)}** 条（含原文链接）")
    W(f"- 时间范围：**{min(x['date'] for x in dated)} ～ {max(x['date'] for x in dated)}**")
    W(f"- 生成时间：{now.strftime('%Y-%m-%d %H:%M')} (JST)")
    W("- 说明：仅收录原文元数据与官方链接，标题/机关/文号均为日文原文，未作翻译与改写。")
    W("")

    # 逐年 × 分桶
    W("## 一、年度分布")
    W("")
    W("| 年份 | 介护保险最新情报 | 报道发表 | 合计 |")
    W("|---|---:|---:|---:|")
    for y in range(now.year, start_year - 1, -1):
        sub = [x for x in dated if x["date"].startswith(str(y))]
        a = sum(1 for x in sub if x.get("doc_no"))
        b = len(sub) - a
        W(f"| {y} | {a} | {b} | {len(sub)} |")
    W("")
    W("> 报道发表部分：厚労省官网仅提供 2023 年以后的月度归档页，更早年份的报道类文件不在其现行站点上，"
      "属数据源边界，非遗漏。介护保险最新情报（通知/事务联络）为 10 年完整覆盖。")
    W("")

    # 主题分布
    W("## 二、主题分布（按标题关键词机械归类）")
    W("")
    cnt = Counter(t for x in items for t in (x.get("tags") or []))
    W("| 主题 | 条数 |")
    W("|---|---:|")
    for k, v in cnt.most_common():
        W(f"| {k} | {v} |")
    W("")

    # 年度重点
    W("## 三、历年关键文件（原文标题 + 链接）")
    W("")
    for y in range(now.year, start_year - 1, -1):
        sub = [x for x in dated if x["date"].startswith(str(y))]
        if not sub:
            continue
        W(f"### {y} 年（{len(sub)} 条）")
        W("")
        W("| 日期 | 标题（原文） | 发文机关 |")
        W("|---|---|---|")
        for x in sub[:14]:
            org = (x.get("org") or "—").replace("|", "／")
            W(f"| {x['date']} | {md_link(x)} | {org} |")
        if len(sub) > 14:
            W(f"| … | 其余 {len(sub) - 14} 条见完整库 | |")
        W("")

    return "\n".join(lines)


# --------------------------------------------------------------- 每日简报
def build_daily(payload, max_items=40):
    items = payload.get("new_items") or []
    now = datetime.now(JST)
    lines = []
    W = lines.append
    bootstrap = payload.get("mode") == "bootstrap"

    if bootstrap:
        W(f"# 日本介护政策原文库已建好　{now.strftime('%Y-%m-%d')}")
        W("")
        W(f"共收录 **{payload.get('total_archived', len(items))}** 条近十年原文，"
          f"时间跨度 {payload.get('date_from', '')} ～ {payload.get('date_to', '')}。")
        W("")
        W("从明天起，只推送**当日新增**的原文，不再重复历史。")
        W("")
        W(f"下方列出最新 {min(len(items), 10)} 条作为样例，完整清单见 archive.csv。")
        W("")
        show = sorted(items, key=lambda x: (x.get("date") or "", int(x.get("doc_no") or 0)), reverse=True)[:10]
    else:
        W(f"# 日本介护政策新增　{now.strftime('%Y-%m-%d')}")
        W("")
        if not items:
            W("本期无新增。")
            return "\n".join(lines)
        has_ai = any(x.get("summary_zh") for x in items)
        W(f"本期 **{len(items)}** 条新增。"
          + ("每条含中文摘要，**原文标题与链接均未改动**。" if has_ai else "原文标题与官方链接。"))
        W("")
        show = sorted(items, key=lambda x: (x.get("date") or "", int(x.get("doc_no") or 0)), reverse=True)[:max_items]

    if not items:
        return "\n".join(lines)

    by = defaultdict(list)
    for x in show:
        by[x["source"]].append(x)

    order = ["厚生労働省 介護保険最新情報", "WAM.NET 介護保険最新情報", "厚生労働省 報道発表資料"]
    for src in sorted(by, key=lambda s: order.index(s) if s in order else 99):
        group = by[src]
        # 有 AI 评分时按重要性排序，否则按日期/卷号
        if any(x.get("importance") for x in group):
            group.sort(key=lambda x: (-int(x.get("importance") or 0),
                                      x.get("date") or "",
                                      int(x.get("doc_no") or 0)), reverse=False)
        else:
            group.sort(key=lambda x: ((x.get("date") or ""), int(x.get("doc_no") or 0)), reverse=True)
        title_short = src.replace("厚生労働省 ", "").replace("WAM.NET ", "WAM ")
        W(f"### {title_short}（{len(group)}）")
        W("")
        for x in group:
            vol = f"Vol.{x['doc_no']} · " if x.get("doc_no") else ""
            star = "★" * int(x.get("importance") or 0)
            head = f"[{star}] " if star else ""
            W(f"- **{x.get('date') or '—'}**　{head}{vol}{short(display_title(x), 90)}")
            if x.get("summary_zh"):
                W(f"  · {x['summary_zh']}")
            W(f"  ↳ [{x['url']}]({x['url']})")
            if x.get("org"):
                W(f"  ↳ {x['org']}")
            if x.get("source_note"):
                W(f"  ↳ ⚠ {x['source_note']}")
        W("")

    if not bootstrap:
        W("---")
        W(f"完整归档 {payload.get('total_archived', len(items))} 条，标题均为日文原文，未翻译未改写。")

    if payload.get("errors"):
        W("")
        W("**抓取异常**")
        for e in payload["errors"]:
            W(f"- {e['source']}：{e['error']}")
    return "\n".join(lines)


def main():
    items = load(os.path.join(DATA, "items.json"), [])
    latest = load(os.path.join(DATA, "latest.json"), {"new_items": []})

    summary = build_summary(items, 10)
    daily = build_daily(latest)

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    with open(os.path.join(ROOT, "out", "summary_10y.md"), "w", encoding="utf-8") as f:
        f.write(summary)
    with open(os.path.join(ROOT, "out", "daily.md"), "w", encoding="utf-8") as f:
        f.write(daily)

    # CSV，便于 Excel 打开
    import csv
    with open(os.path.join(ROOT, "out", "archive.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日期", "标题(原文)", "发文机关", "文号", "主题", "原文链接", "其他链接", "数据源", "备注"])
        for x in items:
            w.writerow([x.get("date") or "", x["title"], x.get("org") or "",
                        x.get("doc_no") or "", "／".join(x.get("tags") or []),
                        x["url"], " ".join(x.get("alt_urls") or []),
                        x["source"], x.get("source_note") or ""])

    print("已生成：out/summary_10y.md, out/daily.md, out/archive.csv")


if __name__ == "__main__":
    main()
