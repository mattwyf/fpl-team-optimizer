"""
FPL Team Optimizer — HTTP API

A thin Flask backend that reuses the optimizer logic in ``fpl_optimizer.py``
and exposes it as JSON endpoints so a mobile (iOS) client can request squads.

Endpoints
---------
GET  /api/health              -> basic status + which CSV is loaded
GET  /api/gameweeks           -> available gameweek range + defaults
POST /api/optimize            -> build a squad for a given gameweek

Run with:
    python3 api.py
    # or, for production-style serving:
    #   pip install gunicorn && gunicorn api:app
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request

from fpl_optimizer import (
    DEFAULT_BUDGET,
    DEFAULT_LOOKBACK,
    POSITION_NAMES,
    SQUAD_SIZE,
    DataLoader,
    GameweekRecord,
    Player,
    Predictor,
    Squad,
    SquadBuilder,
    SquadValidator,
    StartingXISelector,
)

app = Flask(__name__)

# Where to look for the dataset, in priority order.
CSV_CANDIDATES = [
    Path(__file__).parent / "fpl-data-stats.csv",
    Path.home() / "Desktop" / "fpl-data-stats.csv",
    Path.home() / "Downloads" / "fpl-data-stats.csv",
]

# The dataset is large; load it once and keep it in memory.
_records: Optional[list[GameweekRecord]] = None
_records_path: Optional[Path] = None


def find_csv() -> Optional[Path]:
    for candidate in CSV_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def get_records() -> list[GameweekRecord]:
    """Load (and cache) the CSV records, raising if the file is missing."""
    global _records, _records_path
    if _records is None:
        path = find_csv()
        if path is None:
            raise FileNotFoundError(
                "No dataset found. Place 'fpl-data-stats.csv' next to api.py, "
                "on the Desktop, or in Downloads."
            )
        _records = DataLoader(path).load()
        _records_path = path
    return _records


def player_to_dict(player: Player, in_xi: bool, is_captain: bool) -> dict:
    return {
        "id": player.player_id,
        "name": player.name,
        "position": player.position,
        "positionName": player.position_name,
        "team": player.team,
        "price": round(player.price, 1),
        "predictedPoints": round(player.predicted_points, 1),
        "efficiency": round(player.efficiency, 2),
        "avgMinutes": round(player.avg_minutes, 1),
        "appearanceRate": round(player.appearance_rate, 2),
        "inStartingXI": in_xi,
        "isCaptain": is_captain,
    }


def serialize_squad(squad: Squad, budget: float, target_gameweek: int) -> dict:
    starting_xi, formation = StartingXISelector.select(squad)
    xi_ids = {p.player_id for p in starting_xi}
    captain = squad.captain()
    captain_id = captain.player_id if captain else None
    valid, errors = SquadValidator.is_valid(squad, budget)

    players = [
        player_to_dict(p, p.player_id in xi_ids, p.player_id == captain_id)
        for p in sorted(
            squad.players,
            key=lambda pl: (pl.position, -pl.predicted_points),
        )
    ]

    return {
        "gameweek": target_gameweek,
        "budget": round(budget, 1),
        "totalCost": squad.total_cost,
        "budgetRemaining": round(budget - squad.total_cost, 1),
        "predictedPoints": squad.total_predicted_points,
        "formation": formation,
        "captain": (
            {
                "id": captain.player_id,
                "name": captain.name,
                "predictedPoints": round(captain.predicted_points, 1),
                "captainPoints": round(captain.predicted_points * 2, 1),
            }
            if captain
            else None
        ),
        "isValid": valid,
        "errors": errors,
        "players": players,
    }


@app.get("/api/health")
def health() -> tuple:
    path = find_csv()
    return (
        jsonify(
            {
                "status": "ok",
                "datasetFound": path is not None,
                "datasetPath": str(path) if path else None,
            }
        ),
        200,
    )


@app.get("/api/gameweeks")
def gameweeks() -> tuple:
    try:
        records = get_records()
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    max_gw = max(r.gameweek for r in records)
    min_gw = min(r.gameweek for r in records)
    return (
        jsonify(
            {
                "minGameweek": min_gw,
                "maxGameweek": max_gw,
                # Can only predict from the second available gameweek onward.
                "minTarget": min_gw + 1,
                "maxTarget": max_gw,
                "defaultTarget": min(max_gw, min_gw + DEFAULT_LOOKBACK + 1),
                "defaultBudget": DEFAULT_BUDGET,
                "defaultLookback": DEFAULT_LOOKBACK,
            }
        ),
        200,
    )


@app.post("/api/optimize")
def optimize() -> tuple:
    try:
        records = get_records()
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    payload = request.get_json(silent=True) or {}

    max_gw = max(r.gameweek for r in records)
    min_gw = min(r.gameweek for r in records)

    try:
        target_gw = int(payload.get("gameweek", min(max_gw, min_gw + DEFAULT_LOOKBACK + 1)))
        budget = float(payload.get("budget", DEFAULT_BUDGET))
        lookback = int(payload.get("lookback", DEFAULT_LOOKBACK))
    except (TypeError, ValueError):
        return jsonify({"error": "gameweek, budget and lookback must be numbers."}), 400

    if not (min_gw + 1 <= target_gw <= max_gw):
        return (
            jsonify(
                {
                    "error": f"gameweek must be between {min_gw + 1} and {max_gw}.",
                }
            ),
            400,
        )
    if not (50.0 <= budget <= 120.0):
        return jsonify({"error": "budget must be between 50 and 120."}), 400
    if not (1 <= lookback <= 15):
        return jsonify({"error": "lookback must be between 1 and 15."}), 400

    predictor = Predictor(lookback_weeks=lookback)
    builder = SquadBuilder(budget=budget)

    players = predictor.build_player_pool(records, target_gw)
    if len(players) < SQUAD_SIZE:
        return (
            jsonify(
                {
                    "error": (
                        f"Only {len(players)} eligible players found for GW{target_gw}. "
                        "Try a later gameweek or a smaller lookback."
                    )
                }
            ),
            422,
        )

    squad = builder.build(players)
    return jsonify(serialize_squad(squad, budget, target_gw)), 200


if __name__ == "__main__":
    # host=0.0.0.0 so a phone on the same Wi-Fi can reach it.
    app.run(host="0.0.0.0", port=8000, debug=True)
