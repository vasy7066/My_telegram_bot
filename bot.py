import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message

# Вставь сюда свой токен
TOKEN = "7874386909:AAG80AW25VRVqrKNCf14lmlRv_ZTPvKaqiw"

# Настраиваем логирование
logging.basicConfig(level=logging.INFO)

# Создаём объект бота и диспетчер (он обрабатывает команды)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Команда /start
@dp.message()
async def start_command(message: Message):
    if message.text == "/start":
        await message.answer("Привет! Я твой бот-напоминалка. Напиши /help, чтобы узнать, что я умею.")
    elif message.text == "/help":
        help_text = (
            "Я умею:\n"
            "/start - Начать работу со мной\n"
            "/help - Показать список команд\n"
        )
        await message.answer(help_text)
    else:
        await message.answer("Я не понимаю эту команду. Напиши /help, чтобы увидеть список доступных команд.")

async def main():
    """Основная функция для запуска бота"""
    await bot.delete_webhook(drop_pending_updates=True)  # Удаляет старые обновления
    await dp.start_polling(bot)  # Запускает бота

if __name__ == "__main__":
    asyncio.run(main())
