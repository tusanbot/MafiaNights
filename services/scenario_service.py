class ScenarioService:
    def __init__(self, scenario_repository):
        self.repo = scenario_repository

    async def list_active(self):
        return await self.repo.list_active()

    async def get(self, scenario_id):
        return await self.repo.get_by_id(scenario_id)

    async def save(self, **data):
        return await self.repo.upsert(**data)
