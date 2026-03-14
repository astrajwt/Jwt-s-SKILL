#!/usr/bin/env python3
"""
download_pdfs.py - Download arxiv PDFs for paper-daily pipeline.

Usage:
    python download_pdfs.py --arxiv-id 2503.18773 --output-dir /path/to/pdfs/
    python download_pdfs.py --arxiv-ids 2503.18773 2503.12345 --output-dir /path/to/pdfs/
"""

import argparse
import os
import ssl
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


def _ssl_ctx():
    for cert_path in ["/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"]:
        if os.path.exists(cert_path):
            return ssl.create_default_context(cafile=cert_path)
    return ssl._create_unverified_context()


def download_pdf(arxiv_id: str, pdf_dir: str, timeout: int = 90, retries: int = 2) -> str:
    """
    Download arxiv PDF to pdf_dir/{arxiv_id}.pdf.
    Returns local path on success, empty string on failure.
    Skips download if file already exists and is >10KB.
    """
    pdf_dir = Path(pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    out_path = pdf_dir / f"{arxiv_id}.pdf"
    if out_path.exists() and out_path.stat().st_size > 10 * 1024:
        print(f"  [PDF] Cache hit: {arxiv_id} ({out_path.stat().st_size // 1024} KB)")
        return str(out_path)

    url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (paper-daily-bot; research use)"},
    )
    ctx = _ssl_ctx()

    for attempt in range(retries + 1):
        if attempt > 0:
            wait = 5 * attempt
            print(f"  [PDF] Retry {attempt}/{retries} in {wait}s...")
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                data = resp.read()
            if len(data) < 10 * 1024:
                print(f"  [WARN] PDF suspiciously small ({len(data)} bytes): {arxiv_id}")
                return ""
            out_path.write_bytes(data)
            print(f"  [PDF] Downloaded {arxiv_id} → {out_path.name} ({len(data) // 1024} KB)")
            return str(out_path)
        except (urllib.error.URLError, OSError) as e:
            print(f"  [WARN] PDF download failed (attempt {attempt + 1}): {e}")

    return ""


def download_pdfs_batch(arxiv_ids: list, pdf_dir: str, delay: float = 3.0) -> dict:
    """
    Download PDFs for a list of arxiv IDs.
    Returns {arxiv_id: local_path_or_empty_string} dict.
    """
    results = {}
    for i, arxiv_id in enumerate(arxiv_ids):
        print(f"  [{i + 1}/{len(arxiv_ids)}] Downloading PDF: {arxiv_id}")
        path = download_pdf(arxiv_id, pdf_dir)
        results[arxiv_id] = path
        if i < len(arxiv_ids) - 1:
            time.sleep(delay)
    return results


def main():
    parser = argparse.ArgumentParser(description="Download arxiv PDFs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--arxiv-id", help="Single arxiv ID (e.g. 2503.18773)")
    group.add_argument("--arxiv-ids", nargs="+", help="Multiple arxiv IDs")
    parser.add_argument("--output-dir", required=True, help="Directory to save PDFs")
    args = parser.parse_args()

    ids = [args.arxiv_id] if args.arxiv_id else args.arxiv_ids
    results = download_pdfs_batch(ids, args.output_dir)

    ok = sum(1 for v in results.values() if v)
    print(f"\n[done] {ok}/{len(ids)} PDFs downloaded → {args.output_dir}")


if __name__ == "__main__":
    main()
