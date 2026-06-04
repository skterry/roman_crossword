import json
import os
import random

import streamlit as st
from PIL import Image

from clues import CLUES
from crossword_generator import CrosswordData, generate_crossword

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
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session-state bootstrap
# ---------------------------------------------------------------------------
for _k, _v in {"game_active": False, "crossword": None}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ---------------------------------------------------------------------------
# Word selection & game start
# ---------------------------------------------------------------------------
def _select_words(clue_dict: dict, n: int = 20) -> list:
    pool = list(clue_dict.keys())
    random.shuffle(pool)
    selected = [pool.pop(0)]
    while len(selected) < n and pool:
        # Pairwise overlap: sum of crossing potential between w and each selected word.
        # min(w.count(ch), sel.count(ch)) estimates how many real intersections are possible
        # for each shared character, which is strictly better than counting unique chars globally.
        def _overlap(w: str) -> int:
            total = 0
            for sel in selected:
                for ch in set(w) & set(sel):
                    total += min(w.count(ch), sel.count(ch))
            return total

        scored = sorted(pool, key=_overlap, reverse=True)
        # Narrow window: at most 8 candidates, not a full third of the pool
        top_n = max(3, min(8, len(scored) // 8))
        chosen = random.choice(scored[:top_n])
        selected.append(chosen)
        pool.remove(chosen)
    return [(w, clue_dict[w]) for w in selected]


def start_game() -> None:
    pairs = _select_words(CLUES, 20)
    cw = generate_crossword(pairs)
    for _ in range(4):
        if cw is not None and len(cw.placements) >= 12:
            break
        pairs = _select_words(CLUES, 20)
        cw = generate_crossword(pairs)
    st.session_state.crossword = cw
    st.session_state.game_active = True


# ---------------------------------------------------------------------------
# Self-contained HTML/JS game builder
# Grid cell sizing (50 % larger than the original 42 / 9 / 19 px)
# ---------------------------------------------------------------------------
_CELL = 46   # cell square size in px
_NUM  = 13   # small number in corner
_LTR  = 28   # revealed letter font size


def _build_game_html(cw: CrosswordData) -> tuple[str, int, int]:
    cell_numbers   = {f"{r},{c}": n    for (r, c), n    in cw.cell_to_number().items()}
    cell_to_words  = {f"{r},{c}": keys for (r, c), keys in cw.cell_to_words().items()}

    data = {
        "grid":        cw.grid,
        "rows":        cw.rows,
        "cols":        cw.cols,
        "placements": [
            {"key": p.get_key(), "word": p.word, "clue": p.clue,
             "row": p.row, "col": p.col, "direction": p.direction, "number": p.number}
            for p in cw.placements
        ],
        "cellNumbers": cell_numbers,
        "cellToWords": cell_to_words,
    }
    # Embed JSON safely (guard against "</script>" inside strings)
    data_json = json.dumps(data).replace("</script>", r"<\/script>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Arial, sans-serif; background: #f5f5f5; padding: 14px; font-size: 18px; }}

/* ── layout ── */
#app {{ display: flex; flex-direction: row; gap: 20px; align-items: flex-start; }}
#grid-wrap {{ overflow-x: auto; flex-shrink: 0; }}
.watermark {{
    text-align: right; margin-top: 5px;
    font-size: 0.65rem; color: rgba(0,0,0,0.30);
    font-family: Arial, sans-serif; letter-spacing: 0.5px;
    pointer-events: none; user-select: none;
}}

/* ── crossword grid ── */
table.cw {{ border-collapse: collapse; border: 2px solid #222; background: #222; }}
td {{ width: {_CELL}px; height: {_CELL}px; padding: 0; position: relative; }}
td.blk {{ background: #222; }}
td.wht {{ background: #fff; border: 1px solid #888; cursor: pointer;
           transition: background .1s; user-select: none; }}
td.wht:hover {{ background: #ddf0ff; }}
td.sel  {{ background: #74c2f5 !important; }}
.num {{ position: absolute; top: 2px; left: 2px; font-size: {_NUM}px;
        color: #222; line-height: 1; pointer-events: none; font-family: Arial; }}
.ltr {{ display: flex; align-items: center; justify-content: center;
        height: {_CELL}px; font-size: {_LTR}px; font-family: Georgia, serif;
        font-weight: bold; color: #111; pointer-events: none; }}

/* ── panel ── */
#panel {{ background: #fff; border-radius: 8px; padding: 16px;
          box-shadow: 0 1px 6px rgba(0,0,0,.12);
          width: 420px; flex-shrink: 0; }}

/* ── answer area ── */
#clue-label {{ font-size: 1.35rem; font-weight: 700; color: #0d1b2a; margin-bottom: 4px; }}
#clue-hint  {{ font-size: 1.1rem;  color: #666; margin-bottom: 8px; }}
#input-row  {{ display: flex; gap: 10px; align-items: center; }}
#answerInput {{
    flex: 1; font-size: 1.35rem; padding: 7px 12px;
    border: 2px solid #ccc; border-radius: 6px; outline: none;
    text-transform: uppercase;
}}
#answerInput:focus {{ border-color: #2e86de; }}
#submitBtn {{
    font-size: 1.2rem; padding: 8px 20px; background: #2e86de;
    color: #fff; border: none; border-radius: 6px; cursor: pointer;
    font-weight: 700; transition: background .15s;
}}
#submitBtn:hover {{ background: #1a6fc4; }}
#submitBtn:disabled {{ background: #aaa; cursor: default; }}
#feedbackMsg {{ font-size: 1.15rem; font-weight: 600; min-height: 1.6em; margin-top: 6px; }}
#giveUpBtn {{
    font-size: 0.95rem; padding: 5px 14px; background: #fff;
    color: #c0392b; border: 1.5px solid #c0392b; border-radius: 6px; cursor: pointer;
    font-weight: 600; transition: background .15s, color .15s; margin-top: 4px;
}}
#giveUpBtn:hover {{ background: #c0392b; color: #fff; }}
#giveUpBtn:disabled {{ opacity: 0.35; cursor: default; }}
#gave-up {{
    display: none; font-size: 1.3rem; font-weight: 700; color: #c0392b;
    text-align: center; padding: 14px 0;
}}

/* ── progress ── */
#prog-wrap {{ margin: 10px 0 4px; }}
#prog-text  {{ font-size: 1.1rem; color: #555; margin-bottom: 4px; }}
#prog-outer {{ height: 9px; background: #e0e0e0; border-radius: 5px; overflow: hidden; }}
#prog-inner {{ height: 9px; background: #2e86de; border-radius: 5px; transition: width .4s; }}

/* ── completion ── */
#completion {{
    display: none; font-size: 1.8rem; font-weight: 800; color: #2a8c2a;
    text-align: center; padding: 18px 0;
}}

/* ── clue lists ── */
hr.divider {{ border: none; border-top: 1px solid #ddd; margin: 12px 0; }}
.clue-lists {{ display: flex; gap: 20px; }}
.clue-col   {{ flex: 1; min-width: 0; }}
.col-head   {{
    font-size: 0.85rem; font-weight: 800; letter-spacing: 2px; color: #555;
    border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-bottom: 8px;
}}
.clue-btn {{
    display: block; width: 100%; text-align: left; font-size: 1.1rem;
    padding: 5px 9px; margin-bottom: 5px; background: #f0f4f8;
    border: 1px solid #ddd; border-radius: 5px; cursor: pointer;
    transition: background .1s; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
}}
.clue-btn:hover        {{ background: #ddf0ff; }}
.clue-btn.active       {{ background: #74c2f5; border-color: #2e86de; font-weight: 700; }}
.clue-btn.solved       {{ color: #999; text-decoration: line-through; }}
.clue-btn.solved.active {{ background: #b8e4b8; border-color: #4caf50; }}
</style>
</head>
<body>
<div id="app">
  <div id="grid-wrap">
    <table class="cw" id="grid"></table>
    <div class="watermark">Created by: S. K. Terry</div>
  </div>
  <div id="panel">
    <div id="clue-label"></div>
    <div id="clue-hint"></div>
    <div id="input-row">
      <input id="answerInput" type="text" placeholder="Type your answer…"
             autocomplete="off" spellcheck="false"
             onkeydown="if(event.key==='Enter')submitAnswer()">
      <button id="submitBtn" onclick="submitAnswer()">Submit ↵</button>
    </div>
    <div id="feedbackMsg"></div>
    <button id="giveUpBtn" onclick="giveUp()">Give Up</button>
    <div id="prog-wrap">
      <div id="prog-text"></div>
      <div id="prog-outer"><div id="prog-inner" style="width:0%"></div></div>
    </div>
    <div id="completion">🎉 Puzzle complete — click New Game to play again!</div>
    <div id="gave-up">Answers revealed — click New Game to play again.</div>
    <hr class="divider">
    <div class="clue-lists">
      <div class="clue-col">
        <div class="col-head">ACROSS</div>
        <div id="across-list"></div>
      </div>
      <div class="clue-col">
        <div class="col-head">DOWN</div>
        <div id="down-list"></div>
      </div>
    </div>
  </div>
</div>

<script type="application/json" id="gameData">{data_json}</script>
<script>
const D = JSON.parse(document.getElementById('gameData').textContent);
let selKey = null;
const revealed = new Set();

/* ── helpers ── */
function selCellSet(key) {{
  const p = D.placements.find(x => x.key === key);
  if (!p) return new Set();
  const s = new Set();
  for (let i = 0; i < p.word.length; i++) {{
    const r = p.row + (p.direction === 'down'   ? i : 0);
    const c = p.col + (p.direction === 'across' ? i : 0);
    s.add(r + ',' + c);
  }}
  return s;
}}

function revealedLetters() {{
  const m = {{}};
  for (const p of D.placements) {{
    if (!revealed.has(p.key)) continue;
    for (let i = 0; i < p.word.length; i++) {{
      const r = p.row + (p.direction === 'down'   ? i : 0);
      const c = p.col + (p.direction === 'across' ? i : 0);
      m[r + ',' + c] = p.word[i];
    }}
  }}
  return m;
}}

/* ── grid rendering ── */
function renderGrid() {{
  const sc   = selCellSet(selKey);
  const rl   = revealedLetters();
  const rows = [];
  for (let r = 0; r < D.rows; r++) {{
    const cells = [];
    for (let c = 0; c < D.cols; c++) {{
      if (D.grid[r][c] === '#') {{ cells.push('<td class="blk"></td>'); continue; }}
      const cls  = sc.has(r+','+c) ? 'wht sel' : 'wht';
      const num  = D.cellNumbers[r+','+c];
      const ltr  = rl[r+','+c] || '';
      cells.push(
        `<td class="${{cls}}" onclick="cellClick(${{r}},${{c}})">` +
        (num ? `<span class="num">${{num}}</span>` : '') +
        `<div class="ltr">${{ltr}}</div></td>`
      );
    }}
    rows.push('<tr>' + cells.join('') + '</tr>');
  }}
  document.getElementById('grid').innerHTML = rows.join('');
}}

/* ── cell click: toggle across ↔ down ── */
function cellClick(r, c) {{
  const words = D.cellToWords[r + ',' + c] || [];
  const aKey  = words.find(k => k.includes('across')) || '';
  const dKey  = words.find(k => k.includes('down'))   || '';
  let target  = '';
  if      (aKey && selKey !== aKey) target = aKey;
  else if (dKey && selKey !== dKey) target = dKey;
  else if (aKey)                    target = aKey;
  else                              target = dKey;
  if (target) selectWord(target);
}}

/* ── select a word ── */
function selectWord(key) {{
  selKey = key;
  renderGrid();
  renderPanel();
  renderClueLists();
  document.getElementById('feedbackMsg').textContent = '';
  const inp = document.getElementById('answerInput');
  inp.value = '';
  if (!revealed.has(key)) inp.focus();
}}

/* ── panel (selected clue + input) ── */
function renderPanel() {{
  const p = D.placements.find(x => x.key === selKey);
  if (!p) return;
  const dir = p.direction === 'across' ? 'ACROSS' : 'DOWN';
  document.getElementById('clue-label').textContent = p.number + ' ' + dir + ': ' + p.clue;
  document.getElementById('clue-hint').textContent  = '(' + p.word.length + ' letters)';
  const done = revealed.has(selKey);
  document.getElementById('answerInput').disabled = done;
  document.getElementById('submitBtn').disabled   = done;
}}

/* ── answer checking ── */
function submitAnswer() {{
  const p = D.placements.find(x => x.key === selKey);
  if (!p || revealed.has(p.key)) return;
  const raw   = document.getElementById('answerInput').value;
  const guess = raw.toUpperCase().trim().replace(/\\s+/g, '');
  const msg   = document.getElementById('feedbackMsg');
  if (guess === p.word) {{
    revealed.add(selKey);
    msg.textContent  = '✓ Correct!';
    msg.style.color  = '#2a8c2a';
    renderGrid();
    renderClueLists();
    updateProgress();
    const unsolved = D.placements.filter(x => !revealed.has(x.key));
    if (unsolved.length === 0) {{
      document.getElementById('completion').style.display = 'block';
      document.getElementById('answerInput').disabled = true;
      document.getElementById('submitBtn').disabled   = true;
    }} else {{
      setTimeout(() => selectWord(unsolved[0].key), 700);
    }}
  }} else {{
    msg.textContent = '✗ Not quite — try again!';
    msg.style.color = '#c0392b';
  }}
}}

/* ── clue list ── */
function renderClueLists() {{
  ['across','down'].forEach(dir => {{
    const items = D.placements
      .filter(p => p.direction === dir)
      .sort((a,b) => a.number - b.number);
    document.getElementById(dir + '-list').innerHTML = items.map(p => {{
      const cls = 'clue-btn' +
        (revealed.has(p.key) ? ' solved' : '') +
        (p.key === selKey    ? ' active' : '');
      const prefix = revealed.has(p.key) ? '✓ ' : '';
      return `<button class="${{cls}}" onclick="selectWord('${{p.key}}')">${{prefix}}${{p.number}}. ${{p.clue}}</button>`;
    }}).join('');
  }});
}}

/* ── progress bar ── */
function updateProgress() {{
  const total = D.placements.length, done = revealed.size;
  document.getElementById('prog-text').textContent = done + ' / ' + total + ' words solved';
  document.getElementById('prog-inner').style.width = Math.round(done/total*100) + '%';
}}

/* ── give up ── */
function giveUp() {{
  if (!confirm('Reveal all answers and end the game?')) return;
  for (const p of D.placements) revealed.add(p.key);
  selKey = null;
  renderGrid();
  renderClueLists();
  updateProgress();
  document.getElementById('answerInput').disabled = true;
  document.getElementById('submitBtn').disabled   = true;
  document.getElementById('giveUpBtn').disabled   = true;
  document.getElementById('feedbackMsg').textContent = '';
  document.getElementById('gave-up').style.display = 'block';
}}

/* ── boot ── */
if (D.placements.length) selectWord(D.placements[0].key);
updateProgress();
</script>
</body>
</html>"""

    grid_w = cw.cols * _CELL + 28
    grid_h = cw.rows * _CELL + 28

    panel_w = 420
    max_clues_per_col = max(
        len([p for p in cw.placements if p.direction == "across"]),
        len([p for p in cw.placements if p.direction == "down"]),
    )
    # Answer area + progress + clue list
    panel_h = 230 + max_clues_per_col * 42

    total_w = grid_w + 20 + panel_w + 28   # grid | gap | panel | body padding
    total_h = max(grid_h, panel_h) + 28
    return html, total_w, total_h


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.markdown('<div class="cw-title">Roman Space Telescope Crossword</div>', unsafe_allow_html=True)

if st.button("New Game", type="primary"):
    start_game()
    st.rerun()

if not st.session_state.game_active:
    st.info("Click **New Game** to generate your puzzle.")
    st.stop()

cw: CrosswordData = st.session_state.crossword
if cw is None:
    st.error("Could not generate a crossword — please try again.")
    if st.button("Retry"):
        start_game()
        st.rerun()
    st.stop()

html_str, w, h = _build_game_html(cw)
st.iframe(html_str, width=w, height=h)
