"""
handlers/user.py - All user-facing handlers (start, categories, help, my orders)
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import messages
import keyboards
from database import Database
from utils import is_admin

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = await Database.get_instance()

    # Upsert user record
    await db.upsert_user(user.id, user.username, user.full_name)

    # Maintenance check (skip for admins)
    if not is_admin(user.id):
        maintenance = await db.get_setting("maintenance")
        if maintenance == "true":
            await update.message.reply_text(messages.maintenance(), parse_mode="Markdown")
            return

        if await db.is_banned(user.id):
            await update.message.reply_text(messages.banned(), parse_mode="Markdown")
            return

    await update.message.reply_text(
        messages.welcome(user.first_name),
        reply_markup=keyboards.main_menu_kb(),
        parse_mode="Markdown",
    )


async def cbq_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        messages.welcome(query.from_user.first_name),
        reply_markup=keyboards.main_menu_kb(),
        parse_mode="Markdown",
    )


async def cbq_browse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    categories = await db.get_categories()

    if not categories:
        await query.edit_message_text(
            messages.no_categories(),
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode="Markdown",
        )
        return

    await query.edit_message_text(
        "🛍️ *Available Categories*\n\nSelect a category to continue:",
        reply_markup=keyboards.categories_kb(categories),
        parse_mode="Markdown",
    )


async def cbq_select_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("_")[1])
    db = await Database.get_instance()

    cat = await db.get_category(cat_id)
    if not cat:
        await query.answer("Category not found!", show_alert=True)
        return

    stock = await db.stock_count(cat_id)

    if stock == 0:
        await query.edit_message_text(
            messages.out_of_stock_msg(cat["name"]),
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode="Markdown",
        )
        return

    await query.edit_message_text(
        messages.category_detail(cat["name"], cat["price"], stock),
        reply_markup=keyboards.quantity_kb(cat_id),
        parse_mode="Markdown",
    )


async def cbq_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        messages.help_msg(),
        reply_markup=keyboards.back_to_main_kb(),
        parse_mode="Markdown",
    )


async def cbq_my_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()

    orders = await db.fetchall(
        "SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (query.from_user.id,),
    )

    if not orders:
        await query.edit_message_text(
            "📦 *No orders found.*\n\nYou haven't placed any orders yet!",
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode="Markdown",
        )
        return

    await query.edit_message_text(
        "📦 *Your Recent Orders:*\n\nSelect an order to view details.",
        reply_markup=keyboards.my_orders_kb(orders),
        parse_mode="Markdown",
    )


async def cbq_view_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("view_order_")[1]
    db = await Database.get_instance()

    order = await db.get_order(order_id)
    if not order or order["user_id"] != query.from_user.id:
        await query.answer("Order not found!", show_alert=True)
        return

    cat = await db.get_category(order["category_id"])
    status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌", "cancelled": "🚫"}.get(
        order["status"], "❓"
    )

    text = (
        f"📋 *Order Details*\n\n"
        f"Order ID   : `{order['order_id']}`\n"
        f"Category   : {cat['name'] if cat else 'N/A'}\n"
        f"Quantity   : {order['quantity']}\n"
        f"Amount     : ₹{order['amount']:.2f}\n"
        f"Status     : {status_emoji} {order['status'].upper()}\n"
        f"Date       : {order['created_at'][:16]}\n"
    )
    if order.get("reject_reason"):
        text += f"\n❌ Reject Reason: {order['reject_reason']}"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 My Orders", callback_data="my_orders")]
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


def register_user_handlers(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cbq_main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(cbq_browse, pattern="^browse$"))
    app.add_handler(CallbackQueryHandler(cbq_select_category, pattern=r"^cat_\d+$"))
    app.add_handler(CallbackQueryHandler(cbq_help, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(cbq_my_orders, pattern="^my_orders$"))
    app.add_handler(CallbackQueryHandler(cbq_view_order, pattern=r"^view_order_ORD-\w+-\w+$"))
