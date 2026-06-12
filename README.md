# Roman Space Telescope Crossword Puzzle

<p>
  Hosted on Streamlit
  <a href="https://streamlit.io/" target="_blank">
    <img src="icon/streamlit_icon.png" alt="Streamlit" height="22" align="top"/>
  </a>
</p>

<a href="https://romancrossword.streamlit.app/" target="_blank">
  <img src="https://img.shields.io/badge/Play%20Now-brightgreen?style=for-the-badge" alt="Play Now!"/>
</a>

An interactive browser-based crossword puzzle themed around the [Nancy Grace Roman Space Telescope](https://roman.gsfc.nasa.gov/) mission.

## Overview

The puzzle is built **offline** by `generate_puzzle.py` into a single `puzzle.json` file, which the app loads and serves. It blends curated Roman-mission clues (science, instrumentation, key personnel, partner observatories, and cosmology) with dictionary-defined filler words on a fixed 12×12 grid. The game runs entirely in the browser — no backend state is required beyond the Streamlit session.

### Features

- **Pre-built, hand-vetted puzzle** — the grid is generated offline, then its clues are reviewed for fairness (abbreviations flagged, obscure/wrong definitions rewritten, offensive entries removed) before being committed as `puzzle.json`. The app loads this one puzzle; "New Game" restarts it with a cleared board.
- **Interactive grid** — click any cell on the puzzle board to select a word; clicking a crossing cell toggles between the across and down word for that cell.
- **Answer submission** — type your answer and press Enter or click Submit. Correct answers are revealed on the grid; incorrect answers prompt a retry.
- **Give Up** — reveals all remaining answers and ends the current game.
- **Progress bar** — tracks how many words have been solved out of the total placed.
- **Completion banner** — shown when all words are solved.

## Project Structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit entry point — loads `puzzle.json`, builds the HTML/JS game, and renders the UI |
| `puzzle.json` | The generated puzzle the app serves (grid, word placements, clues) |
| `generate_puzzle.py` | Offline generator — builds one or more puzzles, assigns clues, and writes `puzzle.json` |
| `grid_filler.py` | Grid engine — themed-word placement, black-square carving, backtracking fill, and the all-real-words repair pass |
| `crossword_generator.py` | Core data classes (`WordPlacement`, `CrosswordData`) and grid helpers shared by the app and generator |
| `wordnet_clues.py` | Offline clue source — turns each filler word into a clue from its WordNet gloss |
| `.streamlit/secrets.toml` | Curated Roman-themed answers and clues (generator input; gitignored) |
| `icon/RST_icon.png` | Browser tab icon |
| `requirements.txt` | Python dependencies for running the app |

> **Note:** the large wordlist inputs (`*.dict`, `clues.tsv`) and the throwaway trial puzzles (`puzzle1.json` … `puzzle.json.bak`) are gitignored — only `puzzle.json` is committed and served.

## Dependencies

**Running the app** (`requirements.txt`):

| Package | Purpose |
|---|---|
| `streamlit>=1.30.0` | Web app framework — renders the UI and manages session state |
| `Pillow>=10.0.0` | Opens the PNG icon file passed to `st.set_page_config` |

**Generating puzzles** (not needed to run the app):

| Package | Purpose |
|---|---|
| `nltk` (+ `wordnet`, `omw-1.4`) | Filler-word clue source and definability filter |

## Running Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app loads the committed `puzzle.json` and opens in your browser at `http://localhost:8501`.

## Generating a Puzzle

Puzzles are produced offline, then a single chosen `puzzle.json` is committed and served.

```bash
# one-time setup for the offline clue source
pip install nltk && python -m nltk.downloader wordnet omw-1.4

# generate 5 candidate puzzles → puzzle1.json … puzzle5.json
python generate_puzzle.py --trials 5

# (or a single puzzle straight to puzzle.json)
python generate_puzzle.py
```

**Selection & review.** With `--trials`, the generator prints a summary (density, word count, themed words) for each candidate. Pick the best one for a human solver — favouring higher density, fewer obscure short entries, and no "junk" answers (e.g. chemical-symbol-plus-S) — copy it to `puzzle.json`, then do a clue-review pass: flag abbreviations, rewrite obscure or wrong definitions, fix singular/plural mismatches, and remove anything offensive.

### How generation works (fixed 12×12)

1. **Themed placement** — Roman-themed answers from `.streamlit/secrets.toml` are placed across the board, edge-anchored and spread vertically, each sealed with a black buffer.
2. **Black squares** — carved in so every white run is at least 3 cells long.
3. **Fill** — every remaining slot is filled by backtracking search over a *scored* crossword wordlist. The filler pool is pre-filtered to words WordNet can define, so every filler is guaranteed cluable.
4. **Repair pass** — any incidental run that isn't a real word is re-lettered into one where possible (and only blackened as a last resort), keeping density around 0.74–0.78.
5. **Clues** — themed answers keep their curated `secrets.toml` clues; filler answers get their WordNet gloss. A `_BLOCKED` set in `generate_puzzle.py` permanently excludes offensive or non-word answers from ever being placed.
6. **Numbering** — cells are numbered left-to-right, top-to-bottom following standard crossword convention.
