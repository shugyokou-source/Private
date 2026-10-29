# -*- coding: utf-8 -*-
"""
kaigo_push.py — 把原文简报推送到手机

通道（任选其一，配好就用，未配置自动跳过）：
  · bark        iPhone，装 Bark App 后拿到一个 URL，最快最简单
  · serverchan  微信推送（Server酱），扫码绑定微信，微信内直接收
  · webhook     飞书/钉钉/企业微信群机器人，群里收消息
  · email      SMTP 邮件，手机上邮件 App 收

正文只含原文标题与官方链接，不含任何改写内容。
"""

import json
import os
import re
import smtplib
import sys
import ssl
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config():
    """优先读 config.local.json（不入版本库），其次环境变量"""
    cfg = {}
    p = os.path.join(ROOT, "config.local.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    for k in ("BARK_URL", "SERVERCHAN_KEY", "WEBHOOK_URL", "SMTP_HOST", "SMTP_PORT",
              "SMTP_USER", "SMTP_PASS", "MAIL_TO"):
        if os.environ.get(k):
            cfg[k.lower()] = os.environ[k]
    return cfg


# ------------------------------------------------------------------ 各通道
def push_bark(cfg, title, body):
    url = cfg["bark_url"].rstrip("/")
    # Bark 用标题做推送标题，正文限制长度，超长自动转为分隔形式
    r = requests.post(f"{url}/{requests.utils.quote(title)}",
                      data={"body": body[:3000], "group": "介护政策",
                            "icon": "", "level": "active", "isArchive": 1},
                      timeout=20)
    r.raise_for_status()
    return "bark"


def push_serverchan(cfg, title, body):
    key = cfg["serverchan_key"]
    r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                      data={"title": title[:32], "desp": body}, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"Server酱返回：{j}")
    return "serverchan"


def push_webhook(cfg, title, body):
    """飞书 / 钉钉 / 企业微信机器人通用"""
    url = cfg["webhook_url"]
    payload = {"msgtype": "text", "text": {"content": f"{title}\n\n{body}"}}
    if "open.feishu.cn" in url:
        payload = {"msg_type": "text", "content": {"text": f"{title}\n\n{body}"}}
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()
    return "webhook"


def push_email(cfg, title, attachment_path=None):
    msg = MIMEText(_html_body(attachment_path), "html", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = formataddr(("介护政策监测", cfg["smtp_user"]))
    msg["To"] = cfg["mail_to"]

    host, port = cfg["smtp_host"], int(cfg.get("smtp_port", 465))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(cfg["smtp_user"], cfg["smtp_pass"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(cfg["smtp_user"], cfg["smtp_pass"])
            s.send_message(msg)
    return "email"


def _html_body(md_path):
    """邮件用 HTML，保留原文链接可点击"""
    if not md_path or not os.path.exists(md_path):
        return "<p>（无内容）</p>"
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    esc = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    esc = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', esc)
    esc = re.sub(r"^### (.*)$", r"<h3>\1</h3>", esc, flags=re.M)
    esc = re.sub(r"^## (.*)$", r"<h2>\1</h2>", esc, flags=re.M)
    esc = re.sub(r"^# (.*)$", r"<h1>\1</h1>", esc, flags=re.M)
    esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
    esc = re.sub(r"^- (.*)$", r"<li>\1</li>", esc, flags=re.M)
    esc = esc.replace("\n\n", "<br><br>").replace("\n", "<br>")
    return f"<div style='font-family:-apple-system,sans-serif;line-height:1.7'>{esc}</div>"


# ------------------------------------------------------------------ 主流程
def push(title, body, md_path=None):
    cfg = load_config()
    done, fails = [], []
    for name, fn in (("bark", lambda c: push_bark(c, title, body)),
                     ("serverchan", lambda c: push_serverchan(c, title, body)),
                     ("webhook", lambda c: push_webhook(c, title, body)),
                     ("email", lambda c: push_email(c, title, md_path))):
        if not any(k.startswith(name) for k in cfg):
            continue
        try:
            fn(cfg)
            done.append(name)
        except Exception as e:
            fails.append(f"{name}: {e}")
    if not done and not fails:
        print("未配置任何推送通道，仅生成本地文件。见 README 配置说明。", file=sys.stderr)
    for f in fails:
        print(f"[push-fail] {f}", file=sys.stderr)
    return done


if __name__ == "__main__":
    md = os.path.join(ROOT, "out", "daily.md")
    if not os.path.exists(md):
        raise SystemExit("请先运行 kaigo_report.py")
    with open(md, encoding="utf-8") as f:
        text = f.read()
    first = text.split("\n")[0].lstrip("# ").strip()
    ok = push(first, text, md)
    print("推送成功通道:", ok or "无")
