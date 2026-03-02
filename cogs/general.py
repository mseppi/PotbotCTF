import discord
from discord.ext import commands
from discord import app_commands
import settings
import subprocess
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        """Check if the bot is alive"""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! Latency: {latency}ms")

    @app_commands.command(name="lastcommit", description="Show the last commit message of the bot")
    async def last_commit(self, interaction: discord.Interaction):
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--pretty=format:%h | %s\n👤 %an\n⏰ %ci"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                await interaction.response.send_message(f"📝 **Last commit:**\n{result.stdout.strip()}")
            else:
                await interaction.response.send_message("❌ Could not retrieve commit info.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="setupdatechannel", description="Set the channel for bot update notifications")
    @app_commands.describe(channel="The channel to send update notifications to")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_update_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        settings.set("update_channel_id", channel.id)
        await interaction.response.send_message(f"✅ Update notifications will be sent to {channel.mention}")

    @set_update_channel.error
    async def set_update_channel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You need Administrator permission to use this command.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
