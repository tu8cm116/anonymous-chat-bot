import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

async def reset_all():
    print("🔄 Подключаюсь к базе данных...")
    
    # Подключаемся к базе
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        # Очищаем ВСЕ таблицы
        await conn.execute('DELETE FROM bans')
        print("✅ Все баны удалены!")
        
        await conn.execute('DELETE FROM reports')
        print("✅ Все жалобы удалены!")
        
        # Сбрасываем состояния пользователей (но не удаляем их полностью)
        await conn.execute("UPDATE users SET state = 'menu', partner_id = NULL")
        print("✅ Все пользователи сброшены в меню!")
        
        # Очищаем последовательности (если используются)
        await conn.execute("ALTER SEQUENCE reports_id_seq RESTART WITH 1")
        print("✅ Счётчики сброшены!")
        
        print("\n🎉 ВСЯ СТАТИСТИКА ПОЛНОСТЬЮ СБРОШЕНА!")
        print("📊 Баны: 0")
        print("📊 Жалобы: 0") 
        print("📊 Пользователи: сброшены")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(reset_all())
