#!/usr/bin/env python3
"""
Render a finished (fully-solved) crossword board from a puzzle.json to a PNG.

Used to archive each week's completed solution so the app can offer a
"View last week's solution" button.  The image mirrors the in-app board:
black squares, clue numbers in the corners, and Roman-themed cells in gold.

Usage:
    python render_solution.py [PUZZLE_JSON] [-o OUTPUT.png] [--title TEXT]

Defaults to reading puzzle.json and writing solution.png beside it.
"""

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — no display needed
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# Colours chosen to match the app's grid (app.py): gold themed cells (#ffd700),
# dark black squares (#222), serif letters.
BLACK = "#222222"
WHITE = "#ffffff"
GOLD = "#ffd700"
GRID_LINE = "#888888"
LETTER = "#111111"
NUMBER = "#222222"


def _themed_cells(data: dict) -> set:
    cells = set()
    for p in data["placements"]:
        if not p.get("is_themed"):
            continue
        for i in range(len(p["word"])):
            r = p["row"] + (i if p["direction"] == "down" else 0)
            c = p["col"] + (i if p["direction"] == "across" else 0)
            cells.add((r, c))
    return cells


def _cell_numbers(data: dict) -> dict:
    """Map (row, col) -> clue number for every word start."""
    nums = {}
    for p in data["placements"]:
        nums.setdefault((p["row"], p["col"]), p["number"])
    return nums


def _title_from_path(path: str) -> str | None:
    """Derive a date title from a dated filename, e.g.
    'past_boards/puzzle_2026-06-14.json' -> '2026-06-14 Solution'.

    Returns None if the path carries no YYYY-MM-DD stamp (e.g. the live
    puzzle.json), in which case the board is rendered untitled.
    """
    m = re.search(r"\d{4}-\d{2}-\d{2}", path)
    return f"{m.group(0)} Solution" if m else None


def render(data: dict, output_path: str, title: str | None = None,
           dpi: int = 300) -> None:
    rows, cols = data["rows"], data["cols"]
    grid = data["grid"]
    themed = _themed_cells(data)
    numbers = _cell_numbers(data)

    cell = 1.0
    fig_w = cols * 0.5
    fig_h = rows * 0.5 + (0.5 if title else 0.0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)

    for r in range(rows):
        for c in range(cols):
            # Matplotlib y grows upward; flip so row 0 is at the top.
            x = c * cell
            y = (rows - 1 - r) * cell
            ch = grid[r][c]
            if ch == "#":
                ax.add_patch(Rectangle((x, y), cell, cell,
                                       facecolor=BLACK, edgecolor=BLACK))
                continue
            face = GOLD if (r, c) in themed else WHITE
            ax.add_patch(Rectangle((x, y), cell, cell,
                                   facecolor=face, edgecolor=GRID_LINE,
                                   linewidth=0.8))
            n = numbers.get((r, c))
            if n is not None:
                ax.text(x + 0.06, y + cell - 0.06, str(n),
                        ha="left", va="top", fontsize=5.5, color=NUMBER)
            ax.text(x + cell / 2, y + cell / 2 - 0.04, ch,
                    ha="center", va="center", fontsize=12,
                    fontweight="bold", color=LETTER,
                    family="serif")

    # Outer border
    ax.add_patch(Rectangle((0, 0), cols * cell, rows * cell,
                           fill=False, edgecolor=BLACK, linewidth=2))

    ax.set_xlim(-0.05, cols * cell + 0.05)
    ax.set_ylim(-0.05, rows * cell + 0.05)
    ax.set_aspect("equal")
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=11, color="#0b3d91",
                     fontweight="bold", pad=8)

    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.15,
                facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("puzzle", nargs="?", default="puzzle.json",
                    help="Path to puzzle JSON (default: puzzle.json)")
    ap.add_argument("-o", "--output", default=None,
                    help="Output PNG path (default: solution.png beside input)")
    ap.add_argument("--title", default=None,
                    help="Title text (default: '<YYYY-MM-DD> Solution' parsed "
                         "from a dated filename, else untitled)")
    ap.add_argument("--dpi", type=int, default=300,
                    help="Output resolution in pixels per inch (default: 300)")
    args = ap.parse_args()

    src = Path(args.puzzle)
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    out = args.output or str(src.with_name("solution.png"))
    # Default the title to the date stamped on the input (or output) filename.
    title = args.title or _title_from_path(str(src)) or _title_from_path(out)
    render(data, out, title=title, dpi=args.dpi)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
