import re
import discord
from discord.ext import tasks, commands
from datetime import datetime, timezone
from dateutil.parser import parse
import requests
from db import ctfs


class CtfTime(commands.Cog):
    """Commands for getting data from ctftime.org."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.upcoming_l = []
        self.updateDB.start()

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        print(error)

    def cog_unload(self):
        self.updateDB.cancel()

    @tasks.loop(minutes=30.0, reconnect=True)
    async def updateDB(self):
        """Every 30 minutes, grab the 5 closest upcoming CTFs from ctftime.org."""
        now = datetime.utcnow()
        unix_now = int(now.replace(tzinfo=timezone.utc).timestamp())
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0",
        }
        try:
            upcoming = "https://ctftime.org/api/v1/events/"
            limit = "5"
            response = requests.get(upcoming, headers=headers, params=limit)
            jdata = response.json()
        except Exception as e:
            print(f"Error fetching ctftime data: {e}")
            return

        info = []
        for num, i in enumerate(jdata):
            ctf_title = jdata[num]["title"]
            ctf_start = parse(jdata[num]["start"].replace("T", " ").split("+", 1)[0])
            ctf_end = parse(jdata[num]["finish"].replace("T", " ").split("+", 1)[0])
            unix_start = int(ctf_start.replace(tzinfo=timezone.utc).timestamp())
            unix_end = int(ctf_end.replace(tzinfo=timezone.utc).timestamp())
            dur_dict = jdata[num]["duration"]
            ctf_hours = str(dur_dict["hours"])
            ctf_days = str(dur_dict["days"])
            ctf_link = jdata[num]["url"]
            ctf_image = jdata[num]["logo"]
            ctf_format = jdata[num]["format"]
            ctf_place = "Online" if not jdata[num]["onsite"] else "Onsite"

            ctf = {
                "name": ctf_title,
                "start": unix_start,
                "end": unix_end,
                "dur": f"{ctf_days} days, {ctf_hours} hours",
                "url": ctf_link,
                "img": ctf_image,
                "format": f"{ctf_place} {ctf_format}",
            }
            info.append(ctf)

        got_ctfs = []
        for ctf in info:
            query = ctf["name"]
            ctfs.update({"name": query}, {"$set": ctf}, upsert=True)
            got_ctfs.append(ctf["name"])
        print(f"{datetime.now()}: Got and updated {got_ctfs}")

        # Delete CTFs that are over
        for ctf in ctfs.find():
            if ctf["end"] < unix_now:
                ctfs.remove({"name": ctf["name"]})

    @updateDB.before_loop
    async def before_updateDB(self):
        await self.bot.wait_until_ready()

    @commands.group()
    async def ctftime(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            ctftime_commands = list(
                set([c.qualified_name for c in CtfTime.walk_commands(self)][1:])
            )
            await ctx.send(f"Current ctftime commands are: {', '.join(ctftime_commands)}")

    @ctftime.command(aliases=["now", "running"])
    async def current(self, ctx: commands.Context):
        """Show currently running CTFs."""
        now = datetime.utcnow()
        unix_now = int(now.replace(tzinfo=timezone.utc).timestamp())
        running = False
        default_image = "https://pbs.twimg.com/profile_images/2189766987/ctftime-logo-avatar_400x400.png"

        for ctf in ctfs.find():
            if ctf["start"] < unix_now and ctf["end"] > unix_now:
                running = True
                embed = discord.Embed(
                    title=":red_circle: " + ctf["name"] + " IS LIVE",
                    description=ctf["url"],
                    color=15874645,
                )
                start = datetime.utcfromtimestamp(ctf["start"]).strftime("%Y-%m-%d %H:%M:%S") + " UTC"
                end = datetime.utcfromtimestamp(ctf["end"]).strftime("%Y-%m-%d %H:%M:%S") + " UTC"
                if ctf["img"] != "":
                    embed.set_thumbnail(url=ctf["img"])
                else:
                    embed.set_thumbnail(url=default_image)
                embed.add_field(name="Duration", value=ctf["dur"], inline=True)
                embed.add_field(name="Format", value=ctf["format"], inline=True)
                embed.add_field(name="Timeframe", value=f"{start} -> {end}", inline=True)
                await ctx.channel.send(embed=embed)

        if not running:
            await ctx.send(
                "No CTFs currently running! Check out `!ctftime countdown` and `!ctftime upcoming` "
                "to see when CTFs will start!"
            )

    @ctftime.command(aliases=["next"])
    async def upcoming(self, ctx: commands.Context, amount: str = None):
        """Show upcoming CTFs from ctftime.org."""
        if not amount:
            amount = "3"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0",
        }
        default_image = "https://pbs.twimg.com/profile_images/2189766987/ctftime-logo-avatar_400x400.png"
        upcoming_ep = "https://ctftime.org/api/v1/events/"
        try:
            r = requests.get(upcoming_ep, headers=headers, params=amount)
            upcoming_data = r.json()
        except Exception as e:
            await ctx.send(f"Error retrieving data: {e}")
            return

        for ctf_idx in range(0, int(amount)):
            try:
                ctf_title = upcoming_data[ctf_idx]["title"]
                ctf_start = upcoming_data[ctf_idx]["start"].replace("T", " ").split("+", 1)[0] + " UTC"
                ctf_end = upcoming_data[ctf_idx]["finish"].replace("T", " ").split("+", 1)[0] + " UTC"
                ctf_start = re.sub(":00 ", " ", ctf_start)
                ctf_end = re.sub(":00 ", " ", ctf_end)
                dur_dict = upcoming_data[ctf_idx]["duration"]
                ctf_hours = str(dur_dict["hours"])
                ctf_days = str(dur_dict["days"])
                ctf_link = upcoming_data[ctf_idx]["url"]
                ctf_image = upcoming_data[ctf_idx]["logo"]
                ctf_format = upcoming_data[ctf_idx]["format"]
                ctf_place = "Online" if not upcoming_data[ctf_idx]["onsite"] else "Onsite"

                embed = discord.Embed(title=ctf_title, description=ctf_link, color=int("f23a55", 16))
                if ctf_image != "":
                    embed.set_thumbnail(url=ctf_image)
                else:
                    embed.set_thumbnail(url=default_image)
                embed.add_field(name="Duration", value=f"{ctf_days} days, {ctf_hours} hours", inline=True)
                embed.add_field(name="Format", value=f"{ctf_place} {ctf_format}", inline=True)
                embed.add_field(name="Timeframe", value=f"{ctf_start} -> {ctf_end}", inline=True)
                await ctx.channel.send(embed=embed)
            except IndexError:
                break

    @ctftime.command(aliases=["leaderboard"])
    async def top(self, ctx: commands.Context, year: str = None):
        """Show ctftime.org leaderboards for a year (defaults to current year)."""
        if not year:
            year = str(datetime.today().year)
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0",
        }
        top_ep = f"https://ctftime.org/api/v1/top/{year}/"
        leaderboards = ""
        r = requests.get(top_ep, headers=headers)
        if r.status_code != 200:
            await ctx.send("Error retrieving data.")
        else:
            try:
                top_data = r.json()[year]
                for team in range(10):
                    rank = team + 1
                    teamname = top_data[team]["team_name"]
                    score = str(round(top_data[team]["points"], 4))

                    if team != 9:
                        leaderboards += f"\n[{rank}]    {teamname}: {score}"
                    else:
                        leaderboards += f"\n[{rank}]   {teamname}: {score}\n"

                await ctx.send(
                    f":triangular_flag_on_post:  **{year} CTFtime Leaderboards**```ini\n{leaderboards}```"
                )
            except KeyError:
                await ctx.send("Please supply a valid year.")

    @ctftime.command()
    async def timeleft(self, ctx: commands.Context):
        """Show time remaining for currently running CTFs."""
        now = datetime.utcnow()
        unix_now = int(now.replace(tzinfo=timezone.utc).timestamp())
        running = False
        for ctf in ctfs.find():
            if ctf["start"] < unix_now and ctf["end"] > unix_now:
                running = True
                time_left = ctf["end"] - unix_now
                days = time_left // (24 * 3600)
                time_left = time_left % (24 * 3600)
                hours = time_left // 3600
                time_left %= 3600
                minutes = time_left // 60
                time_left %= 60
                seconds = time_left
                await ctx.send(
                    f"```ini\n{ctf['name']} ends in: [{days} days], [{hours} hours], "
                    f"[{minutes} minutes], [{seconds} seconds]```\n{ctf['url']}"
                )

        if not running:
            await ctx.send(
                "No CTFs are running! Use `!ctftime upcoming` or `!ctftime countdown` to see upcoming CTFs."
            )

    @ctftime.command()
    async def countdown(self, ctx: commands.Context, params: str = None):
        """Show countdown to upcoming CTFs."""
        now = datetime.utcnow()
        unix_now = int(now.replace(tzinfo=timezone.utc).timestamp())

        if params is None:
            self.upcoming_l = []
            index = ""
            for ctf in ctfs.find():
                if ctf["start"] > unix_now:
                    self.upcoming_l.append(ctf)
            for i, c in enumerate(self.upcoming_l):
                index += f"\n[{i + 1}] {c['name']}\n"
            await ctx.send(f"Type `!ctftime countdown <number>` to select.\n```ini\n{index}```")
        else:
            if not self.upcoming_l:
                for ctf in ctfs.find():
                    if ctf["start"] > unix_now:
                        self.upcoming_l.append(ctf)
            try:
                x = int(params) - 1
                time_left = self.upcoming_l[x]["start"] - unix_now
                days = time_left // (24 * 3600)
                time_left = time_left % (24 * 3600)
                hours = time_left // 3600
                time_left %= 3600
                minutes = time_left // 60
                time_left %= 60
                seconds = time_left
                await ctx.send(
                    f"```ini\n{self.upcoming_l[x]['name']} starts in: [{days} days], [{hours} hours], "
                    f"[{minutes} minutes], [{seconds} seconds]```\n{self.upcoming_l[x]['url']}"
                )
            except (IndexError, ValueError):
                await ctx.send("Invalid selection. Use `!ctftime countdown` to see the list first.")


async def setup(bot: commands.Bot):
    await bot.add_cog(CtfTime(bot))
