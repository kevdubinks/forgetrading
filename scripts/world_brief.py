# world_brief.py — Contexte macro/politique pour Gerard
# FORGE Trading Agent
# Collecte les titres macro-economiques et politiques majeurs
# via RSS feeds publics. Ajoute le contexte au briefing Gerard.

import sys, json, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import setup_logging

logger = setup_logging("world_brief")

# Sources macro/politique (RSS gratuits)
SOURCES = [
    {
        "name": "Reuters World",
        "url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
        "type": "macro"
    },
    {
        "name": "Reuters Business",
        "url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
        "type": "macro"
    },
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "type": "crypto"
    },
    {
        "name": "The Block",
        "url": "https://www.theblock.co/rss.xml",
        "type": "crypto"
    }
]

def fetch_rss(url, max_items=5):
    """Fetch RSS feed and return list of {title, link, pubDate}."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FORGE/2.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        tree = ET.parse(resp)
        items = tree.findall(".//item")
        results = []
        for item in items[:max_items]:
            title = item.find("title")
            link = item.find("link")
            pub = item.find("pubDate")
            results.append({
                "title": title.text.strip() if title is not None and title.text else "?",
                "link": link.text.strip() if link is not None and link.text else "",
                "date": pub.text.strip() if pub is not None and pub.text else ""
            })
        return results
    except Exception as e:
        logger.warning(f"RSS {url[:50]}: {e}")
        return []


def collect_world_context():
    """Collecte le contexte macro et crypto pour le briefing Gerard."""
    context = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "macro_news": [],
        "crypto_news": []
    }

    for source in SOURCES:
        items = fetch_rss(source["url"], max_items=5)
        category = source["type"] + "_news"
        for item in items:
            entry = {
                "source": source["name"],
                "title": item["title"],
                "link": item["link"],
                "date": item["date"]
            }
            if category == "macro_news":
                context["macro_news"].append(entry)
            else:
                context["crypto_news"].append(entry)

    # Resume rapide
    logger.info(
        f"World brief: {len(context['macro_news'])} macro, "
        f"{len(context['crypto_news'])} crypto"
    )
    return context


def add_world_to_briefing(briefing):
    """Ajoute le contexte macro au briefing Gerard existant."""
    try:
        world = collect_world_context()
        briefing["world_context"] = {
            "macro_headlines": [
                {"source": n["source"], "title": n["title"]}
                for n in world["macro_news"][:8]
            ],
            "crypto_headlines": [
                {"source": n["source"], "title": n["title"]}
                for n in world["crypto_news"][:5]
            ]
        }
        logger.info("World context added to Gerard briefing")
    except Exception as e:
        logger.warning(f"World context failed: {e}")
        briefing["world_context"] = {"error": str(e)}
    return briefing


if __name__ == "__main__":
    ctx = collect_world_context()
    print(f"Macro: {len(ctx['macro_news'])} articles")
    for n in ctx['macro_news'][:5]:
        print(f"  [{n['source']}] {n['title'][:100]}")
    print(f"\nCrypto: {len(ctx['crypto_news'])} articles")
    for n in ctx['crypto_news'][:5]:
        print(f"  [{n['source']}] {n['title'][:100]}")
