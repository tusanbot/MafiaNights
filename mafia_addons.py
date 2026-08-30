# mafia_addons.py
import json
import os
import copy
import logging
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

SETTINGS_FILE = "addons_settings.json"
LOG_TAG = "MafiaAddons"
DEFAULT_GROUP_SETTINGS = {
    "security": {"control_speech": True, "delete_out_of_turn": True},
    "next": {"anti_spam": True, "allow_players_next": True, "allow_moderator_next": True},
    "auto_start": {"enabled": False},
    "color": {"primary": True, "challenge": True, "timer_prefix": ""}
}

class MafiaAddons:
    def __init__(self, bot):
        self.bot = bot
        self._all_settings = {}
        self.group_id = None
        self.moderator_id = None
        self.settings = copy.deepcopy(DEFAULT_GROUP_SETTINGS)
        self._legacy_turn_bridge_installed = False
        self._load_from_file()

    def _load_from_file(self):
        if not os.path.exists(SETTINGS_FILE):
            self._all_settings = {}
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._all_settings = data if isinstance(data, dict) else {}
        except Exception as e:
            logging.exception("%s: خطا در خواندن تنظیمات: %s", LOG_TAG, e)
            self._all_settings = {}

    def _save_to_file(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._all_settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.exception("%s: خطا در نوشتن تنظیمات: %s", LOG_TAG, e)

    def _group_key(self, group_id):
        return str(group_id)

    def get_group_settings(self, group_id):
        key = self._group_key(group_id)
        s = self._all_settings.get(key)
        if s is None:
            s = copy.deepcopy(DEFAULT_GROUP_SETTINGS)
            self._all_settings[key] = s
            self._save_to_file()
        return s

    def set_group_settings(self, group_id, settings_dict):
        key = self._group_key(group_id)
        self._all_settings[key] = settings_dict
        if self.group_id and self._group_key(self.group_id) == key:
            self.settings = settings_dict
        self._save_to_file()

    def register(self, *, moderator_id, group_id):
        try:
            self.moderator_id = moderator_id
            self.group_id = group_id
            self.settings = self.get_group_settings(group_id)
            self.settings.setdefault("next", {})
            self.settings["next"].setdefault("anti_spam", True)
            self.settings["next"].setdefault("allow_players_next", True)
            self.settings["next"].setdefault("allow_moderator_next", True)
            self.settings.setdefault("security", {})
            self.settings["security"].setdefault("control_speech", True)
            self.settings["security"].setdefault("delete_out_of_turn", True)
            self.settings.setdefault("auto_start", {})
            self.settings["auto_start"].setdefault("enabled", False)
            self.settings.setdefault("color", {})
            self.settings["color"].setdefault("primary", True)
            self.settings["color"].setdefault("challenge", True)
            self.settings["color"].setdefault("timer_prefix", "")
            self._all_settings[self._group_key(group_id)] = self.settings
            self._save_to_file()
            self._install_legacy_turn_bridge()
        except Exception as e:
            logging.exception("%s: خطا در register افزونه: %s", LOG_TAG, e)

    def _install_legacy_turn_bridge(self):
        if self._legacy_turn_bridge_installed:
            return
        try:
            import __main__ as legacy
            original = getattr(legacy, "start_turn", None)
            if original is None or getattr(original, "_persistent_bridge", False):
                return
            from runtime.migration_adapter import MigrationAdapter
            adapter = MigrationAdapter()

            async def bridged_start_turn(seat, duration=120, is_challenge=False):
                group_id = getattr(legacy, "group_chat_id", None)
                if not group_id:
                    return await original(seat, duration=duration, is_challenge=is_challenge)
                try:
                    await adapter.persist_legacy_turn_start(
                        int(group_id), seat=int(seat), duration_seconds=int(duration),
                        is_challenge=bool(is_challenge),
                        turn_order=list(getattr(legacy, "turn_order", []) or []),
                        current_turn_index=int(getattr(legacy, "current_turn_index", 0)),
                        players=dict(getattr(legacy, "players", {}) or {}),
                        player_slots=dict(getattr(legacy, "player_slots", {}) or {}),
                        moderator_id=getattr(legacy, "moderator_id", None),
                        scenario_id=getattr(legacy, "selected_scenario", None),
                    )
                except Exception:
                    logging.exception("%s: persistent turn start failed", LOG_TAG)
                    bot = getattr(legacy, "bot", self.bot)
                    await bot.send_message(int(group_id), "⚠️ ثبت پایدار نوبت انجام نشد؛ نوبت شروع نشد.")
                    return
                return await original(seat, duration=duration, is_challenge=is_challenge)

            bridged_start_turn._persistent_bridge = True
            legacy.start_turn = bridged_start_turn
            self._legacy_turn_bridge_installed = True
            logging.info("%s: legacy start_turn is now persistence-backed", LOG_TAG)
        except Exception:
            logging.exception("%s: failed to install legacy turn bridge", LOG_TAG)

    def setup_handlers(self, dp):
        dp.register_callback_query_handler(self._open_menu_handler, lambda c: c.data == "addons_menu")
        dp.register_callback_query_handler(self._open_security_menu, lambda c: c.data == "addons_security")
        dp.register_callback_query_handler(self._open_next_menu, lambda c: c.data == "addons_next")
        dp.register_callback_query_handler(self._open_auto_menu, lambda c: c.data == "addons_auto")
        dp.register_callback_query_handler(self._open_color_menu, lambda c: c.data == "addons_color")
        dp.register_callback_query_handler(self._toggle_control_speech, lambda c: c.data == "toggle_control_speech")
        dp.register_callback_query_handler(self._toggle_delete_messages, lambda c: c.data == "toggle_delete_messages")
        dp.register_callback_query_handler(self._toggle_next_antispam, lambda c: c.data == "toggle_next_antispam")
        dp.register_callback_query_handler(self._toggle_autostart, lambda c: c.data == "toggle_autostart")
        dp.register_callback_query_handler(self._toggle_color_primary, lambda c: c.data == "toggle_color_primary")
        dp.register_callback_query_handler(self._toggle_color_challenge, lambda c: c.data == "toggle_color_challenge")
        dp.register_callback_query_handler(self._back_to_addons_menu, lambda c: c.data == "panel_back")
        dp.register_callback_query_handler(self._back_to_main, lambda c: c.data == "addons_menu_back")

    async def open_addons_menu(self, callback):
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔐 امنیت بازی", callback_data="addons_security"))
        kb.add(InlineKeyboardButton("⏭ مدیریت نکست", callback_data="addons_next"))
        kb.add(InlineKeyboardButton("▶ شروع خودکار", callback_data="addons_auto"))
        kb.add(InlineKeyboardButton("🎨 رنگ‌بندی پیام‌ها", callback_data="addons_color"))
        kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="panel_back"))
        try:
            await callback.message.edit_text("⚙️ <b>امکانات اضافه</b>\n\nیکی از بخش‌ها را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        except Exception:
            try: await callback.message.answer("⚙️ <b>امکانات اضافه</b>\n\nیکی از بخش‌ها را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
            except Exception: pass

    async def _open_menu_handler(self, callback): await self.open_addons_menu(callback)

    async def _open_security_menu(self, callback):
        if self.group_id: self.settings = self.get_group_settings(self.group_id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(f"🟦 کنترل نوبت صحبت: {'فعال' if self.settings['security'].get('control_speech', True) else 'غیرفعال'}", callback_data="toggle_control_speech"))
        kb.add(InlineKeyboardButton(f"🗑 حذف پیام‌های خارج نوبت: {'فعال' if self.settings['security'].get('delete_out_of_turn', True) else 'غیرفعال'}", callback_data="toggle_delete_messages"))
        kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="panel_back"))
        try: await callback.message.edit_text("🔐 <b>امنیت بازی</b>\nگزینه‌های زیر را مدیریت کنید:", reply_markup=kb, parse_mode="HTML")
        except Exception: pass

    async def _open_next_menu(self, callback):
        if self.group_id: self.settings = self.get_group_settings(self.group_id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(f"⏭ ضد اسپم نکست: {'فعال' if self.settings['next'].get('anti_spam', True) else 'غیرفعال'}", callback_data="toggle_next_antispam"))
        kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="panel_back"))
        try: await callback.message.edit_text("⏭ <b>مدیریت نکست</b>", reply_markup=kb, parse_mode="HTML")
        except Exception: pass

    async def _open_auto_menu(self, callback):
        if self.group_id: self.settings = self.get_group_settings(self.group_id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(f"▶ Auto Start: {'فعال' if self.settings['auto_start'].get('enabled', False) else 'غیرفعال'}", callback_data="toggle_autostart"))
        kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="panel_back"))
        try: await callback.message.edit_text("▶ <b>شروع خودکار دور جدید</b>", reply_markup=kb, parse_mode="HTML")
        except Exception: pass

    async def _open_color_menu(self, callback):
        if self.group_id: self.settings = self.get_group_settings(self.group_id)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(f"🎨 رنگ نوبت اصلی: {'فعال' if self.settings['color'].get('primary', True) else 'غیرفعال'}", callback_data="toggle_color_primary"))
        kb.add(InlineKeyboardButton(f"🟥 رنگ نوبت چالش: {'فعال' if self.settings['color'].get('challenge', True) else 'غیرفعال'}", callback_data="toggle_color_challenge"))
        kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="panel_back"))
        try: await callback.message.edit_text("🎨 <b>رنگ‌بندی پیام‌ها</b>", reply_markup=kb, parse_mode="HTML")
        except Exception: pass

    async def _toggle_control_speech(self, callback):
        if not self.group_id or callback.from_user.id != self.moderator_id:
            await callback.answer("⚠️ فقط گرداننده می‌تواند این تنظیمات را تغییر دهد.", show_alert=True); return
        self.settings['security']['control_speech'] = not self.settings['security'].get('control_speech', True); self._all_settings[self._group_key(self.group_id)] = self.settings; self._save_to_file(); await callback.answer("✔️ وضعیت ذخیره شد."); await self._open_security_menu(callback)

    async def _toggle_delete_messages(self, callback):
        if not self.group_id or callback.from_user.id != self.moderator_id:
            await callback.answer("⚠️ فقط گرداننده می‌تواند این تنظیمات را تغییر دهد.", show_alert=True); return
        self.settings['security']['delete_out_of_turn'] = not self.settings['security'].get('delete_out_of_turn', True); self._all_settings[self._group_key(self.group_id)] = self.settings; self._save_to_file(); await callback.answer("✔️ وضعیت ذخیره شد."); await self._open_security_menu(callback)

    async def _toggle_next_antispam(self, callback):
        if not self.group_id or callback.from_user.id != self.moderator_id:
            await callback.answer("⚠️ فقط گرداننده می‌تواند این تنظیمات را تغییر دهد.", show_alert=True); return
        self.settings['next']['anti_spam'] = not self.settings['next'].get('anti_spam', True); self._all_settings[self._group_key(self.group_id)] = self.settings; self._save_to_file(); await callback.answer("✔️ وضعیت ذخیره شد."); await self._open_next_menu(callback)

    async def _toggle_autostart(self, callback):
        if not self.group_id or callback.from_user.id != self.moderator_id:
            await callback.answer("⚠️ فقط گرداننده می‌تواند این تنظیمات را تغییر دهد.", show_alert=True); return
        self.settings['auto_start']['enabled'] = not self.settings['auto_start'].get('enabled', False); self._all_settings[self._group_key(self.group_id)] = self.settings; self._save_to_file(); await callback.answer("✔️ وضعیت ذخیره شد."); await self._open_auto_menu(callback)

    async def _toggle_color_primary(self, callback):
        if not self.group_id or callback.from_user.id != self.moderator_id:
            await callback.answer("⚠️ فقط گرداننده می‌تواند این تنظیمات را تغییر دهد.", show_alert=True); return
        self.settings['color']['primary'] = not self.settings['color'].get('primary', True); self._all_settings[self._group_key(self.group_id)] = self.settings; self._save_to_file(); await callback.answer("✔️ وضعیت ذخیره شد."); await self._open_color_menu(callback)

    async def _toggle_color_challenge(self, callback):
        if not self.group_id or callback.from_user.id != self.moderator_id:
            await callback.answer("⚠️ فقط گرداننده می‌تواند این تنظیمات را تغییر دهد.", show_alert=True); return
        self.settings['color']['challenge'] = not self.settings['color'].get('challenge', True); self._all_settings[self._group_key(self.group_id)] = self.settings; self._save_to_file(); await callback.answer("✔️ وضعیت ذخیره شد."); await self._open_color_menu(callback)

    # Public compatibility API expected by main.py
    async def menu_security(self, callback): return await self._open_security_menu(callback)
    async def menu_next(self, callback): return await self._open_next_menu(callback)
    async def menu_auto(self, callback): return await self._open_auto_menu(callback)
    async def menu_color(self, callback): return await self._open_color_menu(callback)
    def toggle(self, section, key):
        if self.group_id:
            self.settings = self.get_group_settings(self.group_id)
        self.settings.setdefault(section, {})
        self.settings[section][key] = not self.settings[section].get(key, False)
        if self.group_id:
            self._all_settings[self._group_key(self.group_id)] = self.settings
            self._save_to_file()
        return self.settings[section][key]

    async def _back_to_addons_menu(self, callback): await self.open_addons_menu(callback)
    async def _back_to_main(self, callback): await self.open_addons_menu(callback)

    def is_control_speech_enabled(self): return self.settings.get("security", {}).get("control_speech", True)
    def is_delete_out_of_turn_enabled(self): return self.settings.get("security", {}).get("delete_out_of_turn", True)
    def is_next_antispam_enabled(self): return self.settings.get("next", {}).get("anti_spam", True)
    def is_player_next_allowed(self): return self.settings.get("next", {}).get("allow_players_next", True)
    def is_moderator_next_allowed(self): return self.settings.get("next", {}).get("allow_moderator_next", True)
    def is_auto_start_enabled(self): return self.settings.get("auto_start", {}).get("enabled", False)
    def is_color_primary(self): return self.settings.get("color", {}).get("primary", True)
    def is_color_challenge(self): return self.settings.get("color", {}).get("challenge", True)
    def get_timer_prefix(self): return self.settings.get("color", {}).get("timer_prefix", "")
    def ensure_defaults_for_group(self, group_id):
        key = self._group_key(group_id)
        if key not in self._all_settings:
            self._all_settings[key] = copy.deepcopy(DEFAULT_GROUP_SETTINGS); self._save_to_file()
    def export_current_settings(self): return self.settings
