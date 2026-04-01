import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ====================== LOAD ENV ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN missing in .env")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ====================== DATABASE ======================
conn = sqlite3.connect("bot.db", check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    premium_until TEXT,
    referred_by INTEGER
)''')

c.execute('''CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    coin TEXT,
    target REAL,
    condition TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS referral_earnings (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0
)''')

conn.commit()

# ====================== HELPERS ======================
def is_premium(user_id: int) -> bool:
    c.execute("SELECT premium_until FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row or not row[0]:
        return False
    try:
        return datetime.fromisoformat(row[0]) > datetime.now()
    except:
        return False

def max_alerts(user_id: int) -> int:
    return 999 if is_premium(user_id) else 5

# ====================== COINGECKO ======================
async def get_price(coin: str) -> float:
    coin = coin.lower().strip()
    ids = {
        "btc": "bitcoin",
        "eth": "ethereum",
        "sol": "solana",
        "usdt": "tether",
        "bnb": "binancecoin"
    }
    coin_id = ids.get(coin, coin)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
            ) as resp:
                data = await resp.json()
                return float(data.get(coin_id, {}).get("usd", 0)) or 0
    except:
        return 0

async def get_daily_signals():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&page=1&price_change_percentage=24h"
            ) as resp:
                data = await resp.json()
                text = "<b>📊 Daily Trading Signals (Top 8)</b>\n\n"
                for coin in data[:8]:
                    change = coin.get("price_change_percentage_24h", 0)
                    signal = "🟢 BUY" if change > 3 else "🔴 SELL" if change < -3 else "⚪ HOLD"
                    text += f"{coin['symbol'].upper()} ${coin['current_price']:.2f} | {change:+.1f}% → {signal}\n"
                return text
    except:
        return "⚠️ Failed to fetch signals. Try again later."

# ====================== ALERT CHECKER ======================
async def check_alerts():
    c.execute("SELECT * FROM alerts")
    alerts = c.fetchall()

    for alert in alerts:
        alert_id, user_id, coin, target, condition = alert
        current = await get_price(coin)

        if current == 0:
            continue

        hit = (condition == "above" and current > target) or (condition == "below" and current < target)

        if hit:
            try:
                await bot.send_message(
                    user_id,
                    f"🚨 <b>ALERT TRIGGERED!</b>\n{coin.upper()} is now ${current:,.2f}\nTarget was ${target:,.2f} ({condition})"
                )
            except:
                pass

            c.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
            conn.commit()

scheduler = AsyncIOScheduler()
scheduler.add_job(check_alerts, "interval", minutes=5)
scheduler.start()

# ====================== REFERRALS ======================
async def record_referral(referred_id: int, referrer_id: int):
    if referred_id == referrer_id:
        return

    c.execute("INSERT OR IGNORE INTO users (user_id, referred_by) VALUES (?, ?)", (referred_id, referrer_id))
    conn.commit()

def add_referral_earning(referrer_id: int, amount_naira: int):
    c.execute("INSERT OR IGNORE INTO referral_earnings (user_id, balance) VALUES (?, 0)", (referrer_id,))
    c.execute("UPDATE referral_earnings SET balance = balance + ? WHERE user_id=?", (amount_naira, referrer_id))
    conn.commit()

# ====================== HANDLERS ======================
@dp.message(Command("start"))
async def start(message: types.Message):
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    user_id = message.from_user.id

    if args and args[0].startswith("ref"):
        try:
            referrer_id = int(args[0][3:])
            await record_referral(user_id, referrer_id)
            await message.answer("🎁 You joined via referral. Share yours to earn!")
        except:
            pass

    await message.answer(
        "🚀 <b>Crypto Alert Pro NG</b>\n\n"
        "Free: 5 alerts\nPremium unlocks unlimited\n\n"
        "/price BTC\n"
        "/alert BTC 95000\n"
        "/signals\n"
        "/subscribe\n"
        "/referrals\n"
        "/request_payout"
    )

@dp.message(Command("price"))
async def price_cmd(message: types.Message):
    try:
        coin = message.text.split()[1]
        price = await get_price(coin)

        if price:
            await message.answer(f"💰 <b>{coin.upper()}</b> = ${price:,.2f}")
        else:
            await message.answer("❌ Coin not found")
    except:
        await message.answer("Usage: /price BTC")

@dp.message(Command("alert"))
async def set_alert(message: types.Message):
    user_id = message.from_user.id

    try:
        _, coin, target_str = message.text.split()
        target = float(target_str)
        current = await get_price(coin)

        if current == 0:
            await message.answer("❌ Invalid coin")
            return

        condition = "above" if target > current else "below"

        c.execute("SELECT COUNT(*) FROM alerts WHERE user_id=?", (user_id,))
        current_alerts = c.fetchone()[0]

        if current_alerts >= max_alerts(user_id):
            await message.answer("❌ Limit reached. Upgrade with /subscribe")
            return

        c.execute(
            "INSERT INTO alerts (user_id, coin, target, condition) VALUES (?, ?, ?, ?)",
            (user_id, coin.lower(), target, condition)
        )
        conn.commit()

        await message.answer(f"✅ Alert set for {coin.upper()} {condition} ${target}")

    except:
        await message.answer("Usage: /alert BTC 95000")

@dp.message(Command("signals"))
async def signals_cmd(message: types.Message):
    text = await get_daily_signals()
    await message.answer(text)

# ====================== SUBSCRIPTION ======================
@dp.message(Command("subscribe"))
async def subscribe(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Weekly — 170 Stars", callback_data="sub_weekly")],
        [types.InlineKeyboardButton(text="Monthly — 400 Stars", callback_data="sub_monthly")]
    ])

    await message.answer(
        "🔥 <b>Upgrade to Premium</b>\n\nUnlimited alerts + signals\n\nChoose plan 👇",
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("sub_"))
async def process_sub(callback: types.CallbackQuery):
    plan = callback.data
    stars = 170 if "weekly" in plan else 400
    days = 7 if "weekly" in plan else 30
    name = "Weekly" if "weekly" in plan else "Monthly"

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"{name} Premium",
        description="Unlimited alerts + signals",
        payload=f"premium_{days}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Subscription", amount=stars)]
    )

    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def payment_received(message: types.Message):
    payload = message.successful_payment.invoice_payload
    days = int(payload.split("_")[-1])
    user_id = message.from_user.id

    premium_until = (datetime.now() + timedelta(days=days)).isoformat()

    c.execute("INSERT OR REPLACE INTO users (user_id, premium_until) VALUES (?, ?)", (user_id, premium_until))
    conn.commit()

    # Referral reward
    c.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()

    if row and row[0]:
        referrer = row[0]
        commission = 600 if days == 7 else 1400
        add_referral_earning(referrer, commission)

    await message.answer(f"🎉 Premium active until {premium_until[:10]}")

# ====================== START ======================
async def main():
    print("✅ Bot running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())