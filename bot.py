import os
import random
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# ================= CONFIGURATION =================
BOT_TOKEN = "8198318399:AAEK3qvRpSr6EqKldxBXnlDfcsjhUdWPPhU"
MONGO_URI = "mongodb+srv://baleny:zpQKH66B4AaYldIx@cluster0.ichdp1p.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN not set!")
    exit(1)

# ================= DATABASE SETUP =================
# MongoDB Atlas connection with proper configuration
client = AsyncIOMotorClient(
    MONGO_URI,
    tls=True,  # Enable TLS/SSL for Atlas
    tlsAllowInvalidCertificates=False,  # For security
    connectTimeoutMS=30000,
    socketTimeoutMS=30000,
    serverSelectionTimeoutMS=30000
)

# Database and collections
db = client["telegram_bot_db"]
users_col = db["users"]
media_col = db["media"]

# Test connection
async def test_mongodb_connection():
    try:
        await client.admin.command('ping')
        print("✅ MongoDB Connection Successful!")
        # Create indexes for better performance
        await users_col.create_index("_id")
        await users_col.create_index("plan")
        await users_col.create_index("expires")
        await media_col.create_index("channel_id")
        print("✅ Database indexes created!")
    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}")
        exit(1)

# ================= CHANNEL SETUP =================
FORCE_SUB_CHANNELS = [-1002302092974, -1003208417224, -1003549158411]
CATEGORY_CHANNELS = {
    "🎬 All ": -1003549767561,
}
CHANNEL_JOIN_PLAN = []
DEFAULT_CHANNEL = -1002539932770
LOG_CHANNEL_ID = -1002686058050
ADMINS = [5298223577]

# ================= BOT SETTINGS =================
TRIAL_HOURS = 24
REFERRAL_REQUIREMENT = 1
MAX_DAILY_VIDEOS_TRIAL = 10
MAX_DAILY_VIDEOS_PREMIUM = 1000
MAX_DAILY_VIDEOS_EXTRA_TRIAL = 15

CAPTION_TEXT = (
    "ⓘ 𝙏𝙝𝙞𝙨 𝙢𝙚𝙙𝙞𝙖 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙖𝙪𝙩𝙤𝙢𝙖𝙩𝙞𝙘𝙖𝙡𝙡𝙮 𝙙𝙚𝙡𝙚𝙩𝙚𝙙 𝙖𝙛𝙩𝙚𝙧 10 𝙢𝙞𝙣𝙪𝙩𝙚𝙨.\n"
    "𝙋𝙡𝙚𝙖𝙨𝙚 𝙗𝙤𝙤𝙠𝙢𝙖𝙧𝙠 𝙤𝙧 𝙙𝙤𝙬𝙣𝙡𝙤𝙖𝙙 𝙞𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙬𝙖𝙩𝙘𝙝 𝙡𝙖𝙩𝙚𝙧.\n\n\n"
    "━━━━━━━━━━━━━━━\n"
    "🤖 𝙈𝙤𝙫𝙞𝙚 𝘽𝙤𝙩 : @ChaudharyAutoFilterbot\n"
    "📢 𝘽𝙖𝙘𝙠𝙪𝙥 𝘾𝙝𝙖𝙣𝙣𝙚𝙡 : @cinewood_flix\n"
    "🔒 𝙋𝙧𝙞𝙫𝙖𝙩𝙚 𝘾𝙝𝙖𝙣𝙣𝙚𝙡 : https://t.me/+IKEPBquEvmc0ODhl\n"
    "━━━━━━━━━━━━━━━"
)

# ================= UTILITY FUNCTIONS =================

def now():
    return datetime.now()

def format_datetime(dt_str):
    if isinstance(dt_str, str):
        dt = datetime.fromisoformat(dt_str)
    else:
        dt = dt_str
    return dt.strftime("%d/%m/%Y, %I:%M %p")

async def check_user_membership(bot, user_id, channels):
    if not channels: return True
    for channel_id in channels:
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logging.error(f"Membership error: {e}")
            return False
    return True

# ================= KEYBOARDS =================

def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶ Start Browsing", callback_data="send_media")],
        [InlineKeyboardButton("📊 My Status", callback_data="status")],
        [InlineKeyboardButton("💎 Plans", callback_data="plans")],
        [InlineKeyboardButton("🔄 Change Category", callback_data="change_category")]
    ])

def get_media_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👍 Like", callback_data="like"), InlineKeyboardButton("👎 Dislike", callback_data="dislike")],
        [InlineKeyboardButton("⬇ Download", callback_data="download"), InlineKeyboardButton("⭐ Bookmark", callback_data="bookmark")],
        [InlineKeyboardButton("⏮ Previous", callback_data="previous"), InlineKeyboardButton("⏭ Next", callback_data="next")],
        [InlineKeyboardButton("🔄 Change Category", callback_data="change_category"), InlineKeyboardButton("❌ Close", callback_data="close")]
    ])

def get_plans_keyboard():
    buttons = [[InlineKeyboardButton("💰 Paid Plan", callback_data="plan_paid")],
               [InlineKeyboardButton("🔗 Referral Plan", callback_data="plan_referral")]]
    if CHANNEL_JOIN_PLAN:
        buttons.append([InlineKeyboardButton("📢 Channel Join Plan", callback_data="plan_channel")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

def get_category_keyboard():
    buttons = []
    for category in CATEGORY_CHANNELS.keys():
        buttons.append([InlineKeyboardButton(f"{category}", callback_data=f"set_category_{category}")])
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

# ================= MANAGERS (MONGODB) =================

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
            "daily_downloads": 0,
            "category_changes": 0,
            "searches": 0,
            "bookmarks": [],
            "current_category": default_cat,
            "last_sent_media": [],
            "last_activity": now().isoformat(),
            "joined_date": now().isoformat(),
            "extra_trial_given": False
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
            if new_refs >= REFERRAL_REQUIREMENT and not referrer.get("extra_trial_given", False):
                new_exp = datetime.fromisoformat(referrer["expires"]) + timedelta(days=1)
                upd.update({"expires": new_exp.isoformat(), "extra_trial_given": True, "plan": "extra_trial"})
            await self.update_user(referrer_id, upd)

    async def is_premium(self, user_id):
        user = await self.get_user(user_id)
        if not user: return False
        return datetime.fromisoformat(user["expires"]) > now()

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
        
        unseen = [m for m in all_ids if m not in user_last_seen_ids[-50:]]
        if unseen: return random.choice(unseen)
        
        avoid_recent = set(user_last_seen_ids[-10:])
        available = [m for m in all_ids if m not in avoid_recent]
        return random.choice(available) if available else random.choice(all_ids)

    async def get_media_count(self, channel_id=None):
        if channel_id:
            doc = await media_col.find_one({"channel_id": str(channel_id)})
            return len(doc.get("message_ids", [])) if doc else 0
        else:
            total = 0
            async for doc in media_col.find():
                total += len(doc.get("message_ids", []))
            return total

# ================= HANDLERS =================

user_manager = UserManager()
media_manager = MediaManager()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if FORCE_SUB_CHANNELS:
        if not await check_user_membership(context.bot, user.id, FORCE_SUB_CHANNELS):
            buttons = []
            for cid in FORCE_SUB_CHANNELS:
                try:
                    chat = await context.bot.get_chat(cid)
                    buttons.append([InlineKeyboardButton(f"🔔 Join {chat.title}", url=chat.invite_link or await chat.export_invite_link())])
                except: continue
            buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_join")])
            await update.message.reply_text("❗ Join our channels to use the bot:", reply_markup=InlineKeyboardMarkup(buttons))
            return

    user_data = await user_manager.get_user(user.id)
    if not user_data:
        if update.message.text and "ref_" in update.message.text:
            ref_id = update.message.text.split("ref_")[1]
            if ref_id != str(user.id): await user_manager.add_referral(ref_id)
        user_data = await user_manager.create_user(user.id, user.full_name)
        await context.bot.send_message(LOG_CHANNEL_ID, f"🆕 New User: {user.full_name} ({user.id})")

    text = f"✨ Welcome {user_data['name']}!\n\nCategory: {user_data['current_category']}\nPlan: {user_data['plan'].title()}"
    await update.message.reply_text(text, reply_markup=get_main_keyboard())

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_data = await user_manager.get_user(query.from_user.id)
    
    expiry = datetime.fromisoformat(user_data["expires"])
    total_m = await media_manager.get_media_count()
    
    status_text = (
        f"📊 <b>My Status</b>\n\n👤 {user_data['name']}\n🎁 Plan: {user_data['plan'].title()}\n"
        f"⏳ Expires: {format_datetime(expiry)}\n🎬 Category: {user_data['current_category']}\n"
        f"✅ Watched Today: {user_data.get('daily_videos', 0)}\n🔗 Referrals: {user_data['referrals']}"
    )
    await query.message.edit_text(status_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

async def send_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_data = await user_manager.get_user(query.from_user.id)

    if not await user_manager.is_premium(query.from_user.id):
        await query.message.reply_text("❌ Trial Expired!", reply_markup=get_plans_keyboard())
        return

    # Daily Limit Logic
    plan = user_data.get("plan", "trial")
    limit = MAX_DAILY_VIDEOS_PREMIUM if plan == "premium" else (MAX_DAILY_VIDEOS_EXTRA_TRIAL if plan == "extra_trial" else MAX_DAILY_VIDEOS_TRIAL)
    
    if user_data.get("daily_videos", 0) >= limit:
        await query.message.reply_text(f"📊 Daily Limit ({limit}) Reached!", reply_markup=get_plans_keyboard())
        return

    cat = user_data.get("current_category", "🎬 All ")
    cid = CATEGORY_CHANNELS.get(cat, DEFAULT_CHANNEL)
    
    mid = await media_manager.get_intelligent_media(cid, user_data.get("last_sent_media", []))
    if not mid:
        await query.message.reply_text("📭 No media found in this category.")
        return

    try:
        sent = await context.bot.copy_message(
            chat_id=query.from_user.id, from_chat_id=cid, message_id=mid,
            caption=CAPTION_TEXT + f"\n\n🎬 Category: {cat}", reply_markup=get_media_keyboard()
        )
        
        last_sent = user_data.get("last_sent_media", [])
        last_sent.append(mid)
        await user_manager.update_user(query.from_user.id, {
            "daily_videos": user_data.get("daily_videos", 0) + 1,
            "last_sent_media": last_sent[-100:]
        })
        asyncio.create_task(auto_delete(context, query.from_user.id, sent.message_id))
    except Exception as e:
        logging.error(f"Send error: {e}")

async def auto_delete(context, chat_id, mid):
    await asyncio.sleep(600)
    try: await context.bot.delete_message(chat_id, mid)
    except: pass

async def change_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "change_category":
        await query.message.edit_text("🎬 Select a Category:", reply_markup=get_category_keyboard())
    else:
        cat = query.data.replace("set_category_", "")
        await user_manager.update_user(query.from_user.id, {"current_category": cat})
        await query.message.edit_text(f"✅ Category set to: {cat}", reply_markup=get_main_keyboard())

async def save_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and (update.channel_post.photo or update.channel_post.video):
        await media_manager.add_media(update.channel_post.chat_id, update.channel_post.message_id)

async def callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "status": await status_command(update, context)
    elif data == "send_media": await send_media_handler(update, context)
    elif data == "change_category" or data.startswith("set_category_"): await change_category_handler(update, context)
    elif data == "back_to_menu":
        user_data = await user_manager.get_user(update.callback_query.from_user.id)
        await update.callback_query.message.edit_text(f"✨ Welcome back {user_data['name']}!", reply_markup=get_main_keyboard())

def main():
    # Test MongoDB connection before starting bot
    asyncio.run(test_mongodb_connection())
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_dispatcher))
    
    # Media Auto-save from channels
    all_cids = list(set(list(CATEGORY_CHANNELS.values()) + [DEFAULT_CHANNEL]))
    app.add_handler(MessageHandler(filters.Chat(chat_id=all_cids) & (filters.PHOTO | filters.VIDEO), save_media_handler))
    
    print("🚀 Bot is running with MongoDB Atlas...")
    app.run_polling()

if __name__ == "__main__":
    main()
