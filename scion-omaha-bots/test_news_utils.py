from news_utils import extract_news_fields


def test_extract_news_fields_preserves_caller_options():
    records = [
        {
            "content": {
                "title": "Nested",
                "provider": {"displayName": "Provider"},
                "canonicalUrl": {"url": "https://nested.example"},
                "pubDate": "2026-08-31",
                "description": "Details",
            }
        },
        {
            "title": "Legacy",
            "publisher": "Publisher",
            "link": "https://legacy.example",
        },
    ]

    assert extract_news_fields(records, legacy=True, description=True) == [
        {
            "title": "Nested",
            "publisher": "Provider",
            "link": "https://nested.example",
            "pubDate": "2026-08-31",
            "description": "Details",
        },
        {
            "title": "Legacy",
            "publisher": "Publisher",
            "link": "https://legacy.example",
            "pubDate": "",
            "description": "",
        },
    ]
    assert extract_news_fields(records[1:]) == [
        {"title": "Legacy", "publisher": "Unknown", "link": "", "pubDate": ""}
    ]
