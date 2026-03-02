import collections
import string
import discord
from discord.ext import commands


class Ciphers(commands.Cog):
    """Cipher encoding/decoding commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    async def rot(self, ctx: commands.Context, message: str, direction: str = None):
        """Bruteforce all ROT cipher rotations."""
        allrot = ""
        for i in range(0, 26):
            upper = collections.deque(string.ascii_uppercase)
            lower = collections.deque(string.ascii_lowercase)
            upper.rotate(-i)
            lower.rotate(-i)
            upper = "".join(list(upper))
            lower = "".join(list(lower))
            translated = message.translate(
                str.maketrans(string.ascii_uppercase, upper)
            ).translate(str.maketrans(string.ascii_lowercase, lower))
            allrot += f"{i}: {translated}\n"
        await ctx.send(f"```{allrot}```")

    @commands.command()
    async def atbash(self, ctx: commands.Context, message: str):
        """Perform the atbash cipher on a message."""
        normal = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        changed = "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA"
        trans = str.maketrans(normal, changed)
        atbashed = message.translate(trans)
        await ctx.send(atbashed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ciphers(bot))
