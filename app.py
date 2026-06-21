import glob
import json
import os

import streamlit as st
from PIL import Image

from crossword_generator import CrosswordData, WordPlacement

# ---------------------------------------------------------------------------
# Page config — custom icon
# ---------------------------------------------------------------------------
_icon_path = os.path.join(os.path.dirname(__file__), "icon", "RST_icon.png")
st.set_page_config(
    page_title="Crossword Puzzle",
    layout="wide",
    page_icon=Image.open(_icon_path),
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Global CSS  (Streamlit wrapper only — grid lives inside the iframe)
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer     {visibility: hidden;}

    .cw-title {
        font-size: 3.3rem;
        font-weight: 800;
        letter-spacing: 3px;
        text-align: center;
        color: #0b3d91;
        margin-bottom: 0;
    }
    .cw-sub {
        text-align: center;
        color: #888;
        font-size: 1.35rem;
        margin-bottom: 1rem;
    }
    /* New-game button */
    div[data-testid="stButton"] > button {
        font-size: 1.2rem;
        padding: 8px 20px;
    }
    /* Tighten the page chrome on phones so the game gets the screen */
    @media (max-width: 760px) {
        .cw-title { font-size: 2rem; letter-spacing: 1px; }
        .cw-sub   { font-size: 1rem; margin-bottom: 0.6rem; }
        .block-container { padding-left: 0.6rem; padding-right: 0.6rem; }
        div[data-testid="stButton"] > button { font-size: 1rem; padding: 6px 12px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Puzzle loader — reads puzzle.json once and caches it for the server lifetime
# ---------------------------------------------------------------------------

@st.cache_resource
def _load_puzzle(mtime: float) -> CrosswordData | None:
    # mtime is part of the cache key (no leading underscore, so Streamlit hashes
    # it) — the cache auto-invalidates whenever puzzle.json is replaced (e.g. the
    # weekly push), even if the Streamlit server process is reused on redeploy.
    puzzle_path = os.path.join(os.path.dirname(__file__), "puzzle.json")
    if not os.path.exists(puzzle_path):
        return None
    with open(puzzle_path, encoding="utf-8") as f:
        data = json.load(f)
    placements = [
        WordPlacement(
            word=p["word"],
            clue=p["clue"],
            row=p["row"],
            col=p["col"],
            direction=p["direction"],
            number=p["number"],
            is_themed=p.get("is_themed", False),
        )
        for p in data["placements"]
    ]
    return CrosswordData(
        grid=data["grid"],
        placements=placements,
        rows=data["rows"],
        cols=data["cols"],
    )


# ---------------------------------------------------------------------------
# Last week's solution image (archived under past_boards/ by render_solution.py)
# ---------------------------------------------------------------------------

def _latest_solution_png() -> str | None:
    """Path to the most recently archived solution PNG, or None if none exist.

    Filenames are dated (solution_YYYY-MM-DD.png), so lexical sort == newest last.
    """
    folder = os.path.join(os.path.dirname(__file__), "past_boards")
    if not os.path.isdir(folder):
        return None
    pngs = sorted(glob.glob(os.path.join(folder, "solution_*.png")))
    return pngs[-1] if pngs else None


def _solution_clues(png_path: str) -> tuple[list[tuple[int, str, str]],
                                            list[tuple[int, str, str]]] | None:
    """Across/Down clue lists for a solution PNG's matching puzzle JSON.

    Each solution_<date>.png sits beside a puzzle_<date>.json holding that
    week's placements. Returns (across, down) where each entry is
    (number, ANSWER, clue), sorted by clue number, or None if the JSON is
    missing/unreadable.
    """
    json_path = png_path.replace("solution_", "puzzle_").rsplit(".", 1)[0] + ".json"
    if not os.path.exists(json_path):
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    across, down = [], []
    for p in data.get("placements", []):
        entry = (p["number"], p["word"], p.get("clue") or "")
        (across if p["direction"] == "across" else down).append(entry)
    across.sort(key=lambda e: e[0])
    down.sort(key=lambda e: e[0])
    return across, down


# ---------------------------------------------------------------------------
# Session-state bootstrap
# ---------------------------------------------------------------------------
if "game_active" not in st.session_state:
    st.session_state.game_active = False
if "show_solution" not in st.session_state:
    st.session_state.show_solution = False


# ---------------------------------------------------------------------------
# Self-contained HTML/JS game builder
#
# Interaction model: pick a clue (tap a cell or a clue button), type the whole
# answer into the separate answer field, and submit. A correct guess reveals
# the word's letters on the board (and any crossings it completes); revealed
# letters are plain display text, so they can't be edited or deleted.
#
# Layout is responsive. The iframe is embedded with width="stretch" /
# height="content" (see the render call), so Streamlit sizes it fluidly and
# auto-measures its height. Inside, a viewport meta + CSS media query let the
# same markup sit side-by-side on desktop and stack/scale on phones. The clue
# + answer field live in a bar above the grid so that, on a phone, tapping a
# cell focuses the input near the top of the screen.
#
# _CELL is the *maximum* cell size in px; on narrow screens the cells shrink
# via `min(_CELL px, (100vw - margin) / cols)` so the whole board fits the
# screen width. Number/letter font sizes derive from --cell in CSS.
# ---------------------------------------------------------------------------
_CELL = 44   # max cell square size in px (shrinks to fit narrow screens)

# Below this viewport width the grid and panel stack vertically (phones /
# narrow tablets), chosen so the side-by-side layout only stays while it fits:
# grid (cols*_CELL) + gap + panel.
_STACK_BELOW = 920


def _build_game_html(cw: CrosswordData) -> str:
    cell_numbers   = {f"{r},{c}": n    for (r, c), n    in cw.cell_to_number().items()}
    cell_to_words  = {f"{r},{c}": keys for (r, c), keys in cw.cell_to_words().items()}

    # Cells belonging to Roman-themed words get a gold highlight
    themed_cells = [
        f"{r},{c}"
        for p in cw.placements if p.is_themed
        for r, c in p.cells()
    ]

    data = {
        "grid":        cw.grid,
        "rows":        cw.rows,
        "cols":        cw.cols,
        "placements": [
            {"key": p.get_key(), "word": p.word, "clue": p.clue,
             "row": p.row, "col": p.col, "direction": p.direction,
             "number": p.number, "isThemed": p.is_themed}
            for p in cw.placements
        ],
        "cellNumbers":  cell_numbers,
        "cellToWords":  cell_to_words,
        "themedCells":  themed_cells,
    }
    # Embed JSON safely (guard against "</script>" inside strings)
    data_json = json.dumps(data).replace("</script>", r"<\/script>")

    # Template uses __TOKEN__ placeholders (not f-string interpolation) so the
    # large JS/CSS block keeps its single braces and reads normally.
    html = _GAME_TEMPLATE
    html = html.replace("__CELL__", str(_CELL))
    html = html.replace("__COLS__", str(cw.cols))
    html = html.replace("__STACK__", str(_STACK_BELOW))
    html = html.replace("__DATA__", data_json)
    return html


_GAME_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: #f5f5f5; }
body { font-family: Arial, sans-serif; padding: 12px; font-size: 18px; -webkit-text-size-adjust: 100%; }

:root {
  --cell: min(__CELL__px, calc((100vw - 26px) / __COLS__));
  --num:  calc(var(--cell) * 0.30);
  --ltr:  calc(var(--cell) * 0.58);
}

/* ── clue + answer bar (sits above the board) ── */
#control {
  position: sticky; top: 0; z-index: 10;
  max-width: 1080px; margin: 0 auto 12px;
  background: #fff; border: 1px solid #d8e0ea; border-left: 5px solid #2e86de;
  border-radius: 8px; padding: 10px 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,.10);
}
#clue-label { font-size: 1.2rem; color: #0d1b2a; line-height: 1.3; margin-bottom: 8px; overflow-wrap: anywhere; }
#clue-label .ql-num  { color: #0b3d91; font-weight: 800; }
#clue-label .ql-hint { color: #888; font-weight: 600; font-size: 0.95rem; }
#input-row  { display: flex; gap: 10px; align-items: center; }
#answerInput {
  flex: 1; min-width: 0; font-size: 1.2rem; padding: 8px 12px;
  border: 2px solid #ccc; border-radius: 6px; outline: none; text-transform: uppercase;
}
#answerInput:focus { border-color: #2e86de; }
#submitBtn {
  font-size: 1.05rem; padding: 9px 18px; background: #2e86de; color: #fff;
  border: none; border-radius: 6px; cursor: pointer; font-weight: 700; white-space: nowrap;
}
#submitBtn:hover    { background: #1a6fc4; }
#submitBtn:disabled { background: #aaa; cursor: default; }
#feedbackMsg { font-size: 1.05rem; font-weight: 600; min-height: 1.4em; margin-top: 6px; }

/* ── layout ── */
#app { display: flex; flex-direction: row; gap: 20px; align-items: flex-start;
       justify-content: center; max-width: 1080px; margin: 0 auto; }
#grid-wrap { flex-shrink: 0; }
.watermark { text-align: right; margin-top: 5px; font-size: 0.65rem;
             color: rgba(0,0,0,0.30); letter-spacing: 0.5px;
             pointer-events: none; user-select: none; }

/* ── crossword grid (display only) ── */
table.cw { border-collapse: collapse; border: 2px solid #222; background: #222; }
td { width: var(--cell); height: var(--cell); padding: 0; position: relative; }
td.blk { background: #222; }
td.wht { background: #fff; border: 1px solid #888; cursor: pointer;
         transition: background .1s; user-select: none; }
td.wht:hover { background: #ddf0ff; }
td.gld { background: #ffd700 !important; border-color: #b8860b; }
td.gld:hover { background: #f0c000 !important; }
td.sel { background: #74c2f5 !important; border-color: #2e86de !important; }
.num { position: absolute; top: 1px; left: 2px; font-size: var(--num); line-height: 1;
       color: #222; pointer-events: none; font-family: Arial; }
.ltr { display: flex; align-items: center; justify-content: center; height: var(--cell);
       font-size: var(--ltr); font-family: Georgia, serif; font-weight: bold;
       color: #111; pointer-events: none; }

/* ── side panel (progress + clue lists) ── */
#panel { width: 340px; flex-shrink: 0; background: #fff; border-radius: 8px;
         padding: 14px; box-shadow: 0 1px 6px rgba(0,0,0,.12); }
#prog-wrap  { margin: 0 0 4px; }
#prog-text  { font-size: 1.05rem; color: #555; margin-bottom: 4px; }
#prog-outer { height: 9px; background: #e0e0e0; border-radius: 5px; overflow: hidden; }
#prog-inner { height: 9px; background: #2e86de; border-radius: 5px; transition: width .4s; }
#completion { display: none; font-size: 1.5rem; font-weight: 800; color: #2a8c2a;
              text-align: center; padding: 14px 0; }
hr.divider { border: none; border-top: 1px solid #ddd; margin: 12px 0; }
.clue-lists { display: flex; gap: 18px; }
.clue-col   { flex: 1; min-width: 0; }
.col-head   { font-size: 0.8rem; font-weight: 800; letter-spacing: 2px; color: #555;
              border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-bottom: 8px; }
.clue-btn   { display: block; width: 100%; text-align: left; font-size: 1.0rem;
              padding: 6px 9px; margin-bottom: 5px; background: #f0f4f8;
              border: 1px solid #ddd; border-radius: 5px; cursor: pointer;
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.clue-btn.active        { background: #74c2f5; border-color: #2e86de; font-weight: 700; }
.clue-btn.solved        { color: #999; text-decoration: line-through; }
.clue-btn.solved.active { background: #b8e4b8; border-color: #4caf50; }

/* ── phones / narrow tablets: stack the board above the panel ── */
@media (max-width: __STACK__px) {
  body { padding: 8px; font-size: 16px; }
  #app { flex-direction: column; align-items: center; gap: 14px; }
  #panel { width: 100%; max-width: 560px; }
  #clue-label { font-size: 1.1rem; }
  .clue-btn { font-size: 0.95rem; }
}
</style>
</head>
<body>
  <div id="control">
    <div id="clue-label"></div>
    <div id="input-row">
      <input id="answerInput" type="text" placeholder="Type your answer…"
             autocomplete="off" autocorrect="off" spellcheck="false" autocapitalize="characters"
             onkeydown="if(event.key==='Enter')submitAnswer()">
      <button id="submitBtn" onclick="submitAnswer()">Submit ↵</button>
    </div>
    <div id="feedbackMsg"></div>
  </div>
  <div id="app">
    <div id="grid-wrap">
      <table class="cw" id="grid"></table>
      <div class="watermark">Created by: S. K. Terry</div>
    </div>
    <div id="panel">
      <div id="prog-wrap">
        <div id="prog-text"></div>
        <div id="prog-outer"><div id="prog-inner" style="width:0%"></div></div>
      </div>
      <div id="completion">🎉 Puzzle complete — Congratulations!</div>
      <hr class="divider">
      <div class="clue-lists">
        <div class="clue-col"><div class="col-head">ACROSS</div><div id="across-list"></div></div>
        <div class="clue-col"><div class="col-head">DOWN</div><div id="down-list"></div></div>
      </div>
    </div>
  </div>

<script type="application/json" id="gameData">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('gameData').textContent);
const themedSet = new Set(D.themedCells || []);
const revealed = new Set();   // keys of solved words
let selKey = null;            // active word key

function byKey(k){ return D.placements.find(p => p.key === k); }
function escapeHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* cells of the active word (for the blue highlight) */
function selCellSet(key){
  const p = byKey(key); const s = new Set(); if (!p) return s;
  for (let i = 0; i < p.word.length; i++){
    const r = p.row + (p.direction === 'down'   ? i : 0);
    const c = p.col + (p.direction === 'across' ? i : 0);
    s.add(r + ',' + c);
  }
  return s;
}
/* letters revealed by every solved word */
function revealedLetters(){
  const m = {};
  for (const p of D.placements){
    if (!revealed.has(p.key)) continue;
    for (let i = 0; i < p.word.length; i++){
      const r = p.row + (p.direction === 'down'   ? i : 0);
      const c = p.col + (p.direction === 'across' ? i : 0);
      m[r + ',' + c] = p.word[i];
    }
  }
  return m;
}
/* mark any word whose cells are all filled by crossings as solved (loop to
   stable, since one auto-solve can complete another) */
function autoSolveCrossed(){
  let changed = true;
  while (changed){
    changed = false;
    const rl = revealedLetters();
    for (const p of D.placements){
      if (revealed.has(p.key)) continue;
      let complete = true;
      for (let i = 0; i < p.word.length; i++){
        const r = p.row + (p.direction === 'down'   ? i : 0);
        const c = p.col + (p.direction === 'across' ? i : 0);
        if (!rl[r + ',' + c]){ complete = false; break; }
      }
      if (complete){ revealed.add(p.key); changed = true; }
    }
  }
}

/* ── grid render ── */
function renderGrid(){
  const sc = selCellSet(selKey);
  const rl = revealedLetters();
  const rows = [];
  for (let r = 0; r < D.rows; r++){
    let tr = '<tr>';
    for (let c = 0; c < D.cols; c++){
      if (D.grid[r][c] === '#'){ tr += '<td class="blk"></td>'; continue; }
      const key = r + ',' + c;
      const cls = 'wht' + (themedSet.has(key) ? ' gld' : '') + (sc.has(key) ? ' sel' : '');
      const num = D.cellNumbers[key];
      const ltr = rl[key] || '';
      tr += '<td class="' + cls + '" onclick="cellClick(' + r + ',' + c + ')">'
          + (num ? '<span class="num">' + num + '</span>' : '')
          + '<div class="ltr">' + ltr + '</div></td>';
    }
    rows.push(tr + '</tr>');
  }
  document.getElementById('grid').innerHTML = rows.join('');
}

/* ── cell click: choose a word, preferring an unsolved one; re-tap toggles ── */
function cellClick(r, c){
  const words = D.cellToWords[r + ',' + c] || [];
  const aKey = words.find(k => k.endsWith('-across')) || '';
  const dKey = words.find(k => k.endsWith('-down'))   || '';
  // re-tapping the active word's cell flips to the crossing word
  if (selKey === aKey && dKey){ selectWord(dKey); return; }
  if (selKey === dKey && aKey){ selectWord(aKey); return; }
  // fresh tap: prefer a still-unsolved word so tapping a finished letter
  // surfaces the crossing mystery clue you're actually after
  const cands = [aKey, dKey].filter(Boolean);
  if (!cands.length) return;
  selectWord(cands.find(k => !revealed.has(k)) || cands[0]);
}

/* ── select a word ── */
function selectWord(key, focus){
  selKey = key;
  renderGrid(); renderControl(); renderClueLists();
  document.getElementById('feedbackMsg').textContent = '';
  const inp = document.getElementById('answerInput');
  inp.value = '';
  // focus the answer box (so the keyboard opens) only for unsolved words, and
  // not on the initial boot selection
  if (focus !== false && !revealed.has(key)) inp.focus();
}

/* ── clue + input bar ── */
function renderControl(){
  const p = byKey(selKey); if (!p) return;
  const dir = p.direction === 'across' ? 'ACROSS' : 'DOWN';
  document.getElementById('clue-label').innerHTML =
    '<span class="ql-num">' + p.number + ' ' + dir + ':</span> ' + escapeHtml(p.clue)
    + ' <span class="ql-hint">(' + p.word.length + ' letters)</span>';
  const done = revealed.has(selKey);
  document.getElementById('answerInput').disabled = done;
  document.getElementById('submitBtn').disabled   = done;
}

/* ── answer checking ── */
function submitAnswer(){
  const p = byKey(selKey); if (!p || revealed.has(p.key)) return;
  const guess = document.getElementById('answerInput').value.toUpperCase().trim().replace(/\\s+/g, '');
  const msg = document.getElementById('feedbackMsg');
  if (guess === p.word){
    revealed.add(selKey); autoSolveCrossed();
    msg.textContent = '\\u2713 Correct!'; msg.style.color = '#2a8c2a';
    renderGrid(); renderControl(); renderClueLists(); updateProgress();
    if (D.placements.every(x => revealed.has(x.key))){
      document.getElementById('completion').style.display = 'block';
      document.getElementById('answerInput').disabled = true;
      document.getElementById('submitBtn').disabled   = true;
    }
  } else {
    msg.textContent = '\\u2717 Not quite \\u2014 try again!'; msg.style.color = '#c0392b';
  }
}

/* ── clue lists ── */
function renderClueLists(){
  ['across','down'].forEach(d => {
    const items = D.placements.filter(p => p.direction === d).sort((a,b)=>a.number-b.number);
    document.getElementById(d + '-list').innerHTML = items.map(p => {
      const cls = 'clue-btn' + (revealed.has(p.key) ? ' solved' : '') + (p.key === selKey ? ' active' : '');
      const pre = revealed.has(p.key) ? '\\u2713 ' : '';
      return '<button type="button" class="' + cls + '" data-key="' + p.key + '">'
           + pre + p.number + '. ' + escapeHtml(p.clue) + '</button>';
    }).join('');
  });
}

/* ── progress ── */
function updateProgress(){
  const total = D.placements.length, done = revealed.size;
  document.getElementById('prog-text').textContent = done + ' / ' + total + ' words solved';
  document.getElementById('prog-inner').style.width = Math.round(done / total * 100) + '%';
}

/* clue-list taps (event delegation survives innerHTML re-renders) */
['across-list','down-list'].forEach(id => {
  document.getElementById(id).addEventListener('click', e => {
    const b = e.target.closest('button[data-key]');
    if (b) selectWord(b.dataset.key);
  });
});

/* boot — highlight the first word but DON'T focus the input, so the phone
   keyboard only opens once the player taps a cell or a clue */
if (D.placements.length) selectWord(D.placements[0].key, false);
updateProgress();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.markdown('<div class="cw-title">Roman Space Telescope Crossword</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="cw-sub">A weekly NYT-style puzzle with some '
    '<span style="color:#b8860b;font-weight:700;">Roman-themed</span> clues.</div>',
    unsafe_allow_html=True,
)

_puzzle_path = os.path.join(os.path.dirname(__file__), "puzzle.json")
_puzzle_mtime = os.path.getmtime(_puzzle_path) if os.path.exists(_puzzle_path) else 0.0
cw = _load_puzzle(_puzzle_mtime)

if cw is None:
    st.error(
        "**puzzle.json not found.** "
        "Run `python generate_puzzle.py` from the project directory to generate it."
    )
    st.stop()

btn_col1, btn_col2, _ = st.columns([1, 1.6, 4])
with btn_col1:
    if st.button("New Game", type="primary"):
        st.session_state.game_active = True
        st.session_state.show_solution = False
        st.rerun()
with btn_col2:
    _sol_png = _latest_solution_png()
    if _sol_png and st.button("View last week's solution"):
        st.session_state.show_solution = not st.session_state.show_solution

if st.session_state.show_solution:
    if _sol_png:
        # Capped column keeps the image a sensible size on desktop while still
        # shrinking to full width when the columns stack on a phone.
        img_col, _spacer = st.columns([3, 2])
        with img_col:
            st.image(_sol_png, caption="Last week's completed solution", width="stretch")

        # Clue list for the same board, so players can see which clue each
        # solved word answered (a grid full of words alone isn't much help).
        _clues = _solution_clues(_sol_png)
        if _clues:
            across, down = _clues

            def _fmt(entries: list[tuple[int, str, str]]) -> str:
                # Two trailing spaces force a Markdown hard line break so each
                # clue sits on its own line within the column.
                return "  \n".join(
                    f"**{n}.** {clue} &nbsp;→&nbsp; **{word}**"
                    for n, word, clue in entries
                )

            with st.expander("Last week's clues & answers", expanded=True):
                ac_col, dn_col = st.columns(2)
                with ac_col:
                    st.markdown("**ACROSS**")
                    st.markdown(_fmt(across), unsafe_allow_html=True)
                with dn_col:
                    st.markdown("**DOWN**")
                    st.markdown(_fmt(down), unsafe_allow_html=True)

        st.caption("Click **View last week's solution** again to hide.")
    else:
        st.info("No past solution is available yet.")

if not st.session_state.game_active:
    st.info("Click **New Game** to start the puzzle.")
    st.stop()

# width defaults to "stretch" and height to "content": Streamlit sizes the
# iframe to the container width and auto-measures the (srcdoc) HTML height, so
# the same embed adapts to desktop and mobile without fixed pixel dimensions.
st.iframe(_build_game_html(cw), height="content")
