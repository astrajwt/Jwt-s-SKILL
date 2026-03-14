#!/usr/bin/env python3
"""
fetch_arxiv.py - Fetch papers from arxiv API with 72-hour window.

Usage:
    python fetch_arxiv.py --date 2026-03-06 --output /tmp/arxiv_papers.json
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    print("[WARN] feedparser not installed. Install: pip3 install feedparser", file=sys.stderr)

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
CONFIG_DIR = SCRIPTS_DIR.parent / "config"

ARXIV_API = "http://export.arxiv.org/api/query"


def _ssl_ctx():
    for cert_path in ["/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"]:
        if os.path.exists(cert_path):
            return ssl.create_default_context(cafile=cert_path)
    return ssl._create_unverified_context()


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.json") as f:
        return json.load(f)


def load_config() -> dict:
    with open(CONFIG_DIR / "interests.json") as f:
        return json.load(f)


def get_all_keywords(config: dict) -> list:
    keywords = []
    for cat_data in config.get("keywords", {}).values():
        if isinstance(cat_data, dict):
            for kws in cat_data.values():
                keywords.extend(kws)
        elif isinstance(cat_data, list):
            keywords.extend(cat_data)
    return list(set(keywords))


def score_paper_keywords(paper: dict, config: dict) -> float:
    weights = config.get("scoring_weights", {})
    title_w = weights.get("title_match", 3.0)
    abstract_w = weights.get("abstract_match", 1.0)
    primary_bonus = weights.get("primary_category_bonus", 2.0)
    secondary_bonus = weights.get("secondary_category_bonus", 0.5)

    score = 0.0
    title_lower = paper.get("title", "").lower()
    abstract_lower = paper.get("abstract", "").lower()

    all_keywords = get_all_keywords(config)
    for kw in all_keywords:
        kw_lower = kw.lower()
        if kw_lower in title_lower:
            score += title_w
        elif kw_lower in abstract_lower:
            score += abstract_w

    # Category bonus
    primary_cats = set(config.get("arxiv_categories", {}).get("primary", []))
    secondary_cats = set(config.get("arxiv_categories", {}).get("secondary", []))
    paper_cats = set(paper.get("categories", []))
    if paper_cats & primary_cats:
        score += primary_bonus
    elif paper_cats & secondary_cats:
        score += secondary_bonus

    return score


def build_arxiv_query(categories: list, start_date: str, end_date: str) -> str:
    """Build arxiv API query with category filter and date range."""
    cat_query = " OR ".join(f"cat:{c}" for c in categories)
    start_fmt = start_date.replace("-", "") + "000000"
    end_fmt = end_date.replace("-", "") + "235959"
    date_range = f"submittedDate:[{start_fmt} TO {end_fmt}]"
    return f"({cat_query}) AND {date_range}"


def fetch_arxiv_batch(query: str, start: int, max_results: int) -> list:
    """Fetch a batch of papers from arxiv API."""
    if not HAS_FEEDPARSER:
        return []

    params = urllib.parse.urlencode({
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"

    ctx = _ssl_ctx()
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=60) as resp:
            content = resp.read().decode("utf-8")
    except Exception as e:
        print(f"[WARN] arxiv API error: {e}", file=sys.stderr)
        return []

    feed = feedparser.parse(content)
    papers = []
    for entry in feed.entries:
        arxiv_id_raw = entry.get("id", "")
        # Extract clean ID: https://arxiv.org/abs/2501.12345v1 -> 2501.12345
        m = re.search(r"(\d{4}\.\d{4,5})", arxiv_id_raw)
        if not m:
            continue
        arxiv_id = m.group(1)

        categories = [t.get("term", "") for t in entry.get("tags", [])]
        authors_list = entry.get("authors", [])
        authors_str = ", ".join(
            a.get("name", "") for a in authors_list[:5]
        )
        if len(authors_list) > 5:
            authors_str += " et al."

        papers.append({
            "arxiv_id": arxiv_id,
            "title": entry.get("title", "").replace("\n", " ").strip(),
            "abstract": entry.get("summary", "").replace("\n", " ").strip(),
            "authors": authors_str,
            "categories": categories,
            "published": entry.get("published", ""),
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
            "source": "arxiv",
            "hf_trending": False,
        })

    return papers


def fetch_papers_for_date(date_str: str, config: dict, settings: dict) -> list:
    """Fetch papers submitted in the 72-hour window ending on date_str."""
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    window_days = settings.get("arxiv", {}).get("window_days", 3)
    window_start = (target_dt - timedelta(days=window_days)).strftime("%Y-%m-%d")

    all_cats = (
        config.get("arxiv_categories", {}).get("primary", []) +
        config.get("arxiv_categories", {}).get("secondary", [])
    )
    max_results_base = settings.get("arxiv", {}).get("max_results_per_category", 100)
    max_results = max_results_base * 3  # 3x for 72h window

    query = build_arxiv_query(all_cats, window_start, date_str)

    all_papers = []
    seen_ids = set()

    # Fetch in batches
    batch_size = 100
    start = 0
    while start < max_results:
        fetch_count = min(batch_size, max_results - start)
        batch = fetch_arxiv_batch(query, start, fetch_count)
        if not batch:
            break
        for p in batch:
            if p["arxiv_id"] not in seen_ids:
                seen_ids.add(p["arxiv_id"])
                all_papers.append(p)
        if len(batch) < fetch_count:
            break  # No more results
        start += fetch_count
        time.sleep(settings.get("arxiv", {}).get("rate_limit_seconds", 3))

    return all_papers


def main():
    parser = argparse.ArgumentParser(description="Fetch arxiv papers")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    args = parser.parse_args()

    settings = load_settings()
    config = load_config()

    print(f"[fetch_arxiv] Fetching papers for {args.date} (72h window)...")
    papers = fetch_papers_for_date(args.date, config, settings)
    print(f"[fetch_arxiv] Fetched {len(papers)} raw papers")

    # Score papers
    for p in papers:
        p["relevance_score"] = score_paper_keywords(p, config)

    # Filter: keep only papers with score > 0 or in primary categories
    primary_cats = set(config.get("arxiv_categories", {}).get("primary", []))
    filtered = [
        p for p in papers
        if p.get("relevance_score", 0) > 0 or
           bool(set(p.get("categories", [])) & primary_cats)
    ]
    filtered.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    output = {
        "date": args.date,
        "source": "arxiv",
        "count": len(filtered),
        "papers": filtered,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[fetch_arxiv] {len(filtered)} relevant papers -> {args.output}")


if __name__ == "__main__":
    main()
