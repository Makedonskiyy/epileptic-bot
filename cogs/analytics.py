import os
import sqlite3
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config
from cogs.security import is_staff, send_mod_log

logger = logging.getLogger("epileptic.analytics")

DB_DIR = Path("data")
DB_PATH = DB_DIR / "analytics.db"


class AnalyticsDatabase:
    """Persistent SQLite database for member join/leave metrics and reporting state."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS member_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_lookup 
                ON member_events(guild_id, event_type, timestamp)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS report_history (
                    guild_id INTEGER NOT NULL,
                    report_type TEXT NOT NULL,
                    report_key TEXT NOT NULL,
                    sent_at REAL NOT NULL,
                    PRIMARY KEY(guild_id, report_type, report_key)
                )
            """)
            conn.commit()

    def record_event(self, guild_id: int, event_type: str, user_id: int):
        """Records a join or leave event."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO member_events (guild_id, event_type, user_id, timestamp) VALUES (?, ?, ?, ?)",
                (guild_id, event_type, user_id, now)
            )
            conn.commit()

    def get_counts(self, guild_id: int, start_time: float, end_time: float) -> tuple[int, int, int]:
        """Returns (joins, leaves, net) between start_time and end_time."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM member_events WHERE guild_id = ? AND event_type = 'join' AND timestamp >= ? AND timestamp < ?",
                (guild_id, start_time, end_time)
            )
            joins = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM member_events WHERE guild_id = ? AND event_type = 'leave' AND timestamp >= ? AND timestamp < ?",
                (guild_id, start_time, end_time)
            )
            leaves = cursor.fetchone()[0]

            return joins, leaves, joins - leaves

    def is_report_sent(self, guild_id: int, report_type: str, report_key: str) -> bool:
        """Checks if a scheduled report was already sent for this period key."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM report_history WHERE guild_id = ? AND report_type = ? AND report_key = ?",
                (guild_id, report_type, report_key)
            )
            return cursor.fetchone() is not None

    def mark_report_sent(self, guild_id: int, report_type: str, report_key: str):
        """Marks a scheduled report as sent."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO report_history (guild_id, report_type, report_key, sent_at) VALUES (?, ?, ?, ?)",
                (guild_id, report_type, report_key, time.time())
            )
            conn.commit()


analytics_db = AnalyticsDatabase()


def build_report_embed(guild: discord.Guild, period: str, joins: int, leaves: int, net: int, date_label: str) -> discord.Embed:
    """Builds a sleek Discord Embed for periodic growth reports."""
    total_members = guild.member_count or len(guild.members)

    period_titles = {
        "daily": "📊 [DAILY REPORT] Server Growth & Activity",
        "weekly": "📈 [WEEKLY REPORT] Weekly Server Summary",
        "monthly": "🗓️ [MONTHLY REPORT] Monthly Server Growth"
    }
    title = period_titles.get(period, "📊 [REPORT] Server Growth Statistics")

    # Format net growth badge
    if net > 0:
        net_str = f"+{net} 🟢 (Growing)"
        color = config.EMBED_COLOR_SUCCESS
    elif net < 0:
        net_str = f"{net} 🔴 (Declining)"
        color = config.EMBED_COLOR_WARNING
    else:
        net_str = "0 ⚪ (Stable)"
        color = config.EMBED_COLOR_DEFAULT

    description = (
        f"**Period:** `{date_label}`\n\n"
        f"👥 **Total Server Members:** `{total_members}`\n"
        f"📥 **Joined:** `+{joins}`\n"
        f"📤 **Left:** `-{leaves}`\n"
        f"📊 **Net Growth:** **{net_str}**"
    )

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(
        text=f"Epileptic Community Analytics • {period.capitalize()} Report",
        icon_url=guild.me.display_avatar.url if guild.me else None
    )
    embed.timestamp = datetime.now(timezone.utc)
    return embed


class AnalyticsCog(commands.Cog, name="Analytics"):
    """Tracks member joins & leaves, and delivers periodic daily, weekly, and monthly growth summaries."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.report_scheduler.start()

    def cog_unload(self):
        self.report_scheduler.cancel()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Records join event in analytics database."""
        analytics_db.record_event(member.guild.id, "join", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Records leave event in analytics database without spamming individual leave alerts."""
        analytics_db.record_event(member.guild.id, "leave", member.id)

    @tasks.loop(minutes=15)
    async def report_scheduler(self):
        """Periodically evaluates whether daily, weekly, or monthly reports are due."""
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)

        for guild in self.bot.guilds:
            try:
                # 1. Daily Report: Sent strictly once per calendar day during the midnight window (00:00 - 01:00 UTC)
                if now.hour == 0:
                    today_key = now.strftime("%Y-%m-%d")
                    if not analytics_db.is_report_sent(guild.id, "daily", today_key):
                        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp()
                        prev_start = start_of_day - 86400
                        joins, leaves, net = analytics_db.get_counts(guild.id, prev_start, start_of_day)

                        yesterday_label = (now - timedelta(days=1)).strftime("%B %d, %Y")
                        embed = build_report_embed(guild, "daily", joins, leaves, net, yesterday_label)
                        sent = await send_mod_log(guild, embed)
                        if sent:
                            analytics_db.mark_report_sent(guild.id, "daily", today_key)
                            logger.info(f"Delivered daily analytics report for {guild.name} ({today_key}).")

                # 2. Weekly Report: Sent strictly once per week on Monday midnight (00:00 - 01:00 UTC)
                if now.weekday() == 0 and now.hour == 0:
                    week_key = now.strftime("%Y-W%W")
                    if not analytics_db.is_report_sent(guild.id, "weekly", week_key):
                        start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp()
                        seven_days_ago = start_of_today - (7 * 86400)
                        joins, leaves, net = analytics_db.get_counts(guild.id, seven_days_ago, start_of_today)

                        week_label = f"Week {(now - timedelta(days=7)).strftime('%b %d')} - {now.strftime('%b %d, %Y')}"
                        embed = build_report_embed(guild, "weekly", joins, leaves, net, week_label)
                        sent = await send_mod_log(guild, embed)
                        if sent:
                            analytics_db.mark_report_sent(guild.id, "weekly", week_key)
                            logger.info(f"Delivered weekly analytics report for {guild.name} ({week_key}).")

                # 3. Monthly Report: Sent strictly on the 1st of each month midnight (00:00 - 01:00 UTC)
                if now.day == 1 and now.hour == 0:
                    month_key = now.strftime("%Y-%m")
                    if not analytics_db.is_report_sent(guild.id, "monthly", month_key):
                        start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp()
                        month_ago = start_of_today - (30 * 86400)
                        joins, leaves, net = analytics_db.get_counts(guild.id, month_ago, start_of_today)

                        prev_month_label = (now - timedelta(days=2)).strftime("%B %Y")
                        embed = build_report_embed(guild, "monthly", joins, leaves, net, prev_month_label)
                        sent = await send_mod_log(guild, embed)
                        if sent:
                            analytics_db.mark_report_sent(guild.id, "monthly", month_key)
                            logger.info(f"Delivered monthly analytics report for {guild.name} ({month_key}).")

            except Exception as e:
                logger.exception(f"Error checking analytics reports for {guild.name}: {e}")

    @report_scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="server_stats",
        description="View live server growth statistics (Today, Last 7 Days, Last 30 Days)."
    )
    @is_staff()
    async def server_stats(self, interaction: discord.Interaction):
        """Displays live server growth metrics on demand."""
        guild = interaction.guild
        now_ts = time.time()
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        # Today
        today_joins, today_leaves, today_net = analytics_db.get_counts(guild.id, start_of_day, now_ts)
        # Last 7 Days
        w_joins, w_leaves, w_net = analytics_db.get_counts(guild.id, now_ts - (7 * 86400), now_ts)
        # Last 30 Days
        m_joins, m_leaves, m_net = analytics_db.get_counts(guild.id, now_ts - (30 * 86400), now_ts)

        total_members = guild.member_count or len(guild.members)

        def format_net(val: int) -> str:
            if val > 0:
                return f"+{val} 🟢"
            elif val < 0:
                return f"{val} 🔴"
            return "0 ⚪"

        embed = discord.Embed(
            title="📊 Server Growth & Activity Analytics",
            description=f"Current Population: **{total_members} members**\nLive tracking summary across standard timeframes:",
            color=config.EMBED_COLOR_DEFAULT
        )
        embed.add_field(
            name="📅 Today (Since 00:00 UTC)",
            value=f"• Joins: `+{today_joins}`\n• Leaves: `-{today_leaves}`\n• Net: **{format_net(today_net)}**",
            inline=True
        )
        embed.add_field(
            name="📈 Last 7 Days",
            value=f"• Joins: `+{w_joins}`\n• Leaves: `-{w_leaves}`\n• Net: **{format_net(w_net)}**",
            inline=True
        )
        embed.add_field(
            name="🗓️ Last 30 Days",
            value=f"• Joins: `+{m_joins}`\n• Leaves: `-{m_leaves}`\n• Net: **{format_net(m_net)}**",
            inline=True
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text="Epileptic Community Analytics")
        embed.timestamp = datetime.now(timezone.utc)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="send_growth_report",
        description="Immediately triggers and posts a daily, weekly, or monthly growth report to mod-logs."
    )
    @app_commands.describe(
        period="Choose report period to generate and send to mod-logs"
    )
    @app_commands.choices(period=[
        app_commands.Choice(name="Daily Report", value="daily"),
        app_commands.Choice(name="Weekly Report", value="weekly"),
        app_commands.Choice(name="Monthly Report", value="monthly"),
    ])
    @is_staff()
    async def send_growth_report(self, interaction: discord.Interaction, period: app_commands.Choice[str]):
        """Staff command to immediately preview or dispatch a growth report."""
        guild = interaction.guild
        now_ts = time.time()
        now = datetime.now(timezone.utc)

        if period.value == "daily":
            start_ts = now_ts - 86400
            label = f"Past 24 Hours ({now.strftime('%B %d, %Y')})"
        elif period.value == "weekly":
            start_ts = now_ts - (7 * 86400)
            label = f"Past 7 Days (Ending {now.strftime('%B %d, %Y')})"
        else:
            start_ts = now_ts - (30 * 86400)
            label = f"Past 30 Days ({now.strftime('%B %Y')})"

        joins, leaves, net = analytics_db.get_counts(guild.id, start_ts, now_ts)
        embed = build_report_embed(guild, period.value, joins, leaves, net, label)

        sent = await send_mod_log(guild, embed)
        if sent:
            await interaction.response.send_message(
                f"✅ **{period.name}** has been successfully published to your mod-logs channel!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ Mod-logs channel not found. Here is the report preview:",
                embed=embed,
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AnalyticsCog(bot))
