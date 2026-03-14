#!/usr/bin/env python3
"""
deep_read.py - Prepare and generate deep-read notes for top N papers.

Two modes:
  1. Prepare mode (default, for daily use):
     Downloads PDFs, extracts figures, writes deepread_queue.json.
     Actual note writing is done by Claude Code reading the queue.

  2. API mode (--api-mode, for backfill):
     Fetches arxiv HTML + calls Claude API to generate notes automatically.

Usage:
    # Daily: prepare for Claude Code to read
    python deep_read.py \
        --scoring /path/to/scoring.json \
        --prepared /tmp/paper-daily/DATE/prepared.json \
        --output-dir /path/to/PaperDaily/YYYY/MM_Month/YYYY-MM-DD/ \
        --top-n 20

    # Backfill: fully automated via API
    python deep_read.py --api-mode \
        --scoring /path/to/scoring.json \
        --prepared /tmp/paper-daily/DATE/prepared.json \
        --output-dir /path/to/PaperDaily/YYYY/MM_Month/YYYY-MM-DD/ \
        --top-n 5
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
from pathlib import Path
from datetime import datetime

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
CONFIG_DIR = SCRIPTS_DIR.parent / "config"

from api_client import call_claude, load_prompt_template
from download_pdfs import download_pdf
from figure_extractor import extract_figures, build_figures_section


# ──────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────

def _ssl_ctx():
    for cert_path in ["/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"]:
        if os.path.exists(cert_path):
            return ssl.create_default_context(cafile=cert_path)
    return ssl._create_unverified_context()


def make_slug(title: str, arxiv_id: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "_", slug).strip("_")
    return f"{arxiv_id}_{slug[:55]}"


def infer_topic_tags(title: str, reason: str) -> str:
    text = (title + " " + reason).lower()
    tags = []
    if any(w in text for w in ["attention", "flash"]):
        tags.append("topic/attention")
    if any(w in text for w in ["quant", "int8", "int4", "w4", "w8"]):
        tags.append("topic/quantization")
    if any(w in text for w in ["sparse", "sparsity", "pruning"]):
        tags.append("topic/sparsity")
    if any(w in text for w in ["rl", "reinforcement", "reward", "grpo", "ppo"]):
        tags.append("topic/rl-reasoning")
    if any(w in text for w in ["distill", "compression", "token budget"]):
        tags.append("topic/distillation")
    if any(w in text for w in ["kernel", "cuda", "triton", "gpu"]):
        tags.append("topic/gpu-kernel")
    if any(w in text for w in ["train", "pretrain", "backward"]):
        tags.append("topic/training-opt")
    if any(w in text for w in ["infer", "decode", "serving", "vllm", "sglang"]):
        tags.append("topic/inference-opt")
    if any(w in text for w in ["moe", "mixture of experts"]):
        tags.append("topic/moe")
    if any(w in text for w in ["multimodal", "vision", "mllm", "vqa", "vlm", "llava", "qwen-vl",
                                "internvl", "diffusion", "text-to-image", "visual", "blip",
                                "clip", "vit", "vision transformer", "image generation"]):
        tags.append("topic/multimodal-vision")
    if not tags:
        tags.append("topic/ml")
    return ", ".join(tags)


def _load_data(scoring_path: str, prepared_path: str):
    with open(scoring_path, encoding="utf-8") as f:
        scores = json.load(f)
    with open(prepared_path, encoding="utf-8") as f:
        prepared = json.load(f)
    date_str = prepared.get("date", datetime.now().strftime("%Y-%m-%d"))
    paper_by_id = {f"arxiv:{p['arxiv_id']}": p for p in prepared.get("papers", [])}
    return scores, prepared, date_str, paper_by_id


def _select_candidates(scores: list, top_n: int) -> list:
    candidates = [s for s in scores if s.get("deep_read", False) or s.get("score", 0) >= 7]
    return candidates[:top_n]


# ──────────────────────────────────────────────────────────────
# Mode 1 — Prepare for Claude Code
# ──────────────────────────────────────────────────────────────

def prepare_deepreads(scoring_path: str, prepared_path: str, output_dir: str,
                      top_n: int = 20, force: bool = False) -> str:
    """
    Download PDFs + extract figures for top-N papers.
    Writes deepread_queue.json in deep-reads/ dir.
    Returns path to deepread_queue.json.

    Claude Code reads this queue + PDFs to write the actual notes.
    """
    output_path = Path(output_dir)
    deep_reads_dir = output_path / "deep-reads"
    deep_reads_dir.mkdir(parents=True, exist_ok=True)

    pdf_dir = output_path / "pdfs"
    figures_root = deep_reads_dir / "figures"

    scores, prepared, date_str, paper_by_id = _load_data(scoring_path, prepared_path)
    candidates = _select_candidates(scores, top_n)

    print(f"[deep_read] Preparing {len(candidates)} papers for Claude Code deep-read")

    queue = []
    for i, score_entry in enumerate(candidates):
        paper_id = score_entry.get("id", "")
        paper = paper_by_id.get(paper_id, {})
        arxiv_id = paper.get("arxiv_id", paper_id.replace("arxiv:", ""))
        title = paper.get("title", score_entry.get("title", "Untitled"))
        score = score_entry.get("score", 0)
        reason = score_entry.get("reason", "")

        slug = make_slug(title, arxiv_id)
        note_path = deep_reads_dir / f"{slug}_deepread.md"

        if note_path.exists() and not force:
            print(f"  [{i+1}/{len(candidates)}] SKIP (note exists): {slug[:50]}")
            continue

        print(f"  [{i+1}/{len(candidates)}] Downloading PDF: {arxiv_id}")
        pdf_path = download_pdf(arxiv_id, str(pdf_dir))

        figures = []
        if pdf_path:
            figs = extract_figures(
                pdf_path, arxiv_id, str(figures_root),
                max_figures=8, min_size_kb=20,
            )
            figures = [str(f) for f in figs]

        queue.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": (paper.get("authors", "") or "")[:200],
            "abstract": (paper.get("abstract", "") or "")[:2000],
            "score": score,
            "reason": reason,
            "topic_tags": infer_topic_tags(title, reason),
            "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_path": pdf_path,
            "figures": figures,
            "note_path": str(note_path),
            "date": date_str,
            "done": False,
        })

        time.sleep(2)  # polite rate limit between downloads

    queue_path = deep_reads_dir / "deepread_queue.json"
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "papers": queue}, f, indent=2, ensure_ascii=False)

    print(f"[deep_read] Queue written → {queue_path}")
    print(f"[deep_read] {len(queue)} papers ready. Run Claude Code to write deep-read notes.")
    return str(queue_path)


# ──────────────────────────────────────────────────────────────
# Mode 2 — API mode (for backfill)
# ──────────────────────────────────────────────────────────────

def fetch_arxiv_html(arxiv_id: str, timeout: int = 30) -> str:
    url = f"https://arxiv.org/html/{arxiv_id}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (paper-daily-bot; research use)"},
    )
    ctx = _ssl_ctx()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as e:
        print(f"  [SKIP] HTML fetch failed for {arxiv_id}: {e}")
        return ""

    html = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", html,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    if len(text) > 12000:
        text = text[:12000] + "\n\n[... truncated ...]"
    return text


def generate_deep_read(paper: dict, score_entry: dict, fulltext: str,
                       date_str: str, prompt_template: str) -> str:
    arxiv_id = paper.get("arxiv_id", "")
    title = paper.get("title", "Untitled")
    authors = (paper.get("authors", "") or "")[:200]
    abstract = (paper.get("abstract", "") or "")[:1500]
    score = score_entry.get("score", 0)
    reason = score_entry.get("reason", "")

    topic_tags = infer_topic_tags(title, reason)
    title_short = title[:80]

    prompt = prompt_template
    prompt = prompt.replace("{{title}}", title)
    prompt = prompt.replace("{{title_short}}", title_short)
    prompt = prompt.replace("{{arxiv_id}}", arxiv_id)
    prompt = prompt.replace("{{authors}}", authors)
    prompt = prompt.replace("{{published}}", date_str)
    prompt = prompt.replace("{{arxiv_url}}", f"https://arxiv.org/abs/{arxiv_id}")
    prompt = prompt.replace("{{interest_hits}}", reason)
    prompt = prompt.replace("{{abstract}}", abstract)
    prompt = prompt.replace("{{fulltext}}", fulltext)
    prompt = prompt.replace("{{date}}", date_str)
    prompt = prompt.replace("{{score}}", str(score))
    prompt = prompt.replace("{{topic_tags}}", topic_tags)

    return call_claude(prompt, max_tokens=4096, temperature=0.3)


def run_deep_reads(scoring_path: str, prepared_path: str, output_dir: str,
                   top_n: int = 20, force: bool = False):
    """API mode: generate deep-read notes via Claude API (for backfill)."""
    output_path = Path(output_dir)
    deep_reads_dir = output_path / "deep-reads"
    deep_reads_dir.mkdir(parents=True, exist_ok=True)

    pdf_dir = output_path / "pdfs"
    figures_root = deep_reads_dir / "figures"

    scores, prepared, date_str, paper_by_id = _load_data(scoring_path, prepared_path)
    candidates = _select_candidates(scores, top_n)

    print(f"[deep_read] API mode: generating {len(candidates)} deep-reads (top {top_n})")

    prompt_template = load_prompt_template("deep_read.txt")

    written = 0
    for i, score_entry in enumerate(candidates):
        paper_id = score_entry.get("id", "")
        paper = paper_by_id.get(paper_id, {})
        arxiv_id = paper.get("arxiv_id", paper_id.replace("arxiv:", ""))
        title = paper.get("title", score_entry.get("title", "Untitled"))

        slug = make_slug(title, arxiv_id)
        out_path = deep_reads_dir / f"{slug}_deepread.md"

        if out_path.exists() and not force:
            print(f"  [{i+1}/{len(candidates)}] SKIP (exists): {slug[:50]}")
            continue

        print(f"  [{i+1}/{len(candidates)}] Deep read: {arxiv_id} — {title[:50]}")
        fulltext = fetch_arxiv_html(arxiv_id)
        if not fulltext:
            fulltext = "(HTML not available; use abstract only)"
        try:
            content = generate_deep_read(paper, score_entry, fulltext, date_str, prompt_template)
            out_path.write_text(content, encoding="utf-8")
            print(f"  [{i+1}/{len(candidates)}] Written → {out_path.name}")

            # Download PDF + extract figures, append to note
            pdf_path = download_pdf(arxiv_id, str(pdf_dir))
            if pdf_path:
                figs = extract_figures(
                    pdf_path, arxiv_id, str(figures_root),
                    max_figures=8, min_size_kb=20,
                )
                if figs:
                    figures_md = build_figures_section(figs, str(deep_reads_dir))
                    with open(out_path, "a", encoding="utf-8") as f:
                        f.write(figures_md)
                    print(f"  [{i+1}/{len(candidates)}] Appended {len(figs)} figures")

            written += 1
        except Exception as e:
            print(f"  [WARN] Deep read failed for {arxiv_id}: {e}", file=sys.stderr)

        if i < len(candidates) - 1:
            time.sleep(2)

    print(f"[deep_read] Done. Written {written}/{len(candidates)} deep-read notes.")
    return written


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Prepare or generate deep-read notes")
    parser.add_argument("--scoring", required=True, help="Path to scoring.json")
    parser.add_argument("--prepared", required=True, help="Path to prepared.json")
    parser.add_argument("--output-dir", required=True, help="Day root directory")
    parser.add_argument("--top-n", type=int, default=20, help="Number of papers to process")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--api-mode", action="store_true",
                        help="Call Claude API to generate notes (for backfill). "
                             "Default: prepare PDFs + figures for Claude Code.")
    args = parser.parse_args()

    if args.api_mode:
        run_deep_reads(args.scoring, args.prepared, args.output_dir, args.top_n, args.force)
    else:
        prepare_deepreads(args.scoring, args.prepared, args.output_dir, args.top_n, args.force)


if __name__ == "__main__":
    main()
