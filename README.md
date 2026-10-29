# 日本介护政策原文库（kaigo-radar）

自动抓取、归档、检索日本厚生劳动省介护政策**原文**的工具，支持 **AI 中文摘要** 与 **GitHub Actions 免费云端每日推送**。

核心原则：原文永远一字不改。AI 的译文、摘要、重要度评分写入独立字段，在手机端以「中文摘要」标签页呈现，与日文原文并列显示、互不覆盖。

## 交付物

| 文件 | 说明 |
|---|---|
| `out/kaigo.html` | **手机端应用**（单文件）。发送到手机用浏览器打开，可添加到主屏幕当 App 用 |
| `out/summary_10y.md` | 近 10 年汇总报告（年度分布、主题分布、历年关键文件） |
| `out/daily.md` | 每日新增简报（推送正文） |
| `out/archive.csv` | 全量归档表（Excel 可直接打开） |
| `data/items.json` | 本地归档数据库 |

## 部署到 GitHub Actions（免费 7×24 运行）

1. 在 GitHub 新建一个仓库（建议 Private），把本项目全部文件推上去：

   ```bash
   git init && git add -A && git commit -m "init"
   git remote add origin https://github.com/你的用户名/kaigo-radar.git
   git push -u origin main
   ```

2. 配置 Secrets（仓库 Settings → Secrets and variables → Actions）：

   | Secret | 必填 | 说明 |
   |---|---|---|
   | `DEEPSEEK_API_KEY` | 可选 | 填了才有中文摘要；不填则只推原文，同样可用 |
   | `SERVERCHAN_KEY` | 推荐其一 | [sct.ftqq.com](https://sct.ftqq.com) 微信扫码获取，推送到微信 |
   | `BARK_URL` | 推荐其一 | iPhone 装 Bark App 复制其 URL，推送到手机通知 |
   | `WEBHOOK_URL` | 可选 | 飞书/钉钉/企微群机器人地址 |

3. 手动触发一次验证：仓库 Actions 页 → kaigo-daily → Run workflow。
   之后每天北京时间 07:00 自动运行。

4.（可选）开启 GitHub Pages（Settings → Pages → Branch 选 `gh-pages`），
   即可获得一个在线地址，手机随时打开最新版资料库，无需传文件。

## 本地运行

```bash
pip install requests

python3 run_daily.py          # 抓取 → 摘要 → 报表 → 打包 → 推送
python3 kaigo_fetch.py --years 10 --reset   # 首次/重建十年归档
```

本地运行时，环境变量或 `config.local.json`（参考 `config.example.json`）均可配置。

## AI 摘要说明（kaigo_ai.py）

- 默认使用 DeepSeek（`deepseek-chat`），兼容任何 OpenAI 格式接口：改环境变量 `AI_BASE_URL` 与 `AI_MODEL` 即可
- 每条摘要输出三样东西：`title_zh`（中文标题）、`summary_zh`（1-2 句说明这份文件实际要求什么）、`importance`（1-5 星）
- **费用控制**：结果缓存（同一文件只调用一次）+ 单次运行上限（默认 40 条）+ 首次建档自动跳过批量摘要
- **失败降级**：无 key、余额不足、网络失败时自动跳过，简报照常输出原文，主流程不受影响

## 数据源与覆盖范围

| 源 | 覆盖 | 说明 |
|---|---|---|
| WAM.NET 介护保险最新情报 | **2008 年至今全量** | 存档最全 |
| 厚労省 介护保险最新情报 | 2021 年至今 | 元数据最完整（发文机关、文号） |
| 厚労省 報道発表資料 | 2023 年至今 | 厚労省官网月度归档只保留到 2023 年 |

> 介护保险最新情报（政策通知主产地）近 10 年完整覆盖；报道发表更早年份属官方站点已下线，非遗漏。

## 每日运行时序

```
07:00 北京时间  GitHub Actions 触发
  ├─ kaigo_fetch.py    抓取 WAM + 厚労省 + 报道发表，去重后写入归档
  ├─ kaigo_ai.py       对新增条目生成中文摘要（无 key 自动跳过）
  ├─ kaigo_report.py   生成汇总 + 当日简报（按重要度排序）
  ├─ kaigo_build_app.py 重新打包手机端应用
  ├─ kaigo_push.py     推送到微信/手机
  ├─ 提交归档到仓库（版本可追溯）
  └─ 部署到 GitHub Pages（如已开启）
```

## 手机端功能

- 搜索（标题/机关/卷号/日期）、来源与主题筛选、关键词高亮
- **「日文原文 / 中文摘要」双视图切换**：原文始终可见，摘要以引用样式附加
- 重要度星级（AI 评分，★~★★★★★）
- 一键导出当前筛选结果为 CSV
- 深色模式自适应

## 数据质量保障

- **跨源去重**：同卷号自动合并，标题以厚労省原文为准，双方链接都保留
- **源头纠错留痕**：WAM 个别条目存在官方自身的标题串行错误，合并时以厚労省为准并标注
- **零误伤**：正文中的 "Q&A（Vol.18）" 等字样不会被误判为卷号串行
- **日期全覆盖**：全部记录均有日期
