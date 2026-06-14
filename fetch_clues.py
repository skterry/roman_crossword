#!/usr/bin/env python3
"""
Replace placeholder filler clues in puzzle.json with real definitions fetched
asynchronously from the Free Dictionary API (dictionaryapi.dev).

This is the optional step 1.5 of the pipeline:

    python generate_puzzle.py     # builds the grid (filler clues are placeholders)
    python fetch_clues.py         # fills in filler clues from dictionaryapi.dev
    streamlit run app.py          # serve

Only non-themed (filler) words are touched — Roman-themed words keep their
curated clues from secrets.toml.

Coverage note: dictionaryapi.dev only defines single dictionary headwords, so
the jammed-together phrases that appear in crossword wordlists (WELLATTENDED,
SALMONSTEAKS, BEERME, …) will 404.  Those keep a fallback clue.  Results are
cached in clue_cache.json so reruns don't re-hit the API; delete that file or
pass --refresh to re-fetch.

Usage:
    python fetch_clues.py [options]

Options:
    --puzzle PATH       Puzzle JSON to update (default: puzzle.json)
    --cache PATH        Definition cache file (default: clue_cache.json)
    --concurrency N     Max simultaneous requests (default: 4; dictionaryapi.dev
                        throttles higher rates with transient errors)
    --timeout S         Per-request timeout in seconds (default: 8)
    --max-len N         Truncate clues to N characters (default: 110)
    --refresh           Ignore the cache and re-fetch every filler word
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp

API = "https://api.dictionaryapi.dev/api/v2/entries/en/{}"

# Sentinel stored in the cache for a word the API has no definition for, so we
# don't keep re-requesting known misses on every run.
_MISS = ""


def fallback_clue(word: str) -> str:
    return f"{len(word)}-letter word (no dictionary clue available)"


# ---------------------------------------------------------------------------
# Clue construction from an API payload
# ---------------------------------------------------------------------------

def _censor(word: str, text: str) -> str:
    """Hide the answer (and simple inflections like plurals) inside the clue."""
    pat = re.compile(r"\b" + re.escape(word) + r"\w*", re.IGNORECASE)
    return pat.sub("____", text)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].rstrip(",;: ")
    return f"{cut}…"


def build_clue(word: str, payload: object, max_len: int) -> Optional[str]:
    """First usable definition → censored, truncated clue (no POS prefix)."""
    if not isinstance(payload, list):
        return None
    for entry in payload:
        for meaning in entry.get("meanings", []):
            for d in meaning.get("definitions", []):
                text = (d.get("definition") or "").strip()
                if not text:
                    continue
                clue = _truncate(_censor(word, text), max_len)
                clue = clue[0].upper() + clue[1:] if clue else clue
                return clue
    return None


# ---------------------------------------------------------------------------
# Async fetching
# ---------------------------------------------------------------------------

async def _fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    word: str,
    max_len: int,
) -> Tuple[str, str, Optional[str]]:
    """
    Returns (word, status, clue) where status is:
      'ok'    -> clue is a definition string (cache it)
      'miss'  -> 404 / no definition (cache the miss)
      'error' -> transient failure; do NOT cache, retry next run
    """
    url = API.format(word.lower())
    for attempt in range(3):
        async with sem:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        clue = build_clue(word, await resp.json(), max_len)
                        return (word, "ok", clue) if clue else (word, "miss", None)
                    if resp.status == 404:
                        return word, "miss", None
                    # 429 / 5xx: fall through to retry
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
        await asyncio.sleep(0.4 * (attempt + 1))
    return word, "error", None


async def _fetch_all(
    words: List[str], concurrency: int, timeout: int, max_len: int
) -> Dict[str, Tuple[str, Optional[str]]]:
    sem = asyncio.Semaphore(concurrency)
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    headers = {"User-Agent": "roman-crossword/1.0 (clue fetcher)"}
    results: Dict[str, Tuple[str, Optional[str]]] = {}
    async with aiohttp.ClientSession(timeout=timeout_cfg, headers=headers) as session:
        tasks = [_fetch_one(session, sem, w, max_len) for w in words]
        done = 0
        for coro in asyncio.as_completed(tasks):
            word, status, clue = await coro
            results[word] = (status, clue)
            done += 1
            print(f"\r  fetched {done}/{len(words)} …", end="", flush=True)
    print()
    return results


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def load_cache(path: str) -> Dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(path: str, cache: Dict[str, str]) -> None:
    Path(path).write_text(
        json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch dictionaryapi.dev clues for filler words.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--puzzle",      default="puzzle.json")
    parser.add_argument("--cache",       default="clue_cache.json")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout",     type=int, default=8)
    parser.add_argument("--max-len",     type=int, default=110)
    parser.add_argument("--refresh",     action="store_true")
    args = parser.parse_args()

    puzzle_path = Path(args.puzzle)
    if not puzzle_path.exists():
        print(f"{args.puzzle} not found — run generate_puzzle.py first.",
              file=sys.stderr)
        sys.exit(1)

    data = json.loads(puzzle_path.read_text(encoding="utf-8"))
    placements = data["placements"]

    # Unique filler words (themed words keep their curated clues).
    filler_words = sorted({
        p["word"] for p in placements if not p.get("is_themed", False)
    })
    print(f"{len(filler_words)} unique filler words in {args.puzzle}.")

    cache = {} if args.refresh else load_cache(args.cache)
    to_fetch = [w for w in filler_words if w not in cache]
    print(f"{len(cache)} cached, {len(to_fetch)} to fetch from dictionaryapi.dev.")

    if to_fetch:
        results = asyncio.run(
            _fetch_all(to_fetch, args.concurrency, args.timeout, args.max_len)
        )
        errors = 0
        for word, (status, clue) in results.items():
            if status == "ok":
                cache[word] = clue
            elif status == "miss":
                cache[word] = _MISS
            else:                       # transient error — leave uncached
                errors += 1
        save_cache(args.cache, cache)
        if errors:
            print(f"  {errors} transient errors (not cached; rerun to retry).")

    # Apply clues back to the puzzle.
    hits = misses = 0
    for p in placements:
        if p.get("is_themed", False):
            continue
        cached = cache.get(p["word"], None)
        if cached:                      # non-empty string == real definition
            p["clue"] = cached
            hits += 1
        else:                           # missing or _MISS
            p["clue"] = fallback_clue(p["word"])
            misses += 1

    puzzle_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    total = hits + misses
    pct = 100 * hits / total if total else 0
    print(f"\n── Clue coverage ──────────────────────────────────────────────")
    print(f"  Definitions applied : {hits}/{total} ({pct:.0f}%)")
    print(f"  Fallback clues       : {misses}  (no dictionaryapi.dev entry)")
    print(f"  Cache                : {args.cache}")
    print(f"  Updated              : {args.puzzle}")


if __name__ == "__main__":
    main()
