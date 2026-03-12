import re
import discord
from discord.ext import tasks, commands
from datetime import datetime, timezone, timedelta
from dateutil.parser import parse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from db import ctfs, serverdb


class CtfTime(commands.Cog):
    """Commands for getting data from ctftime.org."""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0",
    }
    DEFAULT_IMAGE = "https://pbs.twimg.com/profile_images/2189766987/ctftime-logo-avatar_400x400.png"
    TZ = timezone(timedelta(hours=2))  # UTC+2

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.upcoming_l = []
        self.my_upcoming_l = []
        self.updateDB.start()

    # ── Helpers ──────────────────────────────────────────────

    def _get_team_config(self, guild_id: int):
        """Return the team doc for a guild, or None."""
        sconf = serverdb[str(guild_id) + "-CONF"]
        return sconf.find_one({"name": "ctftime_team"})

    def _scrape_team_events(self, team_id: int) -> list[dict]:
        """Scrape planned events directly from the CTFtime team page (no API calls).

        Returns a list of dicts with keys: name, url, event_id, start, date_str.
        'start' is a UTC unix timestamp parsed from the date column.
        """
        try:
            r = requests.get(f"https://ctftime.org/team/{team_id}", headers=self.HEADERS)
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception:
            return []

        events = []
        # Find the "Plan to participate" / "Upcoming" section
        for header in soup.find_all(["h2", "h3", "h4"]):
            header_text = header.get_text().lower()
            if any(w in header_text for w in ["plan", "upcoming", "will participate"]):
                table = header.find_next("table")
                if not table:
                    continue
                for row in table.find_all("tr"):
                    cols = row.find_all("td")
                    if len(cols) < 2:
                        continue
                    link = cols[0].find("a", href=re.compile(r"/event/(\d+)"))
                    if not link:
                        continue
                    m = re.search(r"/event/(\d+)", link["href"])
                    if not m:
                        continue
                    event_name = link.get_text(strip=True)
                    event_id = int(m.group(1))
                    date_str = cols[1].get_text(strip=True)
                    # Parse date like "March 27, 2026, 7 p.m." or "Feb. 18, 2026, 2 a.m."
                    # Treat as UTC for consistency with countdown logic
                    try:
                        unix_start = int(parse(date_str).replace(tzinfo=timezone.utc).timestamp())
                    except Exception:
                        unix_start = 0
                    events.append({
                        "name": event_name,
                        "url": f"https://ctftime.org/event/{event_id}",
                        "event_id": event_id,
                        "start": unix_start,
                        "date_str": date_str,
                        "img": "",
                    })
                break  # Only process the first matching table
        return events

    def _scrape_team_past_events(self, team_id: int, year: int = None) -> list[dict]:
        """Scrape past participated events from the CTFtime team page.

        Returns a list of dicts: name, url, event_id, place, ctf_points, rating_points.
        If year is given, only returns events from that year's tab.
        """
        try:
            r = requests.get(f"https://ctftime.org/team/{team_id}", headers=self.HEADERS)
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception:
            return []

        events = []
        for header in soup.find_all(["h2", "h3", "h4"]):
            if "participated" in header.get_text().lower():
                # The tab-content div after this header contains yearly tables
                tab_content = header.find_next("div", class_="tab-content")
                if not tab_content:
                    continue
                # Each year is a tab-pane; IDs like "year_2025" or just iterate tables
                if year is not None:
                    pane = tab_content.find("div", id=re.compile(rf"rating[_\-]?{year}", re.I))
                    tables = pane.find_all("table", class_="table") if pane else []
                else:
                    tables = tab_content.find_all("table", class_="table")
                for table in tables:
                    for row in table.find_all("tr"):
                        cols = row.find_all("td")
                        if len(cols) < 4:
                            continue
                        link = row.find("a", href=re.compile(r"/event/(\d+)"))
                        if not link:
                            continue
                        m = re.search(r"/event/(\d+)", link["href"])
                        if not m:
                            continue
                        # cols: [place_ico, place, event_link, ctf_points, rating_points]
                        place_text = cols[1].get_text(strip=True) if len(cols) > 1 else "?"
                        ctf_pts = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                        rat_pts = cols[4].get_text(strip=True) if len(cols) > 4 else ""
                        events.append({
                            "name": link.get_text(strip=True),
                            "url": f"https://ctftime.org/event/{m.group(1)}",
                            "event_id": int(m.group(1)),
                            "place": place_text,
                            "ctf_points": ctf_pts,
                            "rating_points": rat_pts,
                        })
                break
        return events

    def _fetch_event_weight(self, event_id: int) -> float:
        """Fetch the weight of an event from the CTFtime API."""
        try:
            r = requests.get(
                f"https://ctftime.org/api/v1/events/{event_id}/", headers=self.HEADERS
            )
            if r.status_code == 200:
                return float(r.json().get("weight", 0.0))
        except Exception:
            pass
        return 0.0

    def _fetch_event_detail(self, event_id: int) -> dict | None:
        """Fetch a single event from the CTFtime API and return a normalized dict."""
        try:
            r = requests.get(
                f"https://ctftime.org/api/v1/events/{event_id}/", headers=self.HEADERS
            )
            if r.status_code != 200:
                return None
            data = r.json()
            ctf_start = parse(data["start"].replace("T", " ").split("+", 1)[0])
            ctf_end = parse(data["finish"].replace("T", " ").split("+", 1)[0])
            unix_start = int(ctf_start.replace(tzinfo=timezone.utc).timestamp())
            unix_end = int(ctf_end.replace(tzinfo=timezone.utc).timestamp())
            dur = data.get("duration", {})
            ctf_place = "Online" if not data.get("onsite") else "Onsite"
            return {
                "name": data["title"],
                "start": unix_start,
                "end": unix_end,
                "dur": f"{dur.get('days', 0)} days, {dur.get('hours', 0)} hours",
                "url": data["url"],
                "img": data.get("logo", ""),
                "format": f"{ctf_place} {data.get('format', '')}",
            }
        except Exception:
            return None

    def _get_team_events(self, guild_id: int) -> tuple[list[dict], str]:
        """Return (list_of_event_dicts, team_name) for the guild's team.

        Uses HTML scraping only (fast, single request).
        """
        team_doc = self._get_team_config(guild_id)
        if not team_doc:
            return [], ""
        team_id = team_doc["team_id"]
        team_name = team_doc.get("team_name", "Your team")
        events = self._scrape_team_events(team_id)
        return events, team_name

    def _get_team_events_full(self, guild_id: int) -> tuple[list[dict], str]:
        """Like _get_team_events but fetches full details (including end time) from the API.

        Used only by mycurrent/mytimeleft which need end timestamps.
        """
        team_doc = self._get_team_config(guild_id)
        if not team_doc:
            return [], ""
        team_id = team_doc["team_id"]
        team_name = team_doc.get("team_name", "Your team")
        scraped = self._scrape_team_events(team_id)
        # Only fetch API details for events that could be running now (started in past)
        now_unix = int(datetime.utcnow().replace(tzinfo=timezone.utc).timestamp())
        need_detail = [e for e in scraped if e["start"] <= now_unix]
        if not need_detail:
            return [], team_name
        events = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(self._fetch_event_detail, e["event_id"]): e for e in need_detail}
            for fut in as_completed(futures):
                ev = fut.result()
                if ev:
                    events.append(ev)
        return events, team_name

    @staticmethod
    def _format_timeleft(seconds_remaining: int) -> str:
        days = seconds_remaining // (24 * 3600)
        seconds_remaining %= 24 * 3600
        hours = seconds_remaining // 3600
        seconds_remaining %= 3600
        minutes = seconds_remaining // 60
        seconds_remaining %= 60
        return f"[{days} days], [{hours} hours], [{minutes} minutes], [{seconds_remaining} seconds]"

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        print(error)

    def cog_unload(self):
        self.updateDB.cancel()

    @tasks.loop(minutes=30.0, reconnect=True)
    async def updateDB(self):
        """Every 30 minutes, grab the 5 closest upcoming CTFs from ctftime.org."""
        now = datetime.utcnow()
        unix_now = int(now.replace(tzinfo=timezone.utc).timestamp())
        try:
            upcoming = "https://ctftime.org/api/v1/events/"
            limit = "5"
            response = requests.get(upcoming, headers=self.HEADERS, params=limit)
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

    def _make_live_embed(self, ctf: dict) -> discord.Embed:
        """Create an embed for a currently running CTF."""
        embed = discord.Embed(
            title=":red_circle: " + ctf["name"] + " IS LIVE",
            description=ctf["url"],
            color=15874645,
        )
        start = datetime.fromtimestamp(ctf["start"], tz=self.TZ).strftime("%Y-%m-%d %H:%M:%S") + " +2"
        end = datetime.fromtimestamp(ctf["end"], tz=self.TZ).strftime("%Y-%m-%d %H:%M:%S") + " +2"
        embed.set_thumbnail(url=ctf["img"] or self.DEFAULT_IMAGE)
        embed.add_field(name="Duration", value=ctf["dur"], inline=True)
        embed.add_field(name="Format", value=ctf["format"], inline=True)
        embed.add_field(name="Timeframe", value=f"{start} -> {end}", inline=True)
        return embed

    def _make_upcoming_embed(self, ctf: dict) -> discord.Embed:
        """Create an embed for an upcoming CTF."""
        embed = discord.Embed(title=ctf["name"], description=ctf["url"], color=int("f23a55", 16))
        embed.set_thumbnail(url=ctf["img"] or self.DEFAULT_IMAGE)
        embed.add_field(name="Duration", value=ctf["dur"], inline=True)
        embed.add_field(name="Format", value=ctf["format"], inline=True)
        start = datetime.fromtimestamp(ctf["start"], tz=self.TZ).strftime("%Y-%m-%d %H:%M:%S") + " +2"
        end = datetime.fromtimestamp(ctf["end"], tz=self.TZ).strftime("%Y-%m-%d %H:%M:%S") + " +2"
        embed.add_field(name="Timeframe", value=f"{start} -> {end}", inline=True)
        return embed

    # ── Global commands ──────────────────────────────────────

    @ctftime.command(aliases=["now", "running"])
    async def current(self, ctx: commands.Context):
        """Show currently running CTFs."""
        now = datetime.utcnow()
        unix_now = int(now.replace(tzinfo=timezone.utc).timestamp())
        running = False

        for ctf in ctfs.find():
            if ctf["start"] < unix_now and ctf["end"] > unix_now:
                running = True
                await ctx.channel.send(embed=self._make_live_embed(ctf))

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
        upcoming_ep = "https://ctftime.org/api/v1/events/"
        try:
            r = requests.get(upcoming_ep, headers=self.HEADERS, params=amount)
            upcoming_data = r.json()
        except Exception as e:
            await ctx.send(f"Error retrieving data: {e}")
            return

        for ctf_idx in range(0, int(amount)):
            try:
                d = upcoming_data[ctf_idx]
                dur = d.get("duration", {})
                place = "Online" if not d.get("onsite") else "Onsite"
                ev = {
                    "name": d["title"],
                    "start": int(parse(d["start"].replace("T", " ").split("+", 1)[0]).replace(tzinfo=timezone.utc).timestamp()),
                    "end": int(parse(d["finish"].replace("T", " ").split("+", 1)[0]).replace(tzinfo=timezone.utc).timestamp()),
                    "dur": f"{dur.get('days', 0)} days, {dur.get('hours', 0)} hours",
                    "url": d["url"],
                    "img": d.get("logo", ""),
                    "format": f"{place} {d.get('format', '')}",
                }
                await ctx.channel.send(embed=self._make_upcoming_embed(ev))
            except IndexError:
                break

    @ctftime.command(aliases=["leaderboard"])
    async def top(self, ctx: commands.Context, year: str = None):
        """Show ctftime.org leaderboards for a year (defaults to current year)."""
        if not year:
            year = str(datetime.today().year)
        top_ep = f"https://ctftime.org/api/v1/top/{year}/"
        leaderboards = ""
        r = requests.get(top_ep, headers=self.HEADERS)
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
                tl = self._format_timeleft(ctf["end"] - unix_now)
                await ctx.send(f"```ini\n{ctf['name']} ends in: {tl}```\n{ctf['url']}")

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
                tl = self._format_timeleft(self.upcoming_l[x]["start"] - unix_now)
                await ctx.send(
                    f"```ini\n{self.upcoming_l[x]['name']} starts in: {tl}```\n{self.upcoming_l[x]['url']}"
                )
            except (IndexError, ValueError):
                await ctx.send("Invalid selection. Use `!ctftime countdown` to see the list first.")

    # ── Team commands ────────────────────────────────────────

    @ctftime.command()
    @commands.has_permissions(manage_channels=True)
    async def setteam(self, ctx: commands.Context, team_input: str):
        """Set your CTFtime team (use team ID or full URL)."""
        team_id = team_input.strip().rstrip("/")
        if "ctftime.org/team/" in team_id:
            team_id = team_id.split("ctftime.org/team/")[1].split("/")[0].split("?")[0]
        if not team_id.isdigit():
            await ctx.send("Invalid team ID. Use a numeric ID or a URL like `https://ctftime.org/team/12345`")
            return

        try:
            r = requests.get(f"https://ctftime.org/api/v1/teams/{team_id}/", headers=self.HEADERS)
            if r.status_code != 200:
                await ctx.send("Team not found on CTFtime.")
                return
            team_data = r.json()
        except Exception as e:
            await ctx.send(f"Error fetching team info: {e}")
            return

        sconf = serverdb[str(ctx.guild.id) + "-CONF"]
        sconf.update(
            {"name": "ctftime_team"},
            {"$set": {"team_id": int(team_id), "team_name": team_data.get("name", "Unknown")}},
            upsert=True,
        )
        await ctx.send(f"✅ CTFtime team set to **{team_data.get('name', 'Unknown')}** (ID: {team_id})")

    @ctftime.command()
    async def team(self, ctx: commands.Context):
        """Show your CTFtime team info."""
        team_doc = self._get_team_config(ctx.guild.id)
        if not team_doc:
            await ctx.send("No team set! Use `!ctftime setteam <team_id or url>` first.")
            return

        team_id = team_doc["team_id"]
        try:
            r = requests.get(f"https://ctftime.org/api/v1/teams/{team_id}/", headers=self.HEADERS)
            if r.status_code != 200:
                await ctx.send("Error fetching team data from CTFtime.")
                return
            data = r.json()
        except Exception as e:
            await ctx.send(f"Error: {e}")
            return

        embed = discord.Embed(
            title=data.get("name", "Unknown"),
            description=f"https://ctftime.org/team/{team_id}",
            color=int("36a2eb", 16),
        )
        if data.get("logo"):
            embed.set_thumbnail(url=data["logo"])
        if data.get("country"):
            embed.add_field(name="Country", value=data["country"], inline=True)
        if data.get("rating"):
            years = sorted(data["rating"].keys(), reverse=True)
            if years:
                latest = data["rating"][years[0]]
                embed.add_field(
                    name=f"{years[0]} Rating",
                    value=f"#{latest.get('rating_place', '?')} ({round(latest.get('rating_points', 0), 2)} pts)",
                    inline=True,
                )
        if data.get("aliases"):
            embed.add_field(name="Aliases", value=", ".join(data["aliases"][:5]), inline=False)
        await ctx.send(embed=embed)

    @ctftime.command(aliases=["mynow", "myrunning"])
    async def mycurrent(self, ctx: commands.Context):
        """Show currently running CTFs your team is in (with time left)."""
        team_doc = self._get_team_config(ctx.guild.id)
        if not team_doc:
            await ctx.send("No team set! Use `!ctftime setteam <team_id or url>` first.")
            return

        async with ctx.typing():
            events, team_name = self._get_team_events_full(ctx.guild.id)

        unix_now = int(datetime.now(tz=self.TZ).timestamp())
        running = [e for e in events if e["start"] < unix_now and e["end"] > unix_now]

        if not running:
            await ctx.send(
                f"No CTFs currently running for **{team_name}**! "
                f"Use `!ctftime myupcoming` to see what's next."
            )
            return

        for ev in running:
            tl = self._format_timeleft(ev["end"] - unix_now)
            embed = self._make_live_embed(ev)
            embed.add_field(name="Time left", value=tl, inline=False)
            await ctx.channel.send(embed=embed)

    @ctftime.command(aliases=["mynext", "myctf", "myctfs", "registered"])
    async def myupcoming(self, ctx: commands.Context, params: str = None):
        """Show upcoming CTFs your team is registered for, with countdowns.

        Usage:
          !ctftime myupcoming        — list upcoming CTFs
          !ctftime myupcoming <num>   — show countdown for that CTF
          !ctftime myupcoming all     — show all upcoming CTFs
        """
        team_doc = self._get_team_config(ctx.guild.id)
        if not team_doc:
            await ctx.send("No team set! Use `!ctftime setteam <team_id or url>` first.")
            return

        unix_now = int(datetime.utcnow().replace(tzinfo=timezone.utc).timestamp())

        # If a number was given, show countdown for that entry
        if params is not None and params.isdigit():
            if not self.my_upcoming_l:
                await ctx.send("Run `!ctftime myupcoming` first to load the list.")
                return
            try:
                x = int(params) - 1
                ev = self.my_upcoming_l[x]
                tl = self._format_timeleft(ev["start"] - unix_now)
                await ctx.send(
                    f"```ini\n{ev['name']} starts in: {tl}```\n{ev['url']}"
                )
            except (IndexError, ValueError):
                await ctx.send("Invalid selection. Use `!ctftime myupcoming` to see the list.")
            return

        # Fetch & filter
        async with ctx.typing():
            events, team_name = self._get_team_events(ctx.guild.id)

        future = [e for e in events if e["start"] > unix_now]
        future.sort(key=lambda e: e["start"])
        self.my_upcoming_l = future  # store for countdown selection

        if not future:
            await ctx.send(
                f"No upcoming CTFs found for **{team_name}**."
                f"\nCheck the team page: https://ctftime.org/team/{team_doc['team_id']}"
            )
            return

        show_all = params and params.lower() == "all"
        to_show = future if show_all else future[:10]

        embed = discord.Embed(
            title=f"\U0001f4c5 Upcoming CTFs for {team_name}",
            description=f"[Team page](https://ctftime.org/team/{team_doc['team_id']})",
            color=int("f23a55", 16),
        )
        for i, ev in enumerate(to_show):
            # Convert event start time to UTC+2 for display
            start_dt = datetime.fromtimestamp(ev["start"], tz=self.TZ)
            date_display = start_dt.strftime("%b %d, %Y, %H:%M") + " (UTC+2)"
            countdown = self._format_timeleft(ev["start"] - unix_now)
            embed.add_field(
                name=f"[{i + 1}] {ev['name']}",
                value=f"[CTFtime]({ev['url']})\n{date_display}\n\u23f1 {countdown}",
                inline=False,
            )
        embed.set_footer(
            text="Use !ctftime myupcoming <number> for exact countdown"
        )
        await ctx.send(embed=embed)

    @ctftime.command(aliases=["mypast", "myhistory"])
    async def myarchive(self, ctx: commands.Context):
        """Show past CTFs your team participated in."""
        team_doc = self._get_team_config(ctx.guild.id)
        if not team_doc:
            await ctx.send("No team set! Use `!ctftime setteam <team_id or url>` first.")
            return

        team_id = team_doc["team_id"]
        team_name = team_doc.get("team_name", "Your team")

        async with ctx.typing():
            events = self._scrape_team_past_events(team_id)

        if not events:
            await ctx.send(
                f"No past CTFs found for **{team_name}**."
                f"\nCheck the team page: https://ctftime.org/team/{team_id}"
            )
            return

        # Split into pages of 10
        pages = [events[i:i + 10] for i in range(0, len(events), 10)]

        for page_num, page in enumerate(pages[:3]):  # max 3 pages (30 events)
            embed = discord.Embed(
                title=f"\U0001f3c6 Past CTFs for {team_name}" + (f" (page {page_num + 1})" if len(pages) > 1 else ""),
                description=f"[Team page](https://ctftime.org/team/{team_id})",
                color=int("36a2eb", 16),
            )
            for ev in page:
                place = ev.get("place", "?")
                rating = ev.get("rating_points", "0")
                embed.add_field(
                    name=f"#{place} — {ev['name']}",
                    value=f"[CTFtime]({ev['url']}) | Rating: **{rating}** pts",
                    inline=False,
                )
            embed.set_footer(text="Data from ctftime.org")
            await ctx.send(embed=embed)


    @ctftime.command(aliases=["mybest", "myscores"])
    async def mytop(self, ctx: commands.Context, year: str = None):
        """Show your team's top 10 events by rating points for the current year."""
        team_doc = self._get_team_config(ctx.guild.id)
        if not team_doc:
            await ctx.send("No team set! Use `!ctftime setteam <team_id or url>` first.")
            return

        if year is None:
            year = str(datetime.today().year)

        team_id = team_doc["team_id"]
        team_name = team_doc.get("team_name", "Your team")

        async with ctx.typing():
            events = self._scrape_team_past_events(team_id, year=int(year))

        if not events:
            await ctx.send(
                f"No past CTFs found for **{team_name}** in {year}. "
                f"Check the team page: https://ctftime.org/team/{team_id}"
            )
            return

        # Parse rating points and sort descending
        def parse_pts(val: str) -> float:
            try:
                return float(val.replace(",", "."))
            except (ValueError, AttributeError):
                return 0.0

        events.sort(key=lambda e: parse_pts(e["rating_points"]), reverse=True)
        top10 = events[:10]
        total = sum(parse_pts(e["rating_points"]) for e in top10)

        # Fetch weights for top10 events in parallel
        weights: list[float] = [0.0] * len(top10)
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(self._fetch_event_weight, ev["event_id"]): i for i, ev in enumerate(top10)}
            for fut in as_completed(futures):
                weights[futures[fut]] = fut.result()

        embed = discord.Embed(
            title=f"\U0001f3c6 {team_name} — Top {len(top10)} Events ({year})",
            description=f"[Team page](https://ctftime.org/team/{team_id})",
            color=int("f5a623", 16),
        )
        for i, ev in enumerate(top10):
            pts = parse_pts(ev["rating_points"])
            place = ev.get("place", "?")
            w = weights[i]
            embed.add_field(
                name=f"[{i + 1}] {ev['name']}",
                value=f"[CTFtime]({ev['url']}) | Place: **#{place}** | Weight: **{w:.2f}** | Rating pts: **{pts:.4f}**",
                inline=False,
            )
        embed.set_footer(text=f"Total rating points (top {len(top10)}): {total:.4f}")
        await ctx.send(embed=embed)


    @commands.command()
    async def calculate(
        self,
        ctx: commands.Context,
        team_place: int,
        team_points: float,
        best_points: float,
        total_teams: int,
        weight: float,
    ):
        """Calculate CTFtime rating points using the 2017+ formula.

        Usage: !calculate <team_place> <team_points> <best_points> <total_teams> <weight>

        team_place   — your place in the CTF (1 = first)
        team_points  — points your team scored
        best_points  — points scored by the 1st place team
        total_teams  — total number of teams that scored
        weight       — CTF weight from ctftime.org
        """
        if best_points <= 0:
            await ctx.send("best_points must be greater than 0.")
            return
        if team_place <= 0 or total_teams <= 0:
            await ctx.send("team_place and total_teams must be greater than 0.")
            return

        points_coef = team_points / best_points
        place_coef = 1.0 / team_place

        embed = discord.Embed(
            title="\U0001f9ee CTFtime Rating Calculator (2017+ formula)",
            color=int("f5a623", 16),
        )
        embed.add_field(name="points_coef", value=f"`{team_points} / {best_points}` = **{points_coef:.4f}**", inline=True)
        embed.add_field(name="place_coef", value=f"`1 / {team_place}` = **{place_coef:.4f}**", inline=True)
        embed.add_field(name="weight", value=f"**{weight}**", inline=True)

        if points_coef <= 0:
            embed.add_field(name="Estimated Rating", value="**0** (points_coef ≤ 0)", inline=False)
        else:
            # E_rating = (points_coef + place_coef) * weight / (1 / (1 + team_place / total_teams))
            normalizer = 1.0 / (1.0 + team_place / total_teams)
            e_rating = (points_coef + place_coef) * weight / normalizer
            embed.add_field(
                name="normalizer",
                value=f"`1 / (1 + {team_place}/{total_teams})` = **{normalizer:.4f}**",
                inline=True,
            )
            embed.add_field(name="Estimated Rating", value=f"**{e_rating:.4f}**", inline=False)

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CtfTime(bot))
