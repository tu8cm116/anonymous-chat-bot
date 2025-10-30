import asyncpg
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
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
    await conn.close()

async def get_user(tg_id):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow('SELECT * FROM users WHERE tg_id = $1', tg_id)
    await conn.close()
    return dict(row) if row else None

async def update_user(tg_id, **kwargs):
    conn = await asyncpg.connect(DATABASE_URL)
    set_clause = ', '.join(f"{k} = ${i+2}" for i, k in enumerate(kwargs))
    values = [tg_id] + list(kwargs.values())
    await conn.execute(f'''
        INSERT INTO users (tg_id, {', '.join(kwargs.keys())})
        VALUES ({', '.join(f"${i+1}" for i in range(len(values)))})
        ON CONFLICT (tg_id) DO UPDATE SET {set_clause}
    ''', *values)
    await conn.close()

async def find_partner(exclude_id):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow('''
        SELECT tg_id FROM users 
        WHERE state = 'searching' AND tg_id != $1
        ORDER BY last_active ASC LIMIT 1
    ''', exclude_id)
    await conn.close()
    return row['tg_id'] if row else None

async def add_report(from_id, to_id):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('INSERT INTO reports (from_id, to_id) VALUES ($1, $2)', from_id, to_id)
    await conn.close()

async def get_reports_count(tg_id):
    conn = await asyncpg.connect(DATABASE_URL)
    count = await conn.fetchval('SELECT COUNT(*) FROM reports WHERE to_id = $1', tg_id)
    await conn.close()
    return count

async def ban_user(tg_id, hours=24):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        INSERT INTO bans (tg_id, until) VALUES ($1, NOW() + INTERVAL '%s hours')
        ON CONFLICT (tg_id) DO UPDATE SET until = EXCLUDED.until
    ''', tg_id, hours)
    await conn.close()

async def is_banned(tg_id):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow('SELECT until FROM bans WHERE tg_id = $1 AND until > NOW()', tg_id)
    await conn.close()
    return row is not None

async def unban_user(tg_id):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('DELETE FROM bans WHERE tg_id = $1', tg_id)
    await conn.close()

async def get_stats():
    conn = await asyncpg.connect(DATABASE_URL)
    total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
    active_chats = await conn.fetchval('SELECT COUNT(*) / 2 FROM users WHERE state = ''chat''')
    total_reports = await conn.fetchval('SELECT COUNT(*) FROM reports')
    await conn.close()
    return total_users, active_chats, total_reports
