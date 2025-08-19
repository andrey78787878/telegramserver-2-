import os
import json
import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"].rstrip("/")
PORT = int(os.environ.get("PORT", 8443))

with open("questions.json", encoding="utf-8") as f:
    questions = json.load(f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories = sorted({q["category"] for q in questions})
    keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat|{cat}")] for cat in categories]
    await update.message.reply_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(keyboard))

async def on_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("|", 1)[1]
    items = [q for q in questions if q["category"] == category]
    if not items:
        await query.edit_message_text("Нет вопросов в этой категории.")
        return
    context.user_data["current"] = {"category": category, "index": 0, "items": items}
    await show_question(query, items[0])

async def show_question(query, q):
    text = f"Вопрос: {q['task']}" + (f"\nКод: {q.get('code','')}" if q.get("code") else "")
    keyboard = [[
        InlineKeyboardButton("Да", callback_data=f"ans|yes|{q['id']}"),
        InlineKeyboardButton("Нет", callback_data=f"ans|no|{q['id']}"),
        InlineKeyboardButton("Частично", callback_data=f"ans|part|{q['id']}")
    ]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, ans, qid = query.data.split("|")
    qid = int(qid)
    q = next((i for i in questions if i["id"] == qid), None)
    if not q:
        await query.edit_message_text("Ошибка: вопрос не найден")
        return
    user_id = update.effective_user.id
    if ans in ("no","part"):
        context.user_data["pending"] = {"question": q, "answer": "Нет" if ans=="no" else "Частично", "user_id": user_id}
        await query.edit_message_text(f"Вы выбрали '{context.user_data['pending']['answer']}'. Введите комментарий:")
        return
    await send_to_webhook(user_id, q, "Да", "")
    await go_next_question(query, context)

async def on_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending" not in context.user_data:
        return
    pending = context.user_data.pop("pending")
    q = pending["question"]
    await send_to_webhook(pending["user_id"], q, pending["answer"], update.message.text)
    await update.message.reply_text("Комментарий сохранён ✅")
    await go_next_question(update.message, context)

async def go_next_question(msg_or_query, context):
    current = context.user_data.get("current")
    if not current:
        return
    idx = current["index"] + 1
    current["index"] = idx
    items = current["items"]
    if idx < len(items):
        next_q = items[idx]
        if hasattr(msg_or_query, "edit_message_text"):
            await show_question(msg_or_query, next_q)
        else:
            text = f"Вопрос: {next_q['task']}" + (f"\nКод: {next_q.get('code','')}" if next_q.get("code") else "")
            keyboard = [[
                InlineKeyboardButton("Да", callback_data=f"ans|yes|{next_q['id']}"),
                InlineKeyboardButton("Нет", callback_data=f"ans|no|{next_q['id']}"),
                InlineKeyboardButton("Частично", callback_data=f"ans|part|{next_q['id']}")
            ]]
            await msg_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        if hasattr(msg_or_query, "reply_text"):
            await msg_or_query.reply_text("Чек-лист завершён ✅ Спасибо!")
        else:
            await msg_or_query.edit_message_text("Чек-лист завершён ✅ Спасибо!")
        context.user_data.pop("current", None)

async def send_to_webhook(user_id, q, answer, comment):
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "user_id": str(user_id),
        "category": q["category"],
        "task": q["task"],
        "answer": answer,
        "code": q.get("code",""),
        "comment": comment
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print("Ошибка при отправке:", e)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_category, pattern=r"^cat\|"))
    app.add_handler(CallbackQueryHandler(on_answer, pattern=r"^ans\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_comment))

    # Вебхук
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}"
    )

if __name__ == "__main__":
    main()
