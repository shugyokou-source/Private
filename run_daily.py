# -*- coding: utf-8 -*-
"""run_daily.py — 每日流水线：抓取 → AI摘要 → 报表 → 打包 → 推送

环境变量（GitHub Actions 里用 Secrets 注入）：
  DEEPSEEK_API_KEY   可选，不填则跳过摘要，简报仍输出原文
  BARK_URL / SERVERCHAN_KEY / WEBHOOK_URL / SMTP_*   任选其一作为推送通道
  AI_ENRICH_MAX      单次最多调用 AI 的条数，默认 40（控制费用）
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)


def run(script, args=None):
    print(f"\n===== {script} {' '.join(args or [])} =====", flush=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, script)] + (args or []))
    if r.returncode != 0:
        print(f"[warn] {script} 退出码 {r.returncode}")
    return r.returncode


def enrich():
    """给本次新增条目补充中文摘要（失败不影响主流程）"""
    import json
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location("kaigo_ai", os.path.join(ROOT, "kaigo_ai.py"))
        ai = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ai)
    except Exception as e:
        print(f"[ai] 模块加载失败，跳过：{e}")
        return

    latest_path = os.path.join(ROOT, "data", "latest.json")
    if not os.path.exists(latest_path):
        return
    with open(latest_path, encoding="utf-8") as f:
        payload = json.load(f)

    items = payload.get("new_items") or []
    if not items:
        return
    if payload.get("mode") == "bootstrap":
        print("[ai] 首次建档模式，跳过批量摘要（避免上千条调用产生大量费用）。")
        return

    max_calls = int(os.environ.get("AI_ENRICH_MAX", "40"))
    ai.summarize(items, max_calls=max_calls)

    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    run("kaigo_fetch.py")
    enrich()
    run("kaigo_report.py")
    run("kaigo_build_app.py")
    run("kaigo_push.py")
    print("\n全部完成。")
