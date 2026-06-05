import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

ROW_LIMIT = 13
COL_LIMIT = 17

_GridDict = Dict[Tuple[int, int], str]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WordPlacement:
    word: str
    clue: str
    row: int
    col: int
    direction: str  # 'across' or 'down'
    number: int = 0
    is_themed: bool = False  # True for Roman-themed words

    def get_key(self) -> str:
        return f"{self.number}-{self.direction}"

    def cells(self) -> List[Tuple[int, int]]:
        if self.direction == "across":
            return [(self.row, self.col + i) for i in range(len(self.word))]
        return [(self.row + i, self.col) for i in range(len(self.word))]


@dataclass
class CrosswordData:
    grid: List[List[str]]
    placements: List[WordPlacement]
    rows: int
    cols: int

    def get_placement_by_key(self, key: str) -> Optional[WordPlacement]:
        for p in self.placements:
            if p.get_key() == key:
                return p
        return None

    def cell_to_words(self) -> Dict[Tuple[int, int], List[str]]:
        result: Dict[Tuple[int, int], List[str]] = {}
        for p in self.placements:
            for cell in p.cells():
                result.setdefault(cell, []).append(p.get_key())
        return result

    def cell_to_number(self) -> Dict[Tuple[int, int], int]:
        return {(p.row, p.col): p.number for p in self.placements if p.number}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_crossword(
    word_clue_pairs: List[Tuple[str, str]],
    filler_pairs: Optional[List[Tuple[str, str]]] = None,
    max_attempts: int = 200,
    themed_all: Optional[List[Tuple[str, str]]] = None,
) -> Optional[CrosswordData]:
    """
    Filler-first crossword construction.

    All words in word_clue_pairs are filler — they build the dense skeleton.
    After the skeleton is complete, the best-scoring pair of words from
    themed_all is inserted as Roman-themed entries (falling back to one if
    a second cannot be placed).

    Running max_attempts times and keeping the highest-scoring result.
    """
    best: Optional[CrosswordData] = None
    best_score = float("-inf")

    pairs = [(w.upper().strip(), c) for w, c in word_clue_pairs]
    norm_fillers: Optional[List[Tuple[str, str]]] = (
        [(w.upper().strip(), c) for w, c in filler_pairs] if filler_pairs else None
    )
    norm_themed: Optional[List[Tuple[str, str]]] = (
        [(w.upper().strip(), c) for w, c in themed_all] if themed_all else None
    )

    for _ in range(max_attempts):
        shuffled = list(pairs)
        random.shuffle(shuffled)
        shuffled.sort(key=lambda x: len(x[0]), reverse=True)

        result = _attempt(shuffled, norm_fillers, themed_all=norm_themed)
        if result is None:
            continue

        area = result.rows * result.cols
        squareness_bonus = -abs(result.cols - result.rows) * 5

        cell_usage: Dict[Tuple[int, int], int] = {}
        for p in result.placements:
            for cell in p.cells():
                cell_usage[cell] = cell_usage.get(cell, 0) + 1
        total_intersections = sum(1 for v in cell_usage.values() if v > 1)
        unchecked_count    = sum(1 for v in cell_usage.values() if v == 1)
        unique_cells = len(cell_usage)
        density = unique_cells / area

        attempt_score = (
            len(result.placements) * 50
            + density * 600
            + total_intersections * 60
            - unchecked_count * 120
            + squareness_bonus
        )
        if attempt_score > best_score:
            best = result
            best_score = attempt_score

    return best


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _attempt(
    pairs: List[Tuple[str, str]],
    filler_pairs: Optional[List[Tuple[str, str]]] = None,
    themed_all: Optional[List[Tuple[str, str]]] = None,
) -> Optional[CrosswordData]:
    """
    Stage 1 – filler skeleton (7 greedy passes over all pairs).
    Stage 2 – score every word in themed_all against the filler grid, then
              try the top-10 first-word candidates; for each, tentatively
              place it and search for the best second themed word.  The pair
              with the highest combined score wins (falls back to one word if
              no second can be placed).
    Stage 3 – two-tier fill pass for residual singly-covered cells.
    """
    grid: _GridDict = {}
    placed: List[Dict] = []

    if not pairs:
        return None

    # Anchor
    first_word, first_clue = pairs[0]
    _place_dict(first_word, 0, 0, "across", grid)
    placed.append({"word": first_word, "clue": first_clue,
                   "row": 0, "col": 0, "direction": "across"})

    # Stage 1: 7 greedy passes — filler builds the skeleton
    remaining = list(pairs[1:])
    for _pass in range(7):
        still_remaining = []
        for word, clue in remaining:
            candidates = _candidates(word, grid)
            valid = [c for c in candidates if _within_limit(word, c, grid)]
            if not valid:
                still_remaining.append((word, clue))
                continue
            best_cand = max(valid, key=lambda x: x["score"])
            _place_dict(word, best_cand["row"], best_cand["col"],
                        best_cand["direction"], grid)
            placed.append({"word": word, "clue": clue,
                           "row": best_cand["row"], "col": best_cand["col"],
                           "direction": best_cand["direction"]})
        remaining = still_remaining
        if not remaining:
            break

    if len(placed) < 3:
        return None

    # Stage 2: place TWO themed words (best-scoring pair; falls back to one)
    if themed_all:
        used_words = {p["word"] for p in placed}

        # Score every themed word against the current filler grid
        first_candidates: List[Tuple[float, str, str, Dict]] = []
        for word, clue in sorted(themed_all, key=lambda x: -len(x[0])):
            if word in used_words:
                continue
            cands = _candidates(word, grid)
            valid = [c for c in cands if _within_limit(word, c, grid)]
            if not valid:
                continue
            top = max(valid, key=lambda x: x["score"])
            first_candidates.append((top["score"], word, clue, top))

        first_candidates.sort(key=lambda x: -x[0])

        best_pair_score = float("-inf")
        best_first_entry: Optional[Tuple[str, str, Dict]] = None
        best_second_entry: Optional[Tuple[str, str, Dict]] = None

        for sc1, w1, c1, cand1 in first_candidates[:min(10, len(first_candidates))]:
            # Tentatively place the first word to find the best second
            tmp_grid = dict(grid)
            _place_dict(w1, cand1["row"], cand1["col"], cand1["direction"], tmp_grid)

            used_with_first = used_words | {w1}
            best_sc2 = float("-inf")
            second_entry: Optional[Tuple[str, str, Dict]] = None

            for w2, clue2 in sorted(themed_all, key=lambda x: -len(x[0])):
                if w2 in used_with_first:
                    continue
                cands2 = _candidates(w2, tmp_grid)
                valid2 = [c for c in cands2 if _within_limit(w2, c, tmp_grid)]
                if not valid2:
                    continue
                top2 = max(valid2, key=lambda x: x["score"])
                if top2["score"] > best_sc2:
                    best_sc2 = top2["score"]
                    second_entry = (w2, clue2, top2)

            # Strongly prefer pairs that fit two words; fall back to one
            pair_score = sc1 + (best_sc2 if second_entry else -1000.0)
            if pair_score > best_pair_score:
                best_pair_score = pair_score
                best_first_entry = (w1, c1, cand1)
                best_second_entry = second_entry

        if best_first_entry:
            w, c, cand = best_first_entry
            _place_dict(w, cand["row"], cand["col"], cand["direction"], grid)
            placed.append({"word": w, "clue": c,
                           "row": cand["row"], "col": cand["col"],
                           "direction": cand["direction"],
                           "is_themed": True})

            if best_second_entry:
                w2, c2, cand2 = best_second_entry
                _place_dict(w2, cand2["row"], cand2["col"], cand2["direction"], grid)
                placed.append({"word": w2, "clue": c2,
                               "row": cand2["row"], "col": cand2["col"],
                               "direction": cand2["direction"],
                               "is_themed": True})

    # Stage 3: fill pass for singly-covered cells
    if filler_pairs:
        _fill_pass(grid, placed, filler_pairs)

    return _build(placed, grid)


# ---------------------------------------------------------------------------
# Fill pass
# ---------------------------------------------------------------------------

def _singly_covered_cells(
    grid: _GridDict, placed: List[Dict]
) -> List[Tuple[int, int, str]]:
    cell_dirs: Dict[Tuple[int, int], set] = {}
    for p in placed:
        for i in range(len(p["word"])):
            r = p["row"] + (i if p["direction"] == "down" else 0)
            c = p["col"] + (i if p["direction"] == "across" else 0)
            cell_dirs.setdefault((r, c), set()).add(p["direction"])
    return [
        (r, c, "down" if "across" in dirs else "across")
        for (r, c), dirs in cell_dirs.items()
        if len(dirs) == 1
    ]


def _fill_pass(
    grid: _GridDict,
    placed: List[Dict],
    filler_pairs: List[Tuple[str, str]],
) -> None:
    """
    Two-tier fill toward full double-coverage.

    Tier 1 – bridge words (≥2 intersections): net-positive for doubly-checked.
    Tier 2 – gap words  (≥1 intersection): best-effort for remaining cells.
    """
    used = {p["word"] for p in placed}
    pool = [(w, c) for w, c in filler_pairs if w not in used and 3 <= len(w) <= 7]
    random.shuffle(pool)
    if not pool:
        return

    by_letter: Dict[str, List[int]] = {}
    for idx, (word, _) in enumerate(pool):
        for ch in set(word):
            by_letter.setdefault(ch, []).append(idx)

    spent: set = set()

    def _try_place(r: int, c: int, needed_dir: str, min_intersect: int) -> bool:
        target = grid[(r, c)]
        for idx in by_letter.get(target, []):
            if idx in spent:
                continue
            word, clue = pool[idx]
            best_sr, best_sc, best_n = None, None, 0
            for wi, ch in enumerate(word):
                if ch != target:
                    continue
                sr = (r - wi) if needed_dir == "down"   else r
                sc = (c - wi) if needed_dir == "across" else c
                cand = {"row": sr, "col": sc, "direction": needed_dir, "score": 0}
                if not _valid(word, sr, sc, needed_dir, grid):
                    continue
                if not _within_limit(word, cand, grid):
                    continue
                n = sum(
                    1 for i, ch2 in enumerate(word)
                    if grid.get(
                        (sr + (i if needed_dir == "down"   else 0),
                         sc + (i if needed_dir == "across" else 0))
                    ) == ch2
                )
                if n > best_n:
                    best_n, best_sr, best_sc = n, sr, sc
            if best_n >= min_intersect and best_sr is not None:
                _place_dict(word, best_sr, best_sc, needed_dir, grid)
                placed.append({"word": word, "clue": clue,
                               "row": best_sr, "col": best_sc, "direction": needed_dir})
                spent.add(idx)
                return True
        return False

    # Tier 1: bridge pass (≥2 intersections — net positive coverage)
    for _ in range(8):
        unchecked = _singly_covered_cells(grid, placed)
        if not unchecked:
            return
        random.shuffle(unchecked)
        any_placed = False
        for r, c, d in unchecked:
            if _try_place(r, c, d, min_intersect=2):
                any_placed = True
        if not any_placed:
            break

    # Tier 2: gap pass (≥1 intersection — single-crossing fallback)
    for _ in range(6):
        unchecked = _singly_covered_cells(grid, placed)
        if not unchecked:
            return
        random.shuffle(unchecked)
        any_placed = False
        for r, c, d in unchecked:
            if _try_place(r, c, d, min_intersect=1):
                any_placed = True
        if not any_placed:
            break


# ---------------------------------------------------------------------------
# Placement helpers
# ---------------------------------------------------------------------------

def _within_limit(word: str, cand: Dict, grid: _GridDict) -> bool:
    tmp = dict(grid)
    _place_dict(word, cand["row"], cand["col"], cand["direction"], tmp)
    rs = [k[0] for k in tmp]
    cs = [k[1] for k in tmp]
    return (max(rs) - min(rs) < ROW_LIMIT and
            max(cs) - min(cs) < COL_LIMIT)


def _candidates(word: str, grid: _GridDict) -> List[Dict]:
    out = []
    for (gr, gc), gl in list(grid.items()):
        for wi, wl in enumerate(word):
            if wl != gl:
                continue
            r, c = gr, gc - wi
            if _valid(word, r, c, "across", grid):
                out.append({"row": r, "col": c, "direction": "across",
                             "score": _score(word, r, c, "across", grid)})
            r, c = gr - wi, gc
            if _valid(word, r, c, "down", grid):
                out.append({"row": r, "col": c, "direction": "down",
                             "score": _score(word, r, c, "down", grid)})
    return out


def _valid(word: str, row: int, col: int, direction: str, grid: _GridDict) -> bool:
    length = len(word)
    intersections = 0

    if direction == "across":
        if grid.get((row, col - 1)) is not None:
            return False
        if grid.get((row, col + length)) is not None:
            return False
        for i, letter in enumerate(word):
            r, c = row, col + i
            existing = grid.get((r, c))
            if existing is not None:
                if existing != letter:
                    return False
                intersections += 1
            else:
                if grid.get((r - 1, c)) is not None or grid.get((r + 1, c)) is not None:
                    return False
    else:
        if grid.get((row - 1, col)) is not None:
            return False
        if grid.get((row + length, col)) is not None:
            return False
        for i, letter in enumerate(word):
            r, c = row + i, col
            existing = grid.get((r, c))
            if existing is not None:
                if existing != letter:
                    return False
                intersections += 1
            else:
                if grid.get((r, c - 1)) is not None or grid.get((r, c + 1)) is not None:
                    return False

    return intersections >= 1


def _score(word: str, row: int, col: int, direction: str, grid: _GridDict) -> float:
    intersections = 0
    for i, letter in enumerate(word):
        r = row + (i if direction == "down" else 0)
        c = col + (i if direction == "across" else 0)
        if grid.get((r, c)) == letter:
            intersections += 1

    tmp = dict(grid)
    _place_dict(word, row, col, direction, tmp)
    all_r = [k[0] for k in tmp]
    all_c = [k[1] for k in tmp]
    h    = max(all_r) - min(all_r) + 1
    w    = max(all_c) - min(all_c) + 1
    area = h * w
    aspect_penalty = abs(h - w) * 6
    int_score = sum(range(1, intersections + 1)) * 18
    return int_score - area * 0.5 - aspect_penalty + random.uniform(0, 0.4)


def _place_dict(word: str, row: int, col: int, direction: str, grid: _GridDict) -> None:
    for i, letter in enumerate(word):
        r = row + (i if direction == "down" else 0)
        c = col + (i if direction == "across" else 0)
        grid[(r, c)] = letter


def _build(placed: List[Dict], grid: _GridDict) -> CrosswordData:
    min_r = min(k[0] for k in grid)
    min_c = min(k[1] for k in grid)

    norm: _GridDict = {(r - min_r, c - min_c): ltr for (r, c), ltr in grid.items()}
    norm_placed = [{**p, "row": p["row"] - min_r, "col": p["col"] - min_c}
                   for p in placed]

    rows = max(k[0] for k in norm) + 1
    cols = max(k[1] for k in norm) + 1

    g = [["#"] * cols for _ in range(rows)]
    for (r, c), ltr in norm.items():
        g[r][c] = ltr

    number = 1
    cell_numbers: Dict[Tuple[int, int], int] = {}
    for r in range(rows):
        for c in range(cols):
            if g[r][c] == "#":
                continue
            starts_across = (c == 0 or g[r][c-1] == "#") and (c+1 < cols and g[r][c+1] != "#")
            starts_down   = (r == 0 or g[r-1][c] == "#") and (r+1 < rows and g[r+1][c] != "#")
            if starts_across or starts_down:
                cell_numbers[(r, c)] = number
                number += 1

    placements = [
        WordPlacement(
            word=p["word"], clue=p["clue"],
            row=p["row"], col=p["col"], direction=p["direction"],
            number=cell_numbers.get((p["row"], p["col"]), 0),
            is_themed=p.get("is_themed", False),
        )
        for p in norm_placed
    ]
    placements.sort(key=lambda x: (x.number, x.direction))

    return CrosswordData(grid=g, placements=placements, rows=rows, cols=cols)
