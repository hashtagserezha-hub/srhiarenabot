import asyncio
import difflib
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.command import Command
from recipes import CRAFTING_RECIPES, ITEM_CATEGORIES
# Вставьте ваш токен
API_TOKEN = '8152271319:AAG5ypu-H2vA-mVtsrg-MjJjhXIe4LToDS8'
# Настройка логирования
logging.basicConfig(level=logging.INFO)
# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
# Обработчик команды /start
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    kb = [[KeyboardButton(text="Что я могу?")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
    await message.reply("Привет! Я создан для того, чтобы помочь тебе с крафтом в игре Arena Breakout Infinite.", reply_markup=keyboard)
# Подготовка индексов для команд-шорткатов
UNIQUE_NAMES = set()
for item, recipe in CRAFTING_RECIPES.items():
    UNIQUE_NAMES.add(item)
    UNIQUE_NAMES.update(recipe.keys())
INDEX_TO_NAME = sorted(list(UNIQUE_NAMES))
NAME_TO_INDEX = {name: i for i, name in enumerate(INDEX_TO_NAME)}

CATEGORY_LIST = list(ITEM_CATEGORIES.keys())
_k_items = set()
for items in ITEM_CATEGORIES.values():
    _k_items.update(items)
if any(item not in _k_items for item in CRAFTING_RECIPES.keys()):
    CATEGORY_LIST.append("📦 Без категории")

# Обработчик инлайн-кнопок (для списков)
@dp.callback_query(F.data.startswith('cat_'))
async def process_category_callback(callback: types.CallbackQuery):
    idx = int(callback.data[4:])
    if 0 <= idx < len(CATEGORY_LIST):
        category = CATEGORY_LIST[idx]
        builder = InlineKeyboardBuilder()
        
        if category == "📦 Без категории":
            known = set()
            for items in ITEM_CATEGORIES.values():
                known.update(items)
            items_to_show = [item for item in CRAFTING_RECIPES.keys() if item not in known]
            icon = "📦"
        else:
            items_to_show = ITEM_CATEGORIES[category]
            icon = category.split(' ')[0]
            
        for item in sorted(items_to_show):
            item_idx = NAME_TO_INDEX[item]
            builder.button(text=f"{icon} {item.capitalize()}", callback_data=f"i_{item_idx}")
            
        builder.button(text="⬅️ Назад", callback_data="back_to_cats")
        builder.adjust(1)
        
        await callback.message.edit_text(f"<b>{category}:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
        await callback.answer()
    else:
        await callback.answer("Категория не найдена.")

@dp.callback_query(F.data == "back_to_cats")
async def back_to_cats_callback(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for i, category in enumerate(CATEGORY_LIST):
        builder.button(text=category, callback_data=f"cat_{i}")
    builder.adjust(1)
    await callback.message.edit_text("<b>Выберите категорию:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith('i_'))
async def process_item_callback(callback: types.CallbackQuery):
    idx = int(callback.data[2:])
    if 0 <= idx < len(INDEX_TO_NAME):
        text = INDEX_TO_NAME[idx]
        
        if text in CRAFTING_RECIPES:
            recipe = CRAFTING_RECIPES[text]
            response_lines = [f"Для создания <b>{text.capitalize()}</b> нужно:"]
            for res, amount in recipe.items():
                response_lines.append(f"• {res.capitalize()}: {amount} шт.")
            await callback.message.answer("\n".join(response_lines), parse_mode="HTML")
            await callback.answer()
            return
            
        used_in = {}
        for item, recipe in CRAFTING_RECIPES.items():
            if text in recipe:
                used_in[item] = recipe[text]
                
        if used_in:
            response_lines = [f"Ресурс <b>{text.capitalize()}</b> используется для создания:"]
            for item, amount in used_in.items():
                response_lines.append(f"• {item.capitalize()} (нужно {amount} шт.)")
            await callback.message.answer("\n".join(response_lines), parse_mode="HTML")
            await callback.answer()
            return

    await callback.answer("Этот предмет не найден.")

# Обработчик запросов крафта
@dp.message()
async def crafting_lookup(message: types.Message):
    if not message.text:
        return
        
    text = message.text.lower().strip()
    
    # Обработка шорткатов-команд
    if text.startswith("/i") and text[2:].isdigit():
        idx = int(text[2:])
        if 0 <= idx < len(INDEX_TO_NAME):
            text = INDEX_TO_NAME[idx]
        else:
            await message.answer("Этот код устарел или неверен.")
            return
            
    # Команда помощи
    if text in ["что я могу?", "помощь", "/help"]:
        help_text = (
            "<b>Доступные функции:</b>\n\n"
            "🔍 <b>Поиск рецепта:</b> Напишите название предмета (например, <i>Пилюля</i>), и я расскажу, какие ресурсы нужны для его крафта.\n\n"
            "🔍 <b>Поиск ресурса:</b> Напишите название ресурса (например, <i>Антисептик</i>), и я покажу, для создания каких предметов он требуется.\n\n"
            "📋 <b>Полные списки:</b> Напишите <i>Список</i> или нажмите /list, чтобы увидеть все доступные в базе предметы и ресурсы.\n\n"
            "🛠 <b>Умный поиск:</b> Если вы опечатаетесь, я найду похожие варианты и предложу их в виде кнопок!"
        )
        await message.answer(help_text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return
        
    # Обработка запросов списков
    if text in ["список", "листы", "list", "/list"]:
        kb = [[KeyboardButton(text="📦 Предметы")], [KeyboardButton(text="💎 Ресурсы")]]
        keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        await message.answer("Какой список вы хотите посмотреть?", reply_markup=keyboard)
        return
        
    if text == "📦 предметы":
        builder = InlineKeyboardBuilder()
        for i, category in enumerate(CATEGORY_LIST):
            builder.button(text=category, callback_data=f"cat_{i}")
        builder.adjust(1)
        await message.answer("<b>Выберите категорию:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
        return
        
    if text == "💎 ресурсы":
        builder = InlineKeyboardBuilder()
        res_set = set()
        for r in CRAFTING_RECIPES.values():
            res_set.update(r.keys())
            
        for res in sorted(list(res_set)):
            idx = NAME_TO_INDEX[res]
            builder.button(text=f"💎 {res.capitalize()}", callback_data=f"i_{idx}")
            
        builder.adjust(1)
        await message.answer("<b>Выберите ресурс:</b>", parse_mode="HTML", reply_markup=builder.as_markup())
        return
    
    # 1. Поиск предмета (чтобы узнать из чего он крафтится)
    if text in CRAFTING_RECIPES:
        recipe = CRAFTING_RECIPES[text]
        response_lines = [f"Для создания <b>{text.capitalize()}</b> нужно:"]
        for res, amount in recipe.items():
            response_lines.append(f"• {res.capitalize()}: {amount} шт.")
        await message.answer("\n".join(response_lines), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return
        
    # 2. Поиск ресурса (где он используется)
    used_in = {}
    for item, recipe in CRAFTING_RECIPES.items():
        if text in recipe:
            used_in[item] = recipe[text]
            
    if used_in:
        response_lines = [f"Ресурс <b>{text.capitalize()}</b> используется для создания:"]
        for item, amount in used_in.items():
            response_lines.append(f"• {item.capitalize()} (нужно {amount} шт.)")
        await message.answer("\n".join(response_lines), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        return
        
    # 3. Ничего не найдено
    close_matches = difflib.get_close_matches(text, INDEX_TO_NAME, n=8, cutoff=0.4)
    
    if len(text) >= 2:
        close_matches = [m for m in close_matches if any(text[i:i+2] in m for i in range(len(text)-1))]
    
    if close_matches:
        kb = [[KeyboardButton(text=match.capitalize())] for match in close_matches]
        keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        await message.answer(f"Не удалось найти '{message.text}'. Возможно, вы имели в виду что-то из этого?", reply_markup=keyboard)
    else:
        await message.answer(f"Не удалось найти рецепт для предмета или ресурса '{message.text}'.", reply_markup=ReplyKeyboardRemove())
# Функция запуска бота
async def main():
    await dp.start_polling(bot)
if __name__ == '__main__':
    asyncio.run(main())