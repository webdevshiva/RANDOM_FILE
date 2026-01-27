import os
import random
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    Application
)

# ================= LOGGING SETUP =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8198318399:AAEK3qvRpSr6EqKldxBXnlDfcsjhUdWPPhU")
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://baleny:zpQKH66B4AaYldIx@cluster0.ichdp1p.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1002686058050"))
PORT = int(os.getenv("PORT", "8080"))

# Admin ID Configuration
ADMINS_STR = os.getenv("ADMIN_IDS", "5298223577")
ADMINS = []
try:
    # Handles comma separated string "123, 456"
    ADMINS = [int(x.strip()) for x in ADMINS_STR.split(",") if x.strip().isdigit()]
except Exception as e:
    logger.error(f"Error parsing ADMIN_IDS: {e}")
    ADMINS = [5298223577] # Fallback

# Payment / Contact Info
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "cinewood_flix") 
UPI_ID = os.getenv("UPI_ID", "your-upi@paytm")

# ================= CHANNEL SETUP =================
FORCE_SUB_CHANNELS = [-1002302092974, -1003208417224, -1003549158411]
CATEGORY_CHANNELS = {
    "🎬 All ": -1003549767561,
}
# Example: -100123456789
CHANNEL_JOIN_PLAN = [] 
DEFAULT_CHANNEL = -1002539932770

# ================= BOT SETTINGS =================
TRIAL_HOURS = 24
REFERRAL_REQUIREMENT = 3 # Increased slightly to make premium valuable
MAX_DAILY_VIDEOS_TRIAL = 10
MAX_DAILY_VIDEOS_PREMIUM = 1000
MAX_DAILY_VIDEOS_EXTRA_TRIAL = 15

CAPTION_TEXT = (
    "ⓘ 𝙏𝙝𝙞𝙨 𝙢𝙚𝙙𝙞𝙖 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙖𝙪𝙩𝙤𝙢𝙖𝙩𝙞𝙘𝙖𝙡𝙡𝙮 𝙙𝙚𝙡𝙚𝙩𝙚𝙙 𝙖𝙛𝙩𝙚𝙧 10 𝙢𝙞𝙣𝙪𝙩𝙚𝙨.\n"
    "𝙋𝙡𝙚𝙖𝙨𝙚 𝙗𝙤𝙤𝙠𝙢𝙖𝙧𝙠 𝙤𝙧 𝙙𝙤𝙬𝙣𝙡𝙤𝙖𝙙 𝙞𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙬𝙖𝙩𝙘𝙝 𝙡𝙖𝙩𝙚𝙧.\n\n\n"
    "━━━━━━━━━━━━━━━\n"
    "🤖 𝙈𝙤𝙫𝙞𝙚 𝘽𝙤𝙤𝙩 : @ChaudharyAutoFilterbot\n"
    "📢 𝘽𝙖𝙘𝙠𝙪𝙥 𝘾𝙝𝙖𝙣𝙣𝙚𝙡 : @cinewood_flix\n"
    "🔒 𝙋𝙧𝙞𝙫𝙖𝙩𝙚 𝘾𝙝𝙖𝙣𝙣𝙚𝙡 : https://t.me/+IKEPBquEvmc0ODhl\n"
    "━━━━━━━━━━━━━━━"
)

# ================= DATABASE SETUP =================
client = AsyncIOMotorClient(
    MONGO_URI,
    tls=True,
    tlsAllowInvalidCertificates=False,
    connectTimeoutMS=30000,
    socketTimeoutMS=30000,
    serverSelectionTimeoutMS=30000
)

db = client["telegram_bot_db"]
users_col = db["users"]
media_col = db["media"]

# ================= UTILITY FUNCTIONS =================

def now():
    return datetime.now()

def format_datetime(dt_str):
    if isinstance(dt_str, str):
        try:
            dt = datetime.fromisoformat(dt_str)
        except ValueError:
            dt = datetime.now()
    else:
        dt = dt_str
    return dt.strftime("%d/%m/%Y, %I:%M %p")

async def check_user_membership(bot, user_id, channels):
    if not channels: 
        return True
    for channel_id in channels:
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            # If bot isn't admin or channel is private/invalid, skip checking this one
            continue
    return True

# ================= KEYBOARDS =================

def get_main_keyboard(is_admin=False):
    buttons = [
        [InlineKeyboardButton("▶ Start Browsing", callback_data="send_media")],
        [InlineKeyboardButton("📊 My Status", callback_data="status"),
         InlineKeyboardButton("💎 Plans", callback_data="plans")],
        [InlineKeyboardButton("🔄 Change Category", callback_data="change_category")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_media_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👍 Like", callback_data="like"), 
         InlineKeyboardButton("👎 Dislike", callback_data="dislike")],
        [InlineKeyboardButton("⏮ Previous", callback_data="previous"), 
         InlineKeyboardButton("⏭ Next", callback_data="next")],
        [InlineKeyboardButton("🔄 Category", callback_data="change_category"), 
         InlineKeyboardButton("❌ Close", callback_data="close")]
    ])

def get_plans_keyboard():
    buttons = [
        [InlineKeyboardButton("💰 Paid Plan (Unlimited)", callback_data="plan_paid")],
        [InlineKeyboardButton("🔗 Referral Plan (Free)", callback_data="plan_referral")]
    ]
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

def get_category_keyboard():
    buttons = []
    for category in CATEGORY_CHANNELS.keys():
        buttons.append([InlineKeyboardButton(f"{category}", callback_data=f"set_category_{category}")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

def get_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Premium to User", callback_data="admin_add_premium")],
        [InlineKeyboardButton("📤 Index Channel", callback_data="admin_index")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_menu")]
    ])

# ================= USER MANAGER =================

class UserManager:
    async def get_user(self, user_id):
        return await users_col.find_one({"_id": str(user_id)})

    async def create_user(self, user_id, name):
        expiry = now() + timedelta(hours=TRIAL_HOURS)
        default_cat = list(CATEGORY_CHANNELS.keys())[0] if CATEGORY_CHANNELS else "🎬 All "
        user_data = {
            "_id": str(user_id),
            "name": name,
            "plan": "trial",
            "expires": expiry.isoformat(),
            "referrals": 0,
            "daily_videos": 0,
            "current_category": default_cat,
            "last_sent_media": [],
            "last_activity": now().isoformat(),
            "joined_date": now().isoformat()
        }
        await users_col.update_one({"_id": str(user_id)}, {"$set": user_data}, upsert=True)
        return user_data

    async def update_user(self, user_id, updates):
        updates["last_activity"] = now().isoformat()
        await users_col.update_one({"_id": str(user_id)}, {"$set": updates})

    async def add_referral(self, referrer_id):
        referrer = await self.get_user(referrer_id)
        if referrer:
            new_refs = referrer.get("referrals", 0) + 1
            upd = {"referrals": new_refs}
            # Auto reward
            if new_refs % REFERRAL_REQUIREMENT == 0:
                try:
                    current_exp = datetime.fromisoformat(referrer["expires"])
                    if current_exp < now(): current_exp = now()
                    new_exp = current_exp + timedelta(days=1) # 1 Day reward
                    upd.update({"expires": new_exp.isoformat(), "plan": "referral_bonus"})
                except: pass
            await self.update_user(referrer_id, upd)

    async def is_premium(self, user_id):
        user = await self.get_user(user_id)
        if not user: return False
        try:
            return datetime.fromisoformat(user["expires"]) > now()
        except: return False

    async def set_premium(self, user_id, days):
        user = await self.get_user(user_id)
        start_date = now()
        if user:
            try:
                current_exp = datetime.fromisoformat(user["expires"])
                if current_exp > now(): start_date = current_exp
            except: pass
        
        new_exp = start_date + timedelta(days=days)
        await users_col.update_one(
            {"_id": str(user_id)},
            {"$set": {"expires": new_exp.isoformat(), "plan": "premium", "daily_videos": 0}},
            upsert=True
        )
        return new_exp

# ================= MEDIA MANAGER =================

class MediaManager:
    async def add_media(self, channel_id, message_id):
        await media_col.update_one(
            {"channel_id": str(channel_id)},
            {"$addToSet": {"message_ids": message_id}},
            upsert=True
        )

    async def get_intelligent_media(self, channel_id, user_last_seen_ids=None):
        doc = await media_col.find_one({"channel_id": str(channel_id)})
        if not doc or not doc.get("message_ids"): return None
        all_ids = doc["message_ids"]
        if not user_last_seen_ids: return random.choice(all_ids)
        seen_set = set(user_last_seen_ids[-50:])
        unseen = [m for m in all_ids if m not in seen_set]
        return random.choice(unseen) if unseen else random.choice(all_ids)

    async def get_media_count(self):
        total = 0
        async for doc in media_col.find():
            total += len(doc.get("message_ids", []))
        return total

    async def index_single_message(self, bot, channel_id, message_id):
        try:
            existing = await media_col.find_one({"channel_id": str(channel_id), "message_ids": message_id})
            if existing: return False
            msg = await bot.get_message(channel_id, message_id)
            if msg.photo or msg.video or msg.document:
                await media_col.update_one({"channel_id": str(channel_id)}, {"$addToSet": {"message_ids": message_id}}, upsert=True)
                return True
            return False
        except: return False

user_manager = UserManager()
media_manager = MediaManager()

# ================= MAIN BOT FEATURES =================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Referral Logic
    args = context.args
    if args and args[0].startswith("ref_"):
        ref_id = args[0].split("ref_")[1]
        if ref_id != str(user.id):
            await user_manager.add_referral(ref_id)

    user_data = await user_manager.get_user(user.id)
    if not user_data:
        user_data = await user_manager.create_user(user.id, user.full_name)
        try:
            await context.bot.send_message(LOG_CHANNEL_ID, f"🆕 New User: {user.full_name} ({user.id})")
        except: pass

    # Check Join
    if not await check_user_membership(context.bot, user.id, FORCE_SUB_CHANNELS):
        buttons = []
        for cid in FORCE_SUB_CHANNELS:
            try:
                chat = await context.bot.get_chat(cid)
                link = chat.invite_link or await chat.export_invite_link()
                buttons.append([InlineKeyboardButton(f"🔔 Join {chat.title}", url=link)])
            except: pass
        buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_join")])
        await update.message.reply_text("❗ Join channels to use bot:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Welcome
    is_admin = user.id in ADMINS
    text = (
        f"✨ Welcome {user.full_name}!\n\n"
        f"📁 Category: {user_data.get('current_category', 'All')}\n"
        f"🎁 Plan: {user_data.get('plan', 'trial').title()}\n"
        f"⏳ Expires: {format_datetime(user_data['expires'])}"
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin))

async def send_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not await user_manager.is_premium(user_id):
        await query.message.reply_text("❌ Plan Expired! Upgrade now.", reply_markup=get_plans_keyboard())
        return

    user_data = await user_manager.get_user(user_id)
    limit = MAX_DAILY_VIDEOS_PREMIUM if user_data.get("plan") == "premium" else MAX_DAILY_VIDEOS_TRIAL
    
    if user_data.get("daily_videos", 0) >= limit:
        await query.message.reply_text("📊 Daily limit reached.", reply_markup=get_plans_keyboard())
        return

    cat = user_data.get("current_category", "🎬 All ")
    cid = CATEGORY_CHANNELS.get(cat, DEFAULT_CHANNEL)
    mid = await media_manager.get_intelligent_media(cid, user_data.get("last_sent_media", []))
    
    if not mid:
        await query.message.reply_text("📭 No media found.")
        return

    try:
        sent = await context.bot.copy_message(user_id, cid, mid, caption=CAPTION_TEXT, reply_markup=get_media_keyboard())
        await user_manager.update_user(user_id, {
            "daily_videos": user_data.get("daily_videos", 0) + 1,
            "last_sent_media": (user_data.get("last_sent_media", []) + [mid])[-100:]
        })
        asyncio.create_task(auto_delete(context, user_id, sent.message_id))
    except Exception as e:
        logger.error(f"Send failed: {e}")
        await query.message.reply_text("❌ Media unavailable (likely deleted). Try again.")

async def auto_delete(context, chat_id, mid):
    await asyncio.sleep(600)
    try: await context.bot.delete_message(chat_id, mid)
    except: pass

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "💎 <b>Premium Plans</b>\n\n"
        "1️⃣ <b>Referral Plan:</b> Share bot and get free access.\n"
        "2️⃣ <b>Paid Plan:</b> Unlimited access for 30 days.\n\n"
        "Select an option below:",
        reply_markup=get_plans_keyboard(),
        parse_mode="HTML"
    )

async def handle_plans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user
    
    if data == "plan_paid":
        await query.message.edit_text(
            f"💰 <b>Paid Subscription</b>\n\n"
            f"• Price: ₹50 / Month\n"
            f"• UPI ID: <code>{UPI_ID}</code>\n\n"
            f"Send screenshot to @{OWNER_USERNAME} after payment.",
            parse_mode="HTML",
            reply_markup=get_plans_keyboard()
        )
    elif data == "plan_referral":
        link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"
        user_data = await user_manager.get_user(user.id)
        refs = user_data.get('referrals', 0)
        await query.message.edit_text(
            f"🔗 <b>Referral Program</b>\n\n"
            f"Invite friends to get free access!\n"
            f"Get 1 day premium for every {REFERRAL_REQUIREMENT} invites.\n\n"
            f"👥 Your Referrals: {refs}\n"
            f"🔗 Link: <code>{link}</code>",
            parse_mode="HTML",
            reply_markup=get_plans_keyboard()
        )

# ================= ADMIN HANDLERS =================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admins Only!", show_alert=True)
        return
    await query.message.edit_text("⚙️ <b>Admin Panel</b>", reply_markup=get_admin_keyboard(), parse_mode="HTML")

# --- Admin Add Premium Conversation ---
async def admin_premium_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMINS: return ConversationHandler.END
    await query.message.edit_text("👤 <b>Send User ID</b> to add premium:", parse_mode="HTML")
    return "GET_USER_ID"

async def admin_premium_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())
        context.user_data['premium_user_id'] = user_id
        await update.message.reply_text("📅 <b>Enter Number of Days:</b> (e.g., 30)", parse_mode="HTML")
        return "GET_DAYS"
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Try again or /cancel")
        return "GET_USER_ID"

async def admin_premium_get_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        user_id = context.user_data['premium_user_id']
        new_exp = await user_manager.set_premium(user_id, days)
        
        # Notify Admin
        await update.message.reply_text(
            f"✅ <b>Success!</b>\nUser: {user_id}\nAdded: {days} days\nExpires: {format_datetime(new_exp)}",
            parse_mode="HTML"
        )
        # Notify User
        try:
            await context.bot.send_message(user_id, f"🎉 <b>Premium Activated!</b>\nValidity: {days} days\nEnjoy unlimited movies!", parse_mode="HTML")
        except: pass
        
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Enter digits only.")
        return "GET_DAYS"

# --- Admin Indexing ---
async def admin_index_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMINS: return ConversationHandler.END
    await query.message.edit_text("📤 Send Channel Link or ID:", parse_mode="HTML")
    return "GET_CHANNEL"

async def admin_index_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        chat = await context.bot.get_chat(text if text.startswith("-") or text.startswith("@") else f"@{text.split('/')[-1]}")
        context.user_data['index_channel'] = chat.id
        await update.message.reply_text(
            f"✅ Found: {chat.title}\n"
            "🔢 Enter range (e.g. `1-100`) or type `latest` for last 100:",
            parse_mode="HTML"
        )
        return "GET_RANGE"
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def admin_index_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    channel_id = context.user_data['index_channel']
    start_id, end_id = 0, 0
    
    msg = await update.message.reply_text("🚀 Starting...")
    
    if text.lower() == "latest":
        try:
            temp = await context.bot.send_message(channel_id, ".")
            end_id = temp.message_id
            await context.bot.delete_message(channel_id, end_id)
            start_id = max(1, end_id - 100)
        except:
            await msg.edit_text("❌ Bot not admin in channel!")
            return ConversationHandler.END
    elif "-" in text:
        s, e = text.split("-")
        start_id, end_id = int(s), int(e)
    
    asyncio.create_task(run_indexing(context.bot, update.effective_user.id, channel_id, start_id, end_id))
    return ConversationHandler.END

async def run_indexing(bot, admin_id, channel_id, start, end):
    indexed = 0
    for i in range(start, end + 1):
        if await media_manager.index_single_message(bot, channel_id, i):
            indexed += 1
        if i % 20 == 0: await asyncio.sleep(1) # Anti-flood
    await bot.send_message(admin_id, f"✅ Indexing Done!\nIndexed: {indexed} files.")

async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Cancelled.")
    return ConversationHandler.END

# ================= DISPATCHER =================

async def callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    user_id = update.callback_query.from_user.id
    
    if data == "status":
        user_data = await user_manager.get_user(user_id)
        exp = datetime.fromisoformat(user_data["expires"])
        await update.callback_query.message.edit_text(
            f"📊 <b>Status</b>\nPlan: {user_data['plan']}\nExpires: {format_datetime(exp)}\nRef: {user_data.get('referrals',0)}",
            reply_markup=get_main_keyboard(user_id in ADMINS), parse_mode="HTML"
        )
    elif data == "send_media":
        await send_media_handler(update, context)
    elif data == "change_category" or data.startswith("set_category_"):
        if data == "change_category":
            await update.callback_query.message.edit_text("Select Category:", reply_markup=get_category_keyboard())
        else:
            cat = data.replace("set_category_", "")
            await user_manager.update_user(user_id, {"current_category": cat})
            await update.callback_query.message.edit_text(f"✅ Set to {cat}", reply_markup=get_main_keyboard(user_id in ADMINS))
    elif data == "plans":
        await plans_command(update, context)
    elif data in ["plan_paid", "plan_referral"]:
        await handle_plans_callback(update, context)
    elif data == "admin_panel":
        await admin_panel(update, context)
    elif data == "back_to_menu":
        await update.callback_query.message.edit_text("✨ Main Menu", reply_markup=get_main_keyboard(user_id in ADMINS))
    elif data == "admin_stats":
        # Simple stats
        count = await users_col.count_documents({})
        media = await media_manager.get_media_count()
        await update.callback_query.message.edit_text(f"📊 <b>Stats</b>\nUsers: {count}\nMedia: {media}", reply_markup=get_admin_keyboard(), parse_mode="HTML")
    elif data == "check_join":
        if await check_user_membership(context.bot, user_id, FORCE_SUB_CHANNELS):
            await update.callback_query.message.delete()
            await update.callback_query.message.reply_text("✅ Verified!", reply_markup=get_main_keyboard(user_id in ADMINS))
        else:
            await update.callback_query.answer("❌ Not joined yet!", show_alert=True)
    elif data in ["like", "dislike", "close"]:
        await update.callback_query.answer("Feedback recorded!")
        if data == "close": await update.callback_query.message.delete()

async def save_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if msg and (msg.video or msg.document or msg.photo):
        await media_manager.add_media(msg.chat_id, msg.message_id)

# ================= RENDER SERVER =================

async def web_start():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    logger.info(f"🌍 Web server running on port {PORT}")

async def post_init(app: Application):
    await web_start()
    try:
        await client.admin.command('ping')
        logger.info("✅ MongoDB Connected")
    except Exception as e:
        logger.error(f"❌ DB Error: {e}")

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Admin Conversations
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_premium_start, pattern="^admin_add_premium$")],
        states={
            "GET_USER_ID": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_premium_get_id)],
            "GET_DAYS": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_premium_get_days)]
        },
        fallbacks=[CommandHandler("cancel", cancel_op)]
    ))
    
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_index_start, pattern="^admin_index$")],
        states={
            "GET_CHANNEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_index_channel)],
            "GET_RANGE": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_index_run)]
        },
        fallbacks=[CommandHandler("cancel", cancel_op)]
    ))

    # General Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_dispatcher))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, save_media))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
