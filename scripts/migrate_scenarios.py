"""One-time migration of legacy scenarios.json into mafia_scenarios.

Usage: python scripts/migrate_scenarios.py
Requires DATABASE_URL. The script is idempotent because ScenarioRepository.upsert
uses the scenario name as its conflict key.
"""

import json
from pathlib import Path

from repositories.scenario_repository import ScenarioRepository


def main():
    source = Path(__file__).resolve().parents[1] / "scenarios.json"
    if not source.exists():
        raise SystemExit("scenarios.json پیدا نشد")

    with source.open("r", encoding="utf-8") as fh:
        scenarios = json.load(fh)

    repo = ScenarioRepository()
    migrated = 0
    for name, value in scenarios.items():
        roles = value.get("roles", []) if isinstance(value, dict) else []
        repo.upsert(
            name=name,
            min_players=value.get("min_players"),
            max_players=value.get("max_players", len(roles)),
            roles=roles,
            config={"legacy_source": "scenarios.json"},
            is_active=True,
        )
        migrated += 1

    print(f"مهاجرت {migrated} سناریو انجام شد.")


if __name__ == "__main__":
    main()
