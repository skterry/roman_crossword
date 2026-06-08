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

def generate_crossword_themed_first(
    themed_all: List[Tuple[str, str]],
    filler_pairs: Optional[List[Tuple[str, str]]] = None,
    max_attempts: int = 200,
    min_themed: int = 4,
    max_themed: int = 7,
    max_total_words: int = 20,
) -> Optional[CrosswordData]:
    """
    NYT-style themed-first crossword construction.

    Stage 1 – Themed ACROSS words are placed first, edge-anchored:
              odd-indexed entries start at col 0 (left edge); even-indexed
              entries end at the rightmost column (right edge).  Each word
              gets an implicit black-square buffer on its un-anchored end,
              enforced naturally by the adjacency rules in _valid.
              Rows are distributed evenly so DOWN words can thread between them.

    Stage 2 – Greedy filler passes.  With only themed words in the grid the
              first words placed are necessarily DOWN entries (the only ones
              that can intersect existing letters).  Once those seed letters
              into non-themed rows, ACROSS fillers follow.  This replicates
              the spine-and-fill pattern used by NYT constructors.

    Stage 3 – Two-tier fill pass for any remaining singly-covered cells.

    Runs max_attempts times; returns the densest valid result.
    """
    best: Optional[CrosswordData] = None
    best_density = -1.0

    norm_themed  = [(w.upper().strip(), c) for w, c in themed_all]
    norm_fillers = [(w.upper().strip(), c) for w, c in filler_pairs] if filler_pairs else None

    for _ in range(max_attempts):
        result = _attempt_themed_first(
            norm_themed, norm_fillers,
            min_themed=min_themed,
            max_themed=max_themed,
            max_total_words=max_total_words,
        )
        if result is None:
            continue

        n_themed = sum(1 for p in result.placements if p.is_themed)
        if not (min_themed <= n_themed <= max_themed):
            continue

        white   = sum(cell != "#" for row in result.grid for cell in row)
        density = white / (result.rows * result.cols)
        if density > best_density:
            best_density = density
            best = result

    return best


def generate_crossword(
    word_clue_pairs: List[Tuple[str, str]],
    filler_pairs: Optional[List[Tuple[str, str]]] = None,
    max_attempts: int = 200,
    themed_all: Optional[List[Tuple[str, str]]] = None,
    min_themed: int = 4,
    max_themed: int = 7,
    max_total_words: int = 20,
) -> Optional[CrosswordData]:
    """
    Filler-first crossword construction.

    word_clue_pairs build the dense skeleton (Stage 1).
    After the skeleton, min_themed..max_themed words from themed_all are
    greedily inserted as Roman-themed entries (Stage 2).
    A fill pass covers any singly-intersected cells (Stage 3), subject to
    the max_total_words cap.

    Runs max_attempts times and returns the highest-scoring result.
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

        result = _attempt(
            shuffled, norm_fillers,
            themed_all=norm_themed,
            min_themed=min_themed,
            max_themed=max_themed,
            max_total_words=max_total_words,
        )
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
            density * 800
            + total_intersections * 80
            - unchecked_count * 150
            + squareness_bonus
            + len(result.placements) * 20
        )
        if attempt_score > best_score:
            best = result
            best_score = attempt_score

    return best


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _spaced_rows(n: int, max_row: int, min_gap: int = 2) -> Optional[List[int]]:
    """
    Return n row indices in [0, max_row] with at least min_gap empty rows
    between consecutive themed entries (so DOWN words can thread between them).
    Returns None if n themed words cannot fit.
    """
    if n <= 0:
        return []
    # Minimum span needed: n rows + (n-1) gaps of min_gap each
    if n + (n - 1) * min_gap > max_row + 1:
        return None
    if n == 1:
        return [max_row // 2]
    step = max_row / (n - 1)
    rows = [round(i * step) for i in range(n)]
    # Enforce minimum gap after rounding
    for i in range(1, len(rows)):
        rows[i] = max(rows[i], rows[i - 1] + min_gap + 1)
    if rows[-1] > max_row:
        return None
    return rows


def _attempt_themed_first(
    themed_candidates: List[Tuple[str, str]],
    filler_pairs: Optional[List[Tuple[str, str]]],
    min_themed: int,
    max_themed: int,
    max_total_words: int,
) -> Optional[CrosswordData]:
    """
    NYT-style attempt: themed ACROSS entries placed first (edge-anchored),
    then greedy filler fills the remaining space.
    """
    if not themed_candidates:
        return None

    grid:   _GridDict  = {}
    placed: List[Dict] = []

    # ── Stage 1: place themed words ─────────────────────────────────────────

    pool = list(themed_candidates)
    random.shuffle(pool)

    n_themed   = random.randint(min_themed, max_themed)
    to_place   = pool[:min(n_themed, len(pool))]

    if len(to_place) < min_themed:
        return None

    max_len    = max(len(w) for w, _ in to_place)
    # Grid width = longest themed word + 1-cell black-square buffer on the open end.
    # Left-anchored:  word occupies cols 0 … len-1;  buffer at col len.
    # Right-anchored: word occupies cols (grid_width-len) … grid_width-1;
    #                 buffer at col (grid_width-len-1).
    grid_width = max_len + 1

    row_positions = _spaced_rows(n_themed, ROW_LIMIT - 1, min_gap=2)
    if row_positions is None:
        return None

    for i, (row, (word, clue)) in enumerate(zip(row_positions, to_place)):
        if i % 2 == 0:
            col = 0                              # left-anchored
        else:
            col = max(0, grid_width - len(word)) # right-anchored

        _place_dict(word, row, col, "across", grid)
        placed.append({
            "word": word, "clue": clue,
            "row": row, "col": col, "direction": "across",
            "is_themed": True,
        })

    if len(placed) < min_themed:
        return None

    # ── Stage 2: greedy filler placement ────────────────────────────────────
    # With only themed ACROSS words in the grid, _candidates will find
    # DOWN placements that cross their letters first.  Those DOWN words seed
    # letters into non-themed rows, after which ACROSS fillers can follow.
    # This naturally replicates the NYT spine-and-fill sequence.

    if filler_pairs:
        remaining = list(filler_pairs)
        random.shuffle(remaining)
        remaining.sort(key=lambda x: len(x[0]), reverse=True)

        for _pass in range(12):
            still_remaining = []
            for word, clue in remaining:
                if len(placed) >= max_total_words:
                    break
                cands = _candidates(word, grid)
                valid = [c for c in cands if _within_limit(word, c, grid)]
                if not valid:
                    still_remaining.append((word, clue))
                    continue
                best_cand = max(valid, key=lambda x: x["score"])
                _place_dict(word, best_cand["row"], best_cand["col"],
                            best_cand["direction"], grid)
                placed.append({
                    "word": word, "clue": clue,
                    "row": best_cand["row"], "col": best_cand["col"],
                    "direction": best_cand["direction"],
                })
            remaining = still_remaining
            if len(placed) >= max_total_words or not remaining:
                break

    # ── Stage 3: fill pass for singly-covered cells ──────────────────────────
    remaining_slots = max_total_words - len(placed)
    if filler_pairs and remaining_slots > 0:
        _fill_pass(grid, placed, filler_pairs, max_additional=remaining_slots)

    return _build(placed, grid)


def _attempt(
    pairs: List[Tuple[str, str]],
    filler_pairs: Optional[List[Tuple[str, str]]] = None,
    themed_all: Optional[List[Tuple[str, str]]] = None,
    min_themed: int = 4,
    max_themed: int = 7,
    max_total_words: int = 20,
) -> Optional[CrosswordData]:
    """
    Stage 1 – filler skeleton (7 greedy passes over all pairs).
    Stage 2 – greedy themed-word insertion: score every word in themed_all
              against the current grid and place them one at a time (best-fit
              first), until max_themed are placed or no more fit.  Returns
              None if fewer than min_themed were placed.
    Stage 3 – two-tier fill pass for residual singly-covered cells, capped
              so the total word count stays at or below max_total_words.
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

    # Stage 2: greedy placement of min_themed..max_themed themed words.
    # No pre-sorting by length or common-letter count — equal weighting.
    # Fit score alone determines which word is chosen at each step.
    if themed_all:
        used_words = {p["word"] for p in placed}
        pool = [(w, c) for w, c in themed_all if w not in used_words]
        random.shuffle(pool)  # equal weighting across attempts

        themed_placed = 0
        while pool and themed_placed < max_themed:
            scored: List[Tuple[float, str, str, Dict]] = []
            for word, clue in pool:
                cands = _candidates(word, grid)
                valid = [c for c in cands if _within_limit(word, c, grid)]
                if not valid:
                    continue
                top = max(valid, key=lambda x: x["score"])
                scored.append((top["score"], word, clue, top))

            if not scored:
                break

            scored.sort(key=lambda x: -x[0])
            # Sample from top candidates so each attempt explores different words
            top_n = max(1, min(5, len(scored)))
            _, chosen_word, chosen_clue, chosen_cand = random.choice(scored[:top_n])

            _place_dict(chosen_word, chosen_cand["row"], chosen_cand["col"],
                        chosen_cand["direction"], grid)
            placed.append({"word": chosen_word, "clue": chosen_clue,
                           "row": chosen_cand["row"], "col": chosen_cand["col"],
                           "direction": chosen_cand["direction"],
                           "is_themed": True})
            pool = [(w, c) for w, c in pool if w != chosen_word]
            themed_placed += 1

        if themed_placed < min_themed:
            return None

    # Stage 3: fill pass for singly-covered cells, capped at max_total_words
    remaining_slots = max_total_words - len(placed)
    if filler_pairs and remaining_slots > 0:
        _fill_pass(grid, placed, filler_pairs, max_additional=remaining_slots)

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
    max_additional: Optional[int] = None,
) -> None:
    """
    Two-tier fill toward full double-coverage, capped at max_additional words.

    Tier 1 – bridge words (≥2 intersections): net-positive for doubly-checked.
    Tier 2 – gap words  (≥1 intersection): best-effort for remaining cells.
    """
    initial_count = len(placed)
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
        if max_additional is not None and len(placed) - initial_count >= max_additional:
            return False
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
