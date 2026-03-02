import random
import json
import pathlib
import discord
from discord.ext import commands

MAGIC_FILE = pathlib.Path(__file__).resolve().parent.parent / "magic.json"


class Utility(commands.Cog):
    """Miscellaneous utility commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(aliases=["char"])
    async def characters(self, ctx: commands.Context, string: str):
        """Count the number of characters in a string."""
        await ctx.send(len(string))

    @commands.command(aliases=["wc"])
    async def wordcount(self, ctx: commands.Context, *args):
        """Count the number of words."""
        await ctx.send(len(args))

    @commands.command(aliases=["rev"])
    async def reverse(self, ctx: commands.Context, message: str):
        """Reverse a string."""
        await ctx.send(message[::-1])

    @commands.command()
    async def counteach(self, ctx: commands.Context, message: str):
        """Count the amount of each character in a string."""
        count = {}
        for char in message:
            if char in count:
                count[char] += 1
            else:
                count[char] = 1
        await ctx.send(str(count))

    @commands.command(aliases=["head"])
    async def magicb(self, ctx: commands.Context, filetype: str):
        """Get the magic bytes for a file type."""
        try:
            with open(MAGIC_FILE) as f:
                alldata = json.load(f)
            messy_signs = str(alldata[filetype]["signs"])
            signs = messy_signs.split("[")[1].split(",")[0].split("]")[0].replace("'", "")
            mime = alldata[filetype]["mime"]
            await ctx.send(f"{mime}: {signs}")
        except KeyError:
            await ctx.send(
                f"{filetype} not found :( If you think this filetype should be included, let an admin know."
            )
        except FileNotFoundError:
            await ctx.send("magic.json not found on the server.")

    @commands.command()
    async def twitter(self, ctx: commands.Context, twituser: str):
        """Get a Twitter profile link."""
        await ctx.send(f"https://twitter.com/{twituser}")

    @commands.command()
    async def github(self, ctx: commands.Context, gituser: str):
        """Get a GitHub profile link."""
        await ctx.send(f"https://github.com/{gituser}")

    @commands.command(aliases=["5050", "flip"])
    async def cointoss(self, ctx: commands.Context):
        """Flip a coin."""
        choice = random.randint(1, 2)
        if choice == 1:
            await ctx.send("heads")
        if choice == 2:
            await ctx.send("tails")


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
