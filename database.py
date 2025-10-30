import asyncpg
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

pool = None

# --- Инициализация БД ---
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                tg_id BIGINT PRIMARY KEY,
                state TEXT DEFAULT 'menu',
                partner_id BIGINT,
                last_active TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                from_id BIGINT,
                to_id BIGINT,
                timestamp TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS bans (
                tg_id BIGINT PRIMARY KEY,
                until TIMESTAMP
            );
        ''')

# --- Пользователь ---
async def get_user(tg_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT * FROM users WHERE tg_id = $1', tg_id)
        return dict(row) if row else None

async def update_user(tg_id, **kwargs):
    if not kwargs:
        return
    async with pool.acquire() as conn:
        columns = list(kwargs.keys())
        values = list(kwargs.values())
        placeholders = ', '.join(f'${i+2}' for i in range(len(values)))
        set_clause = ', '.join(f"{col} = EXCLUDED.{col}" for col in columns)
        await conn.execute(f'''
            INSERT INTO users (tg_id, {', '.join(columns)})
            VALUES ($1, {placeholders})
            ON CONFLICT (tg_id) DO UPDATE SET {set_clause}
        ''', tg_id, *values)

# --- Поиск партнёра ---
async def find_partner(exclude_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT tg_id FROM users 
            WHERE state = 'searching' AND tg_id != $1
            ORDER BY last_active ASC LIMIT 1
        ''', exclude_id)
        return row['tg_id'] if row else None

# --- Жалобы ---
async def add_report(from_id, to_id):
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO reports (from_id, to_id) VALUES ($1, $2)', from_id, to_id)

async def get_reports_count(tg_id):
    async with pool.acquire() as conn:
        return await conn.fetchval('SELECT COUNT(*) FROM reports WHERE to_id = $1', tg_id)

# --- Баны ---
async def ban_user(tg_id, hours=24):
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO bans (tg_id, until)
            VALUES ($1, NOW() + ($2 || ' hours')::INTERVAL)
            ON CONFLICT (tg_id) DO UPDATE SET until = EXCLUDED.until
        ''', tg_id, str(hours))

async def is_banned(tg_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT until FROM bans WHERE tg_id = $1 AND until > NOW()', tg_id)
        return row is not None

async def unban_user(tg_id):
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM bans WHERE tg_id = $1', tg_id)

# --- Статистика ---
async def get_stats():
    async with pool.acquire() as conn:
        total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
        active_chats = await conn.fetchval("SELECT COUNT(*) / 2 FROM users WHERE state = 'chat'")
        total_reports = await conn.fetchval('SELECT COUNT(*) FROM reports')
        return total_users, active_chats, total_reports
