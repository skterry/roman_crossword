"""
Fixed-grid crossword construction with a scored wordlist.

Strategy (replaces the old floating-size greedy generator):

  1.  Work on a fixed GRID x GRID board (default 12x12).  Every cell starts
      available for a word.
  2.  Place a handful of Roman-themed words ACROSS, edge-anchored (each begins
      at the left edge or ends at the right edge) and spread evenly down the
      board.  A black "buffer" square seals the open end so the themed word is
      a maximal run.
  3.  Carve a black-square template into the rest of the board such that every
      white run (across and down) is length >= 3 — i.e. the grid is fully
      interlocking / fully checked — while keeping density >= the target.
  4.  Fill every remaining white slot with real words drawn from a *scored*
      wordlist (Spread-the-Wordlist / Crossword-Nexus collaborative list),
      using backtracking search with most-constrained-variable ordering and
      forward checking.  This is how dedicated fill software solves a template.

Clues for the filler words are intentionally left as placeholders — the goal
here is purely to pack real English words at high density.  Themed words keep
their real clues.

The dictionaryapi.dev service is deliberately NOT used to *find* fill words:
it is a definition-lookup API and cannot answer "which words match C?T?S".
It is the right tool for fetching clue text later, which is a separate step.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from crossword_generator import CrosswordData, WordPlacement

GRID = 12                       # fixed board edge length
BLACK = "#"
EMPTY = "."
_ALPHA = re.compile(r"^[A-Z]+$")

Cell = Tuple[int, int]
FILLER_CLUE = "(definition pending)"


# ---------------------------------------------------------------------------
# Scored wordlist + pattern index
# ---------------------------------------------------------------------------

class WordIndex:
    """
    Length- and position-indexed view of a scored wordlist.

    matches(pattern) returns the set of words of len(pattern) whose letters
    agree with every non-'.' position of `pattern`.  Lookups are pure set
    intersections, so a slot's candidate list is produced in microseconds.
    """

    def __init__(self, scored: Sequence[Tuple[str, int]]):
        self.score: Dict[str, int] = {}
        self._by_len: Dict[int, Set[str]] = {}
        self._pos: Dict[Tuple[int, int, str], Set[str]] = {}
        for word, sc in scored:
            if word in self.score:
                continue
            self.score[word] = sc
            L = len(word)
            self._by_len.setdefault(L, set()).add(word)
            for i, ch in enumerate(word):
                self._pos.setdefault((L, i, ch), set()).add(word)

    def lengths(self) -> Set[int]:
        return set(self._by_len)

    def matches(self, pattern: str) -> Set[str]:
        L = len(pattern)
        constrained = [(i, ch) for i, ch in enumerate(pattern) if ch != EMPTY]
        if not constrained:
            return self._by_len.get(L, set())
        sets: List[Set[str]] = []
        for i, ch in constrained:
            s = self._pos.get((L, i, ch))
            if not s:
                return set()
            sets.append(s)
        sets.sort(key=len)
        result = set(sets[0])
        for s in sets[1:]:
            result &= s
            if not result:
                break
        return result


def _iter_word_scores(path: str, tsv_score: int):
    """
    Yield (word, score) pairs from one source file.

    * ``.tsv`` files are treated as crossword databases (``pubid year answer
      clue`` columns); the answer column is taken and given ``tsv_score`` since
      these carry no quality score of their own.
    * everything else is parsed as ``WORD;SCORE``.
    """
    is_tsv = str(path).lower().endswith(".tsv")
    with open(path, encoding="utf-8", errors="replace") as f:
        if is_tsv:
            next(f, None)                          # skip header row
            for line in f:
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 3:
                    continue
                yield cols[2].strip().upper(), tsv_score
        else:
            for line in f:
                word, sep, raw = line.strip().partition(";")
                if not sep:
                    continue
                try:
                    yield word.upper(), int(raw)
                except ValueError:
                    continue


def load_scored_wordlist(
    paths: "str | Sequence[str]",
    min_score: int = 50,
    min_len: int = 3,
    max_len: int = GRID,
    exclude: Optional[Set[str]] = None,
    tsv_score: int = 50,
) -> List[Tuple[str, int]]:
    """
    Parse one or more word sources into a merged, deduplicated pool of
    pure-alphabetic entries within the length window.

    Sources may be ``WORD;SCORE`` dict files or ``.tsv`` crossword databases
    (see _iter_word_scores).  When a word appears in several files (or several
    times) the highest score wins, so combining lists can only promote a word,
    never demote it.  The ``min_score`` cut is applied after merging.
    """
    if isinstance(paths, str):
        paths = [paths]
    exclude = {w.upper() for w in (exclude or set())}
    best: Dict[str, int] = {}
    for path in paths:
        for word, sc in _iter_word_scores(path, tsv_score):
            if word in exclude:
                continue
            if not (min_len <= len(word) <= max_len) or not _ALPHA.match(word):
                continue
            if sc > best.get(word, -1):
                best[word] = sc
    return [(w, s) for w, s in best.items() if s >= min_score]


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------

@dataclass
class Slot:
    cells: List[Cell]
    direction: str  # 'across' | 'down'

    @property
    def length(self) -> int:
        return len(self.cells)

    @property
    def start(self) -> Cell:
        return self.cells[0]


def _find_runs(grid: List[List[str]]) -> List[Slot]:
    """Every maximal white run (length >= 3) becomes a slot."""
    slots: List[Slot] = []
    n = len(grid)
    # across
    for r in range(n):
        c = 0
        while c < n:
            if grid[r][c] == BLACK:
                c += 1
                continue
            start = c
            while c < n and grid[r][c] != BLACK:
                c += 1
            if c - start >= 3:
                slots.append(Slot([(r, cc) for cc in range(start, c)], "across"))
    # down
    for c in range(n):
        r = 0
        while r < n:
            if grid[r][c] == BLACK:
                r += 1
                continue
            start = r
            while r < n and grid[r][c] != BLACK:
                r += 1
            if r - start >= 3:
                slots.append(Slot([(rr, c) for rr in range(start, r)], "down"))
    return slots


def _has_bad_run(grid: List[List[str]], r: int, c: int) -> bool:
    """
    True if row r or column c contains a white run of length 1 or 2.
    Only the row/column that just changed need to be re-checked.
    """
    n = len(grid)
    for line in (
        [grid[r][cc] for cc in range(n)],     # row r
        [grid[rr][c] for rr in range(n)],     # column c
    ):
        run = 0
        for cell in line + [BLACK]:
            if cell == BLACK:
                if 0 < run < 3:
                    return True
                run = 0
            else:
                run += 1
    return False


# ---------------------------------------------------------------------------
# Template construction (themed words + black squares)
# ---------------------------------------------------------------------------

def _spread_rows(n: int, edge: int) -> List[int]:
    """n distinct rows spread across [0, edge], preferring a gap between them."""
    if n <= 0:
        return []
    if n == 1:
        return [edge // 2]
    rows = sorted({round(i * edge / (n - 1)) for i in range(n)})
    # If rounding collapsed two rows together, nudge to keep them distinct.
    for i in range(1, len(rows)):
        if rows[i] <= rows[i - 1]:
            rows[i] = rows[i - 1] + 1
    return [r for r in rows if r <= edge]


def _place_themed(
    grid: List[List[str]],
    themed: List[Tuple[str, str]],
    rng: random.Random,
) -> Optional[List[Dict]]:
    """
    Place themed words ACROSS, edge-anchored, on spread-out rows.  Seals each
    open end (and any 1–2 cell leftover) with black squares.  Returns the list
    of placed themed entries, or None if the layout is structurally invalid.
    """
    n = len(grid)
    rows = _spread_rows(len(themed), n - 1)
    if len(rows) < len(themed):
        return None

    placed: List[Dict] = []
    for i, (row, (word, clue)) in enumerate(zip(rows, themed)):
        L = len(word)
        left = (i % 2 == 0)               # alternate left / right anchoring
        col = 0 if left else n - L

        for j, ch in enumerate(word):
            grid[row][col + j] = ch

        # Seal the open end with a black buffer.  If the strip beyond the
        # buffer is only 1–2 cells (too short to be its own word) black it too.
        if left and L < n:
            buffer_c = L
            leftover = n - L - 1                 # cells right of the buffer
            grid[row][buffer_c] = BLACK
            if 0 < leftover < 3:
                for cc in range(buffer_c + 1, n):
                    grid[row][cc] = BLACK
        elif not left and n - L - 1 >= 0:
            buffer_c = n - L - 1
            leftover = buffer_c                  # cells left of the buffer
            grid[row][buffer_c] = BLACK
            if 0 < leftover < 3:
                for cc in range(0, buffer_c):
                    grid[row][cc] = BLACK

        placed.append({
            "word": word, "clue": clue, "row": row, "col": col,
            "direction": "across", "is_themed": True,
        })

    # Reject if the themed/buffer layout already created a 1–2 length run.
    for p in placed:
        if _has_bad_run(grid, p["row"], p["col"]):
            return None
    return placed


def _carve_blacks(
    grid: List[List[str]],
    locked: Set[Cell],
    target_black: int,
    rng: random.Random,
) -> None:
    """
    Randomly add black squares (never onto a locked themed/buffer cell) while
    keeping every white run length >= 3, until target_black is reached or no
    more legal additions are found.
    """
    n = len(grid)
    current = sum(row.count(BLACK) for row in grid)
    free = [
        (r, c) for r in range(n) for c in range(n)
        if grid[r][c] == EMPTY and (r, c) not in locked
    ]
    rng.shuffle(free)

    attempts = 0
    limit = len(free) * 3
    while current < target_black and free and attempts < limit:
        attempts += 1
        r, c = free.pop()
        if grid[r][c] != EMPTY:
            continue
        grid[r][c] = BLACK
        if _has_bad_run(grid, r, c):
            grid[r][c] = EMPTY            # revert illegal cut
        else:
            current += 1


# ---------------------------------------------------------------------------
# Backtracking fill (MRV + forward checking)
# ---------------------------------------------------------------------------

def _pattern(grid: List[List[str]], slot: Slot) -> str:
    return "".join(grid[r][c] for r, c in slot.cells)


def _fill(
    grid: List[List[str]],
    slots: List[Slot],
    cell_slots: Dict[Cell, List[Slot]],
    index: WordIndex,
    used: Set[str],
    budget: List[int],
    rng: random.Random,
) -> bool:
    """Depth-first fill with most-constrained-variable selection.

    NOTE: a slot that becomes fully filled purely by crossing letters is
    accepted without checking it spells a real word — so a few short incidental
    runs (e.g. "AOE") can slip through.  Those are blackened afterwards by
    _repair_to_valid, trading a little density for an all-real-words grid.
    """
    if budget[0] <= 0:
        return False

    # Variable selection: among slots that still have an empty cell, prefer the
    # most-constrained one that already has >=1 letter (its domain is small and
    # cheap to compute).  Fully-empty slots are deferred — querying their whole
    # length-bucket is expensive and pointless until a crossing seeds a letter.
    target: Optional[Slot] = None
    target_cands: Optional[Set[str]] = None
    best = float("inf")
    seed: Optional[Slot] = None
    for slot in slots:
        empty = filled = 0
        for r, c in slot.cells:
            if grid[r][c] == EMPTY:
                empty += 1
            else:
                filled += 1
        if empty == 0:
            continue                      # already satisfied
        if filled == 0:
            if seed is None or slot.length > seed.length:
                seed = slot               # longest empty slot seeds a region
            continue
        cands = index.matches(_pattern(grid, slot)) - used
        if not cands:
            return False
        if len(cands) < best:
            best, target, target_cands = len(cands), slot, cands
            if best == 1:
                break

    if target is None:
        if seed is None:
            return True                   # every slot satisfied
        # Seed an untouched region with its highest-scoring words (capped).
        target = seed
        target_cands = index.matches(_pattern(grid, seed)) - used
        if not target_cands:
            return False

    budget[0] -= 1
    ordered = sorted(
        target_cands,
        key=lambda w: -(index.score[w] + rng.uniform(0, 12)),
    )[:60]
    crossing = _crossings(target, cell_slots)

    for word in ordered:
        changed = _apply(grid, target, word)
        used.add(word)
        if _forward_ok(grid, crossing, index, used) and \
                _fill(grid, slots, cell_slots, index, used, budget, rng):
            return True
        used.discard(word)
        _undo(grid, changed)
        if budget[0] <= 0:
            return False
    return False


def _crossings(slot: Slot, cell_slots: Dict[Cell, List[Slot]]) -> List[Slot]:
    seen: List[Slot] = []
    for cell in slot.cells:
        for other in cell_slots[cell]:
            if other is not slot and other not in seen:
                seen.append(other)
    return seen


def _forward_ok(
    grid: List[List[str]],
    crossing: List[Slot],
    index: WordIndex,
    used: Set[str],
) -> bool:
    for slot in crossing:
        pat = _pattern(grid, slot)
        if EMPTY not in pat:
            continue
        if not (index.matches(pat) - used):
            return False
    return True


def _apply(grid: List[List[str]], slot: Slot, word: str) -> List[Cell]:
    changed: List[Cell] = []
    for (r, c), ch in zip(slot.cells, word):
        if grid[r][c] == EMPTY:
            grid[r][c] = ch
            changed.append((r, c))
    return changed


def _undo(grid: List[List[str]], changed: List[Cell]) -> None:
    for r, c in changed:
        grid[r][c] = EMPTY


# ---------------------------------------------------------------------------
# Post-fill repair — make every entry a real word
# ---------------------------------------------------------------------------

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _is_word(word: str, index: WordIndex, themed_words: Set[str]) -> bool:
    return word in index.score or word in themed_words


def _resolve_junk(
    grid: List[List[str]],
    run: Slot,
    cell_to_slots: Dict[Cell, List[Slot]],
    index: WordIndex,
    themed_words: Set[str],
    themed_cells: Set[Cell],
) -> bool:
    """
    Try to turn a junk run into a real word by re-lettering it in place.

    For each cell, the only word it shares with the rest of the grid is the
    perpendicular crossing word; that word changes by exactly one letter (the
    shared cell), so a substitution that keeps it real causes NO cascade — its
    other cells are untouched.  We compute, per cell, the set of letters that
    keep the crossing word real, then look for a real word for `run` whose
    letters all fall inside those sets.  Returns True (and rewrites the grid)
    on success, False if no such word exists.
    """
    cells = run.cells
    L = len(cells)
    allowed: List[Optional[Set[str]]] = []
    for (r, c) in cells:
        if (r, c) in themed_cells:
            allowed.append({grid[r][c]})        # themed letter is locked
            continue
        perp = next((s for s in cell_to_slots[(r, c)]
                     if s is not run and s.direction != run.direction), None)
        if perp is None:
            allowed.append(None)                # unchecked cell — any letter ok
            continue
        pos = perp.cells.index((r, c))
        cur = [grid[pr][pc] for (pr, pc) in perp.cells]
        ok: Set[str] = set()
        for x in _LETTERS:
            cur[pos] = x
            if _is_word("".join(cur), index, themed_words):
                ok.add(x)
        allowed.append(ok)

    if any(a is not None and not a for a in allowed):
        return False                            # some cell admits no letter

    best_word: Optional[str] = None
    best_score = -1
    for w in index.matches("." * L):            # all real words of this length
        if any(a is not None and ch not in a for ch, a in zip(w, allowed)):
            continue
        sc = index.score[w]
        if sc > best_score:
            best_score, best_word = sc, w
    if best_word is None:
        return False

    for (r, c), ch in zip(cells, best_word):    # rewrite (perp words follow)
        if (r, c) not in themed_cells:
            grid[r][c] = ch
    return True


def _repair_to_valid(
    grid: List[List[str]],
    index: WordIndex,
    themed_words: Set[str],
    themed_cells: Set[Cell],
) -> None:
    """
    Turn the filled grid into an all-real-words grid, preserving as much
    density as possible.

    For each run >= 3 whose word isn't real, first try _resolve_junk to
    re-letter it into a real word (no cells lost).  Only if that fails do we
    blacken a single cell — the one splitting it most evenly — so the junk
    entry disappears while its crossing words stay intact.  Finally, any cell
    left in no run >= 3 is blackened as an orphan.  Themed cells are never
    touched; runs only shrink when blackening, so this converges.
    """
    n = len(grid)
    while True:
        runs = _find_runs(grid)
        cell_to_slots: Dict[Cell, List[Slot]] = {}
        for s in runs:
            for cell in s.cells:
                cell_to_slots.setdefault(cell, []).append(s)

        junk = next((r for r in runs
                     if not _is_word(_pattern(grid, r), index, themed_words)), None)
        if junk is not None:
            if _resolve_junk(grid, junk, cell_to_slots, index,
                             themed_words, themed_cells):
                continue                        # fixed in place; recompute fresh
            # Fallback: minimal blacken (split most evenly, skip themed cells).
            L = len(junk.cells)
            choice: Optional[Cell] = None
            best = 10 ** 9
            for i, cell in enumerate(junk.cells):
                if cell in themed_cells:
                    continue
                worst_side = max(i, L - 1 - i)
                if worst_side < best:
                    best, choice = worst_side, cell
            if choice is not None:
                grid[choice[0]][choice[1]] = BLACK
            continue

        # No junk left — blacken any orphaned (uncovered) white cell.
        covered: Set[Cell] = set()
        for s in runs:
            covered.update(s.cells)
        did_black = False
        for r in range(n):
            for c in range(n):
                if (grid[r][c] != BLACK and (r, c) not in covered
                        and (r, c) not in themed_cells):
                    grid[r][c] = BLACK
                    did_black = True
        if not did_black:
            break


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _build_data(
    grid: List[List[str]],
    themed_lookup: Dict[Tuple[int, int, str], Tuple[str, bool]],
) -> CrosswordData:
    n = len(grid)
    number: Dict[Cell, int] = {}
    counter = 1
    for r in range(n):
        for c in range(n):
            if grid[r][c] == BLACK:
                continue
            starts_a = (c == 0 or grid[r][c - 1] == BLACK) and \
                       (c + 1 < n and grid[r][c + 1] != BLACK)
            starts_d = (r == 0 or grid[r - 1][c] == BLACK) and \
                       (r + 1 < n and grid[r + 1][c] != BLACK)
            if starts_a or starts_d:
                number[(r, c)] = counter
                counter += 1

    placements: List[WordPlacement] = []
    for slot in _find_runs(grid):
        word = _pattern(grid, slot)
        r, c = slot.start
        clue, is_themed = themed_lookup.get(
            (r, c, slot.direction), (FILLER_CLUE, False)
        )
        placements.append(WordPlacement(
            word=word, clue=clue, row=r, col=c,
            direction=slot.direction, number=number.get((r, c), 0),
            is_themed=is_themed,
        ))
    placements.sort(key=lambda p: (p.number, p.direction))
    return CrosswordData(grid=grid, placements=placements, rows=n, cols=n)


def density(cw: CrosswordData) -> float:
    white = sum(cell != BLACK for row in cw.grid for cell in row)
    return white / (cw.rows * cw.cols)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_fixed_puzzle(
    themed_pool: Sequence[Tuple[str, str]],
    index: WordIndex,
    n_themed: int,
    black_target: int,
    node_budget: int = 200_000,
    rng: Optional[random.Random] = None,
) -> Optional[CrosswordData]:
    """
    Build one fully-filled fixed-grid puzzle, or None if this attempt fails.
    Callers run this repeatedly and keep the densest valid result.
    """
    rng = rng or random.Random()

    eligible = [(w, c) for w, c in themed_pool if 3 <= len(w) <= GRID]
    if len(eligible) < n_themed:
        return None
    themed = rng.sample(eligible, n_themed)

    grid = [[EMPTY] * GRID for _ in range(GRID)]
    placed_themed = _place_themed(grid, themed, rng)
    if placed_themed is None:
        return None

    locked: Set[Cell] = {
        (r, c)
        for r in range(GRID) for c in range(GRID)
        if grid[r][c] != EMPTY
    }
    _carve_blacks(grid, locked, black_target, rng)

    slots = _find_runs(grid)
    # Sanity: a slot length the wordlist can't serve dooms the fill outright.
    avail = index.lengths()
    if any(s.length not in avail for s in slots):
        return None

    cell_slots: Dict[Cell, List[Slot]] = {}
    for slot in slots:
        for cell in slot.cells:
            cell_slots.setdefault(cell, []).append(slot)

    themed_words: Set[str] = {p["word"] for p in placed_themed}
    used: Set[str] = set(themed_words)
    budget = [node_budget]
    if not _fill(grid, slots, cell_slots, index, used, budget, rng):
        return None

    # The fast fill can leave a few short incidental runs that aren't real
    # words (e.g. "AOE").  Black them out so every remaining entry is real.
    themed_cells: Set[Cell] = {
        cell for p in placed_themed
        for cell in Slot(
            [(p["row"], p["col"] + i) for i in range(len(p["word"]))], "across"
        ).cells
    }
    _repair_to_valid(grid, index, themed_words, themed_cells)

    themed_lookup = {
        (p["row"], p["col"], p["direction"]): (p["clue"], True)
        for p in placed_themed
    }
    return _build_data(grid, themed_lookup)
