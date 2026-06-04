import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

ROW_LIMIT = 15  # Hard cap on rows  (~14 rows × 46 px ≈ 644 px)
COL_LIMIT = 20  # Hard cap on columns (~19 cols × 46 px ≈ 874 px)

_GridDict = Dict[Tuple[int, int], str]


@dataclass
class WordPlacement:
    word: str
    clue: str
    row: int
    col: int
    direction: str  # 'across' or 'down'
    number: int = 0

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
    max_attempts: int = 200,
) -> Optional[CrosswordData]:
    """
    Run many randomised placement attempts and return the densest valid layout.
    Scoring favours: more words placed, higher density, more crossing cells, squareness.
    """
    best: Optional[CrosswordData] = None
    best_score = -1.0

    pairs = [(w.upper().strip(), c) for w, c in word_clue_pairs]

    for _ in range(max_attempts):
        shuffled = list(pairs)
        random.shuffle(shuffled)
        # Longest words first so they anchor the grid early
        shuffled.sort(key=lambda x: len(x[0]), reverse=True)

        result = _attempt(shuffled)
        if result is None:
            continue

        total_letters = sum(len(p.word) for p in result.placements)
        area = result.rows * result.cols
        squareness_bonus = -abs(result.cols - result.rows) * 5

        # Count cells shared by both an across and a down word (real crossing points)
        cell_usage: Dict[Tuple[int, int], int] = {}
        for p in result.placements:
            for cell in p.cells():
                cell_usage[cell] = cell_usage.get(cell, 0) + 1
        total_intersections = sum(1 for v in cell_usage.values() if v > 1)

        attempt_score = (
            len(result.placements) * 100
            + (total_letters / area) * 200
            + total_intersections * 40   # explicit reward for crossing cells
            + squareness_bonus
        )
        if attempt_score > best_score:
            best = result
            best_score = attempt_score

    return best


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _attempt(pairs: List[Tuple[str, str]]) -> Optional[CrosswordData]:
    grid: _GridDict = {}
    placed: List[Dict] = []

    # Anchor: place the longest word horizontally at the origin
    first_word, first_clue = pairs[0]
    _place_dict(first_word, 0, 0, "across", grid)
    placed.append({"word": first_word, "clue": first_clue,
                   "row": 0, "col": 0, "direction": "across"})

    remaining = list(pairs[1:])

    # Multiple passes: each new word opens intersection opportunities for skipped words
    for _pass in range(5):
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

    return _build(placed, grid)


def _within_limit(word: str, cand: Dict, grid: _GridDict) -> bool:
    tmp = dict(grid)
    _place_dict(word, cand["row"], cand["col"], cand["direction"], tmp)
    rs = [k[0] for k in tmp]
    cs = [k[1] for k in tmp]
    return (max(rs) - min(rs) < ROW_LIMIT and
            max(cs) - min(cs) < COL_LIMIT)


def _candidates(word: str, grid: _GridDict) -> List[Dict]:
    """Return every valid (row, col, direction) placement that intersects the grid."""
    out = []
    for (gr, gc), gl in list(grid.items()):
        for wi, wl in enumerate(word):
            if wl != gl:
                continue
            # Across: word[wi] lands on grid cell (gr, gc)
            r, c = gr, gc - wi
            if _valid(word, r, c, "across", grid):
                out.append({"row": r, "col": c, "direction": "across",
                             "score": _score(word, r, c, "across", grid)})
            # Down
            r, c = gr - wi, gc
            if _valid(word, r, c, "down", grid):
                out.append({"row": r, "col": c, "direction": "down",
                             "score": _score(word, r, c, "down", grid)})
    return out


def _valid(word: str, row: int, col: int, direction: str, grid: _GridDict) -> bool:
    """
    A placement is valid when:
      - it shares ≥1 letter with the existing grid (intersection)
      - no letter-conflict at any shared cell
      - no word is extended at its start/end
      - no new cell runs parallel-adjacent to an existing word
        (which would silently create an unintended word in the crossing direction)
    """
    length = len(word)
    intersections = 0

    if direction == "across":
        if grid.get((row, col - 1)) is not None:          # extends a word to the left
            return False
        if grid.get((row, col + length)) is not None:     # extends a word to the right
            return False
        for i, letter in enumerate(word):
            r, c = row, col + i
            existing = grid.get((r, c))
            if existing is not None:
                if existing != letter:
                    return False
                intersections += 1            # valid crossing
            else:
                # brand-new cell: must not be adjacent to a parallel (also across) word
                if grid.get((r - 1, c)) is not None or grid.get((r + 1, c)) is not None:
                    return False
    else:  # down
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
    """
    Score a candidate placement.

    Key insight: one extra intersection is worth far more than a marginal area saving,
    so intersections dominate.  The area penalty keeps the grid compact when scores tie.
    """
    intersections = 0
    for i, letter in enumerate(word):
        r = row + (i if direction == "down" else 0)
        c = col + (i if direction == "across" else 0)
        if grid.get((r, c)) == letter:
            intersections += 1

    # Bounding box after placement
    tmp = dict(grid)
    _place_dict(word, row, col, direction, tmp)
    all_r = [k[0] for k in tmp]
    all_c = [k[1] for k in tmp]
    h    = max(all_r) - min(all_r) + 1
    w    = max(all_c) - min(all_c) + 1
    area = h * w

    # Penalise deviation from square in either direction.
    # Each cell of excess (tall OR wide) costs 6 pts — less than one intersection
    # (20 pts) so it never overrides a genuinely better crossing, but consistently
    # nudges candidates toward square-ish layouts.
    aspect_penalty = abs(h - w) * 6

    return intersections * 20 - area * 0.15 - aspect_penalty + random.uniform(0, 0.4)


def _place_dict(word: str, row: int, col: int, direction: str, grid: _GridDict) -> None:
    for i, letter in enumerate(word):
        r = row + (i if direction == "down" else 0)
        c = col + (i if direction == "across" else 0)
        grid[(r, c)] = letter


def _build(placed: List[Dict], grid: _GridDict) -> CrosswordData:
    # Normalise so top-left is (0, 0)
    min_r = min(k[0] for k in grid)
    min_c = min(k[1] for k in grid)

    norm: _GridDict = {(r - min_r, c - min_c): ltr for (r, c), ltr in grid.items()}
    norm_placed = [{**p, "row": p["row"] - min_r, "col": p["col"] - min_c}
                   for p in placed]

    rows = max(k[0] for k in norm) + 1
    cols = max(k[1] for k in norm) + 1

    # 2-D char grid: '#' = black square
    g = [["#"] * cols for _ in range(rows)]
    for (r, c), ltr in norm.items():
        g[r][c] = ltr

    # Number cells left-to-right, top-to-bottom (standard crossword convention)
    number = 1
    cell_numbers: Dict[Tuple[int, int], int] = {}
    for r in range(rows):
        for c in range(cols):
            if g[r][c] == "#":
                continue
            starts_across = (c == 0 or g[r][c - 1] == "#") and (c + 1 < cols and g[r][c + 1] != "#")
            starts_down   = (r == 0 or g[r - 1][c] == "#") and (r + 1 < rows and g[r + 1][c] != "#")
            if starts_across or starts_down:
                cell_numbers[(r, c)] = number
                number += 1

    placements = [
        WordPlacement(
            word=p["word"], clue=p["clue"],
            row=p["row"], col=p["col"], direction=p["direction"],
            number=cell_numbers.get((p["row"], p["col"]), 0),
        )
        for p in norm_placed
    ]
    placements.sort(key=lambda x: (x.number, x.direction))

    return CrosswordData(grid=g, placements=placements, rows=rows, cols=cols)
