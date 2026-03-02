import discord
from discord.ext import commands
import string
import requests
import traceback
from db import serverdb, teamdb


def in_ctf_channel():
    async def tocheck(ctx):
        if teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)}):
            return True
        else:
            await ctx.send("You must be in a created ctf channel to use ctf commands!")
            return False
    return commands.check(tocheck)


def strip_string(tostrip, whitelist):
    stripped = "".join([ch for ch in tostrip if ch in whitelist])
    return stripped.strip()


class InvalidProvider(Exception):
    pass

class InvalidCredentials(Exception):
    pass

class CredentialsNotFound(Exception):
    pass

class NonceNotFound(Exception):
    pass


def getChallenges(url, username, password):
    """Pull challenges from a CTFd platform using provided credentials."""
    whitelist = set(
        string.ascii_letters + string.digits + " " + "-" + "!" + "#" + "_"
        + "[" + "]" + "(" + ")" + "?" + "@" + "+" + "<" + ">"
    )
    fingerprint = "Powered by CTFd"
    s = requests.session()
    if url[-1] == "/":
        url = url[:-1]
    r = s.get(f"{url}/login")
    if fingerprint not in r.text:
        raise InvalidProvider("CTF is not based on CTFd, cannot pull challenges.")
    else:
        try:
            nonce = r.text.split("csrfNonce': \"")[1].split('"')[0]
        except:
            try:
                nonce = r.text.split('name="nonce" value="')[1].split('">')[0]
            except:
                raise NonceNotFound(
                    "Was not able to find the nonce token from login, please report this along with the ctf url."
                )
        r = s.post(f"{url}/login", data={"name": username, "password": password, "nonce": nonce})
        if "Your username or password is incorrect" in r.text:
            raise InvalidCredentials("Invalid login credentials")
        r_chals = s.get(f"{url}/api/v1/challenges")
        all_challenges = r_chals.json()
        r_solves = s.get(f"{url}/api/v1/teams/me/solves")
        team_solves = r_solves.json()
        if "success" not in team_solves:
            r_solves = s.get(f"{url}/api/v1/users/me/solves")
            team_solves = r_solves.json()

        solves = []
        if team_solves["success"]:
            for solve in team_solves["data"]:
                cat = solve["challenge"]["category"]
                challname = solve["challenge"]["name"]
                solves.append(f"<{cat}> {challname}")
        challenges = {}
        if all_challenges["success"]:
            for chal in all_challenges["data"]:
                cat = chal["category"]
                challname = chal["name"]
                name = f"<{cat}> {challname}"
                if name not in solves:
                    challenges[strip_string(name, whitelist)] = "Unsolved"
                else:
                    challenges[strip_string(name, whitelist)] = "Solved"
        else:
            raise Exception("Error making request")
        return challenges


class CTF(commands.Cog):
    """Commands for managing CTF competitions."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group()
    async def ctf(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            ctf_commands = list(set([c.qualified_name for c in CTF.walk_commands(self)][1:]))
            await ctx.send(f"Current ctf commands are: {', '.join(ctf_commands)}")

    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    @commands.has_permissions(manage_channels=True)
    @ctf.command(aliases=["new"])
    async def create(self, ctx: commands.Context, name: str):
        """Create a new CTF channel and role."""
        try:
            sconf = serverdb[str(ctx.guild.id) + "-CONF"]
            servcat = sconf.find_one({"name": "category_name"})["ctf_category"]
        except:
            servcat = "CTF"

        category = discord.utils.get(ctx.guild.categories, name=servcat)
        if category is None:
            await ctx.guild.create_category(name=servcat)
            category = discord.utils.get(ctx.guild.categories, name=servcat)

        ctf_name = (
            strip_string(name, set(string.ascii_letters + string.digits + " " + "-"))
            .replace(" ", "-")
            .lower()
        )
        if ctf_name and ctf_name[0] == "-":
            ctf_name = ctf_name[1:]
        # Remove consecutive dashes
        new_ctf_name = ctf_name
        prev = ""
        while "--" in ctf_name:
            for i, c in enumerate(ctf_name):
                if c == prev and c == "-":
                    new_ctf_name = ctf_name[:i] + ctf_name[i + 1 :]
                prev = c
            ctf_name = new_ctf_name

        await ctx.guild.create_text_channel(name=ctf_name, category=category)
        server = teamdb[str(ctx.guild.id)]
        await ctx.guild.create_role(name=ctf_name, mentionable=True)

        ctf_info = {"name": ctf_name, "text_channel": ctf_name}
        server.update({"name": ctf_name}, {"$set": ctf_info}, upsert=True)
        await ctx.message.add_reaction("✅")

    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    @commands.has_permissions(manage_channels=True)
    @ctf.command()
    @in_ctf_channel()
    async def delete(self, ctx: commands.Context):
        """Delete the current CTF channel, role, and data."""
        try:
            role = discord.utils.get(ctx.guild.roles, name=str(ctx.message.channel))
            await role.delete()
            await ctx.send(f"`{role.name}` role deleted")
        except:
            pass
        teamdb[str(ctx.guild.id)].remove({"name": str(ctx.message.channel)})
        await ctx.send(f"`{str(ctx.message.channel)}` deleted from db")

    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    @commands.has_permissions(manage_channels=True)
    @ctf.command(aliases=["over"])
    @in_ctf_channel()
    async def archive(self, ctx: commands.Context):
        """Archive the current CTF channel (delete role, move to archive category)."""
        role = discord.utils.get(ctx.guild.roles, name=str(ctx.message.channel))
        if role:
            await role.delete()
            await ctx.send(f"`{role.name}` role deleted, archiving channel.")
        try:
            sconf = serverdb[str(ctx.guild.id) + "-CONF"]
            servarchive = sconf.find_one({"name": "archive_category_name"})["archive_category"]
        except:
            servarchive = "ARCHIVE"

        category = discord.utils.get(ctx.guild.categories, name=servarchive)
        if category is None:
            await ctx.guild.create_category(name=servarchive)
            category = discord.utils.get(ctx.guild.categories, name=servarchive)
        await ctx.message.channel.edit(sync_permissions=True, category=category)

    @ctf.command()
    @in_ctf_channel()
    async def end(self, ctx: commands.Context):
        """Deprecated: use >ctf delete or >ctf archive instead."""
        await ctx.send(
            "You can now use either `!ctf delete` (which will delete all data), or `!ctf archive/over` "
            "which will move the channel and delete the role, but retain challenge info "
            "(`!config archive_category \"archive category\"` to specify where to archive)."
        )

    @commands.bot_has_permissions(manage_roles=True)
    @ctf.command()
    @in_ctf_channel()
    async def join(self, ctx: commands.Context):
        """Join the current CTF team."""
        role = discord.utils.get(ctx.guild.roles, name=str(ctx.message.channel))
        user = ctx.message.author
        await user.add_roles(role)
        await ctx.send(f"{user} has joined the {str(ctx.message.channel)} team!")

    @commands.bot_has_permissions(manage_roles=True)
    @ctf.command()
    @in_ctf_channel()
    async def leave(self, ctx: commands.Context):
        """Leave the current CTF team."""
        role = discord.utils.get(ctx.guild.roles, name=str(ctx.message.channel))
        user = ctx.message.author
        await user.remove_roles(role)
        await ctx.send(f"{user} has left the {str(ctx.message.channel)} team.")

    @ctf.group(aliases=["chal", "chall", "challenges"])
    @in_ctf_channel()
    async def challenge(self, ctx: commands.Context):
        pass

    @staticmethod
    def updateChallenge(ctx, name, status):
        server = teamdb[str(ctx.guild.id)]
        whitelist = set(
            string.ascii_letters + string.digits + " " + "-" + "!" + "#" + "_"
            + "[" + "]" + "(" + ")" + "?" + "@" + "+" + "<" + ">"
        )
        challenge = {strip_string(str(name), whitelist): status}
        ctf = server.find_one({"name": str(ctx.message.channel)})
        try:
            challenges = ctf["challenges"]
            challenges.update(challenge)
        except:
            challenges = challenge
        ctf_info = {"name": str(ctx.message.channel), "challenges": challenges}
        server.update({"name": str(ctx.message.channel)}, {"$set": ctf_info}, upsert=True)

    @challenge.command(aliases=["a"])
    @in_ctf_channel()
    async def add(self, ctx: commands.Context, name: str):
        """Add a challenge to the current CTF."""
        CTF.updateChallenge(ctx, name, "Unsolved")
        await ctx.send(f"`{name}` has been added to the challenge list for `{str(ctx.message.channel)}`")

    @challenge.command(aliases=["s", "solve"])
    @in_ctf_channel()
    async def solved(self, ctx: commands.Context, name: str):
        """Mark a challenge as solved."""
        solve = f"Solved - {str(ctx.message.author)}"
        CTF.updateChallenge(ctx, name, solve)
        await ctx.send(f":triangular_flag_on_post: `{name}` has been solved by `{str(ctx.message.author)}`")

    @challenge.command(aliases=["w"])
    @in_ctf_channel()
    async def working(self, ctx: commands.Context, name: str):
        """Mark that you're working on a challenge."""
        work = f"Working - {str(ctx.message.author)}"
        CTF.updateChallenge(ctx, name, work)
        await ctx.send(f"`{str(ctx.message.author)}` is working on `{name}`!")

    @challenge.command(aliases=["r", "delete", "d"])
    @in_ctf_channel()
    async def remove(self, ctx: commands.Context, name: str):
        """Remove a challenge from the list."""
        ctf = teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)})
        challenges = ctf["challenges"]
        whitelist = set(
            string.ascii_letters + string.digits + " " + "-" + "!" + "#" + "_"
            + "[" + "]" + "(" + ")" + "?" + "@" + "+" + "<" + ">"
        )
        name = strip_string(name, whitelist)
        challenges.pop(name, None)
        ctf_info = {"name": str(ctx.message.channel), "challenges": challenges}
        teamdb[str(ctx.guild.id)].update(
            {"name": str(ctx.message.channel)}, {"$set": ctf_info}, upsert=True
        )
        await ctx.send(f"Removed `{name}`")

    @challenge.command(aliases=["get", "ctfd"])
    @in_ctf_channel()
    async def pull(self, ctx: commands.Context, url: str):
        """Pull challenges from a CTFd platform."""
        try:
            try:
                pinned = await ctx.message.channel.pins()
                user_pass = CTF.get_creds(pinned)
            except CredentialsNotFound as cnfm:
                await ctx.send(cnfm)
                return
            ctfd_challs = getChallenges(url, user_pass[0], user_pass[1])
            ctf = teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)})
            try:
                challenges = ctf["challenges"]
                challenges.update(ctfd_challs)
            except:
                challenges = ctfd_challs
            ctf_info = {"name": str(ctx.message.channel), "challenges": challenges}
            teamdb[str(ctx.guild.id)].update(
                {"name": str(ctx.message.channel)}, {"$set": ctf_info}, upsert=True
            )
            await ctx.message.add_reaction("✅")
        except InvalidProvider as ipm:
            await ctx.send(ipm)
        except InvalidCredentials as icm:
            await ctx.send(icm)
        except NonceNotFound as nnfm:
            await ctx.send(nnfm)
        except requests.exceptions.MissingSchema:
            await ctx.send("Supply a valid url in the form: `http(s)://ctfd.url`")
        except:
            traceback.print_exc()

    @commands.bot_has_permissions(manage_messages=True)
    @commands.has_permissions(manage_messages=True)
    @ctf.command(aliases=["login"])
    @in_ctf_channel()
    async def setcreds(self, ctx: commands.Context, username: str, password: str):
        """Set CTFd credentials (pinned in channel)."""
        pinned = await ctx.message.channel.pins()
        for pin in pinned:
            if "CTF credentials set." in pin.content:
                await pin.unpin()
        msg = await ctx.send(f"CTF credentials set. name:{username} password:{password}")
        await msg.pin()

    @commands.bot_has_permissions(manage_messages=True)
    @ctf.command(aliases=["getcreds"])
    @in_ctf_channel()
    async def creds(self, ctx: commands.Context):
        """Show the stored CTFd credentials."""
        pinned = await ctx.message.channel.pins()
        try:
            user_pass = CTF.get_creds(pinned)
            await ctx.send(f"name:`{user_pass[0]}` password:`{user_pass[1]}`")
        except CredentialsNotFound as cnfm:
            await ctx.send(cnfm)

    @staticmethod
    def get_creds(pinned):
        for pin in pinned:
            if "CTF credentials set." in pin.content:
                user_pass = pin.content.split("name:")[1].split(" password:")
                return user_pass
        raise CredentialsNotFound('Set credentials with `!ctf setcreds "username" "password"`')

    @staticmethod
    def gen_page(challengelist):
        challenge_page = ""
        challenge_pages = []
        for c in challengelist:
            if not len(challenge_page + c) >= 1989:
                challenge_page += c
                if c == challengelist[-1]:
                    challenge_pages.append(challenge_page)
            elif len(challenge_page + c) >= 1989:
                challenge_pages.append(challenge_page)
                challenge_page = ""
                challenge_page += c
        return challenge_pages

    @challenge.command(aliases=["ls", "l"])
    @in_ctf_channel()
    async def list(self, ctx: commands.Context):
        """List challenges in the current CTF."""
        server = teamdb[str(ctx.guild.id)]
        ctf = server.find_one({"name": str(ctx.message.channel)})
        try:
            ctf_challenge_list = []
            for k, v in ctf["challenges"].items():
                challenge = f"[{k}]: {v}\n"
                ctf_challenge_list.append(challenge)
            for page in CTF.gen_page(ctf_challenge_list):
                await ctx.send(f"```ini\n{page}```")
        except KeyError:
            await ctx.send('Add some challenges with `!ctf challenge add "challenge name"`')
        except:
            traceback.print_exc()


async def setup(bot: commands.Bot):
    await bot.add_cog(CTF(bot))
