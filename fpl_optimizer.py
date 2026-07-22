"""
FPL Team Optimizer — IB Computer Science SL IA
Uses past player statistics to suggest an optimal squad within a budget.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# FPL position codes: 1=GK, 2=DEF, 3=MID, 4=FWD
POSITION_NAMES = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
POSITION_LIMITS = {1: 2, 2: 5, 3: 5, 4: 3}
SQUAD_SIZE = 15
MAX_PER_TEAM = 3
DEFAULT_BUDGET = 100.0
DEFAULT_LOOKBACK = 5
MIN_START_MINUTES = 60  # minutes to count as "started" that gameweek
MIN_APPEARANCES = 3  # must start in at least this many of the last N gameweeks

REQUIRED_COLUMNS = {
    "id",
    "element_type",
    "web_name",
    "team_name",
    "now_cost",
    "gameweek",
    "minutes",
    "total_points",
    "expected_points",
}
HIST_XP_WEIGHT = 0.3  # per-week blend of actual points with that week's xP (noise control)


@dataclass
class GameweekRecord:
    player_id: int
    name: str
    position: int
    team: str
    price: float
    gameweek: int
    minutes: int
    total_points: float
    expected_points: float = 0.0


@dataclass
class Player:
    player_id: int
    name: str
    position: int
    team: str
    price: float
    predicted_points: float = 0.0
    efficiency: float = 0.0
    avg_minutes: float = 0.0
    weeks_used: int = 0
    appearance_rate: float = 0.0  # fraction of lookback weeks with 60+ minutes

    @property
    def position_name(self) -> str:
        return POSITION_NAMES[self.position]


@dataclass
class Squad:
    players: list[Player] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return round(sum(p.price for p in self.players), 1)

    @property
    def total_predicted_points(self) -> float:
        return round(sum(p.predicted_points for p in self.players), 2)

    def team_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for player in self.players:
            counts[player.team] += 1
        return dict(counts)

    def captain(self) -> Optional[Player]:
        if not self.players:
            return None
        return max(self.players, key=lambda p: p.predicted_points)


class DataLoader:
    """Reads and validates the FPL statistics CSV file."""

    def __init__(self, filepath: str | Path) -> None:
        self.filepath = Path(filepath)

    def load(self) -> list[GameweekRecord]:
        if not self.filepath.exists():
            raise FileNotFoundError(f"CSV file not found: {self.filepath}")

        records: list[GameweekRecord] = []

        with self.filepath.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            if reader.fieldnames is None:
                raise ValueError("CSV file has no header row.")

            missing = REQUIRED_COLUMNS - set(reader.fieldnames)
            if missing:
                raise ValueError(f"CSV missing required columns: {sorted(missing)}")

            for row_num, row in enumerate(reader, start=2):
                try:
                    records.append(
                        GameweekRecord(
                            player_id=int(row["id"]),
                            name=row["web_name"].strip(),
                            position=int(row["element_type"]),
                            team=row["team_name"].strip(),
                            price=float(row["now_cost"]),
                            gameweek=int(row["gameweek"]),
                            minutes=int(float(row["minutes"] or 0)),
                            total_points=float(row["total_points"] or 0),
                            expected_points=float(row["expected_points"] or 0),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid data on CSV row {row_num}: {exc}") from exc

        if not records:
            raise ValueError("CSV file contains no data rows.")

        return records


class Predictor:
    """
    Forecasts next-gameweek points using a calendar-based weighted average.

    Improvements over a plain played-weeks average:
    - Counts missed gameweeks as 0 points (avoids one-week spikes like Ben White)
    - Requires the player to have started recently (rotation/injury filter)
    - Scales prediction by appearance rate across the lookback window
    """

    def __init__(self, lookback_weeks: int = DEFAULT_LOOKBACK) -> None:
        self.lookback_weeks = lookback_weeks

    def build_player_pool(
        self, records: list[GameweekRecord], target_gameweek: int
    ) -> list[Player]:
        # Only past gameweeks (strictly before the target) may inform a prediction.
        # No column from the target gameweek row is ever read here.
        by_player: dict[int, list[GameweekRecord]] = defaultdict(list)
        for record in records:
            if record.gameweek < target_gameweek:
                by_player[record.player_id].append(record)

        # The lookback window can only reach back to the first gameweek that
        # actually has data (e.g. targeting GW2 means only GW1 is usable,
        # regardless of the configured lookback).
        first_gameweek = min((r.gameweek for r in records), default=1)

        players: list[Player] = []

        for player_id, history in by_player.items():
            past = list(history)
            if not past:
                continue

            past.sort(key=lambda r: r.gameweek)
            latest = past[-1]

            recent = self._calendar_window(past, target_gameweek, first_gameweek)
            if not recent:
                continue

            # Must have played in the most recent gameweek (avoids injured/benched players)
            if recent[-1].minutes < MIN_START_MINUTES:
                continue

            starts = sum(1 for record in recent if record.minutes >= MIN_START_MINUTES)
            # Scale the appearance requirement to the actual window size:
            # early in the season fewer past weeks exist than MIN_APPEARANCES.
            required_starts = min(MIN_APPEARANCES, len(recent))
            if starts < required_starts:
                continue

            appearance_rate = starts / len(recent)
            # Blend each week's actual points with that week's expected points.
            # Missed weeks stay at 0 (both fields are 0), so hauls are damped
            # while consistent underlying performance is rewarded.
            weekly_scores = [
                (1 - HIST_XP_WEIGHT) * r.total_points + HIST_XP_WEIGHT * r.expected_points
                for r in recent
            ]
            predicted = self._weighted_average(weekly_scores)
            predicted *= appearance_rate

            avg_minutes = sum(r.minutes for r in recent) / len(recent)
            if avg_minutes < MIN_START_MINUTES:
                predicted *= 0.5

            if predicted <= 0:
                continue

            player = Player(
                player_id=player_id,
                name=latest.name,
                position=latest.position,
                team=latest.team,
                price=latest.price,
                predicted_points=round(predicted, 2),
                efficiency=round(predicted / latest.price, 3) if latest.price > 0 else 0.0,
                avg_minutes=round(avg_minutes, 1),
                weeks_used=len(recent),
                appearance_rate=round(appearance_rate, 2),
            )
            players.append(player)

        return players

    def _calendar_window(
        self, past: list[GameweekRecord], target_gameweek: int, first_gameweek: int = 1
    ) -> list[GameweekRecord]:
        """Return one record per gameweek for the last N weeks before the target.

        The window never extends before `first_gameweek` (the earliest gameweek
        present in the dataset), so a large lookback early in the season simply
        uses however many weeks actually exist.
        """
        by_gw = {record.gameweek: record for record in past}
        start_gw = max(first_gameweek, target_gameweek - self.lookback_weeks)
        window: list[GameweekRecord] = []

        for gameweek in range(start_gw, target_gameweek):
            if gameweek in by_gw:
                window.append(by_gw[gameweek])
            else:
                template = past[-1]
                window.append(
                    GameweekRecord(
                        player_id=template.player_id,
                        name=template.name,
                        position=template.position,
                        team=template.team,
                        price=template.price,
                        gameweek=gameweek,
                        minutes=0,
                        total_points=0.0,
                    )
                )

        return window

    @staticmethod
    def _weighted_average(values: list[float]) -> float:
        """Linear weights: oldest week=1, most recent week=n."""
        if not values:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for index, value in enumerate(values, start=1):
            weighted_sum += index * value
            total_weight += index

        return weighted_sum / total_weight if total_weight else 0.0


class SquadValidator:
    """Checks whether a squad satisfies FPL rules."""

    @staticmethod
    def is_valid(squad: Squad, budget: float) -> tuple[bool, list[str]]:
        errors: list[str] = []

        if len(squad.players) != SQUAD_SIZE:
            errors.append(f"Squad must have {SQUAD_SIZE} players (has {len(squad.players)}).")

        position_counts: dict[int, int] = defaultdict(int)
        for player in squad.players:
            position_counts[player.position] += 1

        for position, required in POSITION_LIMITS.items():
            actual = position_counts[position]
            if actual != required:
                name = POSITION_NAMES[position]
                errors.append(f"Need {required} {name}, found {actual}.")

        if squad.total_cost > budget + 0.05:
            errors.append(
                f"Cost £{squad.total_cost:.1f}M exceeds budget £{budget:.1f}M."
            )

        for team, count in squad.team_counts().items():
            if count > MAX_PER_TEAM:
                errors.append(f"Too many players from {team}: {count} (max {MAX_PER_TEAM}).")

        ids = [p.player_id for p in squad.players]
        if len(ids) != len(set(ids)):
            errors.append("Squad contains duplicate players.")

        return len(errors) == 0, errors


class SquadBuilder:
    """Builds a squad using greedy selection with budget repair and upgrades."""

    def __init__(self, budget: float = DEFAULT_BUDGET) -> None:
        self.budget = budget

    def build(self, players: list[Player]) -> Squad:
        by_position: dict[int, list[Player]] = defaultdict(list)
        for player in players:
            if player.position in POSITION_LIMITS:
                by_position[player.position].append(player)

        for position_players in by_position.values():
            position_players.sort(
                key=lambda p: (p.efficiency, p.predicted_points), reverse=True
            )

        squad = Squad()
        team_counts: dict[str, int] = defaultdict(int)
        selected_ids: set[int] = set()

        for position, limit in POSITION_LIMITS.items():
            picked = 0
            for player in by_position[position]:
                if picked >= limit:
                    break
                if player.player_id in selected_ids:
                    continue
                if team_counts[player.team] >= MAX_PER_TEAM:
                    continue

                squad.players.append(player)
                selected_ids.add(player.player_id)
                team_counts[player.team] += 1
                picked += 1

        squad = self._repair_budget(squad, by_position, selected_ids, team_counts)
        squad = self._upgrade_squad(squad, players)
        return squad

    def _repair_budget(
        self,
        squad: Squad,
        by_position: dict[int, list[Player]],
        selected_ids: set[int],
        team_counts: dict[str, int],
    ) -> Squad:
        max_attempts = 200
        attempts = 0

        while squad.total_cost > self.budget and attempts < max_attempts:
            attempts += 1
            worst = min(squad.players, key=lambda p: (p.efficiency, p.predicted_points))

            squad.players.remove(worst)
            selected_ids.remove(worst.player_id)
            team_counts[worst.team] -= 1

            replacement = self._find_replacement(
                squad, by_position, selected_ids, team_counts, worst.position
            )

            if replacement is None:
                squad.players.append(worst)
                selected_ids.add(worst.player_id)
                team_counts[worst.team] += 1
                break

            squad.players.append(replacement)
            selected_ids.add(replacement.player_id)
            team_counts[replacement.team] += 1

        return squad

    def _upgrade_squad(self, squad: Squad, all_players: list[Player]) -> Squad:
        selected_ids = {p.player_id for p in squad.players}
        improved = True

        while improved:
            improved = False
            team_counts = squad.team_counts()

            # Try upgrading cheapest players first (by actual squad index)
            indices = sorted(
                range(len(squad.players)),
                key=lambda i: squad.players[i].price,
            )

            for index in indices:
                current = squad.players[index]

                for candidate in all_players:
                    if candidate.player_id in selected_ids:
                        continue
                    if candidate.position != current.position:
                        continue
                    if candidate.predicted_points <= current.predicted_points:
                        continue

                    new_cost = squad.total_cost - current.price + candidate.price
                    if new_cost > self.budget + 0.05:
                        continue

                    new_team_counts = dict(team_counts)
                    new_team_counts[current.team] -= 1
                    new_team_counts[candidate.team] = new_team_counts.get(candidate.team, 0) + 1

                    if new_team_counts.get(candidate.team, 0) > MAX_PER_TEAM:
                        continue

                    squad.players[index] = candidate
                    selected_ids.remove(current.player_id)
                    selected_ids.add(candidate.player_id)
                    team_counts = squad.team_counts()
                    improved = True
                    break

                if improved:
                    break

        return squad

    def _find_replacement(
        self,
        squad: Squad,
        by_position: dict[int, list[Player]],
        selected_ids: set[int],
        team_counts: dict[str, int],
        position: int,
    ) -> Optional[Player]:
        for candidate in by_position[position]:
            if candidate.player_id in selected_ids:
                continue
            if team_counts[candidate.team] >= MAX_PER_TEAM:
                continue

            new_cost = squad.total_cost + candidate.price
            if new_cost <= self.budget + 0.05:
                return candidate

        for candidate in by_position[position]:
            if candidate.player_id in selected_ids:
                continue
            if team_counts[candidate.team] >= MAX_PER_TEAM:
                continue
            return candidate

        return None


class StartingXISelector:
    """Picks the best valid starting 11 from a 15-player squad."""

    FORMATIONS = [
        (1, 3, 4, 3),
        (1, 3, 5, 2),
        (1, 4, 4, 2),
        (1, 4, 3, 3),
        (1, 5, 3, 2),
        (1, 5, 4, 1),
    ]

    @classmethod
    def select(cls, squad: Squad) -> tuple[list[Player], str]:
        best_xi: list[Player] = []
        best_points = -1.0
        best_label = ""

        pool = sorted(squad.players, key=lambda p: p.predicted_points, reverse=True)
        by_position: dict[int, list[Player]] = defaultdict(list)
        for player in pool:
            by_position[player.position].append(player)

        for gk, defs, mids, fwds in cls.FORMATIONS:
            if len(by_position[1]) < gk:
                continue
            if len(by_position[2]) < defs:
                continue
            if len(by_position[3]) < mids:
                continue
            if len(by_position[4]) < fwds:
                continue

            xi = (
                by_position[1][:gk]
                + by_position[2][:defs]
                + by_position[3][:mids]
                + by_position[4][:fwds]
            )
            points = sum(p.predicted_points for p in xi)

            if points > best_points:
                best_points = points
                best_xi = xi
                best_label = f"{defs}-{mids}-{fwds}"

        return best_xi, best_label


def display_squad(squad: Squad, budget: float, target_gameweek: int) -> None:
    """Print the suggested squad to the terminal."""
    valid, errors = SquadValidator.is_valid(squad, budget)
    captain = squad.captain()
    starting_xi, formation = StartingXISelector.select(squad)
    xi_ids = {p.player_id for p in starting_xi}

    print()
    print("=" * 60)
    print(f"  FPL SQUAD SUGGESTION — Gameweek {target_gameweek}")
    print("=" * 60)
    print(f"  Total cost:            £{squad.total_cost:.1f}M")
    print(f"  Budget remaining:      £{budget - squad.total_cost:.1f}M")
    print(f"  Predicted points (15): {squad.total_predicted_points:.1f}")
    if captain:
        print(
            f"  Captain:               {captain.name} "
            f"({captain.predicted_points:.1f} pts x2 = {captain.predicted_points * 2:.1f})"
        )
    print(f"  Starting XI formation: {formation}")
    print()

    for position in (1, 2, 3, 4):
        group = [p for p in squad.players if p.position == position]
        group.sort(key=lambda p: p.predicted_points, reverse=True)

        print(f"  {POSITION_NAMES[position]} ({len(group)})")
        print(f"  {'-' * 54}")

        for player in group:
            starter = "XI" if player.player_id in xi_ids else "BN"
            cap = " (C)" if captain and player.player_id == captain.player_id else ""
            print(
                f"  [{starter}] {player.name:<22} {player.team:<14} "
                f"£{player.price:>4.1f}M  {player.predicted_points:>5.1f} pts  "
                f"eff {player.efficiency:.2f}  apps {player.appearance_rate:.0%}{cap}"
            )
        print()

    if not valid:
        print("  WARNING: Squad validation failed:")
        for error in errors:
            print(f"    - {error}")
    else:
        print("  Squad passes all FPL constraint checks.")
    print("=" * 60)
    print()


def prompt_float(prompt: str, default: float, minimum: float, maximum: float) -> float:
    """Read a float from the user with validation."""
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default

        try:
            value = float(raw)
        except ValueError:
            print("  Please enter a valid number.")
            continue

        if value < minimum or value > maximum:
            print(f"  Value must be between {minimum} and {maximum}.")
            continue

        return value


def prompt_int(prompt: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer from the user with validation."""
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default

        try:
            value = int(raw)
        except ValueError:
            print("  Please enter a valid whole number.")
            continue

        if value < minimum or value > maximum:
            print(f"  Value must be between {minimum} and {maximum}.")
            continue

        return value


def run_backtest(
    records: list[GameweekRecord],
    target_gameweek: int,
    budget: float,
    lookback: int,
) -> None:
    """Compare predicted squad against actual points in the target gameweek."""
    predictor = Predictor(lookback_weeks=lookback)
    builder = SquadBuilder(budget=budget)

    players = predictor.build_player_pool(records, target_gameweek)
    squad = builder.build(players)

    actual_by_id: dict[int, float] = {}
    for record in records:
        if record.gameweek == target_gameweek:
            actual_by_id[record.player_id] = record.total_points

    actual_total = 0.0
    predicted_total = 0.0
    print()
    print("=" * 60)
    print(f"  BACKTEST — Gameweek {target_gameweek}")
    print("=" * 60)
    print(f"  {'Player':<22} {'Pred':>6} {'Actual':>6} {'Diff':>6}")
    print(f"  {'-' * 54}")

    for player in sorted(squad.players, key=lambda p: p.predicted_points, reverse=True):
        actual = actual_by_id.get(player.player_id, 0.0)
        diff = actual - player.predicted_points
        predicted_total += player.predicted_points
        actual_total += actual
        print(
            f"  {player.name:<22} {player.predicted_points:>6.1f} "
            f"{actual:>6.1f} {diff:>+6.1f}"
        )

    captain = squad.captain()
    if captain and captain.player_id in actual_by_id:
        actual_total += actual_by_id[captain.player_id]

    print(f"  {'-' * 54}")
    print(f"  Predicted total (incl. captain bonus): {predicted_total + (captain.predicted_points if captain else 0):.1f}")
    print(f"  Actual total (incl. captain bonus):    {actual_total:.1f}")
    print("=" * 60)
    print()


def main() -> None:
    print()
    print("=" * 60)
    print("  FPL TEAM OPTIMIZER")
    print("  Fantasy Premier League squad suggestion tool")
    print("=" * 60)
    print()

    # Look for the dataset next to the script, then on the Desktop, then Downloads.
    candidate_paths = [
        Path(__file__).parent / "fpl-data-stats.csv",
        Path.home() / "Desktop" / "fpl-data-stats.csv",
        Path.home() / "Downloads" / "fpl-data-stats.csv",
    ]
    default_csv = next((p for p in candidate_paths if p.exists()), candidate_paths[1])

    csv_prompt = f"CSV file path [{default_csv}]"
    csv_input = input(f"{csv_prompt}: ").strip()
    csv_path = Path(csv_input) if csv_input else default_csv

    try:
        records = DataLoader(csv_path).load()
    except (FileNotFoundError, ValueError) as exc:
        print(f"\nError: {exc}")
        sys.exit(1)

    max_gw = max(r.gameweek for r in records)
    min_gw = min(r.gameweek for r in records)

    print(f"\nLoaded {len(records):,} rows from CSV.")
    print(f"Gameweeks available: {min_gw} to {max_gw}")

    target_gw = prompt_int(
        "\nTarget gameweek to build squad for",
        default=min(max_gw, min_gw + DEFAULT_LOOKBACK + 1),
        minimum=min_gw + 1,
        maximum=max_gw,
    )

    budget = prompt_float("Budget in millions", DEFAULT_BUDGET, 80.0, 100.0)

    # Can't look back further than the history that exists before the target.
    max_lookback = min(10, target_gw - min_gw)
    lookback = prompt_int(
        "Lookback weeks for prediction",
        min(DEFAULT_LOOKBACK, max_lookback),
        1,
        max_lookback,
    )

    backtest_choice = input("\nRun backtest against actual GW points? (y/n) [n]: ").strip().lower()
    run_test = backtest_choice == "y"

    print("\nBuilding squad...")

    predictor = Predictor(lookback_weeks=lookback)
    builder = SquadBuilder(budget=budget)

    players = predictor.build_player_pool(records, target_gw)
    if len(players) < SQUAD_SIZE:
        print(
            f"\nError: Only {len(players)} eligible players found. "
            "Try an earlier gameweek or fewer lookback weeks."
        )
        sys.exit(1)

    squad = builder.build(players)
    display_squad(squad, budget, target_gw)

    if run_test and target_gw <= max_gw:
        run_backtest(records, target_gw, budget, lookback)


if __name__ == "__main__":
    main()
