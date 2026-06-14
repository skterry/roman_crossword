"""
Offline clue source backed by WordNet (via nltk).

Used to (a) restrict the filler pool to words that actually have a dictionary
definition, and (b) turn each placed filler word into a clue from its WordNet
gloss.  This replaces the dictionaryapi.dev fetch for filler clues: it is
instant, fully offline, and guarantees 100% clue coverage because the fill pool
is pre-filtered to defined words.

Requires:  pip install nltk   +   python -m nltk.downloader wordnet omw-1.4
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from nltk.corpus import wordnet as wn

def is_cluable(word: str) -> bool:
    """True if WordNet has at least one sense for the word (morphy-normalised)."""
    return bool(wn.synsets(word.lower()))


def filter_cluable(
    scored: Sequence[Tuple[str, int]]
) -> List[Tuple[str, int]]:
    """Keep only the entries WordNet can define."""
    return [(w, s) for w, s in scored if wn.synsets(w.lower())]


def _censor(word: str, text: str) -> str:
    """Blank out the answer (and simple inflections / its base lemma)."""
    forms = {word.lower()}
    lemma = wn.morphy(word.lower())
    if lemma:
        forms.add(lemma)
    for form in sorted(forms, key=len, reverse=True):
        text = re.sub(r"\b" + re.escape(form) + r"\w*", "____", text, flags=re.IGNORECASE)
    return text


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].rstrip(",;: ")
    return f"{cut}…"


def clue_for(word: str, max_len: int = 110) -> Optional[str]:
    """First WordNet sense -> censored, truncated clue (no POS prefix)."""
    syns = wn.synsets(word.lower())
    if not syns:
        return None
    sense = syns[0]
    gloss = (sense.definition() or "").strip()
    if not gloss:
        return None
    clue = _truncate(_censor(word, gloss), max_len)
    if not clue:
        return None
    return clue[0].upper() + clue[1:]
