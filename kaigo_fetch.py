# -*- coding: utf-8 -*-
"""
kaigo_fetch.py — 日本介护政策原文抓取引擎（原文保真，零改写）

原则：
  · 只采集元数据 + 原文链接，不翻译、不摘要、不改写标题
  · 标题 / 发文机关 / 文号 全部保留日文原文
  · 只做机械分桶（关键词归类）与去重，供检索使用

数据源：
  1. WAM.NET 介护保险最新情报存档   —— 2008-11 至今全量，单页 1496+ 条（主力回溯源）
  2. 厚労省 介护保险最新情报页      —— 最新卷次 + 中间报告类非编号文件
  3. 厚労省 報道発表資料            —— 按月存档，回溯近 10 年

回溯范围：默认近 10 年（可用 --years 调整；WAM 支持到 2008 年）
"""

import json
import os
import re
import sys
import time
import hashlib
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)

ITEMS_FILE = os.path.join(DATA, "items.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MHLW = "https://www.mhlw.go.jp"
WAM = "https://www.wam.go.jp"

# ------------------------------------------------------------------ 数据源
SOURCES = [
    {
        "id": "wam_ksvol",
        "name": "WAM.NET 介護保険最新情報",
        "url": WAM + "/gyoseiShiryou/detail-list?bun=020060090",
        "kind": "wam",
    },
    {
        "id": "mhlw_latestinfo",
        "name": "厚生労働省 介護保険最新情報",
        "url": MHLW + "/stf/seisakunitsuite/bunya/hukushi_kaigo/kaigo_koureisha/index_00010.html",
        "kind": "mhlw_latestinfo",
    },
]

# 報道発表：按月归档页，回溯时批量拉取
HODOU_MONTH = MHLW + "/stf/houdou/houdou_list_{ym}.html"
HODOU_KEYWORDS = ["介護", "高齢", "認知症", "要介護", "介護保険", "特別養護", "老人"]
# 页面导航/固定链接，非报道条目
HODOU_SKIP = {
    "/stf/seisakunitsuite/bunya/hukushi_kaigo/kaigo_koureisha/kouhyou",
    "/stf/seisakunitsuite/bunya/hukushi_kaigo/kaigo_koureisha/kouhyou/",
}

# ------------------------------------------------------------------ 日期
KANJI_NUM = {"元": 1, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}


def _int(s):
    s = s.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    if s in KANJI_NUM:
        return KANJI_NUM[s]
    if "十" in s:
        a, _, b = s.partition("十")
        return (KANJI_NUM.get(a, 1) if a else 1) * 10 + (KANJI_NUM.get(b, 0) if b else 0)
    return None


def parse_jp_date(text):
    if not text:
        return None
    m = re.search(r"(令和|平成|昭和)\s*([元一-九十\d０-９]{1,3})\s*年\s*([一-九十\d０-９]{1,2})\s*月\s*([一-九十\d０-９]{1,2})\s*日", text)
    if m:
        era, y, mo, d = m.groups()
        y, mo, d = _int(y), _int(mo), _int(d)
        if not (y and mo and d):
            return None
        year = ERA_BASE[era] + y
        if era == "令和" and y == 1:
            year = 2019
        return f"{year:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})", text)
    if m:
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


# ------------------------------------------------------------------ 分桶
TAGS = [
    ("介護報酬", ["介護報酬", "報酬改定", "単位数", "処遇改善加算"]),
    ("制度改正", ["改正", "省令", "政令", "施行", "法改正", "公布"]),
    ("要介護認定", ["要介護認定", "認定調査", "主治医意見書", "審査会"]),
    ("認知症", ["認知症"]),
    ("地域支援事業", ["地域支援事業", "総合事業", "生活支援", "介護予防"]),
    ("介護人材", ["人材", "研修", "処遇", "介護福祉士", "外国人", "技能実習", "特定技能", "職員"]),
    ("信息化/DX", ["介護情報基盤", "ケアプラン", "データ", "システム", "DX", "ICT", "WEB", "オンライン"]),
    ("福祉用具/住宅改修", ["福祉用具", "住宅改修"]),
    ("给付费/统计", ["給付費", "統計", "調査", "集計", "実態"]),
    ("监督/事故", ["事故", "監査", "指定取消", "処分", "報告"]),
    ("预算/税制", ["予算", "税制", "交付金", "補助金"]),
    ("感染症", ["新型コロナ", "感染"]),
]


def tag_item(title):
    return [n for n, kws in TAGS if any(k in title for k in kws)]


def strip_size(t):
    """去掉末尾［2.5MB］/（PDF：199KB）容量标注，其余原文不动"""
    t = re.sub(r"\s*[［\[][\d.,]+\s*(?:MB|KB|GB)[］\]]\s*$", "", t)
    t = re.sub(r"\s*[（(]PDF[：:]\s*[\d.,]+\s*(?:MB|KB|GB)[）)]\s*$", "", t)
    return t.strip()


def item_key(title, url):
    h = hashlib.sha1()
    h.update((strip_size(title) + "|" + os.path.basename(url)).encode("utf-8"))
    return h.hexdigest()[:16]


def clean(s):
    s = re.sub(r"<[^>]+>", "", s)
    for a, b in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'")]:
        s = s.replace(a, b)
    return re.sub(r"[ \t\u3000]+", " ", s).strip()


def vol_of(title):
    m = re.search(r"[Vv][Oo][Ll]\.?\s*(\d+)", title)
    return m.group(1) if m else None


def _title_suspect(item, vol):
    """判断某条目的标题是否被源头串行污染。

    WAM 少数字段的标题会拼入相邻卷次的内容（如 Vol.1549 标题里出现
    1548 或其他卷次的主题）。此处只做标记，不改写。
    """
    t = item.get("title") or ""
    if item.get("source_id") == "wam_ksvol" and len(t) > 60:
        return True
    others = re.findall(r"[Vv][Oo][Ll]\.?\s*(\d+)", t)
    return any(o != str(vol) for o in others)


# ------------------------------------------------------------------ 解析器
def parse_wam(html, src):
    """WAM 表格行：<td class=dlist_title> <p><a href=pdf>Vol.1499（PDF：199KB）</a></p>
                    <p>副标题（真正标题）</p> </td> <td class=dlist_date>2026年05月01日</td>"""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        links = re.findall(r'<a[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', row, re.S)
        if not links:
            continue
        url, anchor = links[0]
        dm = re.search(r'dlist_date[^>]*>\s*(\d{4})年(\d{1,2})月(\d{1,2})日', row)
        date = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else None

        anchor_txt = strip_size(clean(anchor))
        # 副标题：td 内除标题行外的 <p>
        tcell = re.search(r'class="dlist_title"[^>]*>(.*?)</td>', row, re.S)
        body = tcell.group(1) if tcell else row
        subs = re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)
        sub = ""
        for s in subs:
            if "<a" in s:          # 标题行本身，跳过
                continue
            st = strip_size(clean(s))
            if len(st) > len(sub):
                sub = st

        title = anchor_txt
        v = vol_of(anchor_txt)
        if sub and len(sub) >= 6:
            title = f"介護保険最新情報Vol.{v} {sub}" if v and f"Vol.{v}" not in sub else sub
        if len(title) < 6:
            continue

        out.append({
            "source": src["name"], "source_id": src["id"],
            "title": title, "org": None, "doc_no": vol_of(anchor_txt),
            "date": date, "url": urljoin(WAM, url), "pdf": urljoin(WAM, url),
            "tags": tag_item(title),
        })
    return out


def parse_mhlw_latestinfo(html, src):
    """厚労省页按 <br> 逻辑行：标题行 + （令和X年X月X日 机关 通知）"""
    lines = re.split(r"<br\s*/?>|</p>", html)
    out, pending = [], None

    def flush(row):
        links = re.findall(r'<a[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', row, re.S)
        if not links:
            return None
        merged = strip_size(clean("".join(t for _, t in links)))
        if len(merged) < 6:
            merged = strip_size(clean(max(links, key=lambda x: len(x[1]))[1]))
        if len(merged) < 6:
            return None
        best = max(links, key=lambda x: len(clean(x[1])))
        return {
            "source": src["name"], "source_id": src["id"],
            "title": merged, "org": None, "doc_no": vol_of(merged),
            "date": None, "url": urljoin(MHLW, best[0]), "pdf": urljoin(MHLW, best[0]),
            "tags": tag_item(merged),
        }

    for line in lines:
        txt = clean(line)
        has_pdf = bool(re.search(r'href="[^"]+\.pdf"', line))
        is_meta = bool(re.match(r"^[（(]\s*(令和|平成|昭和)", txt))

        if is_meta and pending:
            pending["date"] = parse_jp_date(txt)
            mm = re.search(r"[（(][^）)]*?日(.+?)[）)]\s*$", txt)
            if mm:
                pending["org"] = mm.group(1).strip()
            out.append(pending)
            pending = None
        elif has_pdf:
            if pending:
                out.append(pending)
            pending = flush(line)
        elif pending and (txt.startswith(("（", "(")) or len(txt) < 4):
            continue
    if pending:
        out.append(pending)
    return [x for x in out if x and x.get("date")]


def parse_houdou(html, src, ym):
    """報道発表月度页结构：
        <h3 class=m-hdgLv3__hdg>2023年3月31日（金）掲載</h3>
        <ul class="m-listNews"><li><a href=...><div><span>标题</span></div></a></li>...</ul>
    """
    out = []
    blocks = re.split(r'(?=<h3[^>]*class="m-hdgLv3__hdg"[^>]*>)', html)
    cur = None
    for b in blocks:
        hm = re.match(r'<h3[^>]*>(.*?)</h3>', b, re.S)
        if hm:
            cur = parse_jp_date(clean(hm.group(1)))
        for m in re.finditer(r'<li>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</li>', b, re.S):
            url, inner = m.group(1), m.group(2)
            t = clean(inner)
            if len(t) < 10 or not any(k in t for k in HODOU_KEYWORDS):
                continue
            if not url.startswith(("/", "http")) or url.endswith((".css", ".js")):
                continue
            if url.rstrip("/") in HODOU_SKIP or t.strip() in ("介護サービス情報公表システム",):
                continue
            out.append({
                "source": src["name"], "source_id": src["id"],
                "title": re.sub(r"\s+", " ", t).strip(), "org": "厚生労働省", "doc_no": None,
                "date": cur, "url": urljoin(MHLW, url), "pdf": None,
                "tags": tag_item(t), "_ym": ym,
            })
    return out


# ------------------------------------------------------------------ 网络
def fetch(url, retry=3):
    last = None
    for i in range(retry):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def month_range(years):
    now = datetime.now(JST)
    out = []
    y, m = now.year, now.month
    for _ in range(years * 12):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def collect(years=10, include_houdou=True):
    items, errors = [], []
    now = datetime.now(JST)
    cutoff = f"{now.year - years}-{now.month:02d}-01"

    for src in SOURCES:
        try:
            html = fetch(src["url"])
            if not html:
                raise RuntimeError("页面不可达")
            parser = {"wam": parse_wam, "mhlw_latestinfo": parse_mhlw_latestinfo}[src["kind"]]
            got = parser(html, src)
            got = [x for x in got if not x.get("date") or x["date"] >= cutoff]
            items.extend(got)
            print(f"[ok] {src['name']}: {len(got)} 条", file=sys.stderr)
        except Exception as e:
            errors.append({"source": src["name"], "error": repr(e)})
            print(f"[err] {src['name']}: {e}", file=sys.stderr)
        time.sleep(0.8)

    if include_houdou:
        hsrc = {"id": "mhlw_houdou", "name": "厚生労働省 報道発表資料"}
        got_n = 0
        for ym in month_range(years):
            try:
                html = fetch(HODOU_MONTH.format(ym=ym), retry=2)
                if not html:
                    continue
                got = parse_houdou(html, hsrc, ym)
                since = f"{ym[:4]}-{ym[4:6]}"
                for g in got:
                    g["date"] = g.get("date") or None
                items.extend(got)
                got_n += len(got)
            except Exception as e:
                errors.append({"source": f"報道発表 {ym}", "error": repr(e)})
            time.sleep(0.3)
        print(f"[ok] 報道発表資料（近{years}年）: {got_n} 条", file=sys.stderr)

    return items, errors


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--reset", action="store_true", help="清空归档后重建")
    ap.add_argument("--no-houdou", action="store_true", help="跳过報道発表（回溯较慢）")
    args = ap.parse_args()

    now = datetime.now(JST)
    if args.reset and os.path.exists(ITEMS_FILE):
        os.remove(ITEMS_FILE)

    raw, errors = collect(args.years, include_houdou=not args.no_houdou)

    archive = []
    if os.path.exists(ITEMS_FILE):
        with open(ITEMS_FILE, encoding="utf-8") as f:
            archive = json.load(f)
    is_bootstrap = len(archive) == 0
    known = {a["id"]: a for a in archive}

    # ---------- 本次抓取结果：按卷号归并（同卷=同一份文件，多站重复收录）
    def norm(t):
        return re.sub(r"\s", "", t or "")

    groups, passthru = {}, []
    for it in raw:
        it["id"] = item_key(it["title"], it["url"])
        it.pop("_ym", None)
        if it.get("doc_no"):
            groups.setdefault(it["doc_no"], []).append(it)
        else:
            passthru.append(it)

    merged = []
    for v, g in groups.items():
        # 权威排序：厚労省本站 > 有机关名 > 标题未被串行污染
        g.sort(key=lambda x: (x["source_id"] == "mhlw_latestinfo",
                              bool(x.get("org")),
                              _title_suspect(x, v) is False,
                              len(x.get("title") or "")), reverse=True)
        keep = dict(g[0])
        others = g[1:]
        for x in others:
            for k in ("org", "date"):
                if not keep.get(k) and x.get(k):
                    keep[k] = x[k]
        keep["alt_urls"] = sorted({x["url"] for x in others} | set(keep.get("alt_urls") or []))
        # 只将「标题开头的卷号」与本人卷号不符者判为串行（正文中的 Q&A Vol.18 属正常内容）
        def _head_vol(t):
            m = re.match(r"^\s*[○〇]?\s*介護保険最新情報\s*[Vv][Oo][Ll]\.?\s*(\d+)", t or "")
            return m.group(1) if m else None

        if any(_head_vol(x.get("title")) not in (None, str(v)) for x in others):
            keep["source_note"] = "该卷在其他数据源标题串行，已采用厚労省原文"
        keep["tags"] = tag_item(keep["title"])
        merged.append(keep)

    raw = merged + passthru

    fresh = []
    for it in raw:
        if it["id"] in known:
            old = known[it["id"]]
            for k in ("date", "org", "doc_no"):
                if not old.get(k) and it.get(k):
                    old[k] = it[k]
            continue
        it["first_seen"] = now.isoformat()
        fresh.append(it)
        known[it["id"]] = it

    archive.extend(fresh)
    archive.sort(key=lambda x: (x.get("date") or "", int(x.get("doc_no") or 0)), reverse=True)

    with open(ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)

    payload = {
        "generated_at": now.isoformat(),
        "years": args.years,
        "mode": "bootstrap" if is_bootstrap else "increment",
        "total_archived": len(archive),
        "new_count": len(fresh),
        "new_items": fresh,
        "errors": errors,
    }
    for p in (os.path.join(DATA, f"new_{now.strftime('%Y%m%d')}.json"),
              os.path.join(DATA, "latest.json")):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

    dated = [a["date"] for a in archive if a.get("date")]
    print(f"归档 {len(archive)} 条（新增 {len(fresh)}，错误 {len(errors)}）"
          f" 日期范围 {min(dated) if dated else '-'} ~ {max(dated) if dated else '-'}")


if __name__ == "__main__":
    main()
