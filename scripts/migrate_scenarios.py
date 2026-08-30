"""One-time, idempotent migration of scenarios.json into mafia_scenarios.

Usage: python scripts/migrate_scenarios.py
Requires DATABASE_URL and trusted server-side database access.
"""

import json
from pathlib import Path

from repositories.scenario_repository import ScenarioRepository


def main():
    source = Path(__file__).resolve().parents[1] / "scenarios.json"
    if not source.exists():
        raise SystemExit("scenarios.json پیدا نشد")

    scenarios = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(scenarios, dict):
        raise SystemExit("ساختار scenarios.json نامعتبر است")

    repo = ScenarioRepository()
    migrated = 0
    skipped = 0
    for name, value in scenarios.items():
        if not isinstance(value, dict):
            print(f"SKIP: {name}: ساختار سناریو نامعتبر است")
            skipped += 1
            continue

        roles = list(value.get("roles") or [])
        minimum = int(value.get("min_players") or len(roles))
        maximum = int(value.get("max_players") or len(roles))
        if not name or not roles or minimum < 1 or maximum < minimum or maximum != len(roles):
            print(f"SKIP: {name}: محدوده بازیکنان/نقش‌ها نامعتبر است")
            skipped += 1
            continue

        repo.upsert(
            name=name.strip(),
            description=value.get("description"),
            min_players=minimum,
            max_players=maximum,
            roles=roles,
            config={"legacy_source": "scenarios.json"},
            is_active=True,
        )
        migrated += 1
        print(f"OK: {name} ({minimum}-{maximum})")

    print(f"مهاجرت: {migrated} | ردشده: {skipped} | کل: {len(scenarios)}")


if __name__ == "__main__":
    main()
