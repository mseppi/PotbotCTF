import discord
from discord.ext import commands
from discord import app_commands
import settings

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        """Check if the bot is alive"""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! Latency: {latency}ms")

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
