import os
import random
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web  # Required for Render Web Service
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
# NOTE: It is recommended to set these in Render Environment Variables, not hardcode them.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8198318399:AAEK3qvRpSr6EqKldxBXnlDfcsjhUdWPPhU")
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://baleny:zpQKH66B4AaYldIx@cluster0.ichdp1p.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1002686058050"))
PORT = int(os.getenv("PORT", "8080"))  # Render sets this automatically

ADMINS_STR = os.getenv("ADMIN_IDS", "5298223577")
# Robust admin ID parsing
ADMINS = []
if ADMINS_STR:
    ADMINS = [int(x.strip()) for x in ADMINS_STR.split(",") if x.strip().isdigit()]

# ================= CHANNEL SETUP =================
FORCE_SUB_CHANNELS = [-1002302092974, -1003208417224, -1003549158411]
CATEGORY_CHANNELS = {
    "🎬 All ": -1003549767561,
}
CHANNEL_JOIN_PLAN = []
DEFAULT_CHANNEL = -1002539932770

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
    "🤖 𝙈𝙤𝙫𝙞𝙚 𝘽𝙤𝙤𝙩 : @ChaudharyAutoFilterbot\n"
    "📢 𝘽𝙖𝙘𝙠𝙪𝙥 𝘾𝙝𝙖𝙣𝙣𝙚𝙡 : @cinewood_flix\n"
    "🔒 𝙋𝙧𝙞𝙫𝙖𝙩𝙚 𝘾𝙝𝙖𝙣𝙣𝙚𝙡 : https://t.me/+IKEPBquEvmc0ODhl\n"
    "━━━━━━━━━━━━━━━"
)

# ================= DATABASE SETUP =================
# Initialize client globally but connect in post_init
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
    """Check if user is member of required channels"""
    if not channels: 
        return True
    for channel_id in channels:
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logger.error(f"Membership error for {channel_id}: {e}")
            # If bot can't check (not admin), we assume True to avoid blocking user
            # return False 
            continue 
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
        [InlineKeyboardButton("👍 Like", callback_data="like"), 
         InlineKeyboardButton("👎 Dislike", callback_data="dislike")],
        [InlineKeyboardButton("⬇ Download", callback_data="download"), 
         InlineKeyboardButton("⭐ Bookmark", callback_data="bookmark")],
        [InlineKeyboardButton("⏮ Previous", callback_data="previous"), 
         InlineKeyboardButton("⏭ Next", callback_data="next")],
        [InlineKeyboardButton("🔄 Change Category", callback_data="change_category"), 
         InlineKeyboardButton("❌ Close", callback_data="close")]
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

def get_admin_keyboard():
    return InlineKeyboardMarkup([
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
                try:
                    current_exp = datetime.fromisoformat(referrer["expires"])
                    # If expired, start from now, else add to current
                    if current_exp < now():
                        current_exp = now()
                    new_exp = current_exp + timedelta(days=1)
                    upd.update({"expires": new_exp.isoformat(), "extra_trial_given": True, "plan": "extra_trial"})
                except:
                    pass
            await self.update_user(referrer_id, upd)

    async def is_premium(self, user_id):
        user = await self.get_user(user_id)
        if not user: 
            return False
        try:
            return datetime.fromisoformat(user["expires"]) > now()
        except:
            return False

    async def reset_daily_counts(self):
        """Reset daily counts for all users (run daily)"""
        await users_col.update_many(
            {},
            {"$set": {"daily_videos": 0, "daily_downloads": 0}}
        )

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
        if not doc or not doc.get("message_ids"): 
            return None
        
        all_ids = doc["message_ids"]
        if not user_last_seen_ids: 
            return random.choice(all_ids)
        
        # Convert to set for faster lookup
        seen_set = set(user_last_seen_ids[-50:])
        unseen = [m for m in all_ids if m not in seen_set]
        
        if unseen: 
            return random.choice(unseen)
        
        # Fallback if everything recently seen
        return random.choice(all_ids)

    async def get_media_count(self, channel_id=None):
        if channel_id:
            doc = await media_col.find_one({"channel_id": str(channel_id)})
            return len(doc.get("message_ids", [])) if doc else 0
        else:
            total = 0
            async for doc in media_col.find():
                total += len(doc.get("message_ids", []))
            return total

    async def index_single_message(self, bot, channel_id: int, message_id: int) -> bool:
        """Index a single message"""
        try:
            # Check if already exists in DB to save API calls
            existing = await media_col.find_one({
                "channel_id": str(channel_id),
                "message_ids": message_id
            })
            if existing:
                return False

            # Get message from Telegram
            try:
                message = await bot.get_message(channel_id, message_id)
            except Exception:
                # Message might be deleted or inaccessible
                return False
            
            # Check if it has media
            if message.photo or message.video or message.document or message.audio:
                # Add to database
                await media_col.update_one(
                    {"channel_id": str(channel_id)},
                    {"$addToSet": {"message_ids": message_id}},
                    upsert=True
                )
                return True
            
            return False
            
        except Exception as e:
            # Don't log every single error to keep logs clean during mass index
            return False

# ================= INITIALIZE MANAGERS =================

user_manager = UserManager()
media_manager = MediaManager()

# ================= MAIN BOT FEATURES =================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - Main feature"""
    user = update.effective_user
    
    # Get or create user FIRST to ensure data exists
    user_data = await user_manager.get_user(user.id)
    if not user_data:
        if context.args and "ref_" in context.args[0]:
            try:
                ref_id = context.args[0].split("ref_")[1]
                if ref_id != str(user.id): 
                    await user_manager.add_referral(ref_id)
            except:
                pass
        
        # Support deep linking via payload
        elif update.message.text and "ref_" in update.message.text:
            try:
                ref_id = update.message.text.split("ref_")[1]
                if ref_id != str(user.id):
                    await user_manager.add_referral(ref_id)
            except:
                pass

        user_data = await user_manager.create_user(user.id, user.full_name)
        try:
            await context.bot.send_message(
                LOG_CHANNEL_ID, 
                f"🆕 New User: {user.full_name} ({user.id})"
            )
        except:
            pass

    # Check force subscription
    if FORCE_SUB_CHANNELS:
        if not await check_user_membership(context.bot, user.id, FORCE_SUB_CHANNELS):
            buttons = []
            for cid in FORCE_SUB_CHANNELS:
                try:
                    chat = await context.bot.get_chat(cid)
                    invite_link = chat.invite_link
                    if not invite_link:
                        # Try to export if bot is admin, otherwise use public link if available
                        try:
                            invite_link = await chat.export_invite_link()
                        except:
                            pass
                    
                    if invite_link:
                        buttons.append([InlineKeyboardButton(f"🔔 Join {chat.title}", url=invite_link)])
                except Exception as e: 
                    logger.error(f"Force sub error for {cid}: {e}")
                    continue
            
            if buttons:
                buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_join")])
                await update.message.reply_text(
                    "❗ Join our channels to use the bot:", 
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                return

    # Send welcome message
    text = (
        f"✨ Welcome {user_data['name']}!\n\n"
        f"📁 Category: {user_data.get('current_category', 'All')}\n"
        f"🎁 Plan: {user_data.get('plan', 'trial').title()}\n"
        f"⏳ Trial Expires: {format_datetime(user_data['expires'])}"
    )
    
    keyboard = get_main_keyboard()
    if user.id in ADMINS:
        # Add admin button for admins
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶ Start Browsing", callback_data="send_media")],
            [InlineKeyboardButton("📊 My Status", callback_data="status")],
            [InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")],
            [InlineKeyboardButton("🔄 Change Category", callback_data="change_category")]
        ])
    
    await update.message.reply_text(text, reply_markup=keyboard)

async def send_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send media to user"""
    query = update.callback_query
    await query.answer()
    
    user_data = await user_manager.get_user(query.from_user.id)
    if not user_data:
        await query.message.reply_text("⚠️ User not found. Type /start")
        return

    # Check premium status
    if not await user_manager.is_premium(query.from_user.id):
        await query.message.reply_text(
            "❌ Trial Expired!\n\n"
            "Upgrade your plan to continue watching.",
            reply_markup=get_plans_keyboard()
        )
        return

    # Daily Limit Logic
    plan = user_data.get("plan", "trial")
    if plan == "premium":
        limit = MAX_DAILY_VIDEOS_PREMIUM
    elif plan == "extra_trial":
        limit = MAX_DAILY_VIDEOS_EXTRA_TRIAL
    else:
        limit = MAX_DAILY_VIDEOS_TRIAL
    
    if user_data.get("daily_videos", 0) >= limit:
        await query.message.reply_text(
            f"📊 Daily Limit ({limit}) Reached!\n\n"
            f"Come back tomorrow or upgrade your plan.",
            reply_markup=get_plans_keyboard()
        )
        return

    # Get category and channel
    cat = user_data.get("current_category", "🎬 All ")
    cid = CATEGORY_CHANNELS.get(cat, DEFAULT_CHANNEL)
    
    # Get media
    mid = await media_manager.get_intelligent_media(cid, user_data.get("last_sent_media", []))
    if not mid:
        await query.message.reply_text(f"📭 No media found in category: {cat}")
        return

    try:
        # Send media with caption
        sent = await context.bot.copy_message(
            chat_id=query.from_user.id,
            from_chat_id=cid,
            message_id=mid,
            caption=CAPTION_TEXT + f"\n\n🎬 Category: {cat}",
            reply_markup=get_media_keyboard()
        )
        
        # Update user stats
        last_sent = user_data.get("last_sent_media", [])
        last_sent.append(mid)
        
        # Keep list manageable
        if len(last_sent) > 100:
            last_sent = last_sent[-100:]

        await user_manager.update_user(query.from_user.id, {
            "daily_videos": user_data.get("daily_videos", 0) + 1,
            "last_sent_media": last_sent
        })
        
        # Auto delete after 10 minutes
        asyncio.create_task(auto_delete(context, query.from_user.id, sent.message_id))
        
    except Exception as e:
        logger.error(f"Send error: {e}")
        # If message not found (deleted from channel), remove from DB
        if "message to copy not found" in str(e).lower():
             await media_col.update_one(
                {"channel_id": str(cid)},
                {"$pull": {"message_ids": mid}}
             )
             # Try again recursively (once)
             # await send_media_handler(update, context) 
        await query.message.reply_text("❌ Error sending media. Try again or change category.")

async def auto_delete(context, chat_id, mid):
    """Auto delete media after 10 minutes"""
    await asyncio.sleep(600)  # 10 minutes
    try: 
        await context.bot.delete_message(chat_id, mid)
    except: 
        pass

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User status"""
    query = update.callback_query
    await query.answer()
    
    user_data = await user_manager.get_user(query.from_user.id)
    if not user_data:
        await query.message.reply_text("⚠️ User data not found. Type /start")
        return

    expiry = datetime.fromisoformat(user_data["expires"])
    total_media = await media_manager.get_media_count()
    
    status_text = (
        f"📊 <b>My Status</b>\n\n"
        f"👤 {user_data['name']}\n"
        f"🎁 Plan: {user_data['plan'].title()}\n"
        f"⏳ Expires: {format_datetime(expiry)}\n"
        f"🎬 Category: {user_data.get('current_category', 'All')}\n"
        f"✅ Watched Today: {user_data.get('daily_videos', 0)}\n"
        f"📥 Downloads Today: {user_data.get('daily_downloads', 0)}\n"
        f"🔗 Referrals: {user_data['referrals']}\n"
        f"📁 Total Media in Bot: {total_media}"
    )
    
    await query.message.edit_text(status_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

async def change_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change media category"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "change_category":
        await query.message.edit_text("🎬 Select a Category:", reply_markup=get_category_keyboard())
    elif query.data.startswith("set_category_"):
        cat = query.data.replace("set_category_", "")
        await user_manager.update_user(query.from_user.id, {"current_category": cat})
        await query.message.edit_text(f"✅ Category set to: {cat}", reply_markup=get_main_keyboard())

async def callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    data = update.callback_query.data
    
    if data == "status":
        await status_command(update, context)
    elif data == "send_media":
        await send_media_handler(update, context)
    elif data == "change_category" or data.startswith("set_category_"):
        await change_category_handler(update, context)
    elif data == "back_to_menu":
        user_data = await user_manager.get_user(update.callback_query.from_user.id)
        name = user_data['name'] if user_data else "User"
        await update.callback_query.message.edit_text(
            f"✨ Welcome back {name}!",
            reply_markup=get_main_keyboard()
        )
    elif data == "admin_panel":
        await admin_panel(update, context)
    elif data == "check_join":
        await check_join_callback(update, context)
    # Handle other buttons to stop loading animation
    elif data in ["like", "dislike", "download", "bookmark", "close"]:
        await update.callback_query.answer("Feature coming soon!")
        if data == "close":
            await update.callback_query.message.delete()

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if user joined channels"""
    query = update.callback_query
    await query.answer()
    
    if await check_user_membership(context.bot, query.from_user.id, FORCE_SUB_CHANNELS):
        await query.message.delete()
        await query.message.reply_text(
            "✅ Verified! You can now use the bot.",
            reply_markup=get_main_keyboard()
        )
    else:
        await query.answer("❌ Please join all required channels first!", show_alert=True)

async def save_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-save media from channels"""
    if update.channel_post and (update.channel_post.photo or update.channel_post.video or update.channel_post.document):
        await media_manager.add_media(
            update.channel_post.chat_id, 
            update.channel_post.message_id
        )

# ================= ADMIN FEATURES =================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMINS:
        await query.message.edit_text("❌ Access Denied!")
        return
    
    await query.message.edit_text(
        "⚙️ <b>Admin Panel</b>\n\n"
        "Select an option:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )

async def admin_index_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Index channel media - ADMIN ONLY"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMINS:
        await query.message.edit_text("❌ Access Denied!")
        return ConversationHandler.END
    
    await query.message.edit_text(
        "📤 <b>Index Channel Media</b>\n\n"
        "Please send:\n"
        "1. Channel link (t.me/channel)\n"
        "2. Channel message link (t.me/channel/message_id)\n"
        "3. Channel ID (-100...)\n\n"
        "<i>Bot must be admin in the channel!</i>\n\n"
        "Type /cancel to cancel.",
        parse_mode="HTML"
    )
    
    return "ADMIN_GET_CHANNEL"

async def admin_handle_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel input for indexing"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Access Denied!")
        return ConversationHandler.END
    
    try:
        # Extract message ID if present
        message_id = None
        channel_link = text
        
        if "/" in text and text.count("/") >= 2:
            parts = text.strip("/").split("/")
            if parts[-1].isdigit():
                message_id = int(parts[-1])
                channel_link = "/".join(parts[:-1])
        
        # Extract channel username/ID
        if "t.me/" in channel_link:
            username = channel_link.split("t.me/")[-1].replace("@", "").strip()
        else:
            username = channel_link.replace("@", "").strip()
        
        # Get chat info
        try:
            if username.startswith("-100") or username.lstrip("-").isdigit():
                chat = await context.bot.get_chat(int(username))
            else:
                chat = await context.bot.get_chat(f"@{username}")
        except Exception as e:
            await update.message.reply_text(f"❌ Cannot access channel: {str(e)}")
            return ConversationHandler.END
        
        channel_id = chat.id
        channel_title = chat.title
        
        # Check if bot is admin
        try:
            chat_member = await context.bot.get_chat_member(channel_id, context.bot.id)
            if chat_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    f"❌ Bot is not admin in '{channel_title}'!\n"
                    f"Please add bot as admin first."
                )
                return ConversationHandler.END
        except Exception as e:
            await update.message.reply_text(f"❌ Cannot check admin status: {str(e)}")
            return ConversationHandler.END
        
        # If single message ID provided
        if message_id:
            await update.message.reply_text(
                f"📌 <b>Indexing Single Message</b>\n\n"
                f"📢 Channel: {channel_title}\n"
                f"🆔 Message ID: {message_id}\n\n"
                f"<i>Processing...</i>",
                parse_mode="HTML"
            )
            
            success = await media_manager.index_single_message(context.bot, channel_id, message_id)
            
            if success:
                await update.message.reply_text("✅ Message indexed successfully!")
            else:
                await update.message.reply_text("⚠️ Message already indexed or no media found.")
            
            return ConversationHandler.END
        
        # Ask for range
        keyboard = [
            [
                InlineKeyboardButton("Last 50 Messages", callback_data=f"admin_range_{channel_id}_50"),
                InlineKeyboardButton("Last 100 Messages", callback_data=f"admin_range_{channel_id}_100")
            ],
            [
                InlineKeyboardButton("Last 500 Messages", callback_data=f"admin_range_{channel_id}_500"),
                InlineKeyboardButton("Custom Range", callback_data=f"admin_custom_{channel_id}")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📊 <b>Select Range to Index</b>\n\n"
            f"📢 Channel: {channel_title}\n"
            f"🆔 ID: <code>{channel_id}</code>\n\n"
            f"<i>How many recent messages to index?</i>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Admin indexing error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END

async def admin_handle_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle range selection for indexing"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "admin_cancel":
        await query.message.edit_text("❌ Indexing cancelled!")
        return
    
    if query.data.startswith("admin_range_"):
        try:
            # Parse: admin_range_CHANNELID_COUNT
            parts = query.data.split("_")
            channel_id = int(parts[2])
            count = int(parts[3])
            
            # Use current message ID as approximation of end
            # In a real scenario, we might need a more robust way to find the latest ID
            await query.message.edit_text(
                f"🚀 <b>Indexing Started</b>\n\n"
                f"⏳ Indexing last {count} messages...\n"
                f"<i>Finding latest message ID...</i>",
                parse_mode="HTML"
            )
            
            # Try to send a message to get current ID then delete it
            sent_msg = await context.bot.send_message(channel_id, ".")
            end_msg = sent_msg.message_id
            await context.bot.delete_message(channel_id, end_msg)
            
            start_msg = max(1, end_msg - count)
            
            # Start indexing in background
            asyncio.create_task(
                admin_index_messages(context.bot, channel_id, start_msg, end_msg, query.from_user.id)
            )
            
        except Exception as e:
            logger.error(f"Range error: {e}")
            await query.message.edit_text(f"❌ Error: {str(e)}")
    
    elif query.data.startswith("admin_custom_"):
        channel_id = int(query.data.split("_")[2])
        context.user_data['admin_custom_channel'] = channel_id
        await query.message.edit_text(
            "🔢 <b>Enter Custom Range</b>\n\n"
            "Format: <code>start_id-end_id</code>\n"
            "Example: <code>1-100</code>\n\n"
            "Type /cancel to cancel.",
            parse_mode="HTML"
        )
        return "ADMIN_GET_CUSTOM_RANGE"

async def admin_handle_custom_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom range input"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Access Denied!")
        return ConversationHandler.END
    
    try:
        if "-" in text:
            start_id, end_id = map(int, text.split("-"))
        else:
            await update.message.reply_text("❌ Invalid format. Use start-end (e.g., 100-200)")
            return "ADMIN_GET_CUSTOM_RANGE"
        
        channel_id = context.user_data.get('admin_custom_channel')
        
        if start_id > end_id:
            start_id, end_id = end_id, start_id
        
        count = end_id - start_id + 1
        
        await update.message.reply_text(
            f"🚀 <b>Indexing Started</b>\n\n"
            f"⏳ Indexing {count} messages ({start_id} to {end_id})...\n"
            f"<i>This may take a while. I'll notify when done.</i>",
            parse_mode="HTML"
        )
        
        # Start indexing
        asyncio.create_task(
            admin_index_messages(context.bot, channel_id, start_id, end_id, user_id)
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid format or error: {str(e)}")
        return "ADMIN_GET_CUSTOM_RANGE"

async def admin_index_messages(bot, channel_id, start_id, end_id, user_id):
    """Background task to index messages"""
    indexed = 0
    duplicates = 0
    failed = 0
    
    current = start_id
    total = end_id - start_id + 1
    
    try:
        while current <= end_id:
            try:
                success = await media_manager.index_single_message(bot, channel_id, current)
                if success:
                    indexed += 1
                else:
                    duplicates += 1
            except:
                failed += 1
            
            current += 1
            
            # Update progress every 50 messages
            if (current - start_id) % 50 == 0:
                progress = ((current - start_id) / total) * 100
                try:
                    await bot.send_message(
                        user_id,
                        f"📊 <b>Indexing Progress</b>\n\n"
                        f"✅ Indexed: {indexed}\n"
                        f"🔄 Skipped: {duplicates}\n"
                        f"📈 Progress: {progress:.1f}%",
                        parse_mode="HTML"
                    )
                except:
                    pass
            
            await asyncio.sleep(0.05)  # Rate limiting
        
        # Send final report
        await bot.send_message(
            user_id,
            f"✅ <b>Indexing Completed!</b>\n\n"
            f"📊 <b>Summary:</b>\n"
            f"✅ Successfully Indexed: {indexed}\n"
            f"🔄 Skipped: {duplicates}\n"
            f"❌ Failed: {failed}\n"
            f"🎯 Total Processed: {total}",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Background indexing error: {e}")
        try:
            await bot.send_message(user_id, f"❌ Indexing failed: {str(e)}")
        except:
            pass

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMINS:
        await query.message.edit_text("❌ Access Denied!")
        return
    
    try:
        # Get total media count
        total_media = 0
        channel_counts = []
        async for doc in media_col.find():
            count = len(doc.get("message_ids", []))
            total_media += count
            channel_counts.append(f"{doc['channel_id']}: {count}")
        
        # Get user count
        user_count = await users_col.count_documents({})
        
        # Get active users (last 24 hours)
        day_ago = (now() - timedelta(hours=24)).isoformat()
        active_users = await users_col.count_documents({
            "last_activity": {"$gte": day_ago}
        })
        
        stats_text = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"🤖 Bot Status: ✅ Running\n"
            f"👥 Total Users: {user_count}\n"
            f"📈 Active Users (24h): {active_users}\n"
            f"📁 Total Media Files: {total_media}\n"
            f"📢 Indexed Channels: {len(channel_counts)}\n\n"
            f"<b>Channel-wise Media Count:</b>\n"
        )
        
        for i, count in enumerate(channel_counts[:10], 1):  # Show first 10
            stats_text += f"{i}. {count}\n"
        
        if len(channel_counts) > 10:
            stats_text += f"\n... and {len(channel_counts) - 10} more channels"
        
        await query.message.edit_text(stats_text, parse_mode="HTML", reply_markup=get_admin_keyboard())
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await query.message.edit_text(f"❌ Error getting stats: {str(e)}")

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel admin operation"""
    await update.message.reply_text("✅ Operation cancelled!")
    return ConversationHandler.END

# ================= WEB SERVER FOR RENDER =================

async def web_health_check(request):
    """Simple health check for Render"""
    return web.Response(text="Bot is running!")

async def start_web_server():
    """Start the dummy web server"""
    try:
        app = web.Application()
        app.router.add_get('/', web_health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        logger.info(f"✅ Web server started on port {PORT}")
    except Exception as e:
        logger.error(f"❌ Web server failed: {e}")

# ================= INITIALIZATION =================

async def post_init(application: Application):
    """Initialize things after bot starts loop"""
    # 1. Start Web Server (Required for Render)
    await start_web_server()
    
    # 2. Check Database
    try:
        await client.admin.command('ping')
        logger.info("✅ MongoDB Connected")
        await users_col.create_index("_id")
        await media_col.create_index("channel_id")
    except Exception as e:
        logger.error(f"❌ Database error: {e}")

def main():
    """Main function"""
    
    # Create application
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # ================= CONVERSATION HANDLERS =================
    ADMIN_INDEX_CONVERSATION = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_index_channel, pattern="^admin_index$")],
        states={
            "ADMIN_GET_CHANNEL": [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_channel)
            ],
            "ADMIN_GET_CUSTOM_RANGE": [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_custom_range)
            ]
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)]
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    
    # Admin handlers
    application.add_handler(ADMIN_INDEX_CONVERSATION)
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_handle_range, pattern="^admin_"))
    
    # Main callback handler
    application.add_handler(CallbackQueryHandler(callback_dispatcher))
    
    # Auto-save media from channels
    all_cids = list(set(list(CATEGORY_CHANNELS.values()) + [DEFAULT_CHANNEL]))
    application.add_handler(
        MessageHandler(
            filters.Chat(chat_id=all_cids) & (filters.PHOTO | filters.VIDEO | filters.Document.ALL),
            save_media_handler
        )
    )
    
    logger.info("🚀 Bot is starting...")
    
    # Run bot
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
