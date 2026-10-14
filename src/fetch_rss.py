import feedparser
import pandas as pd
from datetime import datetime
from config import NEWS_FEEDS


def fetch_news() -> pd.DataFrame:
    rows = []
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            source = feed.feed.get("title", url)
            for entry in feed.entries[:20]:
                published = (
                    datetime(*entry.published_parsed[:6])
                    if entry.get("published_parsed")
                    else datetime.now()
                )
                rows.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": source,
                    "published": published,
                })
        except Exception as e:
            print(f"[WARN] {url}: {e}")

    df = pd.DataFrame(rows)
    if not df.empty:
        df = (df.drop_duplicates(subset="link")
              .sort_values("published", ascending=False))
    return df


if __name__ == "__main__":
    news = fetch_news()
    print(f"Новостей: {len(news)}")
    if not news.empty:
        print(news[["published", "source", "title"]].head(10).to_string())
