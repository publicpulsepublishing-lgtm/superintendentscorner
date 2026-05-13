#!/usr/bin/env python3
"""
fetch_news.py  -  Superintendent's Corner auto-update script
Runs twice daily via GitHub Actions. Fetches RSS feeds, categorises
articles, and injects them into the correct section on the news page
so the category filters work properly.
"""

import re, json, os, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import feedparser
except ImportError:
    os.system("pip install feedparser --quiet --break-system-packages")
    import feedparser

SITE_DIR = Path(__file__).parent
MAX_AGE_DAYS = 14
TICKER_COUNT       = 8
SIDEBAR_COUNT      = 5
ARTICLE_GRID_COUNT = 6
NEWS_PER_SECTION   = 3

RSS_FEEDS = [
    ("EdWeek",         "https://www.edweek.org/feeds/rss/latest",            "Leadership"),
    ("The 74",         "https://www.the74million.org/feed/",                  "Policy & Legislation"),
    ("Chalkbeat",      "https://www.chalkbeat.org/arc/outboundfeeds/rss/",   "Budget & Finance"),
    ("EdSource",       "https://edsource.org/feed",                           "Budget & Finance"),
    ("District Admin", "https://districtadministration.com/feed/",           "Leadership"),
    ("Education Dive", "https://www.educationdive.com/feeds/news/",          "Policy & Legislation"),
    ("EdSurge",        "https://www.edsurge.com/feed",                       "Technology & AI"),
    ("K12 Dive",       "https://www.educationdive.com/topic/k-12/feed/",     "Policy & Legislation"),
    ("AASA News",      "https://www.aasa.org/news/rss/",                     "Leadership"),
]

CATEGORY_KEYWORDS = {
    "Technology & AI": [
        "ai", "artificial intelligence", "technology", "tech", "edtech",
        "digital", "computer", "software", "cyber", "robot", "chatgpt",
        "machine learning", "data", "online learning", "virtual",
    ],
    "Budget & Finance": [
        "budget", "finance", "fund", "levy", "million", "billion", "deficit",
        "tax", "bond", "fiscal", "revenue", "layoff", "cut", "spending",
        "grant", "allocation", "shortage", "salary",
    ],
    "School Safety": [
        "safety", "safe", "gun", "shooting", "mental health", "bullying",
        "threat", "security", "violence", "crisis", "lockdown", "drug",
        "abuse", "harassment", "vaping", "wellness",
    ],
    "Infrastructure": [
        "infrastructure", "facility", "facilities", "building", "construction",
        "repair", "renovation", "bond measure", "maintenance", "demolish",
        "playground", "classroom", "heating", "cooling", "asbestos",
    ],
    "Policy & Legislation": [
        "policy", "law", "legislation", "bill", "congress", "senate",
        "governor", "regulation", "mandate", "federal", "state", "rule",
        "ban", "court", "lawsuit", "department of education", "title",
    ],
    "Leadership": [
        "superintendent", "principal", "administrator", "leader", "hire",
        "resign", "appointed", "school board", "board meeting", "director",
        "executive", "interim",
    ],
}

# (gradient-rgba, unsplash-id, tag-hex, data-section)
CATEGORY_STYLE = {
    "Technology & AI":      ("rgba(14,107,120",  "1516321318423-f06f85e504b3", "#0E6B78", "tech"),
    "Budget & Finance":     ("rgba(123,63,0",    "1554224155-6726b3ff858f",   "#7B3F00", "budget"),
    "School Safety":        ("rgba(42,92,63",    "1509062522246-3755977927d7","#2A5C3F", "safety"),
    "Infrastructure":       ("rgba(139,58,42",   "1562774053-701939374585",   "#8B3A2A", "infra"),
    "Policy & Legislation": ("rgba(59,45,130",   "1541872703-74c5e44368f9",   "#3B2D82", "policy"),
    "Leadership":           ("rgba(11,37,69",    "1507003211169-0a1dd7228f2d","#0B2545", "leader"),
}

def categorise(title, summary):
    text = (title + " " + (summary or "")).lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in text for k in kws):
            return cat
    return "Leadership"

def parse_date(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc) - timedelta(days=7)

def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def truncate(text, n=220):
    text = strip_html(text)
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."

def fmt_date(dt):    return dt.strftime("%B %-d, %Y")
def fmt_short(dt):   return dt.strftime("%b %-d, %Y")

def inject(html, start, end, content):
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    replacement = start + "\n" + content + "\n          " + end
    result, n = pat.subn(replacement, html)
    if n == 0:
        print(f"  WARNING: marker not found: {start}")
    return result

def img_style(cat, w=500, h=240, card_h=120):
    col, photo, _, _ = CATEGORY_STYLE.get(cat, CATEGORY_STYLE["Leadership"])
    return (f"height:{card_h}px;background:linear-gradient({col},0.55),{col},0.7)),"
            f"url('https://images.unsplash.com/photo-{photo}?w={w}&h={h}&fit=crop') center/cover;")

def hero_style(cat):
    col, photo, _, _ = CATEGORY_STYLE.get(cat, CATEGORY_STYLE["Leadership"])
    return (f"background:linear-gradient({col},0.6),{col},0.75)),"
            f"url('https://images.unsplash.com/photo-{photo}?w=700&h=400&fit=crop') center/cover;")

# ── FETCH ──────────────────────────────────────────────────────────────────

def fetch_all():
    cutoff    = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    seen_path = SITE_DIR / "seen_articles.json"
    seen      = set(json.loads(seen_path.read_text()) if seen_path.exists() else [])
    articles  = []

    for feed_name, url, _ in RSS_FEEDS:
        print(f"  Fetching {feed_name}...")
        try:
            d = feedparser.parse(url, request_headers={
                "User-Agent": "Mozilla/5.0 (compatible; SuperintendentsCornerBot/1.0)"
            })
            for entry in d.entries[:30]:
                link = getattr(entry, "link", None)
                if not link or link in seen:
                    continue
                pub = parse_date(entry)
                if pub < cutoff:
                    continue
                title   = strip_html(getattr(entry, "title", ""))
                summary = strip_html(getattr(entry, "summary", ""))
                if len(title) < 20:
                    continue
                cat = categorise(title, summary)
                _, _, tag_hex, data_section = CATEGORY_STYLE[cat]
                articles.append({
                    "url":          link,
                    "title":        title,
                    "summary":      truncate(summary),
                    "source":       feed_name,
                    "date":         pub.isoformat(),
                    "date_fmt":     fmt_date(pub),
                    "date_short":   fmt_short(pub),
                    "cat":          cat,
                    "tag_hex":      tag_hex,
                    "data_section": data_section,
                })
        except Exception as e:
            print(f"    WARNING {feed_name}: {e}")

    seen_urls = set()
    unique = []
    for a in sorted(articles, key=lambda x: x["date"], reverse=True):
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)

    seen_path.write_text(json.dumps(list(seen | seen_urls)[-5000:]))
    print(f"  -> {len(unique)} fresh articles")
    return unique

# ── GENERATORS ─────────────────────────────────────────────────────────────

def gen_ticker(articles):
    links = "\n      ".join(
        f'<a href="{a["url"]}" target="_blank">{a["title"]}</a>'
        for a in articles[:TICKER_COUNT]
    )
    # Duplicate for seamless CSS scroll loop
    return links + "\n      <!-- loop duplicate -->\n      " + links

def gen_alert(articles):
    if not articles:
        return '\n  <strong>Breaking:</strong>&nbsp; Latest K-12 education news — updated twice daily.\n'
    a = articles[0]
    return (f'\n  <strong>Breaking:</strong>&nbsp; {a["title"]} &nbsp;·&nbsp;\n'
            f'  <a href="{a["url"]}" target="_blank">Read the story &rarr;</a>\n')

def gen_hero_lead(a):
    return f'''<div class="hero-main">
        <a href="{a["url"]}" target="_blank" style="text-decoration:none;display:block;" class="hero-image-link">
        <div class="hero-image">
          <div class="hero-image-pattern"></div>
          <div class="hero-topic-pill">{a["cat"]}</div>
          <div class="hero-source-tag">
            <strong>{a["source"]}</strong>
            <span>{a["date_fmt"]}</span>
          </div>
        </div>
        </a>
        <div class="hero-content">
          <div class="section-label">Lead Story</div>
          <h1 class="hero-headline">{a["title"]}</h1>
          <p class="hero-deck">{a["summary"]}</p>
          <div class="hero-meta">
            <span>{a["source"]}</span>
            <div class="dot"></div>
            <span>{a["date_fmt"]}</span>
          </div>
          <a href="{a["url"]}" target="_blank" class="read-btn">Read Full Story at {a["source"]} &rarr;</a>
        </div>
      </div>'''

def gen_hero_sidebar(articles):
    stories = ""
    for a in articles[:SIDEBAR_COUNT]:
        stories += f'''
        <a href="{a["url"]}" target="_blank" class="sidebar-story">
          <span class="sidebar-tag">{a["cat"]}</span>
          <span class="sidebar-title">{a["title"]}</span>
          <div class="sidebar-byline"><span>{a["source"]}</span><div class="dot"></div><span>{a["date_short"]}</span></div>
        </a>'''
    return f'''<div class="hero-sidebar">
        <div class="sidebar-header">
          <h3>More Stories</h3>
          <span>Updated daily</span>
        </div>{stories}
      </div>'''

def gen_article_cards(articles):
    cards = []
    for a in articles[1:ARTICLE_GRID_COUNT + 1]:
        col, photo, _, _ = CATEGORY_STYLE.get(a["cat"], CATEGORY_STYLE["Leadership"])
        style = (f"height:140px;background:linear-gradient({col},0.6),{col},0.75)),"
                 f"url('https://images.unsplash.com/photo-{photo}?w=500&h=280&fit=crop') center/cover;")
        cards.append(f'''          <a href="{a["url"]}" target="_blank" class="article-card">
            <div class="article-card-img" style="{style}"></div>
            <div class="article-card-body">
              <div class="article-tag">{a["cat"]}</div>
              <div class="article-title">{a["title"]}</div>
              <p class="article-excerpt">{a["summary"]}</p>
            </div>
            <div class="article-footer">
              <span class="article-source">{a["source"]} &middot; {a["date_short"]}</span>
              <span class="article-link">Read &rarr;</span>
            </div>
          </a>''')
    return "\n".join(cards)

def gen_section_cards(articles, data_section):
    """New cards prepended into a specific category section on news.html."""
    matching = [a for a in articles if a["data_section"] == data_section][:NEWS_PER_SECTION]
    if not matching:
        return ""
    cards = []
    for a in matching:
        style = img_style(a["cat"])
        cards.append(f'''          <a href="{a["url"]}" target="_blank" class="art-card" data-topic="{a["data_section"]}">
            <div class="art-card-img" style="{style}"></div>
            <div class="art-card-body">
              <span class="art-tag" style="color:{a["tag_hex"]};">{a["cat"]}</span>
              <div class="art-title">{a["title"]}</div>
              <p class="art-excerpt">{a["summary"]}</p>
            </div>
            <div class="art-footer">
              <span class="art-source">{a["source"]} &middot; {a["date_short"]}</span>
              <span class="art-link">Read &rarr;</span>
            </div>
          </a>''')
    return "\n".join(cards)

# ── RUN ────────────────────────────────────────────────────────────────────

def run():
    print("-- Fetching articles --------------------------------------")
    articles = fetch_all()
    if not articles:
        print("No new articles. Exiting.")
        return

    print("-- Updating pages -----------------------------------------")
    ticker_html = gen_ticker(articles)
    alert_html  = gen_alert(articles)

    for page in sorted(SITE_DIR.glob("*.html")):
        html    = page.read_text(encoding="utf-8")
        changed = False

        if "<!-- ALERT_START -->" in html:
            html = inject(html, "<!-- ALERT_START -->", "<!-- ALERT_END -->", alert_html)
            changed = True
        if "<!-- TICKER_START -->" in html:
            html = inject(html, "<!-- TICKER_START -->", "<!-- TICKER_END -->", ticker_html)
            changed = True

        if page.name == "index.html" and articles:
            html = inject(html, "<!-- HERO_LEAD_START -->",    "<!-- HERO_LEAD_END -->",    gen_hero_lead(articles[0]))
            html = inject(html, "<!-- HERO_SIDEBAR_START -->", "<!-- HERO_SIDEBAR_END -->", gen_hero_sidebar(articles[1:]))
            html = inject(html, "<!-- ARTICLES_START -->",     "<!-- ARTICLES_END -->",     gen_article_cards(articles))
            changed = True

        if page.name == "news.html":
            for sec in ["budget", "tech", "safety", "leader", "infra", "policy"]:
                start = f"<!-- SEC_{sec.upper()}_START -->"
                end   = f"<!-- SEC_{sec.upper()}_END -->"
                if start in html:
                    cards = gen_section_cards(articles, sec)
                    if cards:
                        html = inject(html, start, end, cards)
            changed = True

        if changed:
            page.write_text(html, encoding="utf-8")
            print(f"  OK {page.name}")

    print(f"-- Done: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} --")

if __name__ == "__main__":
    run()
