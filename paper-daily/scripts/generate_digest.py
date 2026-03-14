#!/usr/bin/env python3
"""
generate_digest.py - LLM-powered daily digest generation for paper-daily pipeline.

Usage:
    python generate_digest.py \
        --scoring /path/to/scoring.json \
        --prepared /tmp/paper-daily/DATE/prepared.json \
        --output /path/to/daily-report-DATE.md
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
CONFIG_DIR = SCRIPTS_DIR.parent / "config"

from api_client import call_claude, load_prompt_template


def load_interests() -> dict:
    with open(CONFIG_DIR / "interests.json") as f:
        return json.load(f)


def format_interest_summary(interests: dict) -> str:
    """Short summary of interest areas for the digest prompt."""
    keywords = interests.get("keywords", {})
    areas = list(keywords.keys())
    return ", ".join(a.replace("_", " ") for a in areas)


def build_hf_signal_section(papers: list) -> str:
    """Build HuggingFace trending signal section for digest."""
    hf_papers = [p for p in papers if p.get("hf_trending")]
    if not hf_papers:
        return "(No HuggingFace trending papers today)"

    lines = ["HuggingFace trending papers (high community interest):"]
    for p in hf_papers[:10]:
        upvotes = p.get("hf_upvotes", 0)
        title = p.get("title", "")
        arxiv_id = p.get("arxiv_id", "")
        lines.append(f"- [{upvotes} upvotes] {title} (arxiv:{arxiv_id})")
    return "\n".join(lines)


def build_papers_json_for_digest(scores: list, papers: list) -> str:
    """Build the scored papers JSON for the digest prompt."""
    paper_by_id = {f"arxiv:{p['arxiv_id']}": p for p in papers}

    digest_papers = []
    for s in scores[:20]:  # cap at 20 to keep prompt size manageable
        paper = paper_by_id.get(s.get("id", ""), {})
        digest_papers.append({
            "id": s.get("id", ""),
            "title": s.get("title", "") or paper.get("title", ""),
            "score": s.get("score", 0),
            "reason": (s.get("reason", "") or "")[:150],
            "summary": (s.get("summary", "") or "")[:120],
            "hf_trending": s.get("hf_trending", False),
            "hf_upvotes": s.get("hf_upvotes", 0),
            "deep_read": s.get("deep_read", False),
            "authors": (paper.get("authors", "") or "")[:60],
        })

    return json.dumps(digest_papers, ensure_ascii=False, indent=2)


def build_fulltext_section(scores: list, papers: list, max_papers: int = 5) -> str:
    """Include abstract excerpts for top papers as context."""
    paper_by_id = {f"arxiv:{p['arxiv_id']}": p for p in papers}
    top_papers = [s for s in scores if s.get("score", 0) >= 8][:max_papers]

    if not top_papers:
        top_papers = scores[:2]

    sections = []
    for s in top_papers:
        paper = paper_by_id.get(s.get("id", ""), {})
        abstract = (paper.get("abstract", "") or "")[:150]
        title = s.get("title", "") or paper.get("title", "")
        pid = s.get("id", "")
        if abstract:
            sections.append(f"### {title}\n{pid}\n\n{abstract}")

    return "\n\n---\n\n".join(sections) if sections else "(No full-text excerpts available)"


def prepare_digest(scoring_path: str, prepared_path: str, output_path: str,
                   deep_reads_dir: str = None) -> str:
    """
    Prepare digest_queue.json for Claude Code to write the daily digest.
    Returns path to digest_queue.json.
    Does NOT call Claude API — Claude Code reads the queue and writes the report.
    """
    with open(scoring_path, encoding="utf-8") as f:
        scores = json.load(f)
    with open(prepared_path, encoding="utf-8") as f:
        prepared = json.load(f)

    papers = prepared.get("papers", [])
    date_str = prepared.get("date", datetime.now().strftime("%Y-%m-%d"))
    stats = prepared.get("stats", {})

    interests = load_interests()
    interest_keywords = format_interest_summary(interests)
    paper_by_id = {f"arxiv:{p['arxiv_id']}": p for p in papers}

    # Top 20 scored papers — full metadata for Claude Code
    top_papers = []
    for s in scores[:20]:
        paper = paper_by_id.get(s.get("id", ""), {})
        top_papers.append({
            "id": s.get("id", ""),
            "arxiv_id": paper.get("arxiv_id", s.get("id", "").replace("arxiv:", "")),
            "title": s.get("title", "") or paper.get("title", ""),
            "score": s.get("score", 0),
            "reason": s.get("reason", ""),
            "summary": s.get("summary", ""),
            "abstract": (paper.get("abstract", "") or "")[:600],
            "authors": (paper.get("authors", "") or "")[:120],
            "hf_trending": s.get("hf_trending", False) or paper.get("hf_trending", False),
            "hf_upvotes": s.get("hf_upvotes", 0) or paper.get("hf_upvotes", 0),
            "deep_read": s.get("deep_read", False),
            "arxiv_url": f"https://arxiv.org/abs/{paper.get('arxiv_id', '')}",
            "pdf_url": f"https://arxiv.org/pdf/{paper.get('arxiv_id', '')}",
            "hf_url": f"https://huggingface.co/papers/{paper.get('arxiv_id', '')}",
        })

    # HF trending papers for community signal section
    hf_papers = [
        {
            "arxiv_id": p.get("arxiv_id", ""),
            "title": p.get("title", ""),
            "hf_upvotes": p.get("hf_upvotes", 0),
            "arxiv_url": f"https://arxiv.org/abs/{p.get('arxiv_id', '')}",
        }
        for p in papers if p.get("hf_trending")
    ]
    hf_papers.sort(key=lambda x: x["hf_upvotes"], reverse=True)

    queue = {
        "date": date_str,
        "output_path": str(output_path),
        "deep_reads_dir": str(deep_reads_dir) if deep_reads_dir else None,
        "interest_areas": interest_keywords,
        "stats": {
            **stats,
            "total_scored": len(scores),
            "hf_trending": len(hf_papers),
        },
        "top_papers": top_papers,
        "hf_papers": hf_papers[:15],
        "done": False,
    }

    queue_path = Path(output_path).parent / "digest_queue.json"
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

    print(f"[generate_digest] Queue written → {queue_path}")
    print(f"[generate_digest] {len(top_papers)} papers, {len(hf_papers)} HF trending. Claude Code will write the digest.")
    return str(queue_path)


def run_digest(scoring_path: str, prepared_path: str, output_path: str,
               language: str = "Chinese"):
    """API mode: generate daily digest via Claude API (for backfill)."""
    with open(scoring_path, encoding="utf-8") as f:
        scores = json.load(f)
    with open(prepared_path, encoding="utf-8") as f:
        prepared = json.load(f)

    papers = prepared.get("papers", [])
    date_str = prepared.get("date", datetime.now().strftime("%Y-%m-%d"))

    print(f"[generate_digest] API mode: building digest for {date_str}")
    print(f"[generate_digest] {len(scores)} scored papers, {len(papers)} total papers")

    interests = load_interests()
    interest_keywords = format_interest_summary(interests)

    papers_json = build_papers_json_for_digest(scores, papers)
    hf_signal = build_hf_signal_section(papers)
    fulltext_section = build_fulltext_section(scores, papers, max_papers=2)

    prompt_template = load_prompt_template("daily_digest.txt")
    prompt = prompt_template
    prompt = prompt.replace("{{date}}", date_str)
    prompt = prompt.replace("{{language}}", language)
    prompt = prompt.replace("{{interest_keywords}}", interest_keywords)
    prompt = prompt.replace("{{papers_json}}", papers_json)
    prompt = prompt.replace("{{hf_signal_section}}", hf_signal)
    prompt = prompt.replace("{{fulltext_section}}", fulltext_section)
    prompt = prompt.replace("{{hf_data_section}}", hf_signal)

    print(f"[generate_digest] Calling Claude API...")
    content = call_claude(prompt, model="claude-haiku-4-5", max_tokens=4096, temperature=0.4)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    print(f"[generate_digest] Written → {out_path}")
    return str(out_path)


def main():
    parser = argparse.ArgumentParser(description="Prepare or generate LLM daily digest")
    parser.add_argument("--scoring", required=True, help="Path to scoring.json")
    parser.add_argument("--prepared", required=True, help="Path to prepared.json")
    parser.add_argument("--output", required=True, help="Output path for daily-report-DATE.md")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--api-mode", action="store_true",
                        help="Call Claude API to generate digest (for backfill). "
                             "Default: write digest_queue.json for Claude Code.")
    parser.add_argument("--deep-reads-dir", default=None,
                        help="deep-reads/ dir path (for linking in queue)")
    args = parser.parse_args()

    if args.api_mode:
        run_digest(args.scoring, args.prepared, args.output, args.language)
    else:
        prepare_digest(args.scoring, args.prepared, args.output,
                       deep_reads_dir=args.deep_reads_dir)


if __name__ == "__main__":
    main()
