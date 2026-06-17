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
# The grid, clue bar and clue lists all live inside one iframe. Layout is
# responsive: the iframe is embedded with width="stretch"/height="content"
# (see the render call at the bottom), so Streamlit sizes it fluidly and
# auto-measures its height. Inside, a viewport meta + CSS media query let the
# same markup sit side-by-side on desktop and stack/scale on phones. Answers
# are typed directly into the cells (one <input> per white square) rather than
# into a separate answer box, which is the natural mobile crossword UX.
#
# _CELL is the *maximum* cell size in px; on narrow screens the cells shrink
# via `min(_CELL px, (100vw - margin) / cols)` so the whole board fits the
# screen width. The number/letter font sizes derive from --cell in CSS.
# ---------------------------------------------------------------------------
_CELL = 44   # max cell square size in px (shrinks to fit narrow screens)

# Below this viewport width the grid and panel stack vertically (phones /
# narrow tablets). Chosen so the side-by-side layout only stays while it
# actually fits: grid (cols*_CELL) + gap + panel.
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

/* ── current-clue bar (sits above the board) ── */
#clue-bar {
  position: sticky; top: 0; z-index: 10;
  max-width: 1080px; margin: 0 auto 12px;
  background: #fff; border: 1px solid #d8e0ea; border-left: 5px solid #2e86de;
  border-radius: 8px; padding: 9px 14px; min-height: 2.6em;
  box-shadow: 0 1px 4px rgba(0,0,0,.10);
  display: flex; align-items: baseline; gap: 10px;
}
#clue-bar .cb-num  { font-weight: 800; color: #0b3d91; white-space: nowrap; }
#clue-bar .cb-clue { flex: 1; font-size: 1.15rem; color: #0d1b2a; line-height: 1.3; overflow-wrap: anywhere; }
#clue-bar .cb-len  { color: #888; }
#clue-bar .cb-stat { font-weight: 800; font-size: 1.3rem; }
#clue-bar .cb-stat.ok  { color: #1a7a1a; }
#clue-bar .cb-stat.bad { color: #c0392b; }

/* ── layout ── */
#app { display: flex; flex-direction: row; gap: 20px; align-items: flex-start;
       justify-content: center; max-width: 1080px; margin: 0 auto; }
#grid-wrap { flex-shrink: 0; }
.watermark { text-align: right; margin-top: 5px; font-size: 0.65rem;
             color: rgba(0,0,0,0.30); letter-spacing: 0.5px;
             pointer-events: none; user-select: none; }

/* ── crossword grid ── */
table.cw { border-collapse: collapse; border: 2px solid #222; background: #222; }
td { width: var(--cell); height: var(--cell); padding: 0; position: relative; }
td.blk { background: #222; }
td.wht { background: #fff; border: 1px solid #888; }
td.gld { background: #ffd700; border-color: #b8860b; }
td.word { background: #cfe8ff; }
td.word.gld { background: #ffe680; }
td.cur  { background: #74c2f5 !important; border-color: #2e86de !important; }
td.ok .ci { color: #1a7a1a; }
.num { position: absolute; top: 1px; left: 2px; font-size: var(--num); line-height: 1;
       color: #222; pointer-events: none; font-family: Arial; z-index: 2; }
.ci  { position: absolute; inset: 0; width: 100%; height: 100%; border: none;
       background: transparent; text-align: center; padding: 0;
       font-family: Georgia, serif; font-weight: bold; font-size: var(--ltr);
       color: #111; text-transform: uppercase; caret-color: transparent; outline: none; }
/* locked (solved) cells: keep the letter green & solid, not browser-greyed */
.ci:disabled { color: #1a7a1a; -webkit-text-fill-color: #1a7a1a; opacity: 1; cursor: default; }

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
  #clue-bar .cb-clue { font-size: 1.05rem; }
  .clue-btn { font-size: 0.95rem; }
}
</style>
</head>
<body>
  <div id="clue-bar"></div>
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

const inputs = {};            // "r,c" -> <input>
const entries = {};           // "r,c" -> typed letter
const solved = new Set();     // keys of fully-correct words
const solvedCells = new Set();// "r,c" of cells in a solved word
let dir = 'across';           // current orientation preference
let selKey = null;            // active word key
let selCell = null;           // active cell "r,c"
let preClickSel = null;       // selection captured on pointerdown (for re-tap toggle)

/* ── helpers ── */
function byKey(k){ return D.placements.find(p => p.key === k); }
function gridLetter(key){ const a = key.split(','); return D.grid[+a[0]][+a[1]]; }
function escapeHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function cellsOf(p){
  const out = [];
  for (let i = 0; i < p.word.length; i++){
    const r = p.row + (p.direction === 'down'   ? i : 0);
    const c = p.col + (p.direction === 'across' ? i : 0);
    out.push(r + ',' + c);
  }
  return out;
}
function wordsAt(key){
  const ks = D.cellToWords[key] || [];
  return { across: ks.find(k => k.endsWith('-across')) || null,
           down:   ks.find(k => k.endsWith('-down'))   || null };
}
function orderedKeys(){
  const a = D.placements.filter(p => p.direction === 'across').sort((x,y)=>x.number-y.number).map(p=>p.key);
  const d = D.placements.filter(p => p.direction === 'down'  ).sort((x,y)=>x.number-y.number).map(p=>p.key);
  return a.concat(d);
}

/* ── build the grid once; afterwards we only toggle classes / input values
      so the focused input (and the mobile keyboard) survives updates ── */
function buildGrid(){
  const rows = [];
  for (let r = 0; r < D.rows; r++){
    let tr = '<tr>';
    for (let c = 0; c < D.cols; c++){
      if (D.grid[r][c] === '#'){ tr += '<td class="blk"></td>'; continue; }
      const key = r + ',' + c;
      const num = D.cellNumbers[key];
      tr += '<td class="wht' + (themedSet.has(key) ? ' gld' : '') + '" data-k="' + key + '">'
          + (num ? '<span class="num">' + num + '</span>' : '')
          + '<input class="ci" data-r="' + r + '" data-c="' + c + '" '
          + 'inputmode="text" autocapitalize="characters" autocomplete="off" '
          + 'autocorrect="off" spellcheck="false" enterkeyhint="next" aria-label="cell">'
          + '</td>';
    }
    rows.push(tr + '</tr>');
  }
  document.getElementById('grid').innerHTML = rows.join('');

  document.querySelectorAll('input.ci').forEach(inp => {
    const r = +inp.dataset.r, c = +inp.dataset.c, key = r + ',' + c;
    inputs[key] = inp;
    inp.addEventListener('focus',       () => onFocus(r, c));
    inp.addEventListener('pointerdown', () => { preClickSel = selCell; });
    inp.addEventListener('click',       () => onClick(r, c));
    inp.addEventListener('input',       () => onInput(r, c));
    inp.addEventListener('keydown',     e  => onKey(r, c, e));
  });

  // clue-list buttons (event delegation, set after each render)
  ['across-list','down-list'].forEach(id => {
    document.getElementById(id).addEventListener('click', e => {
      const b = e.target.closest('button[data-key]');
      if (b) selectWord(b.dataset.key);
    });
  });
}

/* ── selection ── */
function onFocus(r, c){
  const key = r + ',' + c;
  inputs[key].select();
  if (selCell !== key) select(r, c, false);
}
function onClick(r, c){
  // tapping the already-selected cell flips across <-> down
  if (preClickSel === r + ',' + c) select(r, c, true);
}
function select(r, c, toggle){
  const key = r + ',' + c;
  const w = wordsAt(key);
  let nd = dir;
  if (toggle && w.across && w.down) nd = (dir === 'across' ? 'down' : 'across');
  if (!w[nd]) nd = w.across ? 'across' : 'down';
  dir = nd; selKey = w[nd]; selCell = key;
  paint(); updateClueBar();
}
/* pick a whole word (clue-list tap / Tab) and jump to its first empty cell */
function selectWord(key, focus){
  const p = byKey(key); if (!p) return;
  dir = p.direction; selKey = key;
  const cells = cellsOf(p);
  selCell = cells.find(k => !entries[k]) || cells[0];
  paint(); updateClueBar();
  if (focus !== false){ const inp = inputs[selCell]; if (inp){ inp.focus(); inp.select(); } }
}

/* ── typing ── */
function onInput(r, c){
  const key = r + ',' + c, inp = inputs[key];
  const v = inp.value.toUpperCase().replace(/[^A-Z]/g, '');
  if (!v){ entries[key] = ''; inp.value = ''; recompute(); updateClueBar(); return; }
  const ch = v[v.length - 1];          // keep last char (handles overtype)
  entries[key] = ch; inp.value = ch;
  recompute(); advance(r, c); updateClueBar();
}
function advance(r, c){
  const p = byKey(selKey); if (!p) return;
  const cells = cellsOf(p);
  const i = cells.indexOf(r + ',' + c);
  // hop to the next still-editable cell (skip letters locked by a solved word)
  for (let j = i + 1; j < cells.length; j++){
    if (!solvedCells.has(cells[j])){ focusKey(cells[j]); return; }
  }
  paint();   // no editable cell ahead: stay put
}
function focusKey(k){
  const inp = inputs[k]; if (!inp) return;
  selCell = k; paint();
  inp.focus(); inp.select();
}
function onKey(r, c, e){
  const key = r + ',' + c;
  if (e.key === 'Backspace'){
    if (!entries[key]){          // empty cell: step back and clear previous
      e.preventDefault();
      const p = byKey(selKey); if (!p) return;
      const cells = cellsOf(p); const i = cells.indexOf(key);
      for (let j = i - 1; j >= 0; j--){   // skip locked letters when stepping back
        const pk = cells[j];
        if (solvedCells.has(pk)) continue;
        entries[pk] = ''; if (inputs[pk]) inputs[pk].value = '';
        recompute(); focusKey(pk); updateClueBar();
        break;
      }
    }
    return;                      // non-empty: the input event clears it
  }
  if (e.key.indexOf('Arrow') === 0){ e.preventDefault(); arrow(r, c, e.key); return; }
  if (e.key === 'Enter' || e.key === 'Tab'){ e.preventDefault(); step(e.shiftKey); return; }
  if (e.key === ' '){ e.preventDefault(); select(r, c, true); }
}
function arrow(r, c, k){
  let dr = 0, dc = 0, wd = dir;
  if (k === 'ArrowRight'){ dc =  1; wd = 'across'; }
  if (k === 'ArrowLeft' ){ dc = -1; wd = 'across'; }
  if (k === 'ArrowDown' ){ dr =  1; wd = 'down';   }
  if (k === 'ArrowUp'   ){ dr = -1; wd = 'down';   }
  let nr = r + dr, nc = c + dc;
  while (nr >= 0 && nr < D.rows && nc >= 0 && nc < D.cols){
    if (D.grid[nr][nc] !== '#'){ dir = wd; select(nr, nc, false); inputs[nr + ',' + nc].focus(); return; }
    nr += dr; nc += dc;
  }
}
function step(back){
  const order = orderedKeys();
  let i = order.indexOf(selKey);
  i = (i + (back ? -1 : 1) + order.length) % order.length;
  selectWord(order[i]);
}

/* ── correctness / rendering ── */
function recompute(){
  solved.clear(); solvedCells.clear();
  for (const p of D.placements){
    const cells = cellsOf(p);
    let ok = true;
    for (const k of cells){ if ((entries[k] || '') !== gridLetter(k)){ ok = false; break; } }
    if (ok){ solved.add(p.key); cells.forEach(k => solvedCells.add(k)); }
  }
  paint(); updateProgress(); renderClueLists();
  document.getElementById('completion').style.display =
    (solved.size === D.placements.length) ? 'block' : 'none';
}
function paint(){
  const wc = selKey ? new Set(cellsOf(byKey(selKey))) : new Set();
  for (const key in inputs){
    const inp = inputs[key];
    const locked = solvedCells.has(key);   // cell belongs to a fully-correct word
    // Lock correct cells: a disabled input can't be focused, highlighted or
    // edited, so solved letters stay put and tapping them does nothing.
    inp.disabled = locked;
    const td = inp.parentElement;
    td.className = 'wht'
      + (themedSet.has(key)    ? ' gld'  : '')
      + (wc.has(key)           ? ' word' : '')
      + (key === selCell && !locked ? ' cur' : '')
      + (locked                ? ' ok'   : '');
  }
}
function updateClueBar(){
  const bar = document.getElementById('clue-bar');
  const p = byKey(selKey);
  if (!p){ bar.innerHTML = ''; return; }
  const lbl = p.direction === 'across' ? 'ACROSS' : 'DOWN';
  let stat = '';
  if (solved.has(p.key)) stat = '<span class="cb-stat ok">\\u2713</span>';
  else if (cellsOf(p).every(k => entries[k])) stat = '<span class="cb-stat bad">\\u2717</span>';
  bar.innerHTML = '<span class="cb-num">' + p.number + ' ' + lbl + '</span>'
    + '<span class="cb-clue">' + escapeHtml(p.clue)
    + ' <span class="cb-len">(' + p.word.length + ')</span></span>' + stat;
}
function updateProgress(){
  const total = D.placements.length, done = solved.size;
  document.getElementById('prog-text').textContent = done + ' / ' + total + ' words solved';
  document.getElementById('prog-inner').style.width = Math.round(done / total * 100) + '%';
}
function renderClueLists(){
  ['across','down'].forEach(d => {
    const items = D.placements.filter(p => p.direction === d).sort((a,b)=>a.number-b.number);
    document.getElementById(d + '-list').innerHTML = items.map(p => {
      const cls = 'clue-btn' + (solved.has(p.key) ? ' solved' : '') + (p.key === selKey ? ' active' : '');
      const pre = solved.has(p.key) ? '\\u2713 ' : '';
      return '<button type="button" class="' + cls + '" data-key="' + p.key + '">'
           + pre + p.number + '. ' + escapeHtml(p.clue) + '</button>';
    }).join('');
  });
}

/* ── boot: highlight the first word but DON'T focus it, so the phone
      keyboard only opens once the player taps a cell ── */
buildGrid();
recompute();
if (D.placements.length) selectWord(orderedKeys()[0], false);
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
