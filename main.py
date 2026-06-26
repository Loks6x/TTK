import sqlite3
import asyncio
import os
import logging
import html
from fastapi.responses import FileResponse
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логов, чтобы видеть ошибки в терминале
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8982256451:AAFge6oA28B_khpKBAhYrQC6NbzQRFhusMk"
CHAT_ID = -1005307316313  # Сделали числом для надежности

bot = Bot(token=BOT_TOKEN)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

conn = sqlite3.connect("orders.db", check_same_thread=False)
cursor = conn.cursor()

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

# === ЛОГИКА ОТПРАВКИ ===
async def send_order_to_tg():
    cursor.execute("SELECT id, item_name, quantity, comment, author_name FROM active_order ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    
    if not rows:
        logger.info("Заявок нет, отправка отменена.")
        return
    
    authors = set()
    items_text = ""
    
    for row in rows:
        _, item_name, quantity, comment, author_name = row
        # Экранируем спецсимволы, чтобы HTML не ломался
        safe_item = html.escape(item_name)
        safe_qty = html.escape(quantity)
        safe_author = html.escape(author_name)
        authors.add(safe_author)
        
        comment_text = f" (<i>{html.escape(comment)}</i>)" if comment else ""
        items_text += f"• <b>{safe_item}</b> — {safe_qty}{comment_text} — [от {safe_author}]\n"
        
    authors_joined = ", ".join(authors)
    
    message = (
        f"📦 <b>ОБЩАЯ ЗАЯВКА</b>\n\n"
        f"{items_text}\n"
        f"👤 <b>Кто составил:</b> {authors_joined}\n"
        f"_________________________\n"
        f"🤖 <i>Сформировано автоматически</i>"
    )
    
    try:
        # Используем ParseMode.HTML — это стабильнее всего
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode=ParseMode.HTML)
        
        # Очищаем базу ТОЛЬКО после успешной отправки
        cursor.execute("DELETE FROM active_order")
        conn.commit()
        logger.info("Заявка успешно отправлена и база очищена.")
    except Exception as e:
        logger.error(f"Ошибка при отправке в Telegram: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Планировщик: в 8 утра и в 8 вечера
    scheduler.add_job(send_order_to_tg, 'cron', hour=8, minute=0)
    scheduler.add_job(send_order_to_tg, 'cron', hour=20, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()
    await bot.session.close()
    conn.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return [{"id": r[0], "item_name": r[1], "quantity": r[2], "comment": r[3], "author_name": r[4]} for r in rows]

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

@app.get("/")
async def serve_frontend():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "index.html not found"}
