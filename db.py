import aiosqlite
import json
import logging
import time

DB_NAME = 'database.db'

# ============================================================
# Простой кэш с TTL (время жизни 5 минут)
# ============================================================
_CACHE: dict = {}
CACHE_TTL = 3600  # секунд

def _cache_get(key: str):
    entry = _CACHE.get(key)
    if entry and time.monotonic() - entry['ts'] < CACHE_TTL:
        return entry['data']
    return None

def _cache_set(key: str, data):
    _CACHE[key] = {'data': data, 'ts': time.monotonic()}

def invalidate_cache():
    """Cбрасывает весь кэш. Вызывать при любом изменении данных."""
    _CACHE.clear()
    logging.info("🔁 Кэш инвалидирован.")

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT,
                icon TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                amount INTEGER NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                data TEXT,
                status TEXT DEFAULT 'pending'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                score INTEGER DEFAULT 0
            )
        ''')
        await db.commit()

async def get_user_score(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT score FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def ensure_resource_exists(resource_name: str):
    """Добавляет ресурс в items если его там ещё нет."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            'INSERT OR IGNORE INTO items (name, category, icon) VALUES (?, ?, ?)',
            (resource_name.lower().strip(), "💎 Ресурсы и прочее", "💎")
        )
        if cursor.rowcount > 0:
            await db.commit()
            invalidate_cache()  # новый ресурс появился, сбрасываем
        else:
            await db.commit()

async def get_all_categories():
    cached = _cache_get('categories')
    if cached is not None:
        return cached
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT DISTINCT category FROM items WHERE category IS NOT NULL AND category != "📦 Без категории" AND category != ""') as cursor:
            rows = await cursor.fetchall()
            result = [row[0] for row in rows]
            _cache_set('categories', result)
            return result

async def get_items_by_category(category):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT id, name, icon FROM items WHERE category = ? ORDER BY name', (category,)) as cursor:
            rows = await cursor.fetchall()
            return [{"id": row[0], "name": row[1], "icon": row[2]} for row in rows]

async def get_uncategorized_items():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT id, name, icon FROM items WHERE category IS NULL OR category = "" OR category = "📦 Без категории" ORDER BY name') as cursor:
            rows = await cursor.fetchall()
            return [{"id": row[0], "name": row[1], "icon": row[2]} for row in rows]

async def get_all_resources():
    cached = _cache_get('resources')
    if cached is not None:
        return cached
    async with aiosqlite.connect(DB_NAME) as db:
        query = '''
            SELECT i.id, i.name 
            FROM items i 
            JOIN (SELECT DISTINCT resource_name FROM recipes) r ON i.name = r.resource_name 
            ORDER BY i.name
        '''
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
            result = [{"id": row[0], "name": row[1]} for row in rows]
            _cache_set('resources', result)
            return result

async def get_recipe(item_name: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT resource_name, amount FROM recipes WHERE item_name = ?', (item_name,)) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows} if rows else None

async def get_used_in(resource_name: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT item_name, amount FROM recipes WHERE resource_name = ?', (resource_name,)) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows} if rows else None

async def get_item_name_by_id(item_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT name FROM items WHERE id = ?', (item_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_all_names():
    cached = _cache_get('all_names')
    if cached is not None:
        return cached
    names = set()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT name FROM items') as cursor:
            for row in await cursor.fetchall():
                names.add(row[0])
        async with db.execute('SELECT DISTINCT resource_name FROM recipes') as cursor:
            for row in await cursor.fetchall():
                names.add(row[0])
    result = sorted(list(names))
    _cache_set('all_names', result)
    return result

async def create_proposal(user_id: int, p_type: str, data: dict):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT INTO proposals (user_id, type, data) VALUES (?, ?, ?)',
                         (user_id, p_type, json.dumps(data, ensure_ascii=False)))
        await db.commit()
        async with db.execute('SELECT last_insert_rowid()') as cursor:
            row = await cursor.fetchone()
            return row[0]

async def get_proposal(proposal_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id, type, data, status FROM proposals WHERE id = ?', (proposal_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"user_id": row[0], "type": row[1], "data": json.loads(row[2]), "status": row[3]}
            return None

async def update_proposal_status(proposal_id: int, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE proposals SET status = ? WHERE id = ?', (status, proposal_id))
        await db.commit()

async def apply_proposal(proposal_id: int):
    proposal = await get_proposal(proposal_id)
    if not proposal or proposal['status'] != 'pending':
        return False
        
    data = proposal['data']
    item_name = data['name'].lower()
    category = data.get('category', '📦 Без категории')
    icon = data.get('icon', '📦')
    recipe = data.get('recipe', {})
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('INSERT OR REPLACE INTO items (name, category, icon) VALUES (?, ?, ?)',
                         (item_name, category, icon))
        await db.execute('DELETE FROM recipes WHERE item_name = ?', (item_name,))
        
        for res_name, amount in recipe.items():
            res_name = res_name.lower().strip()
            # Убедимся, что ресурс есть в items, чтобы у него был ID для инлайн-кнопок
            await db.execute('INSERT OR IGNORE INTO items (name, category, icon) VALUES (?, ?, ?)',
                             (res_name, "💎 Ресурсы и прочее", "💎"))
                             
            await db.execute('INSERT INTO recipes (item_name, resource_name, amount) VALUES (?, ?, ?)',
                             (item_name, res_name, int(amount)))
                             
        # Добавляем баллы пользователю
        p_type = proposal.get('type', 'add')
        points = 10 if p_type == 'add' else 5
        await db.execute('''
            INSERT INTO users (telegram_id, score) 
            VALUES (?, ?) 
            ON CONFLICT(telegram_id) DO UPDATE SET score = users.score + ?
        ''', (proposal['user_id'], points, points))
        
        await db.commit()
        # Инвалидируем кэш после любого изменения базы
        invalidate_cache()
        await update_proposal_status(proposal_id, 'approved')
    return True

async def migrate_from_recipes():
    try:
        from recipes import CRAFTING_RECIPES, ITEM_CATEGORIES
    except ImportError:
        logging.info("Файл recipes.py не найден, миграция пропущена.")
        return
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT COUNT(*) FROM items') as cursor:
            count = (await cursor.fetchone())[0]
            if count > 0:
                logging.info("База данных не пуста. Миграция пропущена.")
                return
                
        logging.info("Начинаем миграцию из recipes.py...")
        cat_map = {}
        for cat, items in ITEM_CATEGORIES.items():
            icon = cat.split(' ')[0]
            for item in items:
                cat_map[item] = (cat, icon)
                
        for item_name, recipe in CRAFTING_RECIPES.items():
            cat_data = cat_map.get(item_name)
            if cat_data:
                category, icon = cat_data
            else:
                category, icon = "📦 Без категории", "📦"
                
            await db.execute('INSERT OR REPLACE INTO items (name, category, icon) VALUES (?, ?, ?)',
                             (item_name, category, icon))
                             
            for res_name, amount in recipe.items():
                await db.execute('INSERT OR IGNORE INTO items (name, category, icon) VALUES (?, ?, ?)',
                                 (res_name, "💎 Ресурсы и прочее", "💎"))
                await db.execute('INSERT INTO recipes (item_name, resource_name, amount) VALUES (?, ?, ?)',
                                 (item_name, res_name, amount))
        await db.commit()
        logging.info("Миграция завершена!")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import asyncio
    asyncio.run(init_db())
    asyncio.run(migrate_from_recipes())
