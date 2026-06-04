# Roman Space Telescope Crossword Puzzle

An interactive browser-based crossword puzzle built with [Streamlit](https://streamlit.io), themed around the [Nancy Grace Roman Space Telescope](https://roman.gsfc.nasa.gov/) mission.

<a href="https://romancrossword.streamlit.app/" target="_blank">
  <img src="https://img.shields.io/badge/Play%20Now-brightgreen?style=for-the-badge" alt="Play Now"/>
</a>

## Overview

Each session generates a unique crossword from a curated bank of clues covering Roman mission science, instrumentation, key personnel, partner observatories, and cosmology concepts. The game runs entirely in the browser — no backend state is required beyond the Streamlit session.

### Features

- **Procedurally generated puzzles** — every "New Game" produces a different layout by randomly selecting ~20 words from the clue bank and running a multi-pass placement algorithm that maximises word intersections and grid compactness.
- **Interactive grid** — click any cell on the puzzle board to select a word; clicking a crossing cell toggles between the across and down word for that cell.
- **Answer submission** — type your answer and press Enter or click Submit. Correct answers are revealed on the grid; incorrect answers prompt a retry.
- **Give Up** — reveals all remaining answers and ends the current game.
- **Progress bar** — tracks how many words have been solved out of the total placed.
- **Completion banner** — shown when all words are solved.

## Project Structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit entry point — page config, session state, word selection, HTML/JS game builder, and UI layout |
| `crossword_generator.py` | Puzzle engine — placement algorithm, scoring, grid normalisation, and data classes (`WordPlacement`, `CrosswordData`) |
| `clues.py` | Clue bank — dictionary mapping answer strings to clue text |
| `icon/RST_icon.png` | Browser tab icon |
| `requirements.txt` | Python dependencies |

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit>=1.30.0` | Web app framework — renders the UI and manages session state |
| `Pillow>=10.0.0` | Opens the PNG icon file passed to `st.set_page_config` |

## Running Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app will open in your default browser at `http://localhost:8501`.

## How the Puzzle Generator Works

1. **Word selection** (`_select_words`) — picks words greedily by character-overlap potential so that the chosen set is likely to intersect well on the grid.
2. **Placement** (`generate_crossword` / `_attempt`) — runs up to 200 randomized attempts. Each attempt anchors the longest word horizontally, then iterates up to 5 passes over the remaining words, placing each at the candidate position with the highest intersection score.
3. **Scoring** — placements are scored by number of letter crossings (dominant term), bounding-box area (compact is better), and aspect-ratio deviation (square grids preferred). The best attempt across all 200 runs is kept.
4. **Grid limits** — the grid is hard-capped at 15 rows × 20 columns so it fits comfortably in the browser at the configured cell size.
5. **Numbering** — cells are numbered left-to-right, top-to-bottom following standard crossword convention.
