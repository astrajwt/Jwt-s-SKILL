#!/usr/bin/env python3
"""
notion_sync.py - Sync paper-daily output to Notion.

Pushes daily reports, deep reads, and aggregate reports as Notion pages.

Setup (.env):
    NOTION_TOKEN=ntn_...          # Notion integration token
    NOTION_ROOT_PAGE_ID=xxxxxxxx  # Root Notion page ID (PaperDaily root)

Usage:
    python notion_sync.py --date 2026-03-07
    python notion_sync.py --date 2026-03-07 --type daily
    python notion_sync.py --date 2026-03-07 --type all
    python notion_sync.py --date-range 2023-01-01 2026-03-07
"""

import argparse
import calendar
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
CONFIG_DIR = SCRIPTS_DIR.parent / "config"
sys.path.insert(0, str(SCRIPTS_DIR))

# Load .env
_env_file = SCRIPTS_DIR.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from file_manager import get_date_paths, get_base_path


# ─── Notion API ───────────────────────────────────────────────────────────────

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _notion_token() -> str:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise RuntimeError(
            "[ERROR] NOTION_TOKEN not set.\n"
            "Add to .env:  NOTION_TOKEN=ntn_...\n"
            "Create at: https://www.notion.so/my-integrations"
        )
    return token


def _notion_root_page() -> str:
    page_id = os.environ.get("NOTION_ROOT_PAGE_ID", "")
    if not page_id:
        raise RuntimeError(
            "[ERROR] NOTION_ROOT_PAGE_ID not set.\n"
            "Add to .env:  NOTION_ROOT_PAGE_ID=<32-char UUID from Notion page URL>"
        )
    return page_id.replace("-", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_notion_token()}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _post(endpoint: str, payload: dict) -> dict:
    url = f"{NOTION_API}{endpoint}"
    if HAS_REQUESTS:
        r = _req.post(url, headers=_headers(), json=payload, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Notion API {r.status_code}: {r.text[:400]}")
        return r.json()
    else:
        import urllib.request, urllib.error
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers=_headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


def _patch(endpoint: str, payload: dict) -> dict:
    url = f"{NOTION_API}{endpoint}"
    if HAS_REQUESTS:
        r = _req.patch(url, headers=_headers(), json=payload, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Notion API {r.status_code}: {r.text[:400]}")
        return r.json()
    else:
        import urllib.request
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, method="PATCH", headers=_headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


def _get(endpoint: str, params: dict = None) -> dict:
    url = f"{NOTION_API}{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    if HAS_REQUESTS:
        r = _req.get(url, headers=_headers(), timeout=30)
        if not r.ok:
            raise RuntimeError(f"Notion API {r.status_code}: {r.text[:400]}")
        return r.json()
    else:
        import urllib.request
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


# ─── Page cache (title → page_id) ────────────────────────────────────────────

_page_cache: dict = {}


def _find_child_page(parent_id: str, title: str) -> str | None:
    """Find a child page by title under a parent. Returns page_id or None."""
    cache_key = f"{parent_id}/{title}"
    if cache_key in _page_cache:
        return _page_cache[cache_key]
    try:
        data = _post(f"/blocks/{parent_id}/children", {})
        # Actually need GET for listing children
        data = _get(f"/blocks/{parent_id}/children", {"page_size": "100"})
        for block in data.get("results", []):
            if block.get("type") == "child_page":
                block_title = block["child_page"].get("title", "")
                if block_title == title:
                    pid = block["id"]
                    _page_cache[cache_key] = pid
                    return pid
    except Exception:
        pass
    return None


def _get_or_create_page(parent_id: str, title: str) -> str:
    """Get or create a child page with given title under parent. Returns page_id."""
    existing = _find_child_page(parent_id, title)
    if existing:
        return existing

    payload = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "children": [],
    }
    result = _post("/pages", payload)
    pid = result["id"]
    cache_key = f"{parent_id}/{title}"
    _page_cache[cache_key] = pid
    print(f"  [notion] Created page: {title}")
    return pid


# ─── Markdown → Notion blocks ────────────────────────────────────────────────

def _text(content: str, bold: bool = False, link: str = None) -> dict:
    obj = {"type": "text", "text": {"content": content}}
    if link:
        obj["text"]["link"] = {"url": link}
    if bold:
        obj["annotations"] = {"bold": True}
    return obj


def _parse_inline(text: str) -> list:
    """Parse inline markdown (bold, links) into Notion rich_text objects."""
    parts = []
    # Match [text](url) and **bold**
    pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*')
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            parts.append(_text(text[last:m.start()]))
        if m.group(1):  # link
            parts.append(_text(m.group(1), link=m.group(2)))
        elif m.group(3):  # bold
            parts.append(_text(m.group(3), bold=True))
        last = m.end()
    if last < len(text):
        parts.append(_text(text[last:]))
    return parts or [_text("")]


def md_to_blocks(md: str, max_blocks: int = 95) -> list:
    """Convert markdown text to Notion block objects (simplified)."""
    blocks = []
    lines = md.splitlines()
    i = 0
    while i < len(lines) and len(blocks) < max_blocks:
        line = lines[i]

        # Heading
        if line.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                           "heading_3": {"rich_text": _parse_inline(line[4:])}})
        elif line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                           "heading_2": {"rich_text": _parse_inline(line[3:])}})
        elif line.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1",
                           "heading_1": {"rich_text": _parse_inline(line[2:])}})
        # Horizontal rule
        elif line.strip() in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        # Bullet list
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": _parse_inline(line[2:])}})
        # Blockquote
        elif line.startswith("> "):
            blocks.append({"object": "block", "type": "quote",
                           "quote": {"rich_text": _parse_inline(line[2:])}})
        # Table row (simplified: render as paragraph)
        elif line.startswith("|") and "|" in line[1:]:
            if not re.match(r'^\|[-| :]+\|$', line.strip()):
                blocks.append({"object": "block", "type": "paragraph",
                               "paragraph": {"rich_text": _parse_inline(line)}})
        # Empty line
        elif not line.strip():
            pass  # skip empty lines
        # Normal paragraph
        else:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": _parse_inline(line)}})
        i += 1
    return blocks


def _upload_content(page_id: str, content: str):
    """Replace page content with markdown-converted blocks."""
    # Notion limits 100 blocks per request; split if needed
    blocks = md_to_blocks(content, max_blocks=95)

    # Append in chunks of 95
    for chunk_start in range(0, len(blocks), 95):
        chunk = blocks[chunk_start:chunk_start + 95]
        _patch(f"/blocks/{page_id}/children", {"children": chunk})
        if chunk_start + 95 < len(blocks):
            time.sleep(0.3)


def _clear_page(page_id: str):
    """Delete all children of a page (for update/overwrite)."""
    data = _get(f"/blocks/{page_id}/children", {"page_size": "100"})
    for block in data.get("results", []):
        try:
            if HAS_REQUESTS:
                _req.delete(f"{NOTION_API}/blocks/{block['id']}", headers=_headers())
            # skip if not requests
        except Exception:
            pass


# ─── Sync functions ───────────────────────────────────────────────────────────

def _load_settings() -> dict:
    with open(CONFIG_DIR / "settings.json") as f:
        return json.load(f)


def sync_daily_report(date_str: str, force: bool = False) -> bool:
    """Sync a daily report to Notion. Returns True if synced."""
    settings = _load_settings()
    base_path = get_base_path(settings)
    paths = get_date_paths(date_str, base_path)
    report_path = Path(paths["daily_report"])

    if not report_path.exists():
        print(f"  [skip] No daily report for {date_str}")
        return False

    content = report_path.read_text(encoding="utf-8")
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.strftime("%Y")
    month = paths["month"]  # e.g. "01_January"

    root = _notion_root_page()
    year_page = _get_or_create_page(root, year)
    month_page = _get_or_create_page(year_page, month)
    day_page_title = f"日报 {date_str}"
    day_page = _get_or_create_page(month_page, day_page_title)

    if force:
        _clear_page(day_page)
    _upload_content(day_page, content)
    print(f"  [notion] Synced daily report: {date_str}")
    return True


def sync_deep_reads(date_str: str, force: bool = False) -> int:
    """Sync all deep reads for a date. Returns count synced."""
    settings = _load_settings()
    base_path = get_base_path(settings)
    paths = get_date_paths(date_str, base_path)
    deep_reads_dir = Path(paths["deep_reads"])

    if not deep_reads_dir.exists():
        return 0

    md_files = list(deep_reads_dir.glob("*_deepread.md"))
    if not md_files:
        return 0

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.strftime("%Y")
    month = paths["month"]

    root = _notion_root_page()
    year_page = _get_or_create_page(root, year)
    month_page = _get_or_create_page(year_page, month)
    day_page = _get_or_create_page(month_page, f"日报 {date_str}")
    deep_reads_page = _get_or_create_page(day_page, "精读笔记")

    count = 0
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        # Extract title from frontmatter or first heading
        title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
        page_title = title_match.group(1)[:100] if title_match else md_file.stem[:100]

        note_page = _get_or_create_page(deep_reads_page, page_title)
        if force:
            _clear_page(note_page)
        _upload_content(note_page, content)
        count += 1
        time.sleep(0.2)

    if count:
        print(f"  [notion] Synced {count} deep reads: {date_str}")
    return count


def sync_aggregate_report(report_path: Path, force: bool = False) -> bool:
    """Sync a weekly/monthly/quarterly/yearly report to Notion."""
    if not report_path.exists():
        return False

    content = report_path.read_text(encoding="utf-8")
    name = report_path.stem  # e.g. weekly-report-2023-W01

    # Determine year from filename
    year_match = re.search(r'(\d{4})', name)
    year = year_match.group(1) if year_match else "Unknown"

    root = _notion_root_page()
    year_page = _get_or_create_page(root, year)

    # Determine report category
    if "weekly" in name:
        container = _get_or_create_page(year_page, "周报")
    elif "monthly" in name:
        container = _get_or_create_page(year_page, "月报")
    elif "quarterly" in name:
        container = _get_or_create_page(year_page, "季报")
    elif "yearly" in name:
        container = year_page
    else:
        container = year_page

    page = _get_or_create_page(container, name)
    if force:
        _clear_page(page)
    _upload_content(page, content)
    print(f"  [notion] Synced aggregate: {name}")
    return True


def sync_date(date_str: str, force: bool = False):
    """Sync all content for a given date (daily report + deep reads + any aggregate reports)."""
    settings = _load_settings()
    base_path = get_base_path(settings)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.strftime("%Y")
    paths = get_date_paths(date_str, base_path)
    month = paths["month"]

    sync_daily_report(date_str, force=force)
    sync_deep_reads(date_str, force=force)

    # Sync aggregate reports that live at year/month level
    year_dir = Path(base_path) / year
    month_dir = year_dir / month

    for pattern in [
        month_dir / f"weekly-report-*.md",
        year_dir / f"monthly-report-{year}-{dt.month:02d}.md",
        year_dir / f"quarterly-report-{year}-Q{(dt.month-1)//3+1}.md",
        year_dir / f"yearly-report-{year}.md",
    ]:
        if isinstance(pattern, Path) and pattern.exists():
            sync_aggregate_report(pattern, force=force)
        elif isinstance(pattern, Path):
            pass
        else:
            for p in year_dir.glob(str(pattern)):
                sync_aggregate_report(p, force=force)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync paper-daily output to Notion")
    parser.add_argument("--date", default="today")
    parser.add_argument("--date-range", nargs=2, metavar=("START", "END"))
    parser.add_argument("--force", action="store_true", help="Overwrite existing pages")
    args = parser.parse_args()

    if args.date_range:
        start = datetime.strptime(args.date_range[0], "%Y-%m-%d")
        end = datetime.strptime(args.date_range[1], "%Y-%m-%d")
        cur = start
        while cur <= end:
            date_str = cur.strftime("%Y-%m-%d")
            print(f"[sync] {date_str}")
            try:
                sync_date(date_str, force=args.force)
            except Exception as e:
                print(f"  [ERROR] {date_str}: {e}", file=sys.stderr)
            cur += timedelta(days=1)
            time.sleep(0.5)
    else:
        if args.date == "today":
            date_str = datetime.now().strftime("%Y-%m-%d")
        elif args.date == "yesterday":
            date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            date_str = args.date
        print(f"[sync] {date_str}")
        sync_date(date_str, force=args.force)


if __name__ == "__main__":
    main()
