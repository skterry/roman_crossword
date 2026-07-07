#!/usr/bin/env python3
"""
Build a scored proper-name pool for the crossword filler from the public-domain
US Census 1990 name frequency lists (names_data/dist.*).

Outputs two files the generator consumes when run with --include-names:

  names_caps.dict   WORD;SCORE  (one per line)  — merged into the filler pool
  names_clues.json  {WORD: "Common surname"|"Common boy's name"|...}
                    — generic category clues, since proper names have no
                    WordNet gloss (see generate_puzzle.py --include-names).

"Common names only": each source list is frequency-ranked with a cumulative
percentage column; we keep names up to CUM_CUTOFF (covers the bulk of real
people without the long rare tail).  Scores map frequency rank into a band that
sits alongside — but generally just below — top dictionary fill, so names enrich
the grid without dominating it (a per-board cap is enforced separately).

Run once after downloading names_data/; safe to re-run (overwrites outputs).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

DATA = Path("names_data")
CUM_CUTOFF = 90.0          # first names: keep within this cumulative-frequency %
MAX_SURNAMES = 10_000      # surnames have a very long tail; keep the top-N most
                           # common by frequency (cum% grows too slowly to use).
MIN_LEN, MAX_LEN = 3, 12   # grid constraints (12x12, fully checked)

# Score bands (generator min-score is 50; good dict fill ranges ~50-100).
FIRST_HI, FIRST_LO = 85, 58   # first names: a touch more solver-friendly
LAST_HI, LAST_LO = 80, 55     # surnames


def _read_census(path: Path, cum_cutoff: float = CUM_CUTOFF,
                 max_n: int | None = None) -> List[str]:
    """Return names (upper) in frequency order, filtered to pure-alpha entries
    within the length window.  Census format is:  NAME  freq%  cumfreq%  rank.

    Kept while cumulative frequency <= ``cum_cutoff`` and (if given) until
    ``max_n`` names have been collected — surnames need the rank cap because
    their cumulative % climbs too slowly to isolate "common" ones.
    """
    out: List[str] = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        word = parts[0].upper()
        try:
            cum = float(parts[2])
        except ValueError:
            continue
        if cum > cum_cutoff:
            break  # list is sorted by frequency; everything after is rarer
        if word.isalpha() and MIN_LEN <= len(word) <= MAX_LEN:
            out.append(word)
            if max_n is not None and len(out) >= max_n:
                break
    return out


def _scored(names: List[str], hi: int, lo: int) -> Dict[str, int]:
    """Linear score by rank: most frequent -> hi, least -> lo."""
    n = len(names)
    if n == 0:
        return {}
    return {
        w: round(hi - (hi - lo) * (i / max(n - 1, 1)))
        for i, w in enumerate(names)
    }


def main() -> None:
    surnames = _read_census(DATA / "dist.all.last", max_n=MAX_SURNAMES)
    male = _read_census(DATA / "dist.male.first")
    female = _read_census(DATA / "dist.female.first")

    print(f"Common surnames   : {len(surnames):,}")
    print(f"Common boys' names: {len(male):,}")
    print(f"Common girls'name : {len(female):,}")

    last_scores = _scored(surnames, LAST_HI, LAST_LO)
    male_scores = _scored(male, FIRST_HI, FIRST_LO)
    female_scores = _scored(female, FIRST_HI, FIRST_LO)

    # Merge scores (highest wins) and clue each name by the category in which
    # it is MOST frequent — so JAMES (a top boys' name that also appears far
    # down the girls' list) is clued "Common boy's name", not girl's.  We track
    # the score that justified the current clue and only override on a strictly
    # higher score; ties keep the first (priority) category.
    scores: Dict[str, int] = {}
    clues: Dict[str, str] = {}
    clue_score: Dict[str, int] = {}

    def add(words_scores: Dict[str, int], clue: str):
        for w, s in words_scores.items():
            if s > scores.get(w, -1):
                scores[w] = s
            if s > clue_score.get(w, -1):   # strictly higher freq wins the clue
                clues[w] = clue
                clue_score[w] = s

    # priority order on score ties: boy/girl first names over surname
    add(male_scores, "Common boy's name")
    add(female_scores, "Common girl's name")
    add(last_scores, "Common surname")

    dict_path = Path("names_caps.dict")
    with dict_path.open("w") as f:
        for w in sorted(scores):
            f.write(f"{w};{scores[w]}\n")

    clues_path = Path("names_clues.json")
    clues_path.write_text(json.dumps(clues, indent=0, sort_keys=True))

    print(f"\nTotal unique names: {len(scores):,}")
    print(f"  -> {dict_path}  ({dict_path.stat().st_size//1024} KB)")
    print(f"  -> {clues_path} ({clues_path.stat().st_size//1024} KB)")
    # a few samples across the score band
    top = sorted(scores, key=lambda w: -scores[w])[:6]
    bot = sorted(scores, key=lambda w: scores[w])[:6]
    print(f"  highest-scored: {[(w, scores[w], clues[w]) for w in top]}")
    print(f"  lowest-scored : {[(w, scores[w]) for w in bot]}")


if __name__ == "__main__":
    main()
