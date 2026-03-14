#!/usr/bin/env python3
"""
figure_extractor.py - Extract figures from arxiv PDFs using pdfimages (poppler).

Requires: pdfimages (brew install poppler)

Usage:
    python figure_extractor.py --pdf /path/to/paper.pdf --arxiv-id 2503.18773 \
        --output-dir /path/to/deep-reads/
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# pdfimages from poppler (installed via brew)
_PDFIMAGES_CANDIDATES = [
    "/opt/homebrew/bin/pdfimages",
    "/usr/local/bin/pdfimages",
    "/usr/bin/pdfimages",
]
PDFIMAGES = shutil.which("pdfimages") or next(
    (p for p in _PDFIMAGES_CANDIDATES if os.path.exists(p)), None
)


def check_pdfimages() -> bool:
    return bool(PDFIMAGES) and os.path.exists(PDFIMAGES)


def extract_figures(
    pdf_path: str,
    arxiv_id: str,
    figures_root: str,
    max_figures: int = 8,
    min_size_kb: int = 20,
) -> list:
    """
    Extract figures from a PDF using pdfimages.

    Saves PNGs to {figures_root}/{arxiv_id}/fig-{page}-{n}.png
    Filters out images smaller than min_size_kb (logos, icons).
    Returns list of Path objects sorted by page order, capped at max_figures.

    Strategy: extract ALL images, sort by file size descending (larger = likely
    real figures, not decorative), keep top max_figures, then re-sort by page.
    """
    if not check_pdfimages():
        print(f"  [WARN] pdfimages not found at {PDFIMAGES}, skipping figure extraction")
        print(f"         Install with: brew install poppler")
        return []

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"  [WARN] PDF not found: {pdf_path}")
        return []

    fig_dir = Path(figures_root) / arxiv_id
    fig_dir.mkdir(parents=True, exist_ok=True)

    # Skip if already extracted
    existing = sorted(fig_dir.glob("*.png"))
    if existing:
        filtered = [f for f in existing if f.stat().st_size >= min_size_kb * 1024]
        filtered.sort(key=lambda x: x.stat().st_size, reverse=True)
        top = filtered[:max_figures]
        top.sort(key=lambda x: x.name)
        print(f"  [Figures] Cache hit: {len(existing)} imgs, using {len(top)} figures")
        return top

    # Run pdfimages: extract all embedded images as PNG with page numbers
    # Timeout scales with PDF size: 60s base + 10s per MB, max 300s
    pdf_size_mb = pdf_path.stat().st_size / (1024 * 1024)
    timeout = min(300, max(60, int(60 + pdf_size_mb * 10)))
    prefix = str(fig_dir / "fig")
    try:
        result = subprocess.run(
            [PDFIMAGES, "-png", "-p", str(pdf_path), prefix],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  [WARN] pdfimages timed out after {timeout}s for {arxiv_id} ({pdf_size_mb:.0f}MB), skipping figures")
        return []

    if result.returncode != 0:
        print(f"  [WARN] pdfimages failed for {arxiv_id}: {result.stderr[:300]}")
        return []

    all_images = sorted(fig_dir.glob("*.png"))
    if not all_images:
        print(f"  [Figures] No images extracted from {arxiv_id}")
        return []

    # Filter by minimum file size
    filtered = [img for img in all_images if img.stat().st_size >= min_size_kb * 1024]

    # Sort by size descending (larger images are more likely to be real figures)
    filtered.sort(key=lambda x: x.stat().st_size, reverse=True)
    top = filtered[:max_figures]

    # Re-sort by filename = page order for logical reading order in the note
    top.sort(key=lambda x: x.name)

    total_kb = sum(f.stat().st_size for f in top) // 1024
    print(
        f"  [Figures] {len(all_images)} extracted, "
        f"{len(filtered)} ≥{min_size_kb}KB, "
        f"keeping {len(top)} ({total_kb} KB total)"
    )
    return top


def build_figures_section(figures: list, note_dir: str) -> str:
    """
    Build a markdown "关键图表" section for a deep-read note.

    note_dir: directory where the .md file lives (for computing relative paths).
    Returns markdown string to append, or empty string if no figures.
    """
    if not figures:
        return ""

    note_dir = Path(note_dir)
    lines = ["\n\n---\n\n## 关键图表 / Key Figures\n"]

    for i, fig_path in enumerate(figures, 1):
        fig_path = Path(fig_path)
        try:
            rel = fig_path.relative_to(note_dir)
            img_ref = str(rel)
        except ValueError:
            img_ref = str(fig_path)

        size_kb = fig_path.stat().st_size // 1024
        lines.append(f"![Figure {i} ({size_kb} KB)]({img_ref})\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Extract figures from arxiv PDF")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--arxiv-id", required=True, help="arxiv ID (e.g. 2503.18773)")
    parser.add_argument("--output-dir", required=True,
                        help="Root dir for figures (saves to output-dir/{arxiv_id}/)")
    parser.add_argument("--max-figures", type=int, default=8)
    parser.add_argument("--min-size-kb", type=int, default=20)
    args = parser.parse_args()

    figures = extract_figures(
        args.pdf, args.arxiv_id, args.output_dir,
        max_figures=args.max_figures, min_size_kb=args.min_size_kb,
    )

    if figures:
        print(f"\nExtracted {len(figures)} figures:")
        for f in figures:
            print(f"  {f}")
    else:
        print("No figures extracted.")


if __name__ == "__main__":
    main()
