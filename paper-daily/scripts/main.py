#!/usr/bin/env python3
"""
main.py - Main orchestrator for paper-daily pipeline.

Usage:
    python main.py --date today                    # Phase 1 only (fetch + dedup)
    python main.py --date today --full-auto        # Full pipeline (all phases)
    python main.py --date 2024-01-15               # Backfill specific date
    python main.py --date-range 2024-01-01 2024-01-31
    python main.py --date today --dry-run
"""

import argparse
import calendar
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
CONFIG_DIR = SCRIPTS_DIR.parent / "config"
sys.path.insert(0, str(SCRIPTS_DIR))

from file_manager import (get_date_paths, setup_date_dirs, check_report_needed,
                          get_base_path, get_db_path, get_log_path)
from dedup import init_db, filter_new_papers, mark_summarized, mark_deep_read, log_run


def load_config() -> dict:
    with open(CONFIG_DIR / "interests.json") as f:
        return json.load(f)


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.json") as f:
        return json.load(f)


def run_script(script: str, args: list, timeout: int = 180) -> tuple:
    cmd = [sys.executable, str(SCRIPTS_DIR / script)] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def fetch_all_papers(date_str: str, config: dict, temp_dir: Path) -> dict:
    all_papers = []
    hf_ids = set()

    # 1. HuggingFace
    hf_output = temp_dir / "hf_papers.json"
    rc, stdout, stderr = run_script("fetch_hf.py", ["--date", date_str, "--output", str(hf_output)])
    if rc == 0 and hf_output.exists():
        with open(hf_output) as f:
            hf_data = json.load(f)
        for p in hf_data.get("papers", []):
            p["source"] = "huggingface"
            p["hf_trending"] = True
            all_papers.append(p)
            hf_ids.add(p.get("arxiv_id", ""))
        print(f"[OK] HuggingFace: {len(hf_data.get('papers', []))} papers")
    else:
        print(f"[WARN] HuggingFace fetch failed: {stderr[:200]}", file=sys.stderr)

    time.sleep(2)

    # 2. arxiv
    arxiv_output = temp_dir / "arxiv_papers.json"
    rc, stdout, stderr = run_script("fetch_arxiv.py", ["--date", date_str, "--output", str(arxiv_output)])
    if rc == 0 and arxiv_output.exists():
        with open(arxiv_output) as f:
            arxiv_data = json.load(f)
        for p in arxiv_data.get("papers", []):
            arxiv_id = p.get("arxiv_id", "")
            if arxiv_id in hf_ids:
                for existing in all_papers:
                    if existing.get("arxiv_id") == arxiv_id:
                        existing["relevance_score"] = (
                            existing.get("relevance_score", 0) + p.get("relevance_score", 0)
                        )
                        existing["abstract"] = existing.get("abstract") or p.get("abstract", "")
                        break
            else:
                all_papers.append(p)
        print(f"[OK] arxiv: {len(arxiv_data.get('papers', []))} papers")
    else:
        print(f"[WARN] arxiv fetch failed: {stderr[:200]}", file=sys.stderr)

    all_papers.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return {"date": date_str, "count": len(all_papers), "papers": all_papers}


def prepare_day(date_str: str, dry_run: bool = False, bypass_dedup: bool = False) -> dict:
    settings = load_settings()
    config = load_config()

    print(f"\n{'='*60}")
    print(f"Paper Daily: {date_str}")
    print(f"{'='*60}\n")

    base_path = get_base_path(settings)
    if not dry_run:
        paths = setup_date_dirs(date_str, base_path)
        print(f"[OK] Directories: {paths['day_root']}")
    else:
        paths = get_date_paths(date_str, base_path)
        print(f"[DRY] Would create: {paths['day_root']}")

    temp_dir = Path("/tmp/paper-daily") / date_str
    temp_dir.mkdir(parents=True, exist_ok=True)

    print("\nFetching papers...")
    all_papers_data = fetch_all_papers(date_str, config, temp_dir)
    total_fetched = len(all_papers_data["papers"])
    print(f"[OK] Total fetched: {total_fetched} papers")

    print("\nDeduplication...")
    db_path = get_db_path(settings, base_path)
    conn = init_db(db_path)

    if bypass_dedup:
        # Skip dedup filter — use all fetched papers (for reprocessing already-seen dates)
        new_papers = all_papers_data["papers"]
        skipped = []
        print(f"[OK] Bypass dedup: using all {len(new_papers)} fetched papers")
    else:
        max_trending = config.get("max_trending_count", 3)
        new_papers, skipped = filter_new_papers(
            conn, all_papers_data["papers"], date_str,
            max_trending_count=max_trending
        )
    print(f"[OK] New: {len(new_papers)}, Skipped: {len(skipped)}")

    max_per_day = config.get("max_papers_per_day", 50)
    new_papers = new_papers[:max_per_day]

    deep_read_threshold = config.get("deep_read_threshold", 8.0)
    max_deep_reads = config.get("max_deep_reads_per_day", 10)
    deep_read_papers = [
        p for p in new_papers
        if p.get("relevance_score", 0) >= deep_read_threshold or p.get("hf_trending", False)
    ][:max_deep_reads]

    deep_read_ids = {p["arxiv_id"] for p in deep_read_papers}
    for p in new_papers:
        p["deep_read"] = p.get("arxiv_id", "") in deep_read_ids

    prepared_data = {
        "date": date_str,
        "paths": {k: str(v) for k, v in paths.items()},
        "papers": new_papers,
        "skipped": skipped,
        "deep_read_papers": deep_read_papers,
        "stats": {
            "total_fetched": total_fetched,
            "new": len(new_papers),
            "skipped": len(skipped),
            "deep_reads": len(deep_read_papers),
        },
        "check_reports": check_report_needed(date_str),
    }

    output_file = temp_dir / "prepared.json"
    with open(output_file, "w") as f:
        json.dump(prepared_data, f, indent=2, ensure_ascii=False)

    print(f"\nSummary:")
    print(f"  Total fetched: {total_fetched}")
    print(f"  New papers:    {len(new_papers)}")
    print(f"  Deep reads:    {len(deep_read_papers)}")
    print(f"  Skipped:       {len(skipped)}")
    print(f"\nPrepared data: {output_file}")

    conn.close()
    return prepared_data


def run_full_auto(target_date: str, top_n: int = 20, force_deepread: bool = False,
                  bypass_dedup: bool = False, api_mode: bool = False):
    """Full automatic pipeline: fetch -> score -> deep-read -> digest."""
    settings = load_settings()
    base_path = get_base_path(settings)

    dt = datetime.strptime(target_date, "%Y-%m-%d")
    month_name = f"{dt.month:02d}_{calendar.month_name[dt.month]}"
    year = dt.strftime("%Y")
    day_root = Path(base_path) / year / month_name / target_date
    day_root.mkdir(parents=True, exist_ok=True)

    prepared_path = Path("/tmp/paper-daily") / target_date / "prepared.json"
    scoring_path = day_root / "scoring.json"
    digest_path = day_root / f"daily-report-{target_date}.md"

    # Phase 1
    print("\n" + "="*60)
    print("Phase 1: Fetch & Dedup")
    print("="*60)
    prepare_day(target_date, bypass_dedup=bypass_dedup)
    if not prepared_path.exists():
        print(f"[ERROR] prepared.json not found at {prepared_path}", file=sys.stderr)
        sys.exit(1)

    # Phase 2 (skip if scoring.json already exists — allows retry without re-scoring)
    print("\n" + "="*60)
    print("Phase 2: LLM Batch Scoring")
    print("="*60)
    if scoring_path.exists():
        print(f"[skip] scoring.json already exists, skipping re-score")
    else:
        from score_papers import run_scoring
        run_scoring(str(prepared_path), str(day_root))
        if not scoring_path.exists():
            print("[ERROR] scoring.json not found, aborting", file=sys.stderr)
            sys.exit(1)

    # Phase 3a: Download PDFs + extract figures + deep-read notes
    print("\n" + "="*60)
    print(f"Phase 3a: PDF Download + Figure Extraction (top {top_n})")
    print("="*60)
    if api_mode:
        from deep_read import run_deep_reads
        run_deep_reads(str(scoring_path), str(prepared_path), str(day_root),
                       top_n=top_n, force=force_deepread)
    else:
        from deep_read import prepare_deepreads
        prepare_deepreads(str(scoring_path), str(prepared_path), str(day_root),
                          top_n=top_n, force=force_deepread)

    # Phase 3b: Generate daily digest
    print("\n" + "="*60)
    print("Phase 3b: Daily Digest")
    print("="*60)
    if api_mode:
        from generate_digest import run_digest
        run_digest(str(scoring_path), str(prepared_path), str(digest_path))
    else:
        from generate_digest import prepare_digest
        deep_reads_dir = day_root / "deep-reads"
        prepare_digest(str(scoring_path), str(prepared_path), str(digest_path),
                       deep_reads_dir=str(deep_reads_dir))

    # Clean up intermediate files (scoring.json not needed after digest)
    if scoring_path.exists():
        scoring_path.unlink()
        print(f"[cleanup] Removed scoring.json")

    # Phase 4: Aggregate reports (auto-detect weekly/monthly/quarterly/yearly)
    print("\n" + "="*60)
    print("Phase 4: Aggregate Reports (auto-detect)")
    print("="*60)
    from report_aggregator import run_auto
    generated = run_auto(target_date)
    if generated:
        print(f"[OK] Generated: {', '.join(Path(p).name for p in generated)}")
    else:
        print("[skip] No aggregate reports due today")

    # Phase 5: Sync to Notion (skip if NOTION_TOKEN not configured)
    notion_token = os.environ.get("NOTION_TOKEN", "")
    notion_root = os.environ.get("NOTION_ROOT_PAGE_ID", "")
    if notion_token and notion_root:
        print("\n" + "="*60)
        print("Phase 5: Notion Sync")
        print("="*60)
        try:
            from notion_sync import sync_date
            sync_date(target_date)
        except Exception as e:
            print(f"[WARN] Notion sync failed: {e}", file=sys.stderr)
    else:
        print("\n[skip] Phase 5: NOTION_TOKEN or NOTION_ROOT_PAGE_ID not set, skipping Notion sync")

    print("\n" + "="*60)
    print(f"Full pipeline complete: {target_date}")
    print(f"  Day root: {day_root}")
    print(f"  Digest:   {digest_path}")
    print("="*60)


def mark_papers_done(date_str: str, arxiv_ids: list):
    settings = load_settings()
    base_path = get_base_path(settings)
    db_path = get_db_path(settings, base_path)
    conn = init_db(db_path)
    for arxiv_id in arxiv_ids:
        mark_summarized(conn, arxiv_id)
    log_run(conn, date_str, 0, len(arxiv_ids), 0, 0)
    conn.close()
    print(f"[OK] Marked {len(arxiv_ids)} papers as processed")


def backfill_date_range(start_date: str, end_date: str, dry_run: bool = False,
                        full_auto: bool = False, top_n: int = 20,
                        bypass_dedup: bool = False, api_mode: bool = False):
    settings = load_settings()
    base_path = get_base_path(settings)
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total = (end - start).days + 1
    current = start
    done = 0
    errors = []

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        done += 1
        print(f"\n{'='*60}")
        print(f"[backfill {done}/{total}] {date_str}")
        print(f"{'='*60}")

        if full_auto:
            month_name = f"{current.month:02d}_{calendar.month_name[current.month]}"
            year = current.strftime("%Y")
            digest_path = (Path(base_path) / year / month_name / date_str
                           / f"daily-report-{date_str}.md")
            if digest_path.exists():
                print(f"[skip] Already done: {digest_path.name}")
                current += timedelta(days=1)
                continue
            try:
                run_full_auto(date_str, top_n=top_n, bypass_dedup=bypass_dedup,
                              api_mode=api_mode)
            except Exception as e:
                msg = f"[ERROR] {date_str}: {e}"
                print(msg, file=sys.stderr)
                errors.append(msg)
        else:
            try:
                prepare_day(date_str, dry_run)
            except Exception as e:
                msg = f"[ERROR] {date_str}: {e}"
                print(msg, file=sys.stderr)
                errors.append(msg)

        current += timedelta(days=1)
        time.sleep(5)

    print(f"\n{'='*60}")
    print(f"Backfill complete: {done} days processed, {len(errors)} errors")
    if errors:
        print("Errors:")
        for e in errors:
            print(f"  {e}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Paper Daily - Main orchestrator")
    parser.add_argument("--date", default="today",
                        help="Target date (YYYY-MM-DD, 'today', 'yesterday')")
    parser.add_argument("--date-range", nargs=2, metavar=("START", "END"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--full-auto", action="store_true",
                        help="Run full pipeline: fetch -> score -> deep-read -> digest")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--force-deepread", action="store_true")
    parser.add_argument("--mark-done", nargs="+",
                        help="DATE ARXIV_ID1 ARXIV_ID2 ...")
    parser.add_argument("--output-json", help="Save prepared.json to this path")
    parser.add_argument("--bypass-dedup", action="store_true",
                        help="Skip dedup filter (use all fetched papers); for reprocessing dates")
    parser.add_argument("--api-mode", action="store_true",
                        help="Use Claude API to auto-generate deep-read notes and digest (for backfill)")
    args = parser.parse_args()

    if args.date == "today":
        target_date = datetime.now().strftime("%Y-%m-%d")
    elif args.date == "yesterday":
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        target_date = args.date

    if args.date_range:
        backfill_date_range(args.date_range[0], args.date_range[1], args.dry_run,
                            full_auto=args.full_auto, top_n=args.top_n,
                            bypass_dedup=args.bypass_dedup, api_mode=args.api_mode)
    elif args.mark_done:
        mark_papers_done(args.mark_done[0], args.mark_done[1:])
    elif args.full_auto:
        run_full_auto(target_date, top_n=args.top_n, force_deepread=args.force_deepread,
                      bypass_dedup=args.bypass_dedup, api_mode=args.api_mode)
    else:
        result = prepare_day(target_date, args.dry_run, bypass_dedup=args.bypass_dedup)
        if args.output_json:
            with open(args.output_json, "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
