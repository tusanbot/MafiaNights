import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TurnMigrationContractTests(unittest.TestCase):
    def test_migration_adapter_exposes_persistent_legacy_start(self):
        tree = ast.parse((ROOT / "runtime" / "migration_adapter.py").read_text(encoding="utf-8"))
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("persist_legacy_turn_start", names)
        self.assertIn("ensure_legacy_game", names)

    def test_legacy_addon_bridge_wraps_start_turn(self):
        tree = ast.parse((ROOT / "mafia_addons.py").read_text(encoding="utf-8"))
        source = (ROOT / "mafia_addons.py").read_text(encoding="utf-8")
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("_install_legacy_turn_bridge", names)
        self.assertIn("bridged_start_turn", source)
        self.assertIn("persist_legacy_turn_start", source)

    def test_bridge_is_installed_from_register(self):
        source = (ROOT / "mafia_addons.py").read_text(encoding="utf-8")
        register_start = source.index("    def register(")
        bridge_call = source.index("self._install_legacy_turn_bridge()", register_start)
        self.assertGreater(bridge_call, register_start)


if __name__ == "__main__":
    unittest.main()
