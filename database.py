import asyncpg
import os
from datetime import datetime, timedelta
import logging

DATABASE_URL = os.getenv("DATABASE_URL")
pool = None

async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        async with pool.acquire() as conn:
            # users
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    tg_id BIGINT PRIMARY KEY,
                    state TEXT DEFAULT 'menu',
                    partner_id BIGINT,
                    chat_start TIMESTAMP,
                    last_active TIMESTAMP DEFAULT NOW(),
                    created_at TIMESTAMP DEFAULT NOW()
                );
            ''')

            # reports
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    from_id BIGINT,
                    to_id BIGINT,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT NOW()
                );
            ''')

            # bans
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bans (
                    tg_id BIGINT PRIMARY KEY,
                    until TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            ''')

            # chat_logs — НОВАЯ ТАБЛИЦА
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_logs (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    partner_id BIGINT,
                    duration INTERVAL,
                    ended_at TIMESTAMP DEFAULT NOW()
                );
            ''')

            # МИГРАЦИИ
            await conn.execute('ALTER TABLE reports ADD COLUMN IF NOT EXISTS reason TEXT;')
            await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_start TIMESTAMP;')

        logging.info("Database initialized successfully")
    except Exception as e:
        logging.error(f"Database initialization failed: {e}")
        raise

# === ПОЛЬЗОВАТЕЛИ ===
async def get_user(tg_id):
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM users WHERE tg_id = $1', tg_id)
            return dict(row) if row else None
    except Exception as e:
        logging.error(f"Error getting user {tg_id}: {e}")
        return None

async def update_user(tg_id, **kwargs):
    if not kwargs:
        return
    try:
        async with pool.acquire() as conn:
            columns = list(kwargs.keys())
            values = list(kwargs.values())
            set_clause = ', '.join([f"{col} = ${i+2}" for i, col in enumerate(columns)])
            query = f'''
                INSERT INTO users (tg_id, {', '.join(columns)})
                VALUES ($1, {', '.join([f'${i+2}' for i in range(len(values))])})
                ON CONFLICT (tg_id) DO UPDATE SET {set_clause}, last_active = NOW()
            '''
            await conn.execute(query, tg_id, *values)
    except Exception as e:
        logging.error(f"Error updating user {tg_id}: {e}")

# === ЧАТЫ ===
async def log_chat_end(user_id, partner_id, duration):
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO chat_logs (user_id, partner_id, duration) VALUES ($1, $2, $3)',
                user_id, partner_id, duration
            )
            await conn.execute(
                'INSERT INTO chat_logs (user_id, partner_id, duration) VALUES ($1, $2, $3)',
                partner_id, user_id, duration
            )
    except Exception as e:
        logging.error(f"Error logging chat: {e}")

async def get_user_chat_stats(tg_id):
    try:
        async with pool.acquire() as conn:
            total_chats = await conn.fetchval(
                'SELECT COUNT(*) FROM chat_logs WHERE user_id = $1', tg_id
            )
            total_seconds = await conn.fetchval(
                'SELECT COALESCE(SUM(EXTRACT(EPOCH FROM duration)), 0) FROM chat_logs WHERE user_id = $1', tg_id
            )
            return total_chats or 0, int(total_seconds)
    except Exception as e:
        logging.error(f"Error getting chat stats: {e}")
        return 0, 0

# === ОТЧЁТЫ ===
async def add_report(reporter_id, reported_id, reason=None):
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO reports (from_id, to_id, reason) VALUES ($1, $2, $3)',
                reporter_id, reported_id, reason
            )
    except Exception as e:
        logging.error(f"Error adding report: {e}")

async def get_reports_count(tg_id):
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval('SELECT COUNT(*) FROM reports WHERE to_id = $1', tg_id)
    except Exception as e:
        logging.error(f"Error getting reports count: {e}")
        return 0

async def get_all_reports():
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM reports ORDER BY timestamp DESC LIMIT 50')
            return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Error getting all reports: {e}")
        return []

async def get_user_reports(tg_id):
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM reports WHERE to_id = $1 ORDER BY timestamp DESC LIMIT 10', tg_id)
            return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Error getting user reports: {e}")
        return []

async def get_reports_today():
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval('SELECT COUNT(*) FROM reports WHERE timestamp >= CURRENT_DATE')
    except Exception as e:
        logging.error(f"Error getting today's reports: {e}")
        return 0

# === БАНЫ ===
async def ban_user(tg_id, hours=24):
    try:
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO bans (tg_id, until)
                VALUES ($1, NOW() + INTERVAL '1 hour' * $2)
                ON CONFLICT (tg_id) DO UPDATE SET until = EXCLUDED.until
            ''', tg_id, hours)
            await conn.execute('UPDATE users SET state = $1, partner_id = NULL WHERE tg_id = $2', 'menu', tg_id)
    except Exception as e:
        logging.error(f"Error banning user {tg_id}: {e}")

async def ban_user_permanent(tg_id):
    try:
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO bans (tg_id, until)
                VALUES ($1, NOW() + INTERVAL '100 years')
                ON CONFLICT (tg_id) DO UPDATE SET until = EXCLUDED.until
            ''', tg_id)
            await conn.execute('UPDATE users SET state = $1, partner_id = NULL WHERE tg_id = $2', 'menu', tg_id)
    except Exception as e:
        logging.error(f"Error permanent banning user {tg_id}: {e}")

async def is_banned(tg_id):
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow('SELECT until FROM bans WHERE tg_id = $1 AND until > NOW()', tg_id)
            return row is not None
    except Exception as e:
        logging.error(f"Error checking ban for {tg_id}: {e}")
        return False

async def unban_user(tg_id):
    try:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM bans WHERE tg_id = $1', tg_id)
            await conn.execute('DELETE FROM reports WHERE to_id = $1', tg_id)
    except Exception as e:
        logging.error(f"Error unbanning user {tg_id}: {e}")

# === СТАТИСТИКА ===
async def get_stats():
    try:
        async with pool.acquire() as conn:
            total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
            active_chats = await conn.fetchval("SELECT COUNT(*) FROM users WHERE state = 'chat'")
            total_reports = await conn.fetchval('SELECT COUNT(*) FROM reports')
            return total_users, active_chats // 2, total_reports
    except Exception as e:
        logging.error(f"Error getting stats: {e}")
        return 0, 0, 0
