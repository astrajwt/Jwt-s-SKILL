#!/usr/bin/env python3
"""
score_papers.py - LLM-powered batch scoring for paper-daily pipeline.

Reads prepared.json, calls Claude API to score all papers,
outputs scoring.json + individual summary .md files.

Usage:
    python score_papers.py \
        --prepared /tmp/paper-daily/2026-03-06/prepared.json \
        --output-dir /path/to/PaperDaily/2026/March/2026-03-06/
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
CONFIG_DIR = SCRIPTS_DIR.parent / "config"

from api_client import call_claude, load_prompt_template


def load_interests() -> dict:
    with open(CONFIG_DIR / "interests.json") as f:
        return json.load(f)


def flatten_keywords(interests: dict) -> str:
    """Flatten interests.json keywords into a readable list for the prompt."""
    keywords_dict = interests.get("keywords", {})
    weights = interests.get("scoring_weights", {})

    lines = []
    for category, subcats in keywords_dict.items():
        cat_label = category.replace("_", " ")
        lines.append(f"\n### {cat_label}")
        if isinstance(subcats, dict):
            for subcat, kws in subcats.items():
                sub_label = subcat.replace("_", " ")
                kw_str = ", ".join(kws)
                lines.append(f"- {sub_label}: {kw_str}")
        elif isinstance(subcats, list):
            lines.append(f"- {', '.join(subcats)}")

    # Add scoring weights summary
    if weights:
        lines.append("\n### Scoring weights")
        for k, v in weights.items():
            lines.append(f"- {k}: {v}")

    return "\n".join(lines)


def papers_to_prompt_json(papers: list) -> str:
    """Convert paper list to compact JSON for the scoring prompt."""
    compact = []
    for p in papers:
        compact.append({
            "id": f"arxiv:{p.get('arxiv_id', '')}",
            "title": p.get("title", ""),
            "abstract": (p.get("abstract", "") or "")[:300],  # truncate long abstracts
            "hf_trending": p.get("hf_trending", False),
            "hf_upvotes": p.get("hf_upvotes", 0),
            "authors": (p.get("authors", "") or "")[:60],
        })
    return json.dumps(compact, ensure_ascii=False, indent=2)


def parse_scoring_response(raw: str) -> list:
    """Parse the LLM's JSON response, handling common formatting issues."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()

    # Find the JSON array
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array found in response: {cleaned[:200]}")

    return json.loads(match.group(0))


def make_slug(title: str, arxiv_id: str) -> str:
    """Generate a file-system-safe slug from a paper title."""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "_", slug).strip("_")
    slug = slug[:55]
    return f"{arxiv_id}_{slug}"


def write_summary_md(paper: dict, score_entry: dict, output_dir: Path, date_str: str):
    """Write a summary .md file for a single paper."""
    arxiv_id = paper.get("arxiv_id", "")
    title = paper.get("title", "Untitled")
    slug = make_slug(title, arxiv_id)
    source = paper.get("source", "arxiv")
    authors = paper.get("authors", "")
    score = score_entry.get("score", 0)
    summary = score_entry.get("summary", "")
    reason = score_entry.get("reason", "")

    tags = ["paper", f"source/{source}"]
    # Infer topic tags from reason text
    topic_map = {
        "attention": "topic/attention",
        "quant": "topic/quantization",
        "sparse": "topic/sparsity",
        "rl": "topic/rl-reasoning",
        "distill": "topic/distillation",
        "kernel": "topic/gpu-kernel",
        "train": "topic/training-opt",
        "infer": "topic/inference-opt",
        "moe": "topic/moe",
        "agent": "topic/agent",
    }
    reason_lower = (reason + " " + title).lower()
    for key, tag in topic_map.items():
        if key in reason_lower and tag not in tags:
            tags.append(tag)

    content = f"""---
title: "{title}"
arxiv_id: "{arxiv_id}"
date: {date_str}
authors: "{authors[:120]}"
source: {source}
url: "https://arxiv.org/abs/{arxiv_id}"
pdf: "https://arxiv.org/pdf/{arxiv_id}"
tags: [{", ".join(tags)}]
score: {score}
---
# {title}

## 核心贡献 (Key Contributions)
{summary}

## 为什么值得关注 (Why It Matters)
{reason}

## 相关论文 (Related Work)
<!-- Add [Title](arxiv_url) links here if relevant -->
"""

    summaries_dir = output_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    out_path = summaries_dir / f"{slug}.md"
    out_path.write_text(content, encoding="utf-8")
    return str(out_path)


def run_scoring(prepared_path: str, output_dir: str, batch_size: int = 10):
    """Main scoring function."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load data
    with open(prepared_path, encoding="utf-8") as f:
        prepared = json.load(f)

    papers = prepared.get("papers", [])
    date_str = prepared.get("date", datetime.now().strftime("%Y-%m-%d"))
    print(f"[score_papers] Scoring {len(papers)} papers for {date_str}")

    # Load interests
    interests = load_interests()
    interest_keywords = flatten_keywords(interests)

    # Load prompt template
    prompt_template = load_prompt_template("score_papers.txt")

    # Score in batches (avoid context limits)
    all_scores = []
    batches = [papers[i:i+batch_size] for i in range(0, len(papers), batch_size)]

    for batch_idx, batch in enumerate(batches):
        print(f"[score_papers] Batch {batch_idx+1}/{len(batches)} ({len(batch)} papers)...")

        papers_json = papers_to_prompt_json(batch)
        prompt = prompt_template.replace("{{interest_keywords}}", interest_keywords)
        prompt = prompt.replace("{{papers_json}}", papers_json)

        try:
            response = call_claude(prompt, max_tokens=4096, temperature=0.2)
            batch_scores = parse_scoring_response(response)
            all_scores.extend(batch_scores)
            print(f"[score_papers] Batch {batch_idx+1} done: {len(batch_scores)} scored")
        except Exception as e:
            print(f"[WARN] Batch {batch_idx+1} failed: {e}", file=sys.stderr)
            # Add placeholder scores for failed batch
            for p in batch:
                all_scores.append({
                    "id": f"arxiv:{p.get('arxiv_id', '')}",
                    "score": 0,
                    "reason": "scoring failed",
                    "summary": p.get("abstract", "")[:200],
                    "deep_read": False,
                })

        if batch_idx < len(batches) - 1:
            time.sleep(2)  # rate limiting between batches

    # Build id→paper lookup
    paper_by_id = {f"arxiv:{p['arxiv_id']}": p for p in papers}

    # Enrich scores with HF data
    for s in all_scores:
        paper = paper_by_id.get(s.get("id", ""), {})
        s["title"] = paper.get("title", "")
        s["hf_upvotes"] = paper.get("hf_upvotes", 0)
        s["hf_trending"] = paper.get("hf_trending", False)
        # Mark deep_read for top papers if not already set by LLM
        if s.get("score", 0) >= 7 and "deep_read" not in s:
            s["deep_read"] = True

    # Sort by score descending
    all_scores.sort(key=lambda x: (x.get("score", 0), x.get("hf_upvotes", 0)), reverse=True)

    # Save scoring.json
    scoring_path = output_path / "scoring.json"
    with open(scoring_path, "w", encoding="utf-8") as f:
        json.dump(all_scores, f, ensure_ascii=False, indent=2)
    print(f"[score_papers] Saved scoring.json → {scoring_path}")

    print(f"[score_papers] Top 5 papers:")
    for s in all_scores[:5]:
        print(f"  [{s.get('score', '?')}] {s.get('title', s.get('id', ''))[:70]}")

    return all_scores


def main():
    parser = argparse.ArgumentParser(description="LLM batch scoring for paper-daily")
    parser.add_argument("--prepared", required=True, help="Path to prepared.json")
    parser.add_argument("--output-dir", required=True, help="Output directory (day root)")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Papers per API call (default: 50)")
    args = parser.parse_args()

    run_scoring(args.prepared, args.output_dir, args.batch_size)


if __name__ == "__main__":
    main()
