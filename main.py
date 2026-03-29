import asyncio
import difflib
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.command import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import db

load_dotenv()
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')

if not API_TOKEN:
    raise ValueError("❌ Токен не найден! Создайте файл .env и пропишите туда API_TOKEN=ваш_токен")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# FSM Состояния
class ProposalState(StatesGroup):
    waiting_for_name = State()
    waiting_for_category = State()
    waiting_for_resources = State()
    waiting_for_resource_confirmation = State()  # подтверждение нового ресурса

GREETINGS = {"привет", "прив", "хай", "ку", "q", "hi", "hey", "hello", "aloha",
             "здарова", "здравствуй", "добрый день", "доброе утро", "добрый вечер",
             "приветик", "хеллоу", "хело"}

# ============================================================
# БЛОК 1: Команды (Command) — регистрируются первыми
# ============================================================

@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    kb = [[KeyboardButton(text="Что я могу?"), KeyboardButton(text="Мой профиль")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
    await message.reply("Привет! Я справочник по крафту в Arena Breakout Infinite.", reply_markup=keyboard)

@dp.message(Command("profile"))
async def my_profile(message: types.Message):
    score = await db.get_user_score(message.from_user.id)
    text = (
        "👤 <b>Ваш профиль контрибьютора</b>\n\n"
        f"🏆 Ваш рейтинг: <b>{score} баллов</b>\n\n"
        "<i>Как заработать баллы?</i>\n"
        "• Одобренное добавление нового рецепта (/add): <b>+10 баллов</b>\n"
        "• Одобренное редактирование старого рецепта (/edit): <b>+5 баллов</b>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять! Просто напишите название предмета или ресурса для поиска.", reply_markup=ReplyKeyboardRemove())
        return
    await state.clear()
    await message.answer("❌ Действие отменено. Что хотите узнать?", reply_markup=ReplyKeyboardRemove())

@dp.message(Command("add"))
async def add_cmd(message: types.Message, state: FSMContext):
    await state.update_data(p_type="add")
    await state.set_state(ProposalState.waiting_for_name)
    kb = [[KeyboardButton(text="❌ Отмена")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=False)
    await message.answer("Введите точное название нового предмета:", reply_markup=keyboard)

@dp.message(Command("edit"))
async def edit_cmd(message: types.Message, state: FSMContext):
    await state.update_data(p_type="edit")
    await state.set_state(ProposalState.waiting_for_name)
    kb = [[KeyboardButton(text="❌ Отмена")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=False)
    await message.answer("Введите название существующего предмета, который хотите отредактировать:", reply_markup=keyboard)

# ============================================================
# БЛОК 2: Инлайн-кнопки (callback_query)
# ============================================================

@dp.callback_query(F.data.startswith('res_confirm_'))
async def resource_confirm_callback(callback: types.CallbackQuery, state: FSMContext):
    """Пользователь выбрал вариант ресурса из подсказок или подтвердил создание нового."""
    action = callback.data[len('res_confirm_'):]
    data = await state.get_data()
    pending = data.get('pending_resource', {})
    res_name = pending.get('name')
    amount = pending.get('amount')

    if action == 'new':
        # Создать новый ресурс как есть
        chosen_name = res_name
    else:
        # Пользователь выбрал существующий вариант
        chosen_name = action

    r_dict = data.get('recipe', {})
    r_dict[chosen_name.capitalize()] = amount
    await state.update_data(recipe=r_dict, pending_resource={})
    await db.ensure_resource_exists(chosen_name)
    await state.set_state(ProposalState.waiting_for_resources)
    kb = [[KeyboardButton(text="❌ Отмена")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=False)
    await callback.message.answer(
        f"➕ Добавлен: {chosen_name.capitalize()} ({amount} шт). Отправьте следующий ресурс или напишите Готово.",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith('admin_approve_'))
async def admin_approve(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID):
        await callback.answer("У вас нет прав!", show_alert=True)
        return
    prop_id = int(callback.data.split("_")[2])
    success = await db.apply_proposal(prop_id)
    if success:
        await callback.message.edit_text(callback.message.text + "\n\n✅ ОДОБРЕНО И ДОБАВЛЕНО")
        await callback.answer()
        prop = await db.get_proposal(prop_id)
        if prop:
            try:
                await bot.send_message(prop['user_id'], f"🎉 Ваша заявка #{prop_id} на предмет \"{prop['data']['name']}\" одобрена! Вам начислены баллы. Посмотреть: /profile")
            except:
                pass
    else:
        await callback.message.edit_text(callback.message.text + "\n\n⚠️ Заявка уже обработана.")

@dp.callback_query(F.data.startswith('admin_reject_'))
async def admin_reject(callback: types.CallbackQuery):
    if str(callback.from_user.id) != str(ADMIN_ID):
        await callback.answer("У вас нет прав!", show_alert=True)
        return
    prop_id = int(callback.data.split("_")[2])
    await db.update_proposal_status(prop_id, "rejected")
    await callback.message.edit_text(callback.message.text + "\n\n❌ ОТКЛОНЕНО")
    await callback.answer()
    prop = await db.get_proposal(prop_id)
    if prop:
        try:
            await bot.send_message(prop['user_id'], f"😔 Ваша заявка #{prop_id} (предмет: {prop['data']['name']}) была отклонена.")
        except:
            pass

@dp.callback_query(F.data.startswith('cat_'))
async def process_category_callback(callback: types.CallbackQuery):
    idx = int(callback.data[4:])
    cats = await db.get_all_categories()
    cats.append("📦 Без категории")
    if 0 <= idx < len(cats):
        category = cats[idx]
        builder = InlineKeyboardBuilder()
        if category == "📦 Без категории":
            items = await db.get_uncategorized_items()
            icon = "📦"
        else:
            items = await db.get_items_by_category(category)
            icon = category.split(' ')[0]
        for item in items:
            builder.button(text=f"{icon} {item['name'].capitalize()}", callback_data=f"i_{item['id']}")
        builder.button(text="⬅️ Назад", callback_data="back_to_cats")
        builder.adjust(1)
        await callback.message.edit_text(f"<b>{category}:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
        await callback.answer()
    else:
        await callback.answer("Категория не найдена.")

@dp.callback_query(F.data == "back_to_cats")
async def back_to_cats_callback(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    cats = await db.get_all_categories()
    cats.append("📦 Без категории")
    for i, category in enumerate(cats):
        builder.button(text=category, callback_data=f"cat_{i}")
    builder.adjust(1)
    await callback.message.edit_text("<b>Выберите категорию:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith('i_'))
async def process_item_callback(callback: types.CallbackQuery):
    item_id = int(callback.data[2:])
    name = await db.get_item_name_by_id(item_id)
    if name:
        recipe = await db.get_recipe(name)
        if recipe:
            lines = [f"Для создания <b>{name.capitalize()}</b> нужно:"]
            for res, amount in recipe.items():
                lines.append(f"• {res.capitalize()}: {amount} шт.")
            await callback.message.answer("\n".join(lines), parse_mode="HTML")
            await callback.answer()
            return
        used_in = await db.get_used_in(name)
        if used_in:
            lines = [f"Ресурс <b>{name.capitalize()}</b> используется для создания:"]
            for item, amount in used_in.items():
                lines.append(f"• {item.capitalize()} (нужно {amount} шт.)")
            await callback.message.answer("\n".join(lines), parse_mode="HTML")
            await callback.answer()
            return
    await callback.answer("Рецепт не найден в базе данных.")

# ============================================================
# БЛОК 3: FSM-диалог (состояния)
# ============================================================

@dp.message(ProposalState.waiting_for_name)
async def process_proposal_name(message: types.Message, state: FSMContext):
    if message.text.strip().lower() in ["❌ отмена", "отмена", "/cancel"]:
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    await state.update_data(name=message.text.strip())
    cats = await db.get_all_categories()
    kb = [[KeyboardButton(text=c)] for c in cats]
    kb.append([KeyboardButton(text="📦 Без категории")])
    kb.append([KeyboardButton(text="❌ Отмена")])
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
    await state.set_state(ProposalState.waiting_for_category)
    await message.answer("Выберите или введите категорию для этого предмета:", reply_markup=keyboard)

@dp.message(ProposalState.waiting_for_category)
async def process_proposal_category(message: types.Message, state: FSMContext):
    if message.text.strip().lower() in ["❌ отмена", "отмена", "/cancel"]:
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    category = message.text.strip()
    icon = "📦" if "📦" in category else category.split()[0] if category else "📦"
    await state.update_data(category=category, icon=icon, recipe={})
    await state.set_state(ProposalState.waiting_for_resources)
    kb = [[KeyboardButton(text="❌ Отмена")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=False)
    await message.answer(
        "Отправляйте ресурсы по одному в формате `Название: Количество`. Например:\n`Мыло: 2`\n\nКогда добавите все ресурсы, напишите слово **Готово**.",
        parse_mode="Markdown", reply_markup=keyboard
    )

@dp.message(ProposalState.waiting_for_resources)
async def process_proposal_resources(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ["❌ отмена", "отмена", "/cancel"]:
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    if text.lower() == "готово":
        data = await state.get_data()
        recipe = data.get("recipe", {})
        if not recipe:
            await message.answer("Нужно добавить хотя бы один ресурс! Ожидаю `Ресурс: Число`.")
            return
        p_type = data.get("p_type", "add")
        prop_id = await db.create_proposal(message.from_user.id, p_type, data)
        await message.answer("✅ Заявка отправлена на одобрение администратору!", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        if ADMIN_ID:
            summary = f"📦 Заявка #{prop_id} от {message.from_user.id}\n"
            summary += f"Тип: {p_type.upper()}\n"
            summary += f"Предмет: {data['name']}\n"
            summary += f"Категория: {data['category']}\n"
            summary += "Рецепт:\n"
            for r, a in recipe.items():
                summary += f" - {r}: {a}\n"
            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Одобрить", callback_data=f"admin_approve_{prop_id}")
            builder.button(text="❌ Отклонить", callback_data=f"admin_reject_{prop_id}")
            try:
                await bot.send_message(ADMIN_ID, summary, reply_markup=builder.as_markup())
            except Exception as e:
                logging.error(f"Не удалось уведомить админа: {e}")
        return
    parts = text.split(":")
    if len(parts) != 2:
        await message.answer("⚠️ Неверный формат! Напишите `Название: Количество` (например: `Мыло: 2`) или `Готово`.")
        return
    res_name = parts[0].strip()
    try:
        amount = int(parts[1].strip())
        data = await state.get_data()          # ← получаем актуальное состояние
        all_names = await db.get_all_names()
        res_lower = res_name.lower()

        # Ресурс уже есть в БД
        if res_lower in [n.lower() for n in all_names]:
            r_dict = data.get('recipe', {})
            r_dict[res_name.capitalize()] = amount
            await state.update_data(recipe=r_dict)
            await message.answer(f"➕ Добавлен: {res_name.capitalize()} ({amount} шт). Отправьте следующий ресурс или напишите Готово.")
            return

        # Ресурс неизвестен, ищем похожие
        close = difflib.get_close_matches(res_lower, all_names, n=5, cutoff=0.5)
        if len(res_lower) >= 2:
            close = [m for m in close if any(res_lower[i:i+2] in m for i in range(len(res_lower)-1))]

        if close:
            # Есть похожие — предлагаем выбор
            await state.update_data(pending_resource={'name': res_name.capitalize(), 'amount': amount})
            await state.set_state(ProposalState.waiting_for_resource_confirmation)
            builder = InlineKeyboardBuilder()
            for match in close:
                builder.button(text=f"✅ {match.capitalize()}", callback_data=f"res_confirm_{match}")
            builder.button(text=f"➕ Создать «{res_name.capitalize()}»", callback_data="res_confirm_new")
            builder.adjust(1)
            await message.answer(
                f"❓ Ресурс <b>{res_name.capitalize()}</b> не найден в базе. Возможно, вы имели в виду:",
                parse_mode="HTML", reply_markup=builder.as_markup()
            )
        else:
            # Нет похожих — сразу добавляем как новый
            r_dict = data.get('recipe', {})
            r_dict[res_name.capitalize()] = amount
            await state.update_data(recipe=r_dict)
            await db.ensure_resource_exists(res_name)
            await message.answer(f"➕ Новый ресурс «{res_name.capitalize()}» добавлен в базу! Отправьте следующий ресурс или напишите Готово.")
    except ValueError:
        await message.answer("⚠️ Количество должно быть числом! Попробуйте еще раз.")

# ============================================================
# БЛОК 4: Общий обработчик текста (ПОСЛЕДНИЙ)
# ============================================================

@dp.message()
async def crafting_lookup(message: types.Message):
    if not message.text:
        return
    text = message.text.lower().strip()

    # Приветствия
    if text in GREETINGS or any(text.startswith(g + ' ') for g in GREETINGS) or any(text.endswith(' ' + g) for g in GREETINGS):
        await message.answer("👋 Привет! Просто напиши название предмета или ресурса, и я найду рецепт! Если нужен полный список — напиши <i>Список</i>.", parse_mode="HTML")
        return

    # Кнопка профиля
    if text in ["мой профиль", "профиль"]:
        score = await db.get_user_score(message.from_user.id)
        await message.answer(
            f"👤 <b>Ваш профиль контрибьютора</b>\n\n🏆 Рейтинг: <b>{score} баллов</b>\n\n"
            "<i>Как заработать баллы?</i>\n"
            "• /add (новый рецепт): <b>+10 баллов</b>\n"
            "• /edit (редактирование): <b>+5 баллов</b>",
            parse_mode="HTML"
        )
        return

    # Кнопка отмены вне FSM
    if text in ["❌ отмена", "отмена"]:
        await message.answer("Нечего отменять!", reply_markup=ReplyKeyboardRemove())
        return

    # Помощь
    if text in ["что я могу?", "помощь", "/help"]:
        help_text = (
            "<b>Доступные функции:</b>\n\n"
            "🔍 <b>Поиск:</b> Напишите название предмета или ресурса.\n\n"
            "📋 <b>Список:</b> Напишите <i>Список</i> для меню всех предметов.\n\n"
            "✍️ <b>Предложить рецепт:</b> /add — новый, /edit — изменить существующий.\n\n"
            "❌ <b>Отмена:</b> /cancel или кнопка ❌ Отмена во время диалога.\n\n"
            "🛠 <b>Умный поиск:</b> Распознает опечатки."
        )
        await message.answer(help_text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    # Список
    if text in ["список", "листы", "list", "/list"]:
        kb = [[KeyboardButton(text="📦 Предметы")], [KeyboardButton(text="💎 Ресурсы")]]
        keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        await message.answer("Какой список вы хотите посмотреть?", reply_markup=keyboard)
        return

    if text == "📦 предметы":
        builder = InlineKeyboardBuilder()
        cats = await db.get_all_categories()
        cats.append("📦 Без категории")
        for i, category in enumerate(cats):
            builder.button(text=category, callback_data=f"cat_{i}")
        builder.adjust(1)
        await message.answer("<b>Выберите категорию:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
        return

    if text == "💎 ресурсы":
        builder = InlineKeyboardBuilder()
        resources = await db.get_all_resources()
        for res in resources:
            builder.button(text=f"💎 {res['name'].capitalize()}", callback_data=f"i_{res['id']}")
        builder.adjust(1)
        await message.answer("<b>Выберите ресурс:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
        return

    # Поиск предмета
    recipe = await db.get_recipe(text)
    if recipe:
        lines = [f"Для создания <b>{text.capitalize()}</b> нужно:"]
        for res, amount in recipe.items():
            lines.append(f"• {res.capitalize()}: {amount} шт.")
        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    # Поиск ресурса
    used_in = await db.get_used_in(text)
    if used_in:
        lines = [f"Ресурс <b>{text.capitalize()}</b> используется для создания:"]
        for item, amount in used_in.items():
            lines.append(f"• {item.capitalize()} (нужно {amount} шт.)")
        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return

    # Умный поиск (опечатки)
    all_names = await db.get_all_names()
    close_matches = difflib.get_close_matches(text, all_names, n=8, cutoff=0.4)
    if len(text) >= 2:
        close_matches = [m for m in close_matches if any(text[i:i+2] in m for i in range(len(text)-1))]
    if close_matches:
        kb = [[KeyboardButton(text=match.capitalize())] for match in close_matches]
        keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        await message.answer(f"Не удалось найти '{message.text}'. Возможно, вы имели в виду что-то из этого?", reply_markup=keyboard)
    else:
        await message.answer(f"Не удалось найти '{message.text}'. Попробуйте /add или /edit, чтобы предложить рецепт!", reply_markup=ReplyKeyboardRemove())

async def main():
    await db.init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
