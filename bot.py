import os
import json
import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# Конфигурация
# =========================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8443))

# =========================
# Загружаем вопросы
# =========================
with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

# =========================
# /start
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories = sorted({q["category"] for q in questions})
    keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat|{cat}")] for cat in categories]
    await update.message.reply_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(keyboard))

# =========================
# Выбор категории
# =========================
async def on_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("|")[1]
    items = [q for q in questions if q["category"] == category]
    context.user_data["current"] = {"items": items, "index": 0}
    await show_question(query, items[0])

# =========================
# Показ вопроса
# =========================
async def show_question(query, q):
    text = f"Вопрос: {q['task']}" + (f"\nКод: {q.get('code', '')}" if q.get("code") else "")
    keyboard = [[
        InlineKeyboardButton("Да", callback_data=f"ans|yes|{q['id']}"),
        InlineKeyboardButton("Нет", callback_data=f"ans|no|{q['id']}"),
        InlineKeyboardButton("Частично", callback_data=f"ans|part|{q['id']}")
    ]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# =========================
# Ответ на вопрос (кнопки)
# =========================
async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, ans, qid = query.data.split("|")
    qid = int(qid)
    q = next(x for x in questions if x["id"] == qid)
    user_id = update.effective_user.id

    if ans in ("no", "part"):
        # ждём текстовый комментарий
        context.user_data["pending"] = {
            "question": q,
            "answer": "Нет" if ans == "no" else "Частично",
            "user_id": user_id
        }
        await query.edit_message_text(
            f"Вы выбрали «{'Нет' if ans == 'no' else 'Частично'}». "
            "Введите, пожалуйста, комментарий одним сообщением:"
        )
        return

    # Если "Да" — отправляем сразу
    await send_to_webhook(user_id, q, "Да", "")
    await go_next_question(query, context)

# =========================
# Приём комментария
# =========================
async def on_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending" not in context.user_data:
        return

    pending = context.user_data.pop("pending")
    q = pending["question"]
    user_id = pending["user_id"]
    comment_text = update.message.text.strip()
    await send_to_webhook(user_id, q, pending["answer"], comment_text)
    await update.message.reply_text("Комментарий сохранён ✅")
    await go_next_question(update.message, context)

# =========================
# Переход к следующему вопросу
# =========================
async def go_next_question(message_or_query, context):
    current = context.user_data.get("current", {})
    items = current.get("items", [])
    idx = current.get("index", 0) + 1
    context.user_data["current"]["index"] = idx

    if idx < len(items):
        next_q = items[idx]
        if hasattr(message_or_query, "edit_message_text"):
            await show_question(message_or_query, next_q)
        else:
            text = f"Вопрос: {next_q['task']}" + (f"\nКод: {next_q.get('code','')}" if next_q.get("code") else "")
            keyboard = [[
                InlineKeyboardButton("Да", callback_data=f"ans|yes|{next_q['id']}"),
                InlineKeyboardButton("Нет", callback_data=f"ans|no|{next_q['id']}"),
                InlineKeyboardButton("Частично", callback_data=f"ans|part|{next_q['id']}")
            ]]
            await message_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        if hasattr(message_or_query, "reply_text"):
            await message_or_query.reply_text("Чек-лист завершён ✅ Спасибо!")
        else:
            await message_or_query.edit_message_text("Чек-лист завершён ✅ Спасибо!")
        context.user_data.pop("current", None)

# =========================
# Отправка в Google Apps Script
# =========================
async def send_to_webhook(user_id, q, answer, comment):
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "user_id": str(user_id),
        "category": q["category"],
        "task": q["task"],
        "answer": answer,
        "code": q.get("code", ""),
        "comment": comment
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=7)
    except Exception as e:
        print("Ошибка отправки:", e)

# =========================
# Основной запуск
# =========================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_category, pattern="^cat\|"))
    app.add_handler(CallbackQueryHandler(on_answer, pattern="^ans\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_comment))

    # Запуск вебхука
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}",
        secret_token="WEBHOOK_SECRET"  # опционально для безопасности
    )

if __name__ == "__main__":
    main()
