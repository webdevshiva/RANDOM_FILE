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
    filters,
    ConversationHandler
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

ADMINS_STR = os.getenv("ADMIN_IDS", "5298223577")
ADMINS = [int(admin_id.strip()) for admin_id in ADMINS_STR.split(",") if admin_id.strip().isdigit()]

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
    "🤖 𝙈𝙤𝙫𝙞𝙚 𝘽𝙤𝙩 : @ChaudharyAutoFilterbot\n"
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
indexing_col = db["indexing_status"]

# ================= INDEXING STATUS CLASS =================

class IndexingStatus:
    def __init__(self, user_id: int, channel_id: int, total_messages: int):
        self.user_id = user_id
        self.channel_id = channel_id
        self.total_messages = total_messages
        self.indexed = 0
        self.duplicates = 0
        self.failed = 0
        self.start_time = datetime.now()
        self.current_message_id = None
        self.is_running = True
        
    def to_dict(self):
        return {
            "user_id": self.user_id,
            "channel_id": self.channel_id,
            "total_messages": self.total_messages,
            "indexed": self.indexed,
            "duplicates": self.duplicates,
            "failed": self.failed,
            "start_time": self.start_time.isoformat(),
            "current_message_id": self.current_message_id,
            "is_running": self.is_running
        }
    
    def get_progress(self):
        if self.total_messages == 0:
            return 0
        return (self.indexed / self.total_messages) * 100
    
    def get_remaining(self):
        return self.total_messages - self.indexed

# Store active indexing processes
active_indexing = {}

# ================= INDEXING FUNCTIONS =================

async def check_bot_admin(bot, channel_id):
    """Check if bot is admin in channel"""
    try:
        chat_member = await bot.get_chat_member(channel_id, bot.id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Admin check error: {e}")
        return False

async def get_last_message_id(bot, channel_id):
    """Get last message ID from channel"""
    try:
        messages = []
        async for message in bot.get_chat_history(channel_id, limit=1):
            messages.append(message)
        
        if messages:
            return messages[0].message_id
        return 0
    except Exception as e:
        logger.error(f"Get last message error: {e}")
        return 0

async def index_channel_media(bot, channel_id, start_message_id, end_message_id, status: IndexingStatus, user_id):
    """Index all media from channel"""
    try:
        message_id = start_message_id
        
        while message_id >= end_message_id and status.is_running:
            status.current_message_id = message_id
            
            try:
                # Try to get message
                message = await bot.get_message(channel_id, message_id)
                
                # Check if message has media (photo, video, document)
                if message.photo or message.video or message.document:
                    # Check if media already exists in database
                    existing = await media_col.find_one({
                        "channel_id": str(channel_id),
                        "message_ids": message_id
                    })
                    
                    if existing:
                        status.duplicates += 1
                        logger.info(f"Duplicate skipped: {message_id}")
                    else:
                        # Add to database
                        await media_col.update_one(
                            {"channel_id": str(channel_id)},
                            {"$addToSet": {"message_ids": message_id}},
                            upsert=True
                        )
                        status.indexed += 1
                        logger.info(f"Indexed: {message_id}")
                
                # Send progress every 10 messages
                if status.indexed % 10 == 0:
                    progress_msg = await generate_progress_message(status)
                    await bot.send_message(
                        user_id,
                        progress_msg,
                        parse_mode="HTML"
                    )
                    
            except Exception as e:
                status.failed += 1
                logger.error(f"Failed to index {message_id}: {e}")
            
            message_id -= 1
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)
        
        # Indexing completed
        status.is_running = False
        final_msg = await generate_final_report(status)
        await bot.send_message(user_id, final_msg, parse_mode="HTML")
        
        # Save to database
        await indexing_col.insert_one(status.to_dict())
        
        # Remove from active indexing
        if user_id in active_indexing:
            del active_indexing[user_id]
            
    except Exception as e:
        logger.error(f"Indexing error: {e}")
        await bot.send_message(user_id, f"❌ Indexing failed: {str(e)}")

async def generate_progress_message(status: IndexingStatus):
    """Generate progress update message"""
    progress = status.get_progress()
    remaining = status.get_remaining()
    
    message = (
        f"📊 <b>Indexing Progress</b>\n\n"
        f"✅ Indexed: {status.indexed}\n"
        f"🔄 Duplicates Skipped: {status.duplicates}\n"
        f"❌ Failed: {status.failed}\n"
        f"📈 Progress: {progress:.2f}%\n"
        f"⏳ Remaining: {remaining} messages\n"
        f"🎯 Total: {status.total_messages} messages\n\n"
        f"🆔 Current Message ID: {status.current_message_id}"
    )
    return message

async def generate_final_report(status: IndexingStatus):
    """Generate final indexing report"""
    duration = datetime.now() - status.start_time
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    message = (
        f"✅ <b>Indexing Completed!</b>\n\n"
        f"📊 <b>Final Report:</b>\n"
        f"✅ Successfully Indexed: {status.indexed}\n"
        f"🔄 Duplicates Skipped: {status.duplicates}\n"
        f"❌ Failed: {status.failed}\n"
        f"🎯 Total Messages: {status.total_messages}\n\n"
        f"⏱️ <b>Time Taken:</b> {hours}h {minutes}m {seconds}s\n"
        f"📈 <b>Success Rate:</b> {(status.indexed/status.total_messages*100):.2f}%\n\n"
        f"📁 <b>Channel ID:</b> {status.channel_id}"
    )
    return message

# ================= ADMIN COMMANDS =================

async def index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start indexing process"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if user_id not in ADMINS:
        await update.message.reply_text("❌ You are not authorized to use this command!")
        return
    
    # Check if already indexing
    if user_id in active_indexing:
        await update.message.reply_text("⚠️ You already have an indexing process running!")
        return
    
    # Ask for channel link/message
    await update.message.reply_text(
        "📤 <b>Index Channel Media</b>\n\n"
        "Please send me:\n"
        "1. The channel invite link\n"
        "OR\n"
        "2. A message from the channel\n\n"
        "The bot must be admin in the channel!",
        parse_mode="HTML"
    )
    
    return "GET_CHANNEL"

async def get_channel_for_indexing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract channel ID from message"""
    user_id = update.effective_user.id
    message = update.message
    
    channel_id = None
    
    try:
        # Check if message contains channel link
        if message.text and ("t.me/" in message.text or "telegram.me/" in message.text):
            # Extract channel username from link
            if "t.me/" in message.text:
                username = message.text.split("t.me/")[-1].split("/")[0].replace("@", "")
            else:
                username = message.text.split("telegram.me/")[-1].split("/")[0].replace("@", "")
            
            try:
                chat = await context.bot.get_chat(f"@{username}")
                channel_id = chat.id
            except:
                await message.reply_text("❌ Could not find channel. Please check the link.")
                return ConversationHandler.END
        
        # Check if message is forwarded from channel
        elif message.forward_from_chat:
            channel_id = message.forward_from_chat.id
        
        # Check if message contains channel ID
        elif message.text and message.text.startswith("-100"):
            try:
                channel_id = int(message.text)
            except:
                pass
        
        if not channel_id:
            await message.reply_text("❌ Could not extract channel ID. Please send a valid channel link or message.")
            return ConversationHandler.END
        
        # Check if bot is admin
        is_admin = await check_bot_admin(context.bot, channel_id)
        if not is_admin:
            await message.reply_text("❌ Bot is not admin in this channel! Please add bot as admin first.")
            return ConversationHandler.END
        
        # Get last message ID
        last_msg_id = await get_last_message_id(context.bot, channel_id)
        if last_msg_id == 0:
            await message.reply_text("❌ Could not get messages from channel. Bot needs admin rights.")
            return ConversationHandler.END
        
        # Ask for starting message ID
        context.user_data['index_channel_id'] = channel_id
        context.user_data['last_msg_id'] = last_msg_id
        
        await message.reply_text(
            f"📊 <b>Channel Details</b>\n\n"
            f"🆔 Channel ID: <code>{channel_id}</code>\n"
            f"📈 Last Message ID: {last_msg_id}\n\n"
            f"Please send the starting message ID (usually 1):",
            parse_mode="HTML"
        )
        
        return "GET_START_ID"
        
    except Exception as e:
        logger.error(f"Channel extraction error: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END

async def get_start_message_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get starting message ID"""
    user_id = update.effective_user.id
    message = update.message
    
    try:
        start_message_id = int(message.text)
        channel_id = context.user_data['index_channel_id']
        last_msg_id = context.user_data['last_msg_id']
        
        if start_message_id > last_msg_id:
            await message.reply_text("❌ Starting message ID cannot be greater than last message ID!")
            return "GET_START_ID"
        
        total_messages = last_msg_id - start_message_id + 1
        
        if total_messages <= 0:
            await message.reply_text("❌ Invalid message range!")
            return ConversationHandler.END
        
        # Confirm indexing
        keyboard = [
            [
                InlineKeyboardButton("✅ Start Indexing", callback_data=f"confirm_index_{channel_id}_{start_message_id}_{last_msg_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_index")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            f"📋 <b>Indexing Summary</b>\n\n"
            f"🆔 Channel ID: <code>{channel_id}</code>\n"
            f"🎯 Message Range: {start_message_id} to {last_msg_id}\n"
            f"📈 Total Messages: {total_messages}\n\n"
            f"<i>This may take some time depending on message count.</i>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        return ConversationHandler.END
        
    except ValueError:
        await message.reply_text("❌ Please send a valid number!")
        return "GET_START_ID"
    except Exception as e:
        logger.error(f"Start ID error: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END

async def confirm_indexing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and start indexing"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_index":
        await query.message.edit_text("❌ Indexing cancelled!")
        return
    
    if query.data.startswith("confirm_index_"):
        try:
            # Extract data from callback
            _, channel_id_str, start_id_str, end_id_str = query.data.split("_")
            channel_id = int(channel_id_str)
            start_message_id = int(start_id_str)
            end_message_id = int(end_id_str)
            
            user_id = query.from_user.id
            
            # Calculate total messages
            total_messages = end_message_id - start_message_id + 1
            
            # Create indexing status
            status = IndexingStatus(
                user_id=user_id,
                channel_id=channel_id,
                total_messages=total_messages
            )
            
            # Store in active indexing
            active_indexing[user_id] = status
            
            # Send starting message
            await query.message.edit_text(
                f"🚀 <b>Starting Indexing...</b>\n\n"
                f"🆔 Channel ID: <code>{channel_id}</code>\n"
                f"🎯 Message Range: {start_message_id} to {end_message_id}\n"
                f"📈 Total Messages: {total_messages}\n\n"
                f"⏳ Please wait...",
                parse_mode="HTML"
            )
            
            # Start indexing in background
            asyncio.create_task(
                index_channel_media(
                    context.bot,
                    channel_id,
                    end_message_id,
                    start_message_id,
                    status,
                    user_id
                )
            )
            
        except Exception as e:
            logger.error(f"Confirm indexing error: {e}")
            await query.message.edit_text(f"❌ Error starting indexing: {str(e)}")

async def stop_index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop ongoing indexing"""
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    if user_id in active_indexing:
        active_indexing[user_id].is_running = False
        del active_indexing[user_id]
        await update.message.reply_text("✅ Indexing stopped!")
    else:
        await update.message.reply_text("❌ No active indexing process found!")

async def indexing_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check indexing status"""
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ You are not authorized!")
        return
    
    if user_id in active_indexing:
        status = active_indexing[user_id]
        progress_msg = await generate_progress_message(status)
        await update.message.reply_text(progress_msg, parse_mode="HTML")
    else:
        # Check database for previous indexing
        records = await indexing_col.find({"user_id": user_id}).sort("start_time", -1).limit(5).to_list(length=5)
        
        if records:
            message = "📊 <b>Previous Indexing Sessions:</b>\n\n"
            for i, record in enumerate(records, 1):
                start_time = datetime.fromisoformat(record['start_time'])
                message += (
                    f"{i}. Channel: {record['channel_id']}\n"
                    f"   ✅ Indexed: {record['indexed']}\n"
                    f"   ⏰ Started: {start_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                )
            await update.message.reply_text(message, parse_mode="HTML")
        else:
            await update.message.reply_text("ℹ️ No active or previous indexing sessions found.")

# ================= EXISTING FUNCTIONS (कम्प्लीट कोड) =================
# यहाँ आपके पुराने सभी functions रहेंगे जैसे:
# now(), format_datetime(), check_user_membership()
# get_main_keyboard(), get_media_keyboard()
# UserManager class, MediaManager class
# start_command(), status_command(), send_media_handler()
# change_category_handler(), save_media_handler(), callback_dispatcher()

# ================= CONVERSATION HANDLER =================

INDEX_CONVERSATION = ConversationHandler(
    entry_points=[CommandHandler("index", index_command)],
    states={
        "GET_CHANNEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, get_channel_for_indexing)],
        "GET_START_ID": [MessageHandler(filters.TEXT & ~filters.COMMAND, get_start_message_id)],
    },
    fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
    allow_reentry=True
)

# ================= MAIN FUNCTION =================

def main():
    """Main entry point"""
    # Create a new event loop for the main thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Test MongoDB connection
    loop.run_until_complete(test_mongodb_connection())
    
    # Build and configure application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(INDEX_CONVERSATION)
    application.add_handler(CommandHandler("stopindex", stop_index_command))
    application.add_handler(CommandHandler("indexstatus", indexing_status_command))
    application.add_handler(CallbackQueryHandler(confirm_indexing, pattern="^(confirm_index_|cancel_index)"))
    application.add_handler(CallbackQueryHandler(callback_dispatcher))
    
    # Media Auto-save from channels
    all_cids = list(set(list(CATEGORY_CHANNELS.values()) + [DEFAULT_CHANNEL]))
    application.add_handler(MessageHandler(filters.Chat(chat_id=all_cids) & (filters.PHOTO | filters.VIDEO), save_media_handler))
    
    logger.info("🚀 Bot is running with MongoDB Atlas and Indexing Feature...")
    
    # Run the bot
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )

if __name__ == "__main__":
    main()
