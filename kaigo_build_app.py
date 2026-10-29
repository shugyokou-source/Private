# -*- coding: utf-8 -*-
"""kaigo_build_app.py — 把归档数据打包成单文件手机应用（PWA）"""

import json
import os
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")


def main():
    with open(os.path.join(DATA, "items.json"), encoding="utf-8") as f:
        items = json.load(f)

    slim = [{
        "d": x.get("date"), "t": x["title"], "v": x.get("doc_no"),
        "o": x.get("org") or "", "u": x["url"], "a": x.get("alt_urls") or [],
        "g": x.get("tags") or [], "s": x["source"], "n": x.get("source_note") or "",
        "tz": x.get("title_zh") or "", "sz": x.get("summary_zh") or "",
        "im": x.get("importance") or 0,
    } for x in items]

    tpl_path = os.path.join(ROOT, "templates", "app.html")
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()

    dated = [x["d"] for x in slim if x.get("d")]
    payload = {
        "items": slim,
        "meta": {
            "total": len(slim),
            "from": min(dated) if dated else "",
            "to": max(dated) if dated else "",
            "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }

    html = (tpl.replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
               .replace("__BUILT__", payload["meta"]["built"])
               .replace("__TOTAL__", str(payload["meta"]["total"])))

    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, "kaigo.html")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已生成 {dst}（{len(html)/1024:.0f} KB，{len(slim)} 条）")
    return dst


if __name__ == "__main__":
    main()
