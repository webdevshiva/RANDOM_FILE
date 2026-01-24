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
    level=logging.DEBUG  # Changed to DEBUG for more info
)
logger = logging.getLogger(__name__)

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8198318399:AAEK3qvRpSr6EqKldxBXnlDfcsjhUdWPPhU")
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://baleny:zpQKH66B4AaYldIx@cluster0.ichdp1p.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1002686058050"))

ADMINS_STR = os.getenv("ADMIN_IDS", "5298223577")
ADMINS = [int(admin_id.strip()) for admin_id in ADMINS_STR.split(",") if admin_id.strip().isdigit()]

logger.info(f"Admin IDs loaded: {ADMINS}")
logger.info(f"Bot Token: {BOT_TOKEN[:10]}...")  # Log first 10 chars only for security

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

# ================= SIMPLIFIED INDEXING =================

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

# ================= ADMIN COMMANDS =================

async def index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start indexing process - SIMPLIFIED VERSION"""
    user_id = update.effective_user.id
    logger.info(f"/index command received from user: {user_id}")
    
    # Check if user is admin
    if user_id not in ADMINS:
        logger.warning(f"User {user_id} tried to use /index but is not admin")
        await update.message.reply_text("❌ You are not authorized to use this command!")
        return ConversationHandler.END
    
    logger.info(f"User {user_id} is admin, proceeding with indexing")
    
    # Send initial response
    await update.message.reply_text(
        "📤 <b>Index Channel Media</b>\n\n"
        "Please send me:\n"
        "1. The channel invite link (e.g., https://t.me/channel_name)\n"
        "OR\n"
        "2. A forwarded message from the channel\n"
        "OR\n"
        "3. Channel ID (e.g., -1001234567890)\n\n"
        "<i>The bot must be admin in the channel!</i>",
        parse_mode="HTML"
    )
    
    # Return state to continue conversation
    return "GET_CHANNEL_INFO"

async def handle_channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel information from user"""
    user_id = update.effective_user.id
    message = update.message
    
    logger.info(f"Received channel info from user {user_id}: {message.text or 'Forwarded message'}")
    
    channel_id = None
    channel_title = "Unknown"
    
    try:
        # Case 1: Forwarded message from channel
        if message.forward_from_chat:
            channel_id = message.forward_from_chat.id
            channel_title = message.forward_from_chat.title
            logger.info(f"Got channel from forwarded message: {channel_title} ({channel_id})")
        
        # Case 2: Channel link
        elif message.text and ("t.me/" in message.text or "telegram.me/" in message.text):
            # Extract username from link
            link = message.text
            if "t.me/" in link:
                username = link.split("t.me/")[-1].split("/")[0].replace("@", "").strip()
            else:
                username = link.split("telegram.me/")[-1].split("/")[0].replace("@", "").strip()
            
            logger.info(f"Extracted username from link: @{username}")
            
            try:
                # Get chat info
                chat = await context.bot.get_chat(f"@{username}")
                channel_id = chat.id
                channel_title = chat.title
                logger.info(f"Got channel info: {channel_title} ({channel_id})")
            except Exception as e:
                logger.error(f"Failed to get chat info: {e}")
                await message.reply_text(
                    f"❌ Could not find channel @{username}. Please make sure:\n"
                    f"1. Channel exists\n"
                    f"2. Bot is in the channel\n"
                    f"3. Username is correct"
                )
                return "GET_CHANNEL_INFO"
        
        # Case 3: Direct channel ID
        elif message.text and message.text.startswith("-100"):
            try:
                channel_id = int(message.text)
                # Try to get channel info
                chat = await context.bot.get_chat(channel_id)
                channel_title = chat.title
                logger.info(f"Got channel from ID: {channel_title} ({channel_id})")
            except Exception as e:
                logger.error(f"Invalid channel ID: {e}")
                await message.reply_text("❌ Invalid channel ID or bot cannot access this channel")
                return "GET_CHANNEL_INFO"
        
        # Invalid input
        else:
            await message.reply_text(
                "❌ Please send:\n"
                "1. Channel link (t.me/...)\n"
                "2. Forwarded message from channel\n"
                "3. Channel ID (-100...)"
            )
            return "GET_CHANNEL_INFO"
        
        # Check if bot is admin in channel
        try:
            chat_member = await context.bot.get_chat_member(channel_id, context.bot.id)
            is_admin = chat_member.status in ['administrator', 'creator']
            
            if not is_admin:
                logger.warning(f"Bot is not admin in channel {channel_id}")
                await message.reply_text(
                    f"❌ Bot is not admin in '{channel_title}'!\n\n"
                    f"Please make the bot an admin with the following permissions:\n"
                    f"✅ Post Messages\n"
                    f"✅ Edit Messages\n"
                    f"✅ Delete Messages\n"
                    f"✅ View Messages"
                )
                return ConversationHandler.END
                
            logger.info(f"Bot is admin in channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Admin check failed: {e}")
            await message.reply_text(
                f"❌ Cannot check admin status: {str(e)}\n"
                f"Make sure bot is added to the channel."
            )
            return ConversationHandler.END
        
        # Get message count
        try:
            # Get last message
            last_message = None
            async for msg in context.bot.get_chat_history(channel_id, limit=1):
                last_message = msg
                break
            
            if not last_message:
                await message.reply_text("❌ No messages found in this channel!")
                return ConversationHandler.END
            
            last_msg_id = last_message.message_id
            logger.info(f"Last message ID in channel: {last_msg_id}")
            
            # Ask for start message ID
            context.user_data['index_channel_id'] = channel_id
            context.user_data['index_channel_title'] = channel_title
            context.user_data['last_msg_id'] = last_msg_id
            
            keyboard = [
                [InlineKeyboardButton("Start from Message 1", callback_data=f"startid_1")],
                [InlineKeyboardButton(f"Start from Message {max(1, last_msg_id-1000)}", callback_data=f"startid_{max(1, last_msg_id-1000)}")],
                [InlineKeyboardButton("Custom Start ID", callback_data="custom_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.reply_text(
                f"📊 <b>Channel Ready for Indexing</b>\n\n"
                f"📢 Channel: {channel_title}\n"
                f"🆔 ID: <code>{channel_id}</code>\n"
                f"📈 Last Message ID: {last_msg_id}\n"
                f"🗂️ Estimated Messages: {last_msg_id}\n\n"
                f"<b>Select starting point:</b>",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            
            return "GET_START_ID"
            
        except Exception as e:
            logger.error(f"Failed to get message count: {e}")
            await message.reply_text(f"❌ Failed to get channel messages: {str(e)}")
            return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in handle_channel_info: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END

async def handle_start_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle start ID selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "custom_start":
        await query.message.reply_text("Please send the starting message ID (usually 1):")
        context.user_data['awaiting_custom_id'] = True
        return "GET_CUSTOM_ID"
    
    elif query.data.startswith("startid_"):
        start_id = int(query.data.split("_")[1])
        await process_start_id(update, context, start_id)
        return ConversationHandler.END
    
    return ConversationHandler.END

async def handle_custom_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom start ID input"""
    try:
        start_id = int(update.message.text)
        await process_start_id(update, context, start_id)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number!")
        return "GET_CUSTOM_ID"

async def process_start_id(update, context, start_id):
    """Process the selected start ID"""
    channel_id = context.user_data['index_channel_id']
    channel_title = context.user_data['index_channel_title']
    last_msg_id = context.user_data['last_msg_id']
    
    if start_id < 1:
        start_id = 1
    if start_id > last_msg_id:
        start_id = last_msg_id
    
    total_messages = last_msg_id - start_id + 1
    
    # Confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Start Indexing", callback_data=f"start_index_{channel_id}_{start_id}_{last_msg_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_index")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'callback_query'):
        message = update.callback_query.message
        await message.edit_text(
            f"📋 <b>Ready to Index</b>\n\n"
            f"📢 Channel: {channel_title}\n"
            f"🆔 ID: <code>{channel_id}</code>\n"
            f"🎯 Range: {start_id} → {last_msg_id}\n"
            f"📈 Total Messages: {total_messages}\n\n"
            f"<i>This may take some time...</i>\n\n"
            f"<b>Click Start Indexing to begin:</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            f"📋 <b>Ready to Index</b>\n\n"
            f"📢 Channel: {channel_title}\n"
            f"🆔 ID: <code>{channel_id}</code>\n"
            f"🎯 Range: {start_id} → {last_msg_id}\n"
            f"📈 Total Messages: {total_messages}\n\n"
            f"<i>This may take some time...</i>\n\n"
            f"<b>Click Start Indexing to begin:</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

async def start_indexing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the indexing process"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_index":
        await query.message.edit_text("❌ Indexing cancelled!")
        return
    
    if query.data.startswith("start_index_"):
        try:
            # Parse data
            parts = query.data.split("_")
            channel_id = int(parts[2])
            start_id = int(parts[3])
            end_id = int(parts[4])
            
            user_id = query.from_user.id
            
            await query.message.edit_text(
                f"🚀 <b>Indexing Started!</b>\n\n"
                f"⏳ Please wait...\n"
                f"I'll send progress updates here.\n\n"
                f"<i>Processing {end_id - start_id + 1} messages...</i>",
                parse_mode="HTML"
            )
            
            # Start indexing in background
            asyncio.create_task(
                simple_index_media(
                    context.bot,
                    channel_id,
                    start_id,
                    end_id,
                    user_id,
                    query.message.message_id
                )
            )
            
        except Exception as e:
            logger.error(f"Failed to start indexing: {e}")
            await query.message.edit_text(f"❌ Failed to start indexing: {str(e)}")

async def simple_index_media(bot, channel_id, start_id, end_id, user_id, status_msg_id):
    """Simple media indexing function"""
    try:
        indexed = 0
        duplicates = 0
        failed = 0
        
        # Send initial status
        status_msg = await bot.send_message(
            user_id,
            f"📊 <b>Indexing Started</b>\n\n"
            f"✅ Indexed: 0\n"
            f"🔄 Duplicates: 0\n"
            f"❌ Failed: 0\n"
            f"📈 Progress: 0%\n"
            f"⏳ Current: Message {start_id}",
            parse_mode="HTML"
        )
        
        total_messages = end_id - start_id + 1
        current_id = start_id
        
        while current_id <= end_id:
            try:
                # Check if message exists and has media
                message = await bot.get_message(channel_id, current_id)
                
                if message.photo or message.video or message.document or message.audio:
                    # Check if already in database
                    existing = await media_col.find_one({
                        "channel_id": str(channel_id),
                        "message_ids": current_id
                    })
                    
                    if existing:
                        duplicates += 1
                    else:
                        # Add to database
                        await media_col.update_one(
                            {"channel_id": str(channel_id)},
                            {"$addToSet": {"message_ids": current_id}},
                            upsert=True
                        )
                        indexed += 1
                
                # Update progress every 50 messages
                if indexed % 50 == 0:
                    progress = (current_id - start_id + 1) / total_messages * 100
                    await status_msg.edit_text(
                        f"📊 <b>Indexing Progress</b>\n\n"
                        f"✅ Indexed: {indexed}\n"
                        f"🔄 Duplicates: {duplicates}\n"
                        f"❌ Failed: {failed}\n"
                        f"📈 Progress: {progress:.1f}%\n"
                        f"⏳ Current: Message {current_id}/{end_id}",
                        parse_mode="HTML"
                    )
                
            except Exception as e:
                failed += 1
                logger.debug(f"Failed message {current_id}: {e}")
            
            current_id += 1
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.05)
        
        # Send completion message
        await bot.send_message(
            user_id,
            f"✅ <b>Indexing Completed!</b>\n\n"
            f"📊 <b>Summary:</b>\n"
            f"✅ Indexed: {indexed}\n"
            f"🔄 Duplicates Skipped: {duplicates}\n"
            f"❌ Failed: {failed}\n"
            f"🎯 Total Messages: {total_messages}\n\n"
            f"📁 Channel ID: <code>{channel_id}</code>",
            parse_mode="HTML"
        )
        
        # Delete status message
        try:
            await status_msg.delete()
        except:
            pass
        
    except Exception as e:
        logger.error(f"Indexing error: {e}")
        await bot.send_message(user_id, f"❌ Indexing failed: {str(e)}")

# ================= BASIC BOT FUNCTIONS =================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple start command"""
    await update.message.reply_text(
        "🤖 <b>Media Bot</b>\n\n"
        "Use /index to index channels (Admin only)\n"
        "Use /status to check bot status",
        parse_mode="HTML"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check bot status"""
    try:
        # Get media count
        total_media = 0
        async for doc in media_col.find():
            total_media += len(doc.get("message_ids", []))
        
        # Get user count
        user_count = await users_col.count_documents({})
        
        await update.message.reply_text(
            f"📊 <b>Bot Status</b>\n\n"
            f"🤖 Bot: Running\n"
            f"📁 Total Media: {total_media}\n"
            f"👥 Total Users: {user_count}\n"
            f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Status error: {e}")
        await update.message.reply_text(f"❌ Error getting status: {str(e)}")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing operation"""
    await update.message.reply_text("Operation cancelled!")
    return ConversationHandler.END

# ================= CONVERSATION HANDLER =================

INDEX_CONVERSATION = ConversationHandler(
    entry_points=[CommandHandler("index", index_command)],
    states={
        "GET_CHANNEL_INFO": [
            MessageHandler(
                filters.TEXT | filters.FORWARDED,
                handle_channel_info
            )
        ],
        "GET_START_ID": [
            CallbackQueryHandler(handle_start_id, pattern="^(startid_|custom_start)")
        ],
        "GET_CUSTOM_ID": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_id)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_command)
    ]
)

# ================= MAIN FUNCTION =================

async def init_bot():
    """Initialize bot components"""
    logger.info("Initializing bot...")
    
    # Test MongoDB connection
    try:
        await client.admin.command('ping')
        logger.info("✅ MongoDB Connected")
    except Exception as e:
        logger.error(f"❌ MongoDB Connection Failed: {e}")
        raise
    
    # Create indexes
    try:
        await media_col.create_index("channel_id")
        logger.info("✅ Database indexes created")
    except Exception as e:
        logger.error(f"❌ Index creation failed: {e}")

def main():
    """Main entry point"""
    # Create event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Initialize bot
    loop.run_until_complete(init_bot())
    
    # Build application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(INDEX_CONVERSATION)
    application.add_handler(CallbackQueryHandler(start_indexing_callback, pattern="^(start_index_|cancel_index)"))
    
    logger.info("🚀 Bot starting...")
    
    # Run bot
    application.run_polling(
        drop_pending_updates=True,
        close_loop=False
    )

if __name__ == "__main__":
    main()
