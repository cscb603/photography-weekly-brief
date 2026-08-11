#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
摄影周报采集器
- 读取 feeds.json 中的全球摄影 RSS/Atom 源
- 拉取 -> 过滤近 N 天 -> 去重 -> 按板块生成
  * briefs/YYYY-MM-DD.md   （给策展/人工阅读）
  * docs/index.html        （GitHub Pages 公开展示页）
- 图片只收录 URL，不下载（省出站、省存储）
- 每个源独立容错，单个失败不影响整体
"""
import json
import os
import re
import sys
import calendar
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
FEEDS_PATH = os.path.join(REPO_ROOT, "feeds.json")
BRIEFS_DIR = os.path.join(REPO_ROOT, "briefs")
DOCS_DIR = os.path.join(REPO_ROOT, "docs")

CATEGORY_TITLES = {
    "gear_industry": "\U0001F4F0 本周新鲜事（器材 / 行业）",
    "global_eye": "\U0001F30D 全球开眼（摄影师 / 展览 / 经典）",
    "reading_depth": "\U0001F4DA 共读 / 深度",
    "contests": "\U0001F3C6 赛事 / 征稿",
    "interviews": "\U0001F399 访谈 / 幕后",
}
CATEGORY_ORDER = ["gear_industry", "global_eye", "reading_depth", "contests", "interviews"]

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def strip_tags(s):
    if not s:
        return ""
    s = TAG_RE.sub(" ", s)
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    s = CTRL_RE.sub("", s)
    return WS_RE.sub(" ", s).strip()


def parse_date(entry):
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime.fromtimestamp(calendar.timegm(val), tz=timezone.utc)
            except Exception:
                pass
    for key in ("published", "updated", "created"):
        s = entry.get(key)
        if s:
            try:
                dt = parsedate_to_datetime(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None


def fetch_feed(src):
    name = src.get("name", src.get("url"))
    try:
        d = feedparser.parse(src["url"], agent=UA)
        if d.bozo and not d.entries:
            import requests
            r = requests.get(src["url"], headers={"User-Agent": UA}, timeout=25)
            r.raise_for_status()
            d = feedparser.parse(r.content)
        return d
    except Exception as e:
        print(f"[WARN] feed failed {name}: {e}", file=sys.stderr)
        return None


def main():
    with open(FEEDS_PATH, encoding="utf-8") as f:
        config = json.load(f)
    window = int(config.get("window_days", 7))
    feeds = config.get("feeds", [])

    now_utc = datetime.now(timezone.utc)
    # 北京日期，用于文件名与标题（用户在中国时区）
    now_cst = now_utc + timedelta(hours=8)
    date_str = now_cst.strftime("%Y-%m-%d")
    cutoff = now_utc - timedelta(days=window)

    collected = {cat: [] for cat in CATEGORY_ORDER}
    seen = set()
    per_feed_count = {}

    for src in feeds:
        cat = src.get("category", "gear_industry")
        if cat not in collected:
            cat = "gear_industry"
        d = fetch_feed(src)
        if not d:
            continue
        cap = int(src.get("max", 10))
        n = 0
        for e in d.entries:
            link = (e.get("link") or "").strip()
            if not link:
                continue
            if link in seen:
                continue
            date = parse_date(e)

            # 时间窗过滤：有日期且早于 cutoff 则跳过；无日期的保留（兜底）
            if date and date < cutoff:
                continue

            title = strip_tags(e.get("title", "(无标题)")).strip() or "(无标题)"
            summary = ""
            for k in ("summary", "description", "content"):
                v = e.get(k)
                if isinstance(v, list):
                    v = " ".join(x.get("value", "") for x in v if isinstance(x, dict))
                if v:
                    summary = strip_tags(v)
                    break
            summary = summary[:300]
            summary = re.sub(r"\[\s*Read More\s*\]", "", summary, flags=re.I)
            summary = re.sub(r"\s+", " ", summary).strip().rstrip(".…")

            img = ""
            for k in ("media_content", "media_thumbnail"):
                m = e.get(k)
                if isinstance(m, list) and m and isinstance(m[0], dict) and m[0].get("url"):
                    img = m[0]["url"]
                    break
            if not img:
                m = e.get("enclosure")
                if isinstance(m, list):
                    for x in m:
                        if isinstance(x, dict) and x.get("type", "").startswith("image"):
                            img = x.get("url", "")
                            break

            collected[cat].append({
                "title": title,
                "link": link,
                "source": src.get("name", ""),
                "lang": src.get("lang", "en"),
                "date": date.strftime("%Y-%m-%d") if date else "",
                "summary": summary,
                "img": img,
            })
            seen.add(link)
            n += 1
            if n >= cap:
                break
        per_feed_count[src.get("name", src["url"])] = n

    for cat in collected:
        collected[cat].sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)

    os.makedirs(BRIEFS_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    md = render_markdown(collected, date_str, now_utc, window)
    md_path = os.path.join(BRIEFS_DIR, f"{date_str}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    html = render_html(collected, date_str, now_utc, window)
    html_path = os.path.join(DOCS_DIR, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 同时写一份 latest.json 供程序读取
    with open(os.path.join(DOCS_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({
            "date": date_str,
            "generated_utc": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
            "sections": {c: collected[c] for c in CATEGORY_ORDER},
        }, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in collected.values())
    print(f"[OK] brief {date_str}: {total} items across {len(feeds)} feeds")
    for src, c in per_feed_count.items():
        print(f"     - {src}: {c}")


def render_markdown(collected, date_str, now_utc, window):
    lines = []
    lines.append(f"# 摄影周报 · {date_str}")
    lines.append("")
    lines.append(f"> 自动采集自全球摄影媒体，汇总近 **{window} 天**动态。链接均直达原文，图片仅收录地址不下载。")
    lines.append(f"> 生成时间（UTC）：{now_utc.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    for cat in CATEGORY_ORDER:
        items = collected[cat]
        if not items:
            continue
        lines.append(f"## {CATEGORY_TITLES[cat]}")
        lines.append("")
        for it in items:
            meta = it["source"]
            if it["date"]:
                meta += f" · {it['date']}"
            if it["lang"] == "zh":
                meta += " · 中文"
            lines.append(f"- **[{it['title']}]({it['link']})** — {meta}")
            if it["summary"]:
                lines.append(f"  {it['summary']}")
            lines.append("")
    return "\n".join(lines)


def render_html(collected, date_str, now_utc, window):
    sections = []
    total = 0
    for cat in CATEGORY_ORDER:
        items = collected[cat]
        total += len(items)
        if not items:
            continue
        cards = []
        for it in items:
            img_html = (f'<div class="thumb"><a href="{it["link"]}" target="_blank" '
                        f'rel="noopener"><img loading="lazy" src="{it["img"]}" alt=""></a></div>'
                        ) if it["img"] else ""
            meta = it["source"]
            if it["date"]:
                meta += f" · {it['date']}"
            cards.append(f"""
      <article class="card">
        {img_html}
        <div class="body">
          <h3><a href="{it['link']}" target="_blank" rel="noopener">{it['title']}</a></h3>
          <div class="meta">{meta}</div>
          <p>{it['summary']}</p>
        </div>
      </article>""")
        sections.append(f"""
    <section>
      <h2>{CATEGORY_TITLES[cat]}</h2>
      <div class="grid">{''.join(cards)}</div>
    </section>""")
    body = "".join(sections) if sections else '<p class="empty">本周暂无近 %d 天内容。</p>' % window
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>摄影周报 · {date_str}</title>
<style>
  :root {{ --bg:#0f1115; --card:#171a21; --fg:#e8eaed; --mut:#9aa0a6; --acc:#f5a623; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
    line-height:1.6; }}
  header {{ padding:28px 20px 8px; max-width:980px; margin:0 auto; }}
  header h1 {{ margin:0 0 6px; font-size:26px; }}
  header .sub {{ color:var(--mut); font-size:13px; }}
  main {{ max-width:980px; margin:0 auto; padding:12px 20px 60px; }}
  section {{ margin-top:30px; }}
  h2 {{ font-size:19px; border-left:4px solid var(--acc); padding-left:10px; margin:0 0 14px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }}
  .card {{ background:var(--card); border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }}
  .thumb img {{ width:100%; height:160px; object-fit:cover; display:block; background:#222; }}
  .body {{ padding:12px 14px 16px; }}
  .body h3 {{ margin:0 0 6px; font-size:15px; line-height:1.4; }}
  .body h3 a {{ color:var(--fg); text-decoration:none; }}
  .body h3 a:hover {{ color:var(--acc); }}
  .meta {{ color:var(--mut); font-size:12px; margin-bottom:6px; }}
  .body p {{ margin:0; font-size:13px; color:#cfd3d8; }}
  .empty {{ color:var(--mut); }}
  footer {{ max-width:980px; margin:0 auto; padding:20px; color:var(--mut); font-size:12px; }}
</style>
</head>
<body>
<header>
  <h1>摄影周报 · {date_str}</h1>
  <div class="sub">自动采集自全球摄影媒体 · 近 {window} 天 · 共 {total} 条 · 生成于 {now_utc.strftime('%Y-%m-%d %H:%M UTC')}</div>
</header>
<main>{body}</main>
<footer>由 GitHub Actions 每周自动生成 · 图片版权归原作者所有，仅作索引。</footer>
</body>
</html>"""


if __name__ == "__main__":
    main()
