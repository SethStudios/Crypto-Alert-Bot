# Activate premium
    premium_until = (datetime.now() + timedelta(days=days)).isoformat()
    c.execute("INSERT OR REPLACE INTO users (user_id, premium_until) VALUES (?, ?)", (user_id, premium_until))
    conn.commit()

    # Credit referrer if exists
    c.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row and row[0]:
        referrer = row[0]
        commission = 600 if days == 7 else 1400
        add_referral_earning(referrer, commission)
        try:
            await bot.send_message(referrer, f"🎉 Referral payout added!\nSomeone you referred bought {days}-day premium.\nYou earned ₦{commission} (check /referrals)")
        except:
            pass

    await message.answer(
        f"🎉 Payment successful!\n"
        f"✅ Premium activated until {premium_until[:10]}\n"
        f"Unlimited alerts & signals are now LIVE!\n\n"
        f"Use /alert and /signals"
    )

@dp.message(Command("referrals"))
async def referrals_cmd(message: types.Message):
    user_id = message.from_user.id
    bot_username = (await bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"

    c.execute("SELECT balance FROM referral_earnings WHERE user_id=?", (user_id,))
    row = c.fetchone()
    balance = row[0] if row else 0

    c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
    referrals_count = c.fetchone()[0]

    await message.answer(
        f"<b>🔗 Your Referral Link</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"People referred: <b>{referrals_count}</b>\n"
        f"Current earnings: <b>₦{balance}</b>\n\n"
        f"Share the link and earn ₦600 per weekly + ₦1,400 per monthly subscription!\n"
        f"Minimum payout: ₦2,000\n"
        f"Use /request_payout when ready"
    )

@dp.message(Command("request_payout"))
async def request_payout(message: types.Message):
    user_id = message.from_user.id
    c.execute("SELECT balance FROM referral_earnings WHERE user_id=?", (user_id,))
    row = c.fetchone()
    balance = row[0] if row else 0

    if balance < 2000:
        await message.answer(f"❌ Minimum payout is ₦2,000. You currently have ₦{balance}.")
        return

    await message.answer(
        "💸 <b>Payout Request</b>\n\n"
        "Reply to this message with:\n"
        "Your Binance wallet address (for USDT) or Nigerian bank details (Bank name, Account number, Account name)\n\n"
        "Example:\nUSDT: 0x123abc...\nOR\nGTBank • 0123456789 • John Doe"
    )
    # In real use, you can add state to save the next message, but for simplicity you will manually check chat with user

    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"🔔 New payout request from user {user_id}\nBalance: ₦{balance}\nCheck chat with him.")

# ====================== START BOT ======================
async def main():
    print("✅ Crypto Alert Pro NG is LIVE! Ready to make money...")
    await dp.start_polling(bot)

if name == "main":
    asyncio.run(main())
