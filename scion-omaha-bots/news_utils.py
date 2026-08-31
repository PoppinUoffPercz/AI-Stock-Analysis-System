def extract_news_fields(news_raw, *, legacy=False, description=False):
    """Normalize nested and legacy yfinance news records."""
    parsed = []
    for item in news_raw:
        content = item.get("content", item)
        provider = content.get("provider", {})
        canonical = content.get("canonicalUrl", {})
        record = {
            "title": content.get("title", ""),
            "publisher": provider.get(
                "displayName", content.get("publisher", "Unknown") if legacy else "Unknown"
            ),
            "link": canonical.get("url", content.get("link", "") if legacy else ""),
            "pubDate": content.get("pubDate", ""),
        }
        if description:
            record["description"] = content.get("description", "")
        parsed.append(record)
    return parsed
