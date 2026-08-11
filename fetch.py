#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
摄影周报采集器 v2
- 拉取全球 + 国内摄影 RSS/Atom 源
- 过滤近 WINDOW_DAYS 天
- 跨源关键词聚类 -> 标记「多方印证」(交叉比对)
- 语言标记(zh/en)，外文进入 latest.json 供本地翻译加工
- 输出: briefs/YYYY-MM-DD.md  +  docs/index.html (GitHub Pages)  +  briefs/latest.json
不依赖任何 API Key；图片只存 URL 不下载（省出站流量）。
"""
import json, os, sys, io, re, html, ssl, urllib.request, datetime, traceback

WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", 9))
SKIP_BEST_EFFORT = os.environ.get("SKIP_BEST_EFFORT") == "1"
ROOT = os.path.dirname(os.path.abspath(__file__))
BRIEFS = os.path.join(ROOT, "briefs")
DOCS = os.path.join(ROOT, "docs")
os.makedirs(BRIEFS, exist_ok=True)
os.makedirs(DOCS, exist_ok=True)

import feedparser  # noqa: E402

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (compatible; PhotoBriefBot/1.0)"

# ---- 交叉比对信号词：仅用「具体型号/赛事/软件名」，避免泛品牌词噪声 ----
SIGNAL_PATTERNS = [
    # 相机具体型号
    r"A7R\s?VI", r"A7\s?V", r"A1\s?II", r"Z9", r"Z8", r"Z5\b", r"Z6\s?III", r"X-T5", r"X100V?I?",
    r"X-H2", r"X\s?Pro\d?", r"EOS\s?R\d", r"R5\s?II", r"R1\b", r"OM-1", r"M11", r"Q3", r"SL3",
    r"S5\s?II", r"GH6", r"GFX\d+", r"iPhone\s?1[5-9]", r"Pocket\s?3",
    # 镜头/具体产品
    r"G\s?Master", r"100-400", r"24-70", r"25-200mm", r"35mm", r"50mm", r"85mm", r"14mm",
    r"RF\s?\d{2}", r"FE\s?\d{2}", r"X300\s?Ultra", r"Sirui", r"Tamron\s?\d",
    # 运动/影像设备
    r"Insta360", r"GoPro", r"Hero\s?\d", r"DJI", r"Mavic", r"Osmo",
    # 软件（具体名）
    r"darktable", r"GIMP", r"Lightroom", r"Capture\s?One", r"Luminar", r"Photoshop",
    r"RawTherapee", r"Krita", r"DxO", r"Affinity", r"PhotoPrism", r"ExifTool", r"Skylum", r"Topaz",
    # 赛事/活动
    r"Photokina", r"CP\+", r"World\s?Press\s?Photo", r"FIAP", r"Prix", r"Awards?",
    r"Olympic", r"Photo\s?Award",
]
SIGNAL_RE = re.compile("|".join(SIGNAL_PATTERNS), re.IGNORECASE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

CAT_TITLES = {}
with open(os.path.join(ROOT, "feeds.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CAT_TITLES = CFG.get("categories", {})


def stage(msg):
    with open(os.path.join(ROOT, "_stage.log"), "a", encoding="utf-8") as f:
        f.write(msg + "\n")
        f.flush()


def extract_signals(text):
    return {m.group(0).strip().lower() for m in SIGNAL_RE.finditer(text or "") if m.group(0).strip()}


def detect_lang(text):
    return "zh" if CJK_RE.search(text or "") else "en"


def clean(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\[\s*Read\s*More\s*\]", "", text, flags=re.I)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_feed(feed):
    req = urllib.request.Request(feed["url"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
        data = r.read()
    return feedparser.parse(data)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=WINDOW_DAYS)
    items = []
    src_ok, src_fail = [], []
    stage(f"[stage] start window={WINDOW_DAYS} feeds={len(CFG['feeds'])}")

    for feed in CFG["feeds"]:
        if feed.get("best_effort") and SKIP_BEST_EFFORT:
            continue
        stage(f"[fetch] -> {feed['name']} ({feed['url'][:60]})")
        try:
            parsed = fetch_feed(feed)
            entries = parsed.entries or []
            src_ok.append(feed["name"])
            stage(f"[ok] {feed['name']} entries={len(entries)}")
        except Exception as e:
            src_fail.append((feed["name"], str(e)[:50]))
            stage(f"[fail] {feed['name']}: {str(e)[:50]}")
            continue
        for e in entries:
            title = clean(e.get("title", ""))
            link = e.get("link", "")
            if not title or not link:
                continue
            summary = clean(e.get("summary", e.get("description", "")))[:320]
            dp = e.get("published_parsed") or e.get("updated_parsed")
            if dp:
                pub = datetime.datetime(*dp[:6], tzinfo=datetime.timezone.utc)
                if pub < cutoff:
                    continue
                date_str = pub.strftime("%Y-%m-%d")
            else:
                date_str = now.strftime("%Y-%m-%d")
            img = ""
            if e.get("media_thumbnail"):
                img = e["media_thumbnail"][0].get("url", "")
            elif e.get("media_content"):
                img = e["media_content"][0].get("url", "")
            items.append({
                "cat": feed["cat"],
                "source": feed["name"],
                "lang": detect_lang(title + " " + summary),
                "title": title,
                "summary": summary,
                "link": link,
                "date": date_str,
                "image": img,
                "signals": extract_signals(title + " " + summary),
            })

    # 去重（同链接）
    seen, uniq = set(), []
    for it in items:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        uniq.append(it)
    items = uniq

    # ---- 交叉比对：同一信号被 >=2 个不同来源命中 -> 多方印证 ----
    sig_map = {}
    for idx, it in enumerate(items):
        for s in it["signals"]:
            sig_map.setdefault(s, []).append(idx)
    verified_clusters = []
    for sig, idxs in sig_map.items():
        srcs = {items[i]["source"] for i in idxs}
        if len(srcs) >= 2:
            verified_clusters.append({"signal": sig, "sources": sorted(srcs),
                                      "titles": [items[i]["title"] for i in idxs][:4]})
            for i in idxs:
                items[i].setdefault("verified_by", set()).add(sig)
    for it in items:
        it["verified"] = bool(it.get("verified_by"))
        it["verified_signals"] = sorted(it.get("verified_by", set()))
        it.pop("verified_by", None)
        it.pop("signals", None)

    # 按分类聚合，每类取最近 15 条
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["cat"], []).append(it)
    for c in by_cat:
        by_cat[c].sort(key=lambda x: x["date"], reverse=True)
        by_cat[c] = by_cat[c][:15]

    today = now.strftime("%Y-%m-%d")
    stage(f"[stage] items={len(items)} verified={len(verified_clusters)} writing files...")
    out_md = []
    out_md.append(f"# 影像家 · 全球摄影周报 （{today}）\n")
    out_md.append(f"> 采集窗口：近 {WINDOW_DAYS} 天 ｜ 成功源 {len(src_ok)} 个 ｜ 条目 {len(items)} 条 ｜ "
                  f"多方印证 {len(verified_clusters)} 组\n")
    if verified_clusters:
        out_md.append("\n## 🔗 本周多方印证（国内外交叉比对）\n")
        for cl in sorted(verified_clusters, key=lambda x: -len(x["sources"])):
            out_md.append(f"- **{cl['signal'].upper()}**：{ '、'.join(cl['sources']) }")
    out_md.append("")

    for cat, title in CAT_TITLES.items():
        lst = by_cat.get(cat)
        if not lst:
            continue
        out_md.append(f"## {title}\n")
        for it in lst:
            flag = "🔗多方印证 " if it["verified"] else ""
            lang_tag = "【外文】" if it["lang"] == "en" else ""
            out_md.append(f"### {flag}{lang_tag}{it['title']}")
            out_md.append(f"- 来源：{it['source']} ｜ 日期：{it['date']} ｜ 语言：{it['lang']}")
            if it["summary"]:
                out_md.append(f"- 摘要：{it['summary']}")
            out_md.append(f"- 链接：{it['link']}")
            if it["image"]:
                out_md.append(f"- 图：{it['image']}")
            out_md.append("")

    md_path = os.path.join(BRIEFS, f"{today}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_md))
    # 也写 latest.md 方便 Pages 直接读
    with open(os.path.join(BRIEFS, "latest.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out_md))

    # ---- latest.json：供本地自动化翻译/加工 ----
    payload = {
        "generated_at": now.isoformat(),
        "window_days": WINDOW_DAYS,
        "source_counts": {"ok": src_ok, "failed": [s[0] for s in src_fail]},
        "total_items": len(items),
        "cross_verified": verified_clusters,
        "categories": by_cat,
    }
    with open(os.path.join(BRIEFS, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---- docs/index.html：GitHub Pages 展示页 ----
    html_out = render_html(today, len(items), src_ok, verified_clusters, by_cat)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"[OK] items={len(items)} sources_ok={len(src_ok)} verified={len(verified_clusters)}")
    print(f"[OK] wrote {md_path}")
    print(f"[FAIL] sources: {src_fail}")


def render_html(today, total, src_ok, clusters, by_cat):
    rows = ""
    if clusters:
        rows += "<h2>🔗 本周多方印证（国内外交叉比对）</h2><ul>"
        for cl in sorted(clusters, key=lambda x: -len(x["sources"])):
            rows += f"<li><b>{html.escape(cl['signal'].upper())}</b>：{html.escape('、'.join(cl['sources']))}</li>"
        rows += "</ul>"
    for cat, title in CAT_TITLES.items():
        lst = by_cat.get(cat)
        if not lst:
            continue
        rows += f"<h2>{html.escape(title)}</h2><div class='grid'>"
        for it in lst:
            badge = "<span class='v'>🔗多方印证</span>" if it["verified"] else ""
            lang = "<span class='en'>外文</span>" if it["lang"] == "en" else ""
            img = f"<img src='{html.escape(it['image'])}'/>" if it["image"] else ""
            rows += (f"<div class='card'>{img}<div class='t'>{badge}{lang}{html.escape(it['title'])}</div>"
                     f"<div class='m'>{html.escape(it['source'])} · {html.escape(it['date'])}</div>"
                     f"<div class='s'>{html.escape(it['summary'])}</div>"
                     f"<a href='{html.escape(it['link'])}' target='_blank'>阅读原文 ↗</a></div>")
        rows += "</div>"
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>影像家 · 全球摄影周报 {today}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,'PingFang SC','Microsoft YaHei',sans-serif;max-width:1080px;margin:0 auto;padding:24px;background:#0f1115;color:#e8eaed}}
h1{{font-size:26px}}h2{{font-size:20px;margin-top:32px;border-left:4px solid #4f8cff;padding-left:10px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:14px}}
.card{{background:#1a1d23;border:1px solid #2a2e36;border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:6px}}
.card img{{width:100%;height:160px;object-fit:cover;border-radius:8px;background:#000}}
.t{{font-weight:600;font-size:15px}} .m{{color:#9aa0a6;font-size:12px}} .s{{color:#c4c7cc;font-size:13px;line-height:1.5}}
a{{color:#4f8cff;text-decoration:none;font-size:13px}} .v{{color:#ffb74d;font-size:12px;margin-right:6px}} .en{{color:#7ee787;font-size:12px;margin-right:6px}}
.meta{{color:#9aa0a6;font-size:13px}}
</style></head><body>
<h1>📸 影像家 · 全球摄影周报</h1>
<p class="meta">更新日期 {today} ｜ 共 {total} 条 ｜ 成功源 {len(src_ok)} 个 ｜ 多方印证 {len(clusters)} 组 ｜ 数据来自公开 RSS，自动采集</p>
{rows}
<footer class="meta" style="margin-top:40px;border-top:1px solid #2a2e36;padding-top:14px">
由 GitHub Actions 每周自动采集全球摄影资讯；外文条目将在社群分享前翻译为中文。影像家摄影俱乐部 · x-tap.cloud</footer>
</body></html>"""


if __name__ == "__main__":
    try:
        main()
    except Exception:
        with open(os.path.join(ROOT, "_run_error.log"), "w", encoding="utf-8") as _f:
            _f.write(traceback.format_exc())
        raise
