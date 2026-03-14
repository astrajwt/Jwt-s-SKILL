#!/usr/bin/env python3
"""
file_manager.py - Directory structure management for paper-daily.
"""
import calendar
import json
from datetime import datetime
from pathlib import Path


def get_base_path(settings: dict) -> str:
    vault = settings.get("vault_base", "")
    output = settings.get("paper_daily_output", "03_Papers/PaperDaily")
    return str(Path(vault) / output)


def get_db_path(settings: dict, base_path: str = None) -> Path:
    if base_path is None:
        base_path = get_base_path(settings)
    vault = settings.get("vault_base", "")
    db_rel = settings.get("db_path", "03_Papers/PaperDaily/.db/papers.db")
    return Path(vault) / db_rel


def get_log_path(settings: dict, base_path: str = None) -> Path:
    vault = settings.get("vault_base", "")
    log_rel = settings.get("log_path", "03_Papers/PaperDaily/.logs")
    return Path(vault) / log_rel


def get_date_paths(date_str: str, base_path: str) -> dict:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.strftime("%Y")
    month_name = f"{dt.month:02d}_{calendar.month_name[dt.month]}"

    day_root = Path(base_path) / year / month_name / date_str
    return {
        "day_root": str(day_root),
        "deep_reads": str(day_root / "deep-reads"),
        "daily_report": str(day_root / f"daily-report-{date_str}.md"),
        "scoring_json": str(day_root / "scoring.json"),
        "year": year,
        "month": month_name,
        "date": date_str,
    }


def setup_date_dirs(date_str: str, base_path: str) -> dict:
    paths = get_date_paths(date_str, base_path)
    Path(paths["deep_reads"]).mkdir(parents=True, exist_ok=True)
    return paths


def check_report_needed(date_str: str) -> dict:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return {
        "weekly": dt.weekday() == 6,  # Sunday
        "monthly": dt.day == 1,
        "quarterly": dt.day == 1 and dt.month in [1, 4, 7, 10],
    }


if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--date", default="today")
    args = parser.parse_args()

    config_dir = Path(__file__).parent.parent / "config"
    with open(config_dir / "settings.json") as f:
        settings = json.load(f)

    if args.date == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = args.date

    base = get_base_path(settings)
    if args.setup:
        paths = setup_date_dirs(date_str, base)
        print(f"Created dirs for {date_str}: {paths['day_root']}")
    else:
        paths = get_date_paths(date_str, base)
        print(json.dumps(paths, indent=2))
