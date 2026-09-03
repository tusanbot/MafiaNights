"""Make /cancel authoritative while an admin scenario wizard is active."""
from aiogram import types
from aiogram.dispatcher import FSMContext
from runtime.admin_menus_v2 import ScenarioStates


async def cancel_any(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ عملیات لغو شد.")


def install(app):
    # Register for the concrete scenario states and move each handler to the front.
    for state in (ScenarioStates.add_name, ScenarioStates.add_roles, ScenarioStates.add_min,
                  ScenarioStates.edit_roles, ScenarioStates.edit_min):
        app.dp.register_message_handler(cancel_any, commands=["cancel"], state=state)
    handlers = getattr(app.dp.message_handlers, "handlers", [])
    for i in range(len(handlers) - 1, -1, -1):
        h = handlers[i]
        if getattr(getattr(h, "handler", None), "__name__", "") == "cancel_any":
            handlers.insert(0, handlers.pop(i))
    return cancel_any
