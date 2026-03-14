#!/usr/bin/env python3
"""
dedup.py - SQLite deduplication database for paper-daily pipeline.

Schema:
  seen_papers: arxiv_id, first_seen, times_trending, summarized, deep_read
  run_log: date, fetched, new, skipped, deep_reads, created_at
"""

import sqlite3
from datetime import datetime
from pathlib import Path


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize (or open) the SQLite dedup database."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_papers (
            arxiv_id      TEXT PRIMARY KEY,
            first_seen    TEXT NOT NULL,
            times_trending INTEGER DEFAULT 0,
            summarized    INTEGER DEFAULT 0,
            deep_read     INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            fetched    INTEGER DEFAULT 0,
            new        INTEGER DEFAULT 0,
            skipped    INTEGER DEFAULT 0,
            deep_reads INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def filter_new_papers(
    conn: sqlite3.Connection,
    papers: list,
    date_str: str,
    max_trending_count: int = 3,
) -> tuple:
    """
    Split papers into (new_papers, skipped_papers).

    - Papers not in DB → new
    - HF trending papers seen > max_trending_count times → skipped
    - Non-trending papers already seen → skipped
    """
    new_papers = []
    skipped = []
    now = datetime.now().isoformat()

    for paper in papers:
        arxiv_id = paper.get("arxiv_id", "")
        if not arxiv_id:
            new_papers.append(paper)
            continue

        hf_trending = paper.get("hf_trending", False)

        row = conn.execute(
            "SELECT times_trending, summarized FROM seen_papers WHERE arxiv_id = ?",
            (arxiv_id,)
        ).fetchone()

        if row is None:
            # Never seen → insert and include
            conn.execute(
                "INSERT INTO seen_papers (arxiv_id, first_seen, times_trending) VALUES (?, ?, ?)",
                (arxiv_id, date_str, 1 if hf_trending else 0)
            )
            new_papers.append(paper)
        else:
            times_trending, summarized = row
            if hf_trending:
                new_count = times_trending + 1
                conn.execute(
                    "UPDATE seen_papers SET times_trending = ? WHERE arxiv_id = ?",
                    (new_count, arxiv_id)
                )
                if new_count > max_trending_count:
                    skipped.append(arxiv_id)
                else:
                    new_papers.append(paper)
            else:
                # Already seen non-trending paper → skip
                skipped.append(arxiv_id)

    conn.commit()
    return new_papers, skipped


def mark_summarized(conn: sqlite3.Connection, arxiv_id: str):
    conn.execute(
        "UPDATE seen_papers SET summarized = 1 WHERE arxiv_id = ?",
        (arxiv_id,)
    )
    conn.commit()


def mark_deep_read(conn: sqlite3.Connection, arxiv_id: str):
    conn.execute(
        "UPDATE seen_papers SET deep_read = 1 WHERE arxiv_id = ?",
        (arxiv_id,)
    )
    conn.commit()


def log_run(conn: sqlite3.Connection, date_str: str, fetched: int,
            new: int, skipped: int, deep_reads: int):
    conn.execute(
        "INSERT INTO run_log (date, fetched, new, skipped, deep_reads) VALUES (?, ?, ?, ?, ?)",
        (date_str, fetched, new, skipped, deep_reads)
    )
    conn.commit()
