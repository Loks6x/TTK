import sqlite3
import asyncio
import os
from fastapi.responses import FileResponse
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === КОНФИГУРАЦИЯ БОТА И ГРУППЫ ===
BOT_TOKEN = "8982256451:AAFge6oA28B_khpKBAhYrQC6NbzQRFhusMk"
CHAT_ID = "-1005307316313" # ID группы закупщика (обязательно с минусом, если это группа)

# Инициализация
bot = Bot(token=BOT_TOKEN)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow") # Укажи свой часовой пояс

# Подключение к БД (используем стандартный sqlite3 с check_same_thread=False для FastAPI)
conn = sqlite3.connect("orders.db", check_same_thread=False)
cursor = conn.cursor()

# Создание таблицы
cursor.execute("""
CREATE TABLE IF NOT EXISTS active_order (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    quantity TEXT NOT NULL,
    comment TEXT,
    author_name TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# === ЛОГИКА ОТПРАВКИ В TELEGRAM ===
async def send_order_to_tg():
    cursor.execute("SELECT id, item_name, quantity, comment, author_name FROM active_order ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    
    if not rows:
        return # Если база пуста, ничего не отправляем
    
    authors = set()
    items_text = ""
    
    for row in rows:
        _, item_name, quantity, comment, author_name = row
        authors.add(author_name)
        
        comment_text = f" ({comment})" if comment else ""
        items_text += f"• {item_name} — {quantity}{comment_text} — (добавил {author_name})\n"
        
    authors_joined = ", ".join(authors)
    
    message = (
        f"📦 *Общая заявка на продукты*\n\n"
        f"{items_text}\n"
        f"👤 *Заявку составили:* {authors_joined}\n"
        f"_Сформировано автоматически через Тугай Хелпер_"
    )
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        # Очищаем таблицу после успешной отправки
        cursor.execute("DELETE FROM active_order")
        conn.commit()
    except Exception as e:
        print(f"Ошибка отправки в ТГ: {e}")

# === ЖИЗНЕННЫЙ ЦИКЛ ПРИЛОЖЕНИЯ (FastAPI) ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запуск планировщика при старте
    scheduler.add_job(send_order_to_tg, 'cron', hour=8, minute=0)
    scheduler.add_job(send_order_to_tg, 'cron', hour=20, minute=0)
    scheduler.start()
    yield
    # Остановка при выключении
    scheduler.shutdown()
    await bot.session.close()
    conn.close()

app = FastAPI(lifespan=lifespan)

# Разрешаем CORS (чтобы сайт мог делать запросы к API с любого домена)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === МОДЕЛИ ДАННЫХ ===
class OrderItem(BaseModel):
    item_name: str
    quantity: str
    comment: str = ""
    author_name: str

# === API ЭНДПОИНТЫ ===
@app.get("/api/get_orders")
async def get_orders():
    cursor.execute("SELECT id, item_name, quantity, comment, author_name FROM active_order ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    result = [{"id": r[0], "item_name": r[1], "quantity": r[2], "comment": r[3], "author_name": r[4]} for r in rows]
    return result

@app.post("/api/add_order")
async def add_order(item: OrderItem):
    cursor.execute(
        "INSERT INTO active_order (item_name, quantity, comment, author_name) VALUES (?, ?, ?, ?)",
        (item.item_name, item.quantity, item.comment, item.author_name)
    )
    conn.commit()
    return {"status": "success"}

@app.delete("/api/delete_order/{order_id}")
async def delete_order(order_id: int):
    cursor.execute("DELETE FROM active_order WHERE id = ?", (order_id,))
    conn.commit()
    return {"status": "success"}

@app.post("/api/send_now")
async def send_now():
    await send_order_to_tg()
    return {"status": "success"}

# Для локального запуска: uvicorn main:app --host 0.0.0.0 --port 8000
