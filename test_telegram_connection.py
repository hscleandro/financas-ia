"""Teste simples de conexão com Telegram Bot."""
import asyncio
from telegram import Bot
from config import settings

async def test_bot():
    bot = Bot(token=settings.telegram_bot_token)
    me = await bot.get_me()
    print(f"✅ Bot conectado com sucesso!")
    print(f"   Nome: {me.first_name}")
    print(f"   Username: @{me.username}")
    print(f"   ID: {me.id}")

if __name__ == "__main__":
    asyncio.run(test_bot())
