#!/usr/bin/env python3
"""
Offline puzzle generator — run once to produce puzzle.json.

Fixed 12x12 strategy (see grid_filler.py for the full rationale):

  1.  Roman-themed words are placed ACROSS, edge-anchored, spread down a fixed
      12x12 board, each sealed with a black buffer on its open end.
  2.  Black squares are carved in so every white run is length >= 3.
  3.  Every white slot is filled with real words from a *scored* crossword
      wordlist via backtracking search.  The pool is pre-filtered to words that
      WordNet can define, so every filler word is guaranteed cluable.
  4.  A repair pass guarantees every entry is real: any incidental run that
      isn't a word is first re-lettered in place into a real word (recovering
      density), and only blackened if no such re-lettering exists.  Typical
      density after repair is ~0.74-0.78.

Clues are assigned inline: themed words keep their secrets.toml clues; filler
words get their WordNet gloss.  No separate clue-fetch step is needed — just
run this, then `streamlit run app.py`.  (fetch_clues.py remains as an optional
dictionaryapi.dev path but is superseded by the offline WordNet clues.)

Usage:
    python generate_puzzle.py [options]

Options:
    --trials N            Number of independent puzzles to generate (default: 1).
                          With --trials 5, saves puzzle1.json … puzzle5.json.
                          With --trials 1, saves to --output as before.
    --min-themed N        Min Roman-themed words per puzzle (default: 4)
    --max-themed N        Max Roman-themed words per puzzle (default: 6)
    --min-black N         Fewest black squares to try (default: 28)
    --max-black N         Most black squares to try   (default: 36; >=24 keeps
                          density >= 0.75 on a 12x12)
    --min-score N         Minimum wordlist score to use as filler (default: 50)
    --target-density F    Stop as soon as a puzzle reaches this density
                          (default: 0.76; ~0.74-0.78 is typical after the
                          all-real-words repair pass)
    --node-budget N       Search nodes per attempt before giving up (default:
                          25000; lower = fail faster, try more layouts)
    --timeout S           Hard stop per trial after this many seconds (default: 120)
    --seed N              RNG seed for reproducible runs (default: random)
    --output PATH         Output JSON file (default: puzzle.json).
                          With --trials > 1 the stem is used as a prefix, e.g.
                          puzzle.json → puzzle1.json, puzzle2.json, …
    --secrets PATH        Path to .streamlit/secrets.toml
    --wordlist PATHS...   Word sources, merged by max score (default:
                          xwordlist.dict spreadthewordlist_caps.dict clues.tsv).
                          WORD;SCORE .dict files and/or .tsv crossword databases.
    --tsv-score N         Score given to .tsv answers (no native score; def: 50)

The driver runs attempts until --target-density is met or --timeout elapses,
saving the output file each time a new best grid is found.  Press Ctrl+C to
stop early and keep whatever has been saved so far.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from crossword_generator import CrosswordData
from grid_filler import (
    GRID, WordIndex, density, generate_fixed_puzzle, load_scored_wordlist,
)
from grid_filler import FILLER_CLUE

# Offline WordNet clue source (optional — only needed unless --no-clues).
try:
    from wordnet_clues import clue_for, filter_cluable
    _WORDNET_ERR: Optional[Exception] = None
except Exception as _e:           # nltk / corpus not installed
    clue_for = filter_cluable = None  # type: ignore
    _WORDNET_ERR = _e


def apply_clues(cw: CrosswordData) -> None:
    """Give every filler word a WordNet-gloss clue (themed words keep theirs)."""
    for p in cw.placements:
        if not p.is_themed:
            p.clue = clue_for(p.word) or FILLER_CLUE


# ---------------------------------------------------------------------------
# tomllib shim (stdlib in 3.11+; fall back to the 'toml' package)
# ---------------------------------------------------------------------------
try:
    import tomllib as _tomllib

    def _load_toml(path: str) -> dict:
        with open(path, "rb") as f:
            return _tomllib.load(f)
except ImportError:
    import toml as _toml_pkg  # pip install toml

    def _load_toml(path: str) -> dict:
        return _toml_pkg.load(path)


# ---------------------------------------------------------------------------
# Themed clue loader
# ---------------------------------------------------------------------------

def load_roman_clues(secrets_path: str) -> List[Tuple[str, str]]:
    path = Path(secrets_path)
    if not path.exists():
        raise FileNotFoundError(
            f"secrets.toml not found at {secrets_path!r}. "
            "Provide the correct path with --secrets."
        )
    clues = _load_toml(str(path)).get("clues", {})
    pairs: List[Tuple[str, str]] = []
    skipped = 0
    for word, clue in clues.items():
        w = word.upper().strip()
        # Fully-checked grids can't cross a non-letter cell, so digit/symbol
        # acronyms (e.g. H4RG) are unplaceable here — drop them.
        if w.isalpha() and 3 <= len(w) <= GRID:
            pairs.append((w, clue))
        else:
            skipped += 1
    if skipped:
        print(f"  ({skipped} themed answers skipped: non-letter or wrong length)",
              flush=True)
    return pairs


def collect_used_themed(history_dir: str, extra_files: List[str]) -> set:
    """Collect every Roman-themed answer used in previously generated puzzles.

    Reads all *.json under `history_dir` plus any `extra_files`, returning the
    set of upper-cased words marked ``is_themed`` so they can be excluded from
    the next puzzle's themed pool (no week repeats a themed answer).
    """
    used: set = set()
    paths: List[Path] = []
    hist = Path(history_dir)
    if hist.is_dir():
        paths.extend(sorted(hist.glob("*.json")))
    paths.extend(Path(p) for p in extra_files)
    for path in paths:
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  (skipping {path}: {e})", flush=True)
            continue
        for p in data.get("placements", []):
            if p.get("is_themed") and isinstance(p.get("word"), str):
                used.add(p["word"].upper().strip())
    return used


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def save_puzzle(cw: CrosswordData, output_path: str) -> None:
    data = {
        "grid": cw.grid,
        "rows": cw.rows,
        "cols": cw.cols,
        "placements": [
            {
                "word":      p.word,
                "clue":      p.clue,
                "row":       p.row,
                "col":       p.col,
                "direction": p.direction,
                "number":    p.number,
                "is_themed": p.is_themed,
            }
            for p in cw.placements
        ],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Per-trial generation loop
# ---------------------------------------------------------------------------

def run_trial(
    themed, index, args, rng,
    output_path: str,
    trial_num: int,
    n_trials: int,
) -> Optional[CrosswordData]:
    """Run one generation trial; save the best puzzle to output_path.

    Returns the best CrosswordData found, or None if no puzzle was generated.
    Raises KeyboardInterrupt to let the caller handle early exit.
    """
    best: Optional[CrosswordData] = None
    best_density = 0.0
    attempts = solved = 0
    t_start = time.time()

    header = f"Trial {trial_num}/{n_trials}" if n_trials > 1 else "Generating"
    print(f"\n── {header} ──────────────────────────────────────────────────",
          flush=True)

    while time.time() - t_start < args.timeout:
        attempts += 1
        cw = generate_fixed_puzzle(
            themed, index,
            n_themed=rng.randint(args.min_themed, args.max_themed),
            black_target=rng.randint(args.min_black, args.max_black),
            node_budget=args.node_budget,
            rng=rng,
        )
        if cw is None:
            continue
        solved += 1
        d = density(cw)
        if d > best_density:
            best_density = d
            best = cw
            if not args.no_clues:
                apply_clues(best)
            save_puzzle(best, output_path)
            n_themed = sum(1 for p in best.placements if p.is_themed)
            print(
                f"  ★ attempt {attempts:5d}  density={d:.3f}  "
                f"words={len(best.placements):2d}  themed={n_themed}  "
                f"({time.time() - t_start:.0f}s)  → {output_path}",
                flush=True,
            )
        if best_density >= args.target_density:
            print(f"  Target density {args.target_density:.2f} reached.",
                  flush=True)
            break

    elapsed = time.time() - t_start
    if best is None:
        print(f"  No puzzle found in {elapsed:.0f}s ({attempts} attempts).",
              flush=True)
    else:
        n_themed = sum(1 for p in best.placements if p.is_themed)
        blacks = sum(row.count("#") for row in best.grid)
        print(
            f"  density={best_density:.4f}  blacks={blacks}  "
            f"words={len(best.placements)}  themed={n_themed}  "
            f"time={elapsed:.0f}s  → {output_path}",
            flush=True,
        )
    return best


# ---------------------------------------------------------------------------
# Output path helper
# ---------------------------------------------------------------------------

def trial_output_path(base: str, trial_num: int, n_trials: int) -> str:
    """Return the output path for a given trial number.

    With n_trials == 1 returns base unchanged.
    With n_trials > 1 inserts the trial number before the extension,
    e.g. puzzle.json → puzzle1.json, puzzle2.json, …
    """
    if n_trials == 1:
        return base
    p = Path(base)
    return str(p.parent / f"{p.stem}{trial_num}{p.suffix}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Roman Space Telescope crossword (fixed 12x12).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--trials",         type=int,   default=1,
                        help="Number of independent puzzles to generate (default: 1).")
    parser.add_argument("--min-themed",     type=int,   default=4)
    parser.add_argument("--max-themed",     type=int,   default=6)
    parser.add_argument("--min-black",      type=int,   default=28)
    parser.add_argument("--max-black",      type=int,   default=36)
    parser.add_argument("--min-score",      type=int,   default=50)
    parser.add_argument("--target-density", type=float, default=0.76)
    parser.add_argument("--node-budget",    type=int,   default=25_000)
    parser.add_argument("--timeout",        type=int,   default=120)
    parser.add_argument("--seed",           type=int,   default=None)
    parser.add_argument("--output",         default="puzzle.json")
    parser.add_argument("--secrets",        default=".streamlit/secrets.toml")
    parser.add_argument("--wordlist",       nargs="+",
                        default=["xwordlist.dict", "spreadthewordlist_caps.dict",
                                 "clues.tsv"],
                        help="Word sources (WORD;SCORE .dict files and/or .tsv "
                             "crossword databases), merged by max score.")
    parser.add_argument("--tsv-score",      type=int, default=50,
                        help="Score assigned to answers sourced from .tsv files "
                             "(they carry no score of their own; default: 50).")
    parser.add_argument("--no-clues",       action="store_true",
                        help="Skip WordNet filtering/cluing; leave filler clues "
                             "as placeholders (no nltk required).")
    parser.add_argument("--history-dir",    default="past_boards",
                        help="Directory of retired puzzle JSONs whose Roman-themed "
                             "answers must not be reused (default: past_boards).")
    parser.add_argument("--extra-history",  nargs="*", default=["puzzle.json.bak"],
                        help="Additional retired puzzle JSON files to read used "
                             "themed answers from (default: puzzle.json.bak).")
    parser.add_argument("--allow-repeat-themed", action="store_true",
                        help="Permit reusing Roman-themed answers from past "
                             "puzzles (by default they are excluded).")
    args = parser.parse_args()

    if args.trials < 1:
        parser.error("--trials must be at least 1.")
    if args.min_themed < 2:
        parser.error("--min-themed must be at least 2.")
    if args.max_themed < args.min_themed:
        parser.error("--max-themed must be >= --min-themed.")
    if not args.no_clues and clue_for is None:
        parser.error(
            "WordNet clue source unavailable "
            f"({_WORDNET_ERR}).\nInstall it with:\n"
            "  pip install nltk && python -m nltk.downloader wordnet omw-1.4\n"
            "or rerun with --no-clues to leave filler clues as placeholders."
        )

    rng = random.Random(args.seed)

    print("Loading roman-themed clues …", flush=True)
    themed = load_roman_clues(args.secrets)
    print(f"  {len(themed)} themed words available.", flush=True)

    if not args.allow_repeat_themed:
        used = collect_used_themed(args.history_dir, args.extra_history)
        if used:
            before = len(themed)
            themed = [(w, c) for w, c in themed if w not in used]
            removed = before - len(themed)
            print(
                f"  Excluding {removed} themed word(s) already used in past "
                f"puzzles ({len(used)} found); {len(themed)} remain for "
                f"this week.",
                flush=True,
            )
            if len(themed) < args.max_themed:
                print(
                    f"  ⚠ Only {len(themed)} fresh themed words remain "
                    f"(< --max-themed {args.max_themed}). Consider adding new "
                    f"answers to secrets.toml or pass --allow-repeat-themed.",
                    flush=True,
                )

    print(f"Loading scored wordlist(s) {', '.join(args.wordlist)} "
          f"(score >= {args.min_score}) …", flush=True)
    t0 = time.time()
    # Words permanently blocked from appearing as filler answers —
    # either offensive/harmful or simply wrong for a human solver.
    _BLOCKED = {
        "ORIENTAL",   # racial slur when applied to people
        "OTHOS",      # not a real word (junk plural); no fair clue exists
    }

    scored = load_scored_wordlist(
        args.wordlist, min_score=args.min_score,
        exclude={w for w, _ in themed} | _BLOCKED, tsv_score=args.tsv_score,
    )
    print(f"  {len(scored):,} merged filler words loaded in {time.time() - t0:.1f}s.",
          flush=True)
    if not args.no_clues:
        t0 = time.time()
        scored = filter_cluable(scored)
        print(f"  {len(scored):,} have a WordNet definition "
              f"(filtered in {time.time() - t0:.1f}s) — every filler will be cluable.",
              flush=True)
    index = WordIndex(scored)

    print(
        f"\nGrid           : {GRID} x {GRID}\n"
        f"Trials         : {args.trials}\n"
        f"Themed words   : {args.min_themed}–{args.max_themed}\n"
        f"Black squares  : {args.min_black}–{args.max_black} "
        f"(density {1 - args.max_black / GRID**2:.2f}–{1 - args.min_black / GRID**2:.2f})\n"
        f"Target density : {args.target_density:.2f}\n"
        f"Timeout/trial  : {args.timeout}s\n"
        f"Press Ctrl+C to stop early and keep whatever has been saved.\n",
        flush=True,
    )

    results: List[Tuple[int, str, Optional[CrosswordData]]] = []
    try:
        for i in range(args.trials):
            trial_num = i + 1
            out = trial_output_path(args.output, trial_num, args.trials)
            cw = run_trial(themed, index, args, rng, out, trial_num, args.trials)
            results.append((trial_num, out, cw))
    except KeyboardInterrupt:
        print(f"\nInterrupted — keeping puzzles saved so far.", flush=True)

    # Final summary across all trials
    completed = [(n, out, cw) for n, out, cw in results if cw is not None]
    if not completed:
        print(
            "\nNo puzzle generated in any trial. "
            "Try raising --timeout/--max-black or lowering --min-themed.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.trials > 1:
        print(f"\n── Summary ({len(completed)}/{args.trials} trials succeeded) ──────────────────")
        for n, out, cw in completed:
            blacks = sum(row.count("#") for row in cw.grid)
            d = density(cw)
            n_themed = sum(1 for p in cw.placements if p.is_themed)
            themed_words = ", ".join(p.word for p in cw.placements if p.is_themed)
            print(f"  puzzle{n}: density={d:.4f}  blacks={blacks}  "
                  f"words={len(cw.placements)}  themed={n_themed} ({themed_words})")
            print(f"           → {out}")


if __name__ == "__main__":
    main()
