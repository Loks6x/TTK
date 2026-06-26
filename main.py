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

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
# Убедись, что этот ID правильный! Попробуй перепроверить его через @getmyid_bot в группе.
BOT_TOKEN = "8982256451:AAFge6oA28B_khpKBAhYrQC6NbzQRFhusMk"
CHAT_ID = -1005307316313 

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

async def send_order_to_tg():
    cursor.execute("SELECT id, item_name, quantity, comment, author_name FROM active_order ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    
    if not rows:
        logger.info("Заявок нет, база пуста.")
        return
    
    authors = set()
    items_text = ""
    
    for row in rows:
        _, item_name, quantity, comment, author_name = row
        # Экранируем текст, чтобы не было ошибок HTML
        safe_item = html.escape(str(item_name))
        safe_qty = html.escape(str(quantity))
        safe_comment = html.escape(str(comment)) if comment else ""
        safe_author = html.escape(str(author_name))
        
        authors.add(safe_author)
        
        c_text = f" (<i>{safe_comment}</i>)" if safe_comment else ""
        items_text += f"• <b>{safe_item}</b> — {safe_qty}{c_text} [от {safe_author}]\n"
    
    message = (
        f"📦 <b>НОВАЯ ЗАЯВКА</b>\n\n"
        f"{items_text}\n"
        f"👤 <b>Составили:</b> {', '.join(authors)}\n"
    )
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode=ParseMode.HTML)
        
        # ЕСЛИ ОТПРАВКА ПРОШЛА УСПЕШНО — ЧИСТИМ БАЗУ
        cursor.execute("DELETE FROM active_order")
        conn.commit()
        logger.info("Заявка отправлена, база очищена.")
        
    except Exception as e:
        logger.error(f"ОШИБКА TELEGRAM: {e}")
        logger.error(f"Проверь: 1. Бот в группе? 2. Бот админ? 3. CHAT_ID {CHAT_ID} верный?")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
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
    return FileResponse("index.html")
