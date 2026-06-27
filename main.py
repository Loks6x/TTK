import sqlite3
import os
import logging
import html
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8982256451:AAFge6oA28B_khpKBAhYrQC6NbzQRFhusMk"
CHAT_ID = -1005307316313  

bot = Bot(token=BOT_TOKEN)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# База данных
DB_PATH = "orders.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()

init_db()

async def send_order_to_tg():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT item_name, quantity, comment, author_name FROM active_order ORDER BY timestamp ASC")
    rows = cursor.fetchall()
    
    if not rows:
        conn.close()
        return False

    authors = set()
    items_list = []
    for r in rows:
        name, qty, comm, auth = r
        authors.add(html.escape(auth))
        c_part = f" (<i>{html.escape(comm)}</i>)" if comm else ""
        # Убрали приписку [от Имя] возле каждой позиции
        items_list.append(f"• <b>{html.escape(name)}</b> — {html.escape(qty)}{c_part}")
    
    # Имена авторов теперь только в самом низу сообщения один раз
    message = "📦 <b>НОВАЯ ЗАЯВКА</b>\n\n" + "\n".join(items_list) + f"\n\n👤 <b>Кто составил:</b> {', '.join(authors)}"
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode=ParseMode.HTML)
        cursor.execute("DELETE FROM active_order")
        conn.commit()
        logger.info("Заявка отправлена, база очищена.")
        return True
    except Exception as e:
        logger.error(f"Ошибка ТГ: {e}")
        return False
    finally:
        conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(send_order_to_tg, 'cron', hour=8, minute=0)
    scheduler.add_job(send_order_to_tg, 'cron', hour=20, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()
    await bot.session.close()

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

# --- API ЭНДПОИНТЫ ---

@app.get("/api/get_orders")
async def get_orders():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, item_name, quantity, comment, author_name FROM active_order ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "item_name": r[1], "quantity": r[2], "comment": r[3], "author_name": r[4]} for r in rows]

@app.post("/api/add_order")
async def add_order(item: OrderItem):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO active_order (item_name, quantity, comment, author_name) VALUES (?, ?, ?, ?)",
            (item.item_name, item.quantity, item.comment, item.author_name)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/delete_order/{order_id}")
async def delete_order(order_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM active_order WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/send_now")
async def send_now():
    success = await send_order_to_tg()
    if not success:
        raise HTTPException(status_code=500, detail="Ошибка отправки в Telegram. Проверь логи сервера.")
    return {"status": "success"}

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")
