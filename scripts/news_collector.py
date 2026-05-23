# news_collector.py — Collecte et verifie les news crypto/finance
# Auteur: FORGE | Projet: Trading Agent Phase 1
# Sources: RSS (Cointelegraph, Decrypt, CryptoPanic) + Reddit JSON
# Anti-doublons via cache news_cache.json

import json, hashlib, re
from datetime import datetime, timedelta, timezone
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from utils import load_json, save_json, now_iso, NEWS_CACHE, setup_logging, load_settings

logger = setup_logging('news_collector')

MAX_ARTICLES_PER_SOURCE = 10
MAX_AGE_HOURS = 48
CACHE_TTL_HOURS = 72
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradingAgent/1.0'

def make_request(url, timeout=15):
    """Requete HTTP GET avec User-Agent."""
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8')

def hash_article(title, url):
    """Hash unique pour anti-doublons."""
    return hashlib.md5(f'{title}{url}'.encode()).hexdigest()

def is_cached(article_hash):
    """Verifie si un article est deja dans le cache."""
    cache = load_json(NEWS_CACHE) or {}
    return article_hash in cache

def cache_article(article_hash, article):
    """Ajoute un article au cache et nettoie les vieux."""
    cache = load_json(NEWS_CACHE) or {}
    cache[article_hash] = {**article, 'cached_at': now_iso()}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
    cache = {k: v for k, v in cache.items() if v.get('cached_at', '') > cutoff.isoformat()}
    save_json(NEWS_CACHE, cache)
    logger.debug(f'Cached article: {article.get("title", "")[:50]}')

def _clean_html(text):
    """Strip HTML tags."""
    return re.sub(r'<[^>]+>', '', text).strip()

def parse_rss(xml_data, source_name):
    """Parse un flux RSS en articles structures."""
    articles = []
    try:
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')[:MAX_ARTICLES_PER_SOURCE]
        for item in items:
            title = item.findtext('title', '')
            link = item.findtext('link', '')
            desc = item.findtext('description', '')
            pub_date = item.findtext('pubDate', '')
            if title and link:
                articles.append({
                    'title': title.strip(),
                    'url': link.strip(),
                    'summary': _clean_html(desc)[:300],
                    'source': source_name,
                    'type': 'rss',
                    'published': pub_date,
                    'collected_at': now_iso()
                })
    except ET.ParseError as e:
        logger.error(f'Erreur XML parsing {source_name}: {e}')
    return articles

def collect_reddit(subreddits, limit=5):
    """Scrape les posts hot de subreddits via l'API JSON publique."""
    articles = []
    for sub in subreddits:
        url = f'https://www.reddit.com/r/{sub}/hot.json?limit={limit}'
        try:
            data = json.loads(make_request(url))
            posts = data.get('data', {}).get('children', [])
            for post in posts:
                pdata = post['data']
                title = pdata.get('title', '')
                permalink = f"https://reddit.com{pdata.get('permalink', '')}"
                selftext = pdata.get('selftext', '')[:300]
                score = pdata.get('score', 0)
                comments = pdata.get('num_comments', 0)
                created = pdata.get('created_utc', 0)
                if title:
                    articles.append({
                        'title': title.strip(),
                        'url': permalink,
                        'summary': selftext,
                        'source': f'r/{sub}',
                        'type': 'reddit',
                        'score': score,
                        'comments': comments,
                        'published': datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
                        'collected_at': now_iso()
                    })
        except Exception as e:
            logger.warning(f'Reddit r/{sub} inaccessible: {e}')
    return articles

def collect_all_news(settings=None):
    """Point d'entree principal: collecte toutes les sources et retourne les nouveaux articles."""
    if settings is None:
        settings = load_settings()
    rss_feeds = settings['sources']['rss_feeds']
    reddit_subs = settings['sources']['reddit_subs']
    
    all_articles = []
    new_count = 0

    # === RSS ===
    for feed_url in rss_feeds:
        source = feed_url.split('//')[1].split('/')[0]
        try:
            xml_data = make_request(feed_url)
            articles = parse_rss(xml_data, source)
            for art in articles:
                art_hash = hash_article(art['title'], art['url'])
                if not is_cached(art_hash):
                    cache_article(art_hash, art)
                    all_articles.append(art)
                    new_count += 1
            logger.info(f'RSS {source}: {len(articles)} articles, {new_count} nouveaux')
        except Exception as e:
            logger.warning(f'Echec RSS {feed_url}: {e}')

    # === Reddit ===
    reddit_articles = collect_reddit(reddit_subs)
    reddit_new = 0
    for art in reddit_articles:
        art_hash = hash_article(art['title'], art['url'])
        if not is_cached(art_hash):
            cache_article(art_hash, art)
            all_articles.append(art)
            reddit_new += 1
    logger.info(f'Reddit: {len(reddit_articles)} posts, {reddit_new} nouveaux')

    logger.info(f'TOTAL collecte: {len(all_articles)} nouveaux articles')
    return all_articles

if __name__ == '__main__':
    articles = collect_all_news()
    print(f'\n=== {len(articles)} nouveaux articles ===')
    for a in articles[:10]:
        print(f"  [{a['source']}] {a['title'][:80]}")
