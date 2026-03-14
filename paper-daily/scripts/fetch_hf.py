#!/usr/bin/env python3
"""
fetch_hf.py - Fetch HuggingFace Daily Papers for paper-daily pipeline.

Scrapes https://huggingface.co/papers?date=YYYY-MM-DD and returns a JSON
with paper metadata including arxiv_id, title, abstract, hf_upvotes.

Usage:
    python fetch_hf.py --date 2024-01-01 --output /tmp/hf_papers.json
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
from datetime import datetime, timedelta
from pathlib import Path


HF_BASE = "https://huggingface.co/papers"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _ssl_ctx():
    for cert_path in ["/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"]:
        if os.path.exists(cert_path):
            return ssl.create_default_context(cafile=cert_path)
    return ssl._create_unverified_context()


def fetch_hf_papers(date_str: str) -> list:
    """Fetch papers from HuggingFace daily papers page."""
    url = f"{HF_BASE}?date={date_str}"
    papers = []

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        ctx = _ssl_ctx()
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[WARN] HF HTTP {e.code} for {date_str}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[WARN] HF fetch error: {e}", file=sys.stderr)
        return []

    # Extract paper data from HTML
    # HF embeds paper data in JSON-like script tags or structured HTML
    # Pattern: arxiv IDs in links like /papers/2401.00448
    arxiv_pattern = re.compile(r'href=["\']https?://arxiv\.org/abs/(\d{4}\.\d{4,5})["\']')
    hf_paper_pattern = re.compile(r'href=["\'](?:https://huggingface\.co)?/papers/(\d{4}\.\d{4,5})["\']')

    seen_ids = set()

    # Try to extract upvotes from page data
    # HF renders upvotes as data attributes or JSON
    upvote_pattern = re.compile(r'"id":\s*"(\d{4}\.\d{4,5})"[^}]*"upvotes":\s*(\d+)', re.DOTALL)
    upvote_map = {}
    for m in upvote_pattern.finditer(html):
        upvote_map[m.group(1)] = int(m.group(2))

    # Also try simpler pattern
    upvote_pattern2 = re.compile(r'(\d{4}\.\d{4,5}).*?(\d+)\s*(?:upvotes?|likes?)', re.DOTALL)

    # Extract title pattern near paper links
    title_pattern = re.compile(
        r'href=["\'](?:https://huggingface\.co)?/papers/(\d{4}\.\d{4,5})["\'][^>]*>([^<]{10,200})</a>',
        re.DOTALL
    )

    # Build title map
    title_map = {}
    for m in title_pattern.finditer(html):
        arxiv_id = m.group(1)
        title = re.sub(r'\s+', ' ', m.group(2)).strip()
        if len(title) > 10:
            title_map[arxiv_id] = title

    # Collect all arxiv IDs from HF paper links
    for m in hf_paper_pattern.finditer(html):
        arxiv_id = m.group(1)
        if arxiv_id not in seen_ids:
            seen_ids.add(arxiv_id)
            papers.append({
                "arxiv_id": arxiv_id,
                "title": title_map.get(arxiv_id, ""),
                "abstract": "",
                "authors": "",
                "hf_upvotes": upvote_map.get(arxiv_id, 0),
                "hf_trending": True,
                "source": "huggingface",
            })

    # Also collect from direct arxiv links in case
    for m in arxiv_pattern.finditer(html):
        arxiv_id = m.group(1)
        if arxiv_id not in seen_ids:
            seen_ids.add(arxiv_id)
            papers.append({
                "arxiv_id": arxiv_id,
                "title": title_map.get(arxiv_id, ""),
                "abstract": "",
                "authors": "",
                "hf_upvotes": upvote_map.get(arxiv_id, 0),
                "hf_trending": True,
                "source": "huggingface",
            })

    return papers


def main():
    parser = argparse.ArgumentParser(description="Fetch HuggingFace Daily Papers")
    parser.add_argument("--date", required=True,
                        help="Date to fetch (YYYY-MM-DD, 'today', 'yesterday')")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    args = parser.parse_args()

    if args.date == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif args.date == "yesterday":
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        date_str = args.date

    print(f"[fetch_hf] Fetching HuggingFace papers for {date_str}...")
    papers = fetch_hf_papers(date_str)
    print(f"[fetch_hf] Found {len(papers)} papers")

    output = {"date": date_str, "count": len(papers), "papers": papers}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[fetch_hf] Written → {args.output}")


if __name__ == "__main__":
    main()
