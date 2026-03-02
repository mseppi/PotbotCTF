import discord
from discord.ext import commands
from config import TOKEN, INTENTS
import settings
import os
from datetime import datetime

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS
        )

    async def setup_hook(self):
        # Load cogs
        await self.load_extension("cogs.general")

        # Sync slash commands
        await self.tree.sync()
        print("✅ Slash commands synced")

    async def on_ready(self):
        print(f"🤖 Logged in as {self.user} (ID: {self.user.id})")
        
        # Check if bot was updated and send notification
        update_flag = "/tmp/bot_updated.flag"
        commit_msg_file = "/tmp/bot_commit_msg.txt"
        
        update_channel_id = settings.get("update_channel_id")
        
        print(f"🔍 Checking for update flag: {os.path.exists(update_flag)}")
        print(f"🔍 update_channel_id: {update_channel_id}")
        
        if os.path.exists(update_flag):
            print("📌 Update flag found!")
            if update_channel_id:
                channel = self.get_channel(update_channel_id)
                print(f"🔍 Channel found: {channel}")
                if channel:
                    # Read commit message if available
                    commit_msg = "No commit message available"
                    if os.path.exists(commit_msg_file):
                        with open(commit_msg_file, 'r') as f:
                            commit_msg = f.read().strip()
                        print(f"📝 Commit message: {commit_msg}")
                    
                    message = f"🔄 Bot updated and restarted!\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📝 {commit_msg}"
                    await channel.send(message)
                    print("✅ Update notification sent")
                else:
                    print("❌ Channel not found!")
            else:
                print("❌ update_channel_id not set! Use /setupdatechannel to configure.")
            
            # Clean up flag files
            os.remove(update_flag)
            if os.path.exists(commit_msg_file):
                os.remove(commit_msg_file)

bot = MyBot()
bot.run(TOKEN)
