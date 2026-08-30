"""Deterministic registration for the clean feature-parity surface."""
from __future__ import annotations

from runtime.feature_parity_v2 import FeatureParityV2
from runtime.feature_parity import AddScenarioParity


class FeatureParityV3(FeatureParityV2):
    """Feature parity without legacy duplicate callback registrations."""

    def register(self):
        dp = self.app.dp
        dp.register_callback_query_handler(self.open_panel, lambda c: c.data == "fp:panel")
        dp.register_callback_query_handler(self.list_players, lambda c: c.data == "fp:list_players")
        dp.register_callback_query_handler(self.resend_roles, lambda c: c.data == "fp:resend_roles")
        dp.register_callback_query_handler(self.remove_player, lambda c: c.data == "fp:remove_player")
        dp.register_callback_query_handler(self.remove_confirm, lambda c: c.data.startswith("fp:remove:"))
        dp.register_callback_query_handler(self.replace_player, lambda c: c.data == "fp:replace_player")
        dp.register_callback_query_handler(self.choose_replace_seat, lambda c: c.data.startswith("fp:replace-sub:"))
        dp.register_callback_query_handler(self.replace_confirm, lambda c: c.data.startswith("fp:replace:"))
        dp.register_callback_query_handler(self.revive_player, lambda c: c.data == "fp:revive_player")
        dp.register_callback_query_handler(self.revive_confirm, lambda c: c.data.startswith("fp:revive:"))
        dp.register_callback_query_handler(self.challenge_request, lambda c: c.data.startswith("fp:challenge:"))
        dp.register_callback_query_handler(self.challenge_status, lambda c: c.data in {"fp:challenge_status", "challenge_status"})
        dp.register_callback_query_handler(self.challenge_response, lambda c: c.data.startswith("fp:accept:") or c.data.startswith("fp:reject:") or c.data.startswith("accept_before_") or c.data.startswith("accept_after_") or c.data.startswith("reject_"))
        dp.register_callback_query_handler(self.moderator_menu, lambda c: c.data == "fp:moderator")
        dp.register_callback_query_handler(self.set_moderator, lambda c: c.data.startswith("fp:setmod:"))
        dp.register_callback_query_handler(lambda c: self.toggle_next(c, "allow_players_next"), lambda c: c.data == "fp:toggle_player_next")
        dp.register_callback_query_handler(lambda c: self.toggle_next(c, "allow_moderator_next"), lambda c: c.data == "fp:toggle_mod_next")
        dp.register_callback_query_handler(lambda c: self.toggle_next(c, "anti_spam"), lambda c: c.data == "fp:toggle_next_antispam")
        dp.register_callback_query_handler(self.cancel, lambda c: c.data == "fp:cancel")
        dp.register_callback_query_handler(self.scenario_menu, lambda c: c.data == "fp:scenarios")
        dp.register_callback_query_handler(self.add_scenario_start, lambda c: c.data == "fp:add_scenario")
        dp.register_callback_query_handler(self.remove_scenario, lambda c: c.data == "fp:remove_scenario")
        dp.register_callback_query_handler(self.delete_scenario, lambda c: c.data.startswith("fp:delete_scenario:"))
        dp.register_message_handler(self.add_scenario_name, state=AddScenarioParity.waiting_for_name)
        dp.register_message_handler(self.add_scenario_roles, state=AddScenarioParity.waiting_for_roles)
        dp.register_message_handler(self.add_scenario_min, state=AddScenarioParity.waiting_for_min_players)
        dp.register_message_handler(self.add_substitute_message, lambda m: (m.text or "").strip().lower() in {"جایگزین", "/sub"})
        dp.register_message_handler(self.seat_command, lambda m: (m.text or "").strip() == "صندلی من")
        dp.register_message_handler(self.seats_command, lambda m: (m.text or "").strip() == "لیست صندلی")
        dp.register_message_handler(self.role_command, lambda m: (m.text or "").strip() == "نقش من")
        dp.register_message_handler(self.status_command, lambda m: (m.text or "").strip() == "وضعیت بازی")
        dp.register_message_handler(self.players_command, lambda m: (m.text or "").strip() == "لیست بازیکنان")
        dp.register_message_handler(self.tag_list, lambda m: (m.text or "").strip() == "تگ لیست")
        dp.register_message_handler(self.tag_admins, lambda m: (m.text or "").strip() == "تگ ادمین")
        dp.register_callback_query_handler(self.open_panel, lambda c: c.data == "manage_game")
        dp.register_callback_query_handler(self.scenario_menu, lambda c: c.data == "manage_scenarios")
        dp.register_callback_query_handler(self.resend_roles, lambda c: c.data == "resend_roles")
        dp.register_callback_query_handler(self.remove_player, lambda c: c.data == "remove_player")
        dp.register_callback_query_handler(self.replace_player, lambda c: c.data == "replace_player")
        dp.register_callback_query_handler(self.revive_player, lambda c: c.data == "player_birthday")
