from repositories.scenario_repository import ScenarioRepository


class ScenarioService:
    """Business rules for authoritative mafia scenarios."""

    def __init__(self, scenario_repository=None):
        self.repo = scenario_repository or ScenarioRepository()

    def list_active(self):
        return self.repo.list_active()

    def get(self, name):
        return self.repo.get_by_name(name)

    def save(self, name, roles, min_players, description=None, config=None, is_active=True):
        roles = list(roles or [])
        max_players = len(roles)
        if not name or not roles:
            raise ValueError("نام و نقش‌های سناریو الزامی است")
        if min_players < 1 or min_players > max_players:
            raise ValueError("حداقل تعداد بازیکنان نامعتبر است")
        return self.repo.upsert(
            name=name.strip(),
            description=description,
            min_players=int(min_players),
            max_players=max_players,
            roles=roles,
            config=config or {},
            is_active=is_active,
        )

    def deactivate(self, name):
        scenario = self.get(name)
        if not scenario:
            return False
        return self.save(
            name=scenario["name"],
            roles=scenario.get("roles") or [],
            min_players=scenario.get("min_players") or 1,
            description=scenario.get("description"),
            config=scenario.get("config") or {},
            is_active=False,
        )
