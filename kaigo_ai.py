# -*- coding: utf-8 -*-
"""
kaigo_ai.py — 中文摘要与翻译（DeepSeek / 任意 OpenAI 兼容接口）

设计原则（重要）：
  · 摘要结果**写入独立字段** summary_zh / title_zh，永不覆盖原文 title
  · 原文标题、发文机关、文号、链接保持一字不改
  · 无 API key 或调用失败时自动降级：不生成摘要，简报仍按原文照常输出
  · 结果缓存到 data/summary_cache.json，同一文件只调用一次，节省费用
"""

import hashlib
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
CACHE_FILE = os.path.join(DATA, "summary_cache.json")

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是日本介护政策领域的中文情报分析员。用户会给你一份日本厚生劳动省文件的日文标题和发文机关。

任务：
1. title_zh：把标题准确译为中文。专有名词按日本官方中文惯用译法（如「介護保険」→「介护保险」、「要介護認定」→「需要介护认定」、「介護報酬」→「介护报酬」、「地域包括支援センター」→「地区综合支援中心」）。保留 Vol. 编号。
2. summary_zh：用 1-2 句中文说明这份文件**实际要求什么、影响谁**，40-90 字。不要复述标题，不要评价，不要编造标题里没有的事实。
3. importance：1-5 的整数。5=介护报酬改定/法律修订等重大制度变化；4=重要通知、要件变更；3=常规通知；2=事务性联络；1=会议通知、宣传、表彰等。

只输出 JSON，不要任何其他文字：
{"title_zh":"...","summary_zh":"...","importance":3}"""


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(c):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


def _key(item):
    raw = f"{item.get('title','')}|{item.get('org','')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _call(api_key, base, model, item, timeout=45):
    lines = [f"标题：{item['title']}",
             f"发文机关：{item.get('org') or '（页面未标注）'}",
             f"日期：{item.get('date') or ''}"]
    if item.get("doc_no"):
        lines.append(f"文号：Vol.{item['doc_no']}")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(f"{base.rstrip('/')}/chat/completions",
                      headers={"Authorization": f"Bearer {api_key}",
                               "Content-Type": "application/json"},
                      json=body, timeout=timeout)
    if r.status_code == 401:
        raise RuntimeError("API key 无效（401）")
    if r.status_code == 402:
        raise RuntimeError("账户余额不足（402）")
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError(f"返回非 JSON：{txt[:120]}")
    d = json.loads(m.group(0))
    return {
        "title_zh": str(d.get("title_zh", "")).strip(),
        "summary_zh": str(d.get("summary_zh", "")).strip(),
        "importance": int(d.get("importance", 3)) if str(d.get("importance", 3)).isdigit() else 3,
    }


def summarize(items, min_importance=1, max_calls=40, verbose=True):
    """为条目补 summary_zh / title_zh / importance。原地修改并返回统计。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY") or _cfg().get("deepseek_api_key", "")
    base = os.environ.get("AI_BASE_URL") or _cfg().get("ai_base_url") or DEFAULT_BASE
    model = os.environ.get("AI_MODEL") or _cfg().get("ai_model") or DEFAULT_MODEL

    if not api_key:
        if verbose:
            print("[ai] 未配置 DEEPSEEK_API_KEY，跳过摘要（简报仍输出原文）。", file=sys.stderr)
        return {"used": 0, "cached": 0, "failed": 0, "skipped": True}

    cache = load_cache()
    stats = {"used": 0, "cached": 0, "failed": 0, "skipped": False}
    calls = 0
    for it in items:
        k = _key(it)
        if k in cache:
            it.update(cache[k])
            stats["cached"] += 1
            continue
        if calls >= max_calls:
            continue
        # 只对有一定重要性的条目调用，省费用；但标题级全部处理
        try:
            res = _call(api_key, base, model, it)
            it.update(res)
            cache[k] = res
            stats["used"] += 1
            calls += 1
            time.sleep(0.35)   # 温和限速
        except Exception as e:
            stats["failed"] += 1
            if verbose:
                print(f"[ai-fail] {e} ← {it['title'][:40]}", file=sys.stderr)
            if stats["failed"] >= 3 and stats["used"] == 0:
                print("[ai] 连续失败，本轮放弃摘要。", file=sys.stderr)
                break

    save_cache(cache)
    if verbose:
        print(f"[ai] 新摘要 {stats['used']}，缓存命中 {stats['cached']}，失败 {stats['failed']}",
              file=sys.stderr)
    return stats


def _cfg():
    p = os.path.join(ROOT, "config.local.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}
