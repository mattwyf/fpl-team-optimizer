"""
FPL Team Optimizer — Streamlit UI

Run with:
    streamlit run app.py

Wraps the algorithm in fpl_optimizer.py with interactive widgets:
- CSV upload (or auto-detected local file)
- Target gameweek, budget, and lookback controls
- Squad display with starting XI, captain, and validation
- Optional backtest against actual gameweek points
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from fpl_optimizer import (
    DEFAULT_BUDGET,
    DEFAULT_LOOKBACK,
    POSITION_NAMES,
    SQUAD_SIZE,
    DataLoader,
    GameweekRecord,
    Predictor,
    Squad,
    SquadBuilder,
    SquadValidator,
    StartingXISelector,
)

st.set_page_config(page_title="FPL Team Optimizer", page_icon="⚽", layout="wide")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def find_default_csv() -> Path | None:
    candidates = [
        Path(__file__).parent / "fpl-data-stats.csv",
        Path.home() / "Desktop" / "fpl-data-stats.csv",
        Path.home() / "Downloads" / "fpl-data-stats.csv",
    ]
    return next((p for p in candidates if p.exists()), None)


@st.cache_data(show_spinner="Loading CSV...")
def load_records_from_bytes(data: bytes) -> list[GameweekRecord]:
    """DataLoader works on file paths, so stage uploaded bytes in a temp file."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        return DataLoader(tmp_path).load()
    finally:
        tmp_path.unlink(missing_ok=True)


@st.cache_data(show_spinner="Loading CSV...")
def load_records_from_path(path_str: str, mtime: float) -> list[GameweekRecord]:
    # mtime is part of the cache key so edits to the file invalidate the cache
    return DataLoader(Path(path_str)).load()


# ---------------------------------------------------------------------------
# Sidebar: inputs
# ---------------------------------------------------------------------------

st.sidebar.title("⚽ FPL Optimizer")
st.sidebar.caption("Suggests an optimal 15-player squad from past gameweek statistics.")

uploaded = st.sidebar.file_uploader("FPL statistics CSV", type="csv")

records: list[GameweekRecord] | None = None
source_label = ""

try:
    if uploaded is not None:
        records = load_records_from_bytes(uploaded.getvalue())
        source_label = uploaded.name
    else:
        default_csv = find_default_csv()
        if default_csv is not None:
            records = load_records_from_path(str(default_csv), default_csv.stat().st_mtime)
            source_label = str(default_csv)
except (FileNotFoundError, ValueError) as exc:
    st.sidebar.error(f"Could not load CSV: {exc}")

if records is None:
    st.title("FPL Team Optimizer")
    st.info(
        "Upload an FPL statistics CSV in the sidebar to get started.\n\n"
        "Required columns: `id`, `element_type`, `web_name`, `team_name`, "
        "`now_cost`, `gameweek`, `minutes`, `total_points`, `expected_points`."
    )
    st.stop()

st.sidebar.success(f"Loaded {len(records):,} rows\n\n`{source_label}`")

min_gw = min(r.gameweek for r in records)
max_gw = max(r.gameweek for r in records)

st.sidebar.divider()
st.sidebar.subheader("Settings")

target_gw = st.sidebar.number_input(
    "Target gameweek",
    min_value=min_gw + 1,
    max_value=max_gw,
    value=min(max_gw, min_gw + DEFAULT_LOOKBACK + 1),
    help="The gameweek to build a squad for. Only earlier gameweeks inform the prediction.",
)

budget = st.sidebar.slider(
    "Budget (£M)",
    min_value=80.0,
    max_value=100.0,
    value=DEFAULT_BUDGET,
    step=0.5,
)

# Only gameweeks between the start of the data and the target can be looked at,
# so cap the slider at the history that actually exists.
max_lookback = min(10, int(target_gw) - min_gw)
if max_lookback > 1:
    lookback = st.sidebar.slider(
        "Lookback weeks",
        min_value=1,
        max_value=max_lookback,
        value=min(DEFAULT_LOOKBACK, max_lookback),
        help="How many past gameweeks feed the weighted-average prediction. "
        f"Capped at {max_lookback} — the number of gameweeks before the target.",
    )
else:
    lookback = 1
    st.sidebar.caption(
        "Lookback fixed at 1 week — only one gameweek exists before the target."
    )

show_backtest = st.sidebar.checkbox(
    "Backtest against actual points",
    value=False,
    help="Compare the squad's predicted points with what those players actually scored "
    "in the target gameweek.",
)

run = st.sidebar.button("Build squad", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

st.title("FPL Team Optimizer")
st.caption(f"Gameweeks available: {min_gw}–{max_gw}")

if not run:
    st.info("Adjust the settings in the sidebar, then click **Build squad**.")
    st.stop()

predictor = Predictor(lookback_weeks=int(lookback))
builder = SquadBuilder(budget=float(budget))

players = predictor.build_player_pool(records, int(target_gw))
if len(players) < SQUAD_SIZE:
    st.error(
        f"Only {len(players)} eligible players found — need at least {SQUAD_SIZE}. "
        "Try an earlier gameweek or fewer lookback weeks."
    )
    st.stop()

squad: Squad = builder.build(players)
valid, errors = SquadValidator.is_valid(squad, float(budget))
captain = squad.captain()
starting_xi, formation = StartingXISelector.select(squad)
xi_ids = {p.player_id for p in starting_xi}

# --- Summary metrics ---
st.subheader(f"Squad suggestion — Gameweek {target_gw}")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total cost", f"£{squad.total_cost:.1f}M")
col2.metric("Budget remaining", f"£{budget - squad.total_cost:.1f}M")
col3.metric("Predicted points (15)", f"{squad.total_predicted_points:.1f}")
col4.metric(
    "Captain",
    captain.name if captain else "—",
    f"{captain.predicted_points:.1f} pts ×2" if captain else None,
    delta_color="off",
)
col5.metric("Formation", formation)

if valid:
    st.success("Squad passes all FPL constraint checks.")
else:
    st.warning("Squad validation failed:\n" + "\n".join(f"- {e}" for e in errors))

# --- Squad table by position ---
def squad_dataframe(players_group: list) -> pd.DataFrame:
    rows = []
    for p in sorted(players_group, key=lambda p: p.predicted_points, reverse=True):
        rows.append(
            {
                "Role": "⭐ XI" if p.player_id in xi_ids else "Bench",
                "Player": p.name + (" (C)" if captain and p.player_id == captain.player_id else ""),
                "Team": p.team,
                "Price (£M)": p.price,
                "Predicted pts": p.predicted_points,
                "Efficiency": p.efficiency,
                "Apps rate": f"{p.appearance_rate:.0%}",
                "Avg mins": p.avg_minutes,
            }
        )
    return pd.DataFrame(rows)


tab_squad, tab_pool = st.tabs(["Squad", "Player pool"])

with tab_squad:
    for position in (1, 2, 3, 4):
        group = [p for p in squad.players if p.position == position]
        st.markdown(f"**{POSITION_NAMES[position]}** ({len(group)})")
        st.dataframe(
            squad_dataframe(group),
            hide_index=True,
            use_container_width=True,
        )

with tab_pool:
    st.caption(
        f"All {len(players)} players eligible for selection this gameweek, "
        "ranked by predicted points."
    )
    pool_df = pd.DataFrame(
        {
            "Player": p.name,
            "Pos": p.position_name,
            "Team": p.team,
            "Price (£M)": p.price,
            "Predicted pts": p.predicted_points,
            "Efficiency": p.efficiency,
            "Apps rate": f"{p.appearance_rate:.0%}",
        }
        for p in sorted(players, key=lambda p: p.predicted_points, reverse=True)
    )
    st.dataframe(pool_df, hide_index=True, use_container_width=True, height=500)

# --- Backtest ---
if show_backtest:
    st.divider()
    st.subheader(f"Backtest — Gameweek {target_gw}")

    actual_by_id = {
        r.player_id: r.total_points for r in records if r.gameweek == target_gw
    }

    bt_rows = []
    predicted_total = 0.0
    actual_total = 0.0
    for p in sorted(squad.players, key=lambda p: p.predicted_points, reverse=True):
        actual = actual_by_id.get(p.player_id, 0.0)
        predicted_total += p.predicted_points
        actual_total += actual
        bt_rows.append(
            {
                "Player": p.name,
                "Predicted": p.predicted_points,
                "Actual": actual,
                "Diff": round(actual - p.predicted_points, 1),
            }
        )

    if captain and captain.player_id in actual_by_id:
        actual_total += actual_by_id[captain.player_id]
    if captain:
        predicted_total += captain.predicted_points

    bcol1, bcol2, bcol3 = st.columns(3)
    bcol1.metric("Predicted total (incl. captain)", f"{predicted_total:.1f}")
    bcol2.metric("Actual total (incl. captain)", f"{actual_total:.1f}")
    bcol3.metric(
        "Difference",
        f"{actual_total - predicted_total:+.1f}",
        delta_color="off",
    )

    st.dataframe(pd.DataFrame(bt_rows), hide_index=True, use_container_width=True)
