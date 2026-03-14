#!/usr/bin/env python3
"""
report_aggregator.py - Aggregate daily reports into weekly/monthly/quarterly/yearly summaries.

Usage:
    python report_aggregator.py --type weekly --date 2026-03-09
    python report_aggregator.py --type monthly --date 2026-03-31
    python report_aggregator.py --type quarterly --date 2026-03-31
    python report_aggregator.py --type yearly --date 2026-12-31
    python report_aggregator.py --type auto --date today   # auto-detect
"""

import argparse
import calendar
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
CONFIG_DIR = SCRIPTS_DIR.parent / "config"

from api_client import call_claude, load_prompt_template
from file_manager import get_date_paths, get_base_path


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.json") as f:
        return json.load(f)


def get_report_output_path(report_type: str, date_str: str, base_path: str) -> Path:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = str(dt.year)
    month_name = f"{dt.month:02d}_{calendar.month_name[dt.month]}"
    base = Path(base_path)

    if report_type == "weekly":
        iso_week = dt.isocalendar()[1]
        return base / year / month_name / f"weekly-report-{year}-W{iso_week:02d}.md"
    elif report_type == "monthly":
        return base / year / f"monthly-report-{year}-{dt.month:02d}.md"
    elif report_type == "quarterly":
        quarter = (dt.month - 1) // 3 + 1
        return base / year / f"quarterly-report-{year}-Q{quarter}.md"
    elif report_type == "yearly":
        return base / year / f"yearly-report-{year}.md"
    else:
        raise ValueError(f"Unknown report type: {report_type}")


def extract_section(report_text: str, section_keyword: str) -> str:
    """Extract a section's content from a daily report."""
    pattern = rf"##[^#].*?{re.escape(section_keyword)}.*?\n(.*?)(?=\n---|\n##[^#]|\Z)"
    m = re.search(pattern, report_text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def summarize_daily_report(date_str: str, report_text: str, max_chars: int = 2000) -> str:
    """Extract narrative + pulse + quality sections from a daily report."""
    story = extract_section(report_text, "今日叙事")
    pulse = extract_section(report_text, "研究温度计")
    quality = extract_section(report_text, "今日批次质量")

    parts = [f"### {date_str}"]
    if story:
        parts.append(f"**叙事**: {story[:600]}")
    if pulse:
        pulse_lines = "\n".join(pulse.strip().splitlines()[:8])
        parts.append(f"**温度计**:\n{pulse_lines}")
    if quality:
        parts.append(f"**批次质量**: {quality[:400]}")

    return "\n\n".join(parts)[:max_chars]


def collect_daily_summaries(dates: list, base_path: str, max_per_day: int = 2000) -> str:
    """Collect summarized daily reports for a list of dates."""
    summaries = []
    missing = []

    for date_str in dates:
        paths = get_date_paths(date_str, base_path)
        report_path = Path(paths["daily_report"])
        if report_path.exists():
            text = report_path.read_text(encoding="utf-8")
            summaries.append(summarize_daily_report(date_str, text, max_chars=max_per_day))
        else:
            missing.append(date_str)

    if missing:
        print(f"  [INFO] No report for: {', '.join(missing)}")

    return "\n\n---\n\n".join(summaries)


def collect_report_files(paths_list: list, max_per_file: int = 3000) -> str:
    """Read and concatenate existing report files, truncated."""
    parts = []
    for p in paths_list:
        path = Path(p)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            parts.append(f"# {path.stem}\n\n{text[:max_per_file]}")
    return "\n\n---\n\n".join(parts)


def get_week_dates(date_str: str) -> list:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    return [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def get_month_dates(date_str: str) -> list:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    days_in_month = calendar.monthrange(dt.year, dt.month)[1]
    return [dt.replace(day=d).strftime("%Y-%m-%d") for d in range(1, days_in_month + 1)]


def get_quarter_dates(date_str: str) -> list:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    q = (dt.month - 1) // 3 + 1
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    end_day = calendar.monthrange(dt.year, end_month)[1]
    start = datetime(dt.year, start_month, 1)
    end = datetime(dt.year, end_month, end_day)
    dates = []
    cur = start
    while cur <= end:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


# ─── Report runners ───────────────────────────────────────────────────────────

def run_weekly_report(date_str: str, base_path: str, output_path: Path) -> str:
    dates = get_week_dates(date_str)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    iso_week = dt.isocalendar()[1]
    year = dt.year

    print(f"[weekly] Collecting {dates[0]} → {dates[-1]}")
    content_in = collect_daily_summaries(dates, base_path, max_per_day=2500)
    if not content_in.strip():
        print("[weekly] No daily reports found, skipping")
        return ""

    prompt = load_prompt_template("weekly_report.txt")
    prompt = prompt.replace("{{week}}", f"{year}-W{iso_week:02d}")
    prompt = prompt.replace("{{week_start}}", dates[0])
    prompt = prompt.replace("{{week_end}}", dates[-1])
    prompt = prompt.replace("{{daily_summaries}}", content_in)

    print("[weekly] Calling Claude API...")
    result = call_claude(prompt, max_tokens=2048, temperature=0.4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"[weekly] Written → {output_path}")
    return str(output_path)


def run_monthly_report(date_str: str, base_path: str, output_path: Path) -> str:
    dates = get_month_dates(date_str)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    month_label = f"{dt.year}-{dt.month:02d} ({calendar.month_name[dt.month]})"

    print(f"[monthly] Collecting {len(dates)} days")
    content_in = collect_daily_summaries(dates, base_path, max_per_day=1200)
    if not content_in.strip():
        print("[monthly] No daily reports found, skipping")
        return ""

    prompt = load_prompt_template("monthly_report.txt")
    prompt = prompt.replace("{{month}}", month_label)
    prompt = prompt.replace("{{month_start}}", dates[0])
    prompt = prompt.replace("{{month_end}}", dates[-1])
    prompt = prompt.replace("{{daily_summaries}}", content_in)

    print("[monthly] Calling Claude API...")
    result = call_claude(prompt, max_tokens=2048, temperature=0.4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"[monthly] Written → {output_path}")
    return str(output_path)


def run_quarterly_report(date_str: str, base_path: str, output_path: Path) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    quarter = (dt.month - 1) // 3 + 1
    quarter_label = f"{dt.year}-Q{quarter}"
    start_month = (quarter - 1) * 3 + 1

    monthly_paths = [
        str(Path(base_path) / str(dt.year) / f"monthly-report-{dt.year}-{m:02d}.md")
        for m in range(start_month, start_month + 3)
    ]
    content_in = collect_report_files(monthly_paths, max_per_file=3500)

    if not content_in.strip():
        print("[quarterly] Monthly reports missing, falling back to daily summaries")
        dates = get_quarter_dates(date_str)
        content_in = collect_daily_summaries(dates, base_path, max_per_day=400)

    if not content_in.strip():
        print("[quarterly] No data found, skipping")
        return ""

    prompt = load_prompt_template("quarterly_report.txt")
    prompt = prompt.replace("{{quarter}}", quarter_label)
    prompt = prompt.replace("{{monthly_reports}}", content_in)

    print("[quarterly] Calling Claude API...")
    result = call_claude(prompt, max_tokens=3000, temperature=0.4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"[quarterly] Written → {output_path}")
    return str(output_path)


def run_yearly_report(date_str: str, base_path: str, output_path: Path) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.year

    quarterly_paths = [
        str(Path(base_path) / str(year) / f"quarterly-report-{year}-Q{q}.md")
        for q in range(1, 5)
    ]
    content_in = collect_report_files(quarterly_paths, max_per_file=4000)

    if not content_in.strip():
        monthly_paths = [
            str(Path(base_path) / str(year) / f"monthly-report-{year}-{m:02d}.md")
            for m in range(1, 13)
        ]
        content_in = collect_report_files(monthly_paths, max_per_file=2000)

    if not content_in.strip():
        print("[yearly] No quarterly/monthly reports found, skipping")
        return ""

    prompt = load_prompt_template("yearly_report.txt")
    prompt = prompt.replace("{{year}}", str(year))
    prompt = prompt.replace("{{source_reports}}", content_in)

    print("[yearly] Calling Claude API...")
    result = call_claude(prompt, max_tokens=3000, temperature=0.4)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"[yearly] Written → {output_path}")
    return str(output_path)


# ─── Auto-detect ──────────────────────────────────────────────────────────────

def run_auto(date_str: str, force: bool = False) -> list:
    """Auto-detect which reports to generate for the given date."""
    settings = load_settings()
    base_path = get_base_path(settings)

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    last_dom = calendar.monthrange(dt.year, dt.month)[1]

    needs = {
        "weekly":    dt.weekday() == 6,                            # Sunday
        "monthly":   dt.day == last_dom,                           # last day of month
        "quarterly": dt.day == last_dom and dt.month in [3,6,9,12],
        "yearly":    dt.month == 12 and dt.day == 31,
    }

    print(f"[auto] {date_str} — " +
          " | ".join(f"{k}: {'YES' if v else 'no'}" for k, v in needs.items()))

    runners = {
        "weekly": run_weekly_report,
        "monthly": run_monthly_report,
        "quarterly": run_quarterly_report,
        "yearly": run_yearly_report,
    }

    generated = []
    for rtype, needed in needs.items():
        if not needed:
            continue
        out = get_report_output_path(rtype, date_str, base_path)
        if out.exists() and not force:
            print(f"[{rtype}] Already exists: {out.name}")
            continue
        result = runners[rtype](date_str, base_path, out)
        if result:
            generated.append(result)

    return generated


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate aggregated paper reports")
    parser.add_argument("--type", choices=["weekly", "monthly", "quarterly", "yearly", "auto"],
                        default="auto")
    parser.add_argument("--date", default="today")
    parser.add_argument("--output", help="Override output path")
    parser.add_argument("--force", action="store_true", help="Overwrite existing report")
    args = parser.parse_args()

    if args.date == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif args.date == "yesterday":
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        date_str = args.date

    settings = load_settings()
    base_path = get_base_path(settings)

    if args.type == "auto":
        run_auto(date_str, force=args.force)
        return

    out = Path(args.output) if args.output else get_report_output_path(args.type, date_str, base_path)
    if out.exists() and not args.force:
        print(f"[{args.type}] Already exists (use --force to overwrite): {out}")
        return

    runners = {
        "weekly": run_weekly_report,
        "monthly": run_monthly_report,
        "quarterly": run_quarterly_report,
        "yearly": run_yearly_report,
    }
    runners[args.type](date_str, base_path, out)


if __name__ == "__main__":
    main()
