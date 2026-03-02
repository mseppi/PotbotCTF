import base64
import binascii
import urllib.parse
import discord
from discord.ext import commands


class Encoding(commands.Cog):
    """Encoding/Decoding from various schemes."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send("There was an error with the data :[")

    @commands.command()
    async def b64(self, ctx: commands.Context, encode_or_decode: str, string: str):
        """Base64 encode or decode a string."""
        byted_str = str.encode(string)
        if encode_or_decode == "decode":
            decoded = base64.b64decode(byted_str).decode("utf-8")
            await ctx.send(decoded)
        if encode_or_decode == "encode":
            encoded = base64.b64encode(byted_str).decode("utf-8").replace("\n", "")
            await ctx.send(encoded)

    @commands.command()
    async def b32(self, ctx: commands.Context, encode_or_decode: str, string: str):
        """Base32 encode or decode a string."""
        byted_str = str.encode(string)
        if encode_or_decode == "decode":
            decoded = base64.b32decode(byted_str).decode("utf-8")
            await ctx.send(decoded)
        if encode_or_decode == "encode":
            encoded = base64.b32encode(byted_str).decode("utf-8").replace("\n", "")
            await ctx.send(encoded)

    @commands.command()
    async def binary(self, ctx: commands.Context, encode_or_decode: str, string: str):
        """Binary encode or decode a string."""
        if encode_or_decode == "decode":
            string = string.replace(" ", "")
            data = int(string, 2)
            decoded = data.to_bytes((data.bit_length() + 7) // 8, "big").decode()
            await ctx.send(decoded)
        if encode_or_decode == "encode":
            encoded = bin(int.from_bytes(string.encode(), "big")).replace("b", "")
            await ctx.send(encoded)

    @commands.command(name="hex")
    async def hex_cmd(self, ctx: commands.Context, encode_or_decode: str, string: str):
        """Hex encode or decode a string."""
        if encode_or_decode == "decode":
            string = string.replace(" ", "")
            decoded = binascii.unhexlify(string).decode("ascii")
            await ctx.send(decoded)
        if encode_or_decode == "encode":
            byted = string.encode()
            encoded = binascii.hexlify(byted).decode("ascii")
            await ctx.send(encoded)

    @commands.command()
    async def url(self, ctx: commands.Context, encode_or_decode: str, message: str):
        """URL encode or decode a string."""
        if encode_or_decode == "decode":
            if "%20" in message:
                message = message.replace("%20", "(space)")
                await ctx.send(urllib.parse.unquote(message))
            else:
                await ctx.send(urllib.parse.unquote(message))
        if encode_or_decode == "encode":
            await ctx.send(urllib.parse.quote(message))


async def setup(bot: commands.Bot):
    await bot.add_cog(Encoding(bot))
