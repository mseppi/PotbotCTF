import discord
from discord.ext import commands
import asyncio
import string
import re
import requests
import traceback
from db import serverdb, teamdb


def in_ctf_channel():
    async def tocheck(ctx):
        if teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)}):
            return True
        else:
            # Only send the error when the user actually invoked the command,
            # not when the help command is probing checks.
            if ctx.invoked_with != "help":
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

        solved_ids = set()
        if team_solves["success"]:
            for solve in team_solves["data"]:
                solved_ids.add(solve["challenge"]["id"])
        
        challenges = {}
        if all_challenges["success"]:
            for chal in all_challenges["data"]:
                chal_id = chal["id"]
                cat = chal["category"]
                challname = chal["name"]
                description = chal.get("description", "")
                value = chal.get("value", 0)
                
                status = "Solved" if chal_id in solved_ids else "Unsolved"
                
                challenges[str(chal_id)] = {
                    "id": chal_id,
                    "name": challname,
                    "category": cat,
                    "description": description,
                    "value": value,
                    "status": status
                }
        else:
            raise Exception("Error making request")
        return challenges, s, url


def submitFlag(session, base_url, challenge_id, flag):
    """Submit a flag to CTFd. Returns (correct: bool, message: str)."""
    # Fetch a page to extract the csrfNonce (required for POST API calls)
    r = session.get(f"{base_url}/challenges")
    try:
        nonce = r.text.split("csrfNonce': \"")[1].split('"')[0]
    except Exception:
        try:
            nonce = r.text.split('name="nonce" value="')[1].split('">')[0]
        except Exception:
            raise NonceNotFound("Could not find CSRF nonce for flag submission.")
    resp = session.post(
        f"{base_url}/api/v1/challenges/attempt",
        json={"challenge_id": challenge_id, "submission": flag},
        headers={"Csrf-Token": nonce, "Content-Type": "application/json"},
    )
    try:
        data = resp.json()
    except Exception:
        return False, f"Unexpected response (HTTP {resp.status_code}). The CTF may have ended or the platform rejected the request."
    if data.get("success"):
        result = data["data"]
        status = result.get("status", "")
        message = result.get("message", "")
        return status == "correct", message
    return False, data.get("message", "Submission failed.")


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
            ctfd_challs, session, base_url = getChallenges(url, user_pass[0], user_pass[1])
            ctf = teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)})
            try:
                challenges = ctf["challenges"]
                challenges.update(ctfd_challs)
            except:
                challenges = ctfd_challs
            ctf_info = {
                "name": str(ctx.message.channel), 
                "challenges": challenges,
                "ctf_url": url,
                "ctf_creds": {"username": user_pass[0], "password": user_pass[1]}
            }
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

    @staticmethod
    def find_challenge(ctf, identifier):
        """Find a challenge by ID number or partial name match. Returns (key, data) or None."""
        challenges = ctf.get("challenges", {})
        # Try exact ID match first
        if str(identifier) in challenges:
            c = challenges[str(identifier)]
            if isinstance(c, dict):
                return str(identifier), c
        # Try matching by name (case-insensitive partial match)
        identifier_lower = str(identifier).lower()
        for key, val in challenges.items():
            if isinstance(val, dict):
                if identifier_lower in val.get("name", "").lower():
                    return key, val
            else:
                if identifier_lower in key.lower():
                    return key, val
        return None

    @challenge.command(aliases=["ls", "l"])
    @in_ctf_channel()
    async def list(self, ctx: commands.Context):
        """List challenges in the current CTF (with IDs and points)."""
        server = teamdb[str(ctx.guild.id)]
        ctf = server.find_one({"name": str(ctx.message.channel)})
        try:
            challenges = ctf["challenges"]
            if not challenges:
                raise KeyError
            ctf_challenge_list = []
            for k, v in challenges.items():
                if isinstance(v, dict):
                    # Rich challenge data from pull
                    pts = v.get('value', '?')
                    status = v.get('status', 'Unknown')
                    icon = '\u2705' if 'Solved' in status else ('\U0001f527' if 'Working' in status else '\u274c')
                    line = f"{icon} [{k}] <{v.get('category', '?')}> {v['name']} ({pts} pts) - {status}\n"
                else:
                    # Legacy format (manually added)
                    icon = '\u2705' if 'Solved' in str(v) else ('\U0001f527' if 'Working' in str(v) else '\u274c')
                    line = f"{icon} [{k}]: {v}\n"
                ctf_challenge_list.append(line)
            for page in CTF.gen_page(ctf_challenge_list):
                await ctx.send(f"```{page}```")
        except KeyError:
            await ctx.send('No challenges yet. Use `!ctf challenge pull <url>` or `!ctf challenge add "name"`')
        except:
            traceback.print_exc()

    @challenge.command(aliases=["i", "show"])
    @in_ctf_channel()
    async def info(self, ctx: commands.Context, *, identifier: str):
        """Show full details of a challenge by ID or name. Usage: !ctf challenge info <id or name>"""
        ctf = teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)})
        if not ctf or "challenges" not in ctf:
            await ctx.send("No challenges found. Pull challenges first.")
            return
        result = CTF.find_challenge(ctf, identifier)
        if result is None:
            await ctx.send(f"Challenge `{identifier}` not found. Use `!ctf challenge list` to see available challenges.")
            return
        key, val = result
        if not isinstance(val, dict) or "id" not in val:
            await ctx.send(f"**{key}**: {val}")
            return

        # Fetch full challenge details from CTFd (description, files, etc.)
        ctf_url = ctf.get("ctf_url")
        ctf_creds = ctf.get("ctf_creds")
        desc = val.get("description", "") or ""
        files = []
        hints = []
        if ctf_url and ctf_creds:
            try:
                _, session, base_url = getChallenges(ctf_url, ctf_creds["username"], ctf_creds["password"])
                r = session.get(f"{base_url}/api/v1/challenges/{val['id']}")
                detail = r.json()
                if detail.get("success"):
                    chal_data = detail["data"]
                    desc = chal_data.get("description", desc)
                    files = chal_data.get("files", [])
                    hints = chal_data.get("hints", [])
                    # Update stored data with full description
                    challenges = ctf.get("challenges", {})
                    if key in challenges and isinstance(challenges[key], dict):
                        challenges[key]["description"] = desc
                        challenges[key]["files"] = files
                        challenges[key]["hints"] = hints
                        teamdb[str(ctx.guild.id)].update(
                            {"name": str(ctx.message.channel)},
                            {"$set": {"challenges": challenges}},
                            upsert=True,
                        )
            except Exception:
                pass  # Fall back to stored data

        # Strip HTML tags from description
        desc = re.sub(r'<[^>]+>', '', desc).strip()
        if not desc:
            desc = "No description"
        if len(desc) > 1500:
            desc = desc[:1500] + "..."

        embed = discord.Embed(
            title=f"{val.get('name', key)}",
            description=desc,
            color=discord.Color.green() if 'Solved' in val.get('status', '') else discord.Color.red(),
        )
        embed.add_field(name="Category", value=val.get('category', '?'), inline=True)
        embed.add_field(name="Points", value=str(val.get('value', '?')), inline=True)
        embed.add_field(name="Status", value=val.get('status', 'Unknown'), inline=True)
        embed.add_field(name="ID", value=str(val.get('id', key)), inline=True)

        # Add attachment/file links
        if files:
            file_links = []
            for f in files:
                if f.startswith("http"):
                    file_url = f
                else:
                    file_url = f"{ctf_url}{f}" if ctf_url else f
                filename = f.split("/")[-1].split("?")[0]
                file_links.append(f"[{filename}]({file_url})")
            embed.add_field(name="Attachments", value="\n".join(file_links), inline=False)

        # Add hints
        if hints:
            hint_lines = []
            for i, h in enumerate(hints, 1):
                if isinstance(h, dict):
                    content = h.get("content") or h.get("html", "")
                    cost = h.get("cost", 0)
                    if content:
                        clean = re.sub(r'<[^>]+>', '', content).strip()
                        hint_lines.append(f"**Hint {i}** (cost: {cost}): {clean}")
                    else:
                        hint_lines.append(f"**Hint {i}** (cost: {cost}): *Locked — unlock on CTFd*")
                elif isinstance(h, str):
                    hint_lines.append(f"**Hint {i}**: {h}")
            if hint_lines:
                embed.add_field(name="Hints", value="\n".join(hint_lines), inline=False)

        await ctx.send(embed=embed)

    @challenge.command(aliases=["hints", "h"])
    @in_ctf_channel()
    async def hint(self, ctx: commands.Context, identifier: str, hint_num: int = None):
        """View or unlock a hint. Usage: !ctf challenge hint <id or name> [hint_number]"""
        ctf = teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)})
        if not ctf or "challenges" not in ctf:
            await ctx.send("No challenges found. Pull challenges first.")
            return
        result = CTF.find_challenge(ctf, identifier)
        if result is None:
            await ctx.send(f"Challenge `{identifier}` not found.")
            return
        key, val = result
        if not isinstance(val, dict) or "id" not in val:
            await ctx.send("This challenge has no CTFd data.")
            return

        ctf_url = ctf.get("ctf_url")
        ctf_creds = ctf.get("ctf_creds")
        if not ctf_url or not ctf_creds:
            await ctx.send("No CTF URL or credentials stored. Run `!ctf challenge pull <url>` first.")
            return

        try:
            _, session, base_url = getChallenges(ctf_url, ctf_creds["username"], ctf_creds["password"])
            # Fetch the CSRF nonce for POST requests
            page = session.get(f"{base_url}/challenges")
            try:
                nonce = page.text.split("csrfNonce': \"")[1].split('"')[0]
            except Exception:
                nonce = ""

            # Get challenge details for hints
            r = session.get(f"{base_url}/api/v1/challenges/{val['id']}")
            detail = r.json()
            if not detail.get("success"):
                await ctx.send("Failed to fetch challenge details.")
                return
            hints = detail["data"].get("hints", [])
            if not hints:
                await ctx.send("This challenge has no hints.")
                return

            # If no hint number specified, list all hints
            if hint_num is None:
                hint_lines = []
                for i, h in enumerate(hints, 1):
                    if isinstance(h, dict):
                        content = h.get("content") or h.get("html", "")
                        cost = h.get("cost", 0)
                        if content:
                            clean = re.sub(r'<[^>]+>', '', content).strip()
                            hint_lines.append(f"**Hint {i}** (cost: {cost}): {clean}")
                        else:
                            hint_lines.append(f"**Hint {i}** (cost: {cost}): 🔒 *Locked* — use `!ctf challenge hint {identifier} {i}` to unlock")
                    elif isinstance(h, str):
                        hint_lines.append(f"**Hint {i}**: {h}")
                await ctx.send("\n".join(hint_lines))
                return

            # Specific hint requested
            if hint_num < 1 or hint_num > len(hints):
                await ctx.send(f"Invalid hint number. This challenge has {len(hints)} hint(s).")
                return
            h = hints[hint_num - 1]
            if not isinstance(h, dict):
                await ctx.send(f"**Hint {hint_num}**: {h}")
                return

            hint_id = h.get("id")
            content = h.get("content") or h.get("html", "")
            cost = h.get("cost", 0)

            # If already unlocked, just show it
            if content:
                clean = re.sub(r'<[^>]+>', '', content).strip()
                await ctx.send(f"**Hint {hint_num}** (cost: {cost}): {clean}")
                return

            # Locked — ask for confirmation
            confirm_msg = await ctx.send(
                f"🔒 **Hint {hint_num}** costs **{cost} points** to unlock. React ✅ to confirm or ❌ to cancel."
            )
            await confirm_msg.add_reaction("✅")
            await confirm_msg.add_reaction("❌")

            def check(reaction, user):
                return (
                    user == ctx.message.author
                    and str(reaction.emoji) in ("✅", "❌")
                    and reaction.message.id == confirm_msg.id
                )

            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Hint unlock timed out.")
                return

            if str(reaction.emoji) == "❌":
                await ctx.send("Hint unlock cancelled.")
                return

            # Unlock the hint via CTFd API
            resp = session.post(
                f"{base_url}/api/v1/unlocks",
                json={"target": hint_id, "type": "hints"},
                headers={"Csrf-Token": nonce, "Content-Type": "application/json"},
            )
            try:
                unlock_data = resp.json()
            except Exception:
                await ctx.send(f"Unexpected response from CTFd (HTTP {resp.status_code}).")
                return

            if unlock_data.get("success"):
                # Fetch the now-unlocked hint content
                hint_resp = session.get(f"{base_url}/api/v1/hints/{hint_id}")
                try:
                    hint_detail = hint_resp.json()
                    if hint_detail.get("success"):
                        content = hint_detail["data"].get("content") or hint_detail["data"].get("html", "")
                        clean = re.sub(r'<[^>]+>', '', content).strip()
                        await ctx.send(f"🔓 **Hint {hint_num}** unlocked!\n{clean}")
                    else:
                        await ctx.send("🔓 Hint unlocked but could not fetch content.")
                except Exception:
                    await ctx.send("🔓 Hint unlocked but could not parse response.")
            else:
                msg = unlock_data.get("errors", unlock_data.get("message", "Unknown error"))
                await ctx.send(f"❌ Failed to unlock hint: {msg}")

        except InvalidCredentials:
            await ctx.send("Stored credentials are invalid. Update them with `!ctf setcreds`.")
        except Exception as e:
            await ctx.send(f"Error: {e}")
            traceback.print_exc()

    @challenge.command(aliases=["flag", "sub"])
    @in_ctf_channel()
    async def submit(self, ctx: commands.Context, identifier: str, *, flag: str):
        """Submit a flag for a challenge. Usage: !ctf challenge submit <id or name> <flag>"""
        ctf = teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)})
        if not ctf:
            await ctx.send("No CTF data found.")
            return
        # Find the challenge
        result = CTF.find_challenge(ctf, identifier)
        if result is None:
            await ctx.send(f"Challenge `{identifier}` not found. Use `!ctf challenge list` to see available challenges.")
            return
        key, val = result
        if not isinstance(val, dict) or "id" not in val:
            await ctx.send("This challenge was added manually and has no CTFd ID. Cannot submit remotely.")
            return
        chal_id = val["id"]
        # Get CTF URL and creds
        ctf_url = ctf.get("ctf_url")
        ctf_creds = ctf.get("ctf_creds")
        if not ctf_url or not ctf_creds:
            # Fall back to pinned creds
            try:
                pinned = await ctx.message.channel.pins()
                user_pass = CTF.get_creds(pinned)
                ctf_creds = {"username": user_pass[0], "password": user_pass[1]}
            except CredentialsNotFound:
                await ctx.send("No CTF URL or credentials stored. Run `!ctf challenge pull <url>` first.")
                return
            if not ctf_url:
                await ctx.send("No CTF URL stored. Run `!ctf challenge pull <url>` first.")
                return
        try:
            # Reuse getChallenges to get an authenticated session
            _, session, base_url = getChallenges(ctf_url, ctf_creds["username"], ctf_creds["password"])
            correct, message = submitFlag(session, base_url, chal_id, flag)
            if correct:
                # Update status in DB
                challenges = ctf.get("challenges", {})
                if key in challenges and isinstance(challenges[key], dict):
                    challenges[key]["status"] = f"Solved - {str(ctx.message.author)}"
                teamdb[str(ctx.guild.id)].update(
                    {"name": str(ctx.message.channel)},
                    {"$set": {"challenges": challenges}},
                    upsert=True,
                )
                await ctx.send(f":triangular_flag_on_post: **Correct!** `{val['name']}` solved by `{ctx.message.author}`\n{message}")
            else:
                await ctx.send(f":x: **Incorrect.** {message}")
        except InvalidCredentials:
            await ctx.send("Stored credentials are invalid. Update them with `!ctf setcreds`.")
        except InvalidProvider:
            await ctx.send("CTF platform is not CTFd-based.")
        except Exception as e:
            await ctx.send(f"Error submitting flag: {e}")
            traceback.print_exc()

    @ctf.command(aliases=["notifs", "noti"])
    @in_ctf_channel()
    async def notifications(self, ctx: commands.Context, count: int = 5):
        """Show latest CTFd notifications. Usage: !ctf notifications [count]"""
        ctf = teamdb[str(ctx.guild.id)].find_one({"name": str(ctx.message.channel)})
        if not ctf:
            await ctx.send("No CTF data found.")
            return
        ctf_url = ctf.get("ctf_url")
        ctf_creds = ctf.get("ctf_creds")
        if not ctf_url or not ctf_creds:
            await ctx.send("No CTF URL or credentials stored. Run `!ctf challenge pull <url>` first.")
            return
        count = max(1, min(count, 20))
        try:
            _, session, base_url = getChallenges(ctf_url, ctf_creds["username"], ctf_creds["password"])
            r = session.get(f"{base_url}/api/v1/notifications")
            data = r.json()
            if not data.get("success"):
                await ctx.send("Failed to fetch notifications.")
                return
            notifs = data.get("data", [])
            if not notifs:
                await ctx.send("No notifications.")
                return
            # Show latest N (API typically returns newest first)
            for n in notifs[:count]:
                title = n.get("title", "Untitled")
                content = n.get("content", "") or ""
                content = re.sub(r'<[^>]+>', '', content).strip()
                date = n.get("date", "")
                embed = discord.Embed(
                    title=f"📢 {title}",
                    description=content[:2000] if content else "No content",
                    color=discord.Color.blue(),
                )
                if date:
                    embed.set_footer(text=date)
                await ctx.send(embed=embed)
        except InvalidCredentials:
            await ctx.send("Stored credentials are invalid. Update them with `!ctf setcreds`.")
        except Exception as e:
            await ctx.send(f"Error fetching notifications: {e}")
            traceback.print_exc()


async def setup(bot: commands.Bot):
    await bot.add_cog(CTF(bot))
