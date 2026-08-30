class ScenarioService:
    def __init__(self, scenario_repository):
        self.repo = scenario_repository

    def list_active(self):
        return self.repo.list_active()

    def get(self, name):
        return self.repo.get_by_name(name)

    def save(self, **data):
        return self.repo.upsert(**data)
