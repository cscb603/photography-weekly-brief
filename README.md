# 摄影周报 · Photography Weekly Brief

每周自动采集**全球摄影媒体**的最新动态，生成一份结构化简报，并发布到 GitHub Pages 公开展示页。

- 🌐 **简报展示页**：`https://cscb603.github.io/photography-weekly-brief/`
- 🗂 **原始简报（Markdown）**：`briefs/YYYY-MM-DD.md`
- ⚙️ **生成逻辑**：`.github/workflows/weekly.yml` 每周一（北京时间）自动运行 `fetch.py`

## 它做什么

1. 从 `feeds.json` 维护的全球摄影 RSS/Atom 源拉取内容；
2. 过滤**近 7 天**动态、去重、按板块归类；
3. 生成：
   - `briefs/YYYY-MM-DD.md` —— 给人/策展阅读的结构化简报；
   - `docs/index.html` —— GitHub Pages 公开展示页；
   - `docs/latest.json` —— 机器可读的最新一期。

> 图片只收录原始链接（URL），**不下载**，因此几乎不产生出站流量与存储成本。

## 板块

| 板块 | 内容 |
| --- | --- |
| 📰 本周新鲜事（器材 / 行业） | 新机、新镜、行业动向 |
| 🌍 全球开眼（摄影师 / 展览 / 经典） | 大师、展览、经典作品 |
| 📚 共读 / 深度 | 长文、观点、技术随笔 |
| 🏆 赛事 / 征稿 | 比赛、征集、奖项 |
| 🎙 访谈 / 幕后 | 摄影师专访、创作幕后 |

## 怎么用

- **看简报**：直接打开上面的展示页，或读 `briefs/` 下最新的 Markdown。
- **加源**：编辑 `feeds.json`，加一项 `{ "name": "...", "url": "...", "category": "...", "lang": "en|zh" }`，提交即可生效。
- **手动跑一次**：在仓库 Actions 页面点 `Weekly Photo Brief` → `Run workflow`。
- **做微信群分享**：由策展流程把简报二次加工为口语化分享文案（链接可达性核对 + 品牌调性润色）。

## 本地运行

```bash
pip install feedparser requests
python fetch.py
```

## 说明

本仓库仅做**信息索引与聚合**，所有内容版权归原作者所有，链接均直达原文。
