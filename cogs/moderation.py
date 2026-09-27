import logging
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.verification import find_role_by_key
from cogs.security import is_staff, send_mod_log

logger = logging.getLogger("epileptic.moderation")


def check_is_staff_msg(ctx: commands.Context) -> bool:
    """Helper to verify staff permissions for prefix text commands."""
    if not ctx.guild:
        return False
    if ctx.author.id == ctx.guild.owner_id:
        return True
    if ctx.author.guild_permissions.administrator:
        return True
    user_role_names = [r.name.lower() for r in ctx.author.roles]
    for staff_role in config.STAFF_ROLE_NAMES:
        if staff_role in user_role_names:
            return True
    for alias in config.ROLE_ALIASES.get("staff", []):
        if any(alias in r_name for r_name in user_role_names):
            return True
    return False


def is_spam_message_entry(m: discord.Message, kw_lower: str) -> bool:
    """Determines whether a message is an unwanted bot/webhook spam message."""
    # 1. Content check
    c_lower = m.content.lower()
    if kw_lower in c_lower or any(k in c_lower for k in ["spired", "spammed by", "raided by", "nuked by", "spammer"]):
        return True

    # 2. Author check
    if m.author.name:
        a_lower = m.author.name.lower()
        if kw_lower in a_lower or any(k in a_lower for k in ["spired", "spammed", "spammer"]):
            return True

    # 3. Embed check (Spired bot sends embeds)
    for e in m.embeds:
        parts = [e.title or '', e.description or '', getattr(e.footer, 'text', '') or '']
        parts.extend([f"{f.name} {f.value}" for f in e.fields])
        e_text = " ".join(parts).lower()
        if kw_lower in e_text or any(k in e_text for k in ["spired", "spammed by", "raided by", "nuked by", "spammer"]):
            return True

    # 4. Rogue webhook detection
    if m.webhook_id is not None:
        if any(k in c_lower for k in ["discord.gg", "http", "raid", "spam"]):
            return True

    return False


class ModerationCog(commands.Cog, name="Moderation"):
    """Server moderation and utility inspection commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="purge", description="Bulk delete messages in the current channel.")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    @is_staff()
    async def purge(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 100:
            await interaction.response.send_message("Please specify a number between 1 and 100.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)

        await interaction.followup.send(f"🧹 Cleaned up **{len(deleted)}** messages.", ephemeral=True)

        audit_embed = discord.Embed(
            title="🧹 [AUDIT] Messages Purged",
            description=(
                f"**Moderator:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**Channel:** {interaction.channel.mention}\n"
                f"**Amount Deleted:** {len(deleted)}"
            ),
            color=config.EMBED_COLOR_WARNING
        )
        await send_mod_log(interaction.guild, audit_embed)

    @app_commands.command(
        name="clean_spam",
        description="Scan and purge bot/webhook spam messages (removes collapsed 'blocked messages' too)."
    )
    @app_commands.describe(
        keyword="Keyword or pattern to search and delete (default: 'spired')",
        limit="Number of recent messages to scan (default: 500, max 1000)",
        all_channels="Scan and purge spam across all text channels on the server (default: False)"
    )
    @is_staff()
    async def clean_spam(
        self,
        interaction: discord.Interaction,
        keyword: str = "spired",
        limit: int = 500,
        all_channels: bool = False
    ):
        """Scans recent messages and deletes messages matching spam keywords or containing spam embeds."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        kw_lower = keyword.strip().lower()

        target_channels = guild.text_channels if all_channels else [interaction.channel]
        total_deleted = 0
        scan_limit = min(max(limit, 10), 1000)

        for ch in target_channels:
            if ch.permissions_for(guild.me).manage_messages:
                try:
                    deleted = await ch.purge(
                        limit=scan_limit,
                        check=lambda m: is_spam_message_entry(m, kw_lower),
                        bulk=True
                    )
                    total_deleted += len(deleted)
                except Exception as e:
                    logger.warning(f"Error purging in #{ch.name}: {e}")

        location_str = "across all channels" if all_channels else f"in {interaction.channel.mention}"
        await interaction.followup.send(
            f"🧹 Successfully cleaned up **{total_deleted}** spam message(s) {location_str}.\n"
            f"*(Collapsed 'blocked messages' bars should now disappear completely!)*",
            ephemeral=True
        )

        if total_deleted > 0:
            audit_embed = discord.Embed(
                title="🧹 [SECURITY] Spam Purged by Staff",
                description=(
                    f"**Moderator:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                    f"**Target:** {location_str}\n"
                    f"**Messages Deleted:** {total_deleted}"
                ),
                color=config.EMBED_COLOR_SUCCESS
            )
            await send_mod_log(interaction.guild, audit_embed)

    @commands.command(name="cleanspam", aliases=["clean_spam", "purgespam", "purge_spam", "cleanallspam"])
    async def cleanspam_cmd(self, ctx: commands.Context, *args):
        """
        Fast prefix command fallback to wipe spam and delete collapsed 'blocked messages' bars.
        Usage:
          !cleanspam                -> purges spam in current channel (500 msgs)
          !cleanspam all            -> purges spam across ALL text channels
          !cleanallspam             -> purges spam across ALL text channels
          !cleanspam 1000           -> purges up to 1000 msgs in current channel
          !cleanspam all 1000       -> purges up to 1000 msgs across all channels
        """
        if not check_is_staff_msg(ctx):
            await ctx.send("⛔ **Access Denied:** You do not have staff permissions to execute this command.", delete_after=6)
            return

        guild = ctx.guild
        if not guild:
            return

        kw = "spired"
        scan_limit = 500
        all_channels = (ctx.invoked_with == "cleanallspam")

        for arg in args:
            arg_str = str(arg).strip().lower()
            if arg_str in ("all", "--all", "-a", "guild"):
                all_channels = True
            elif arg_str.isdigit():
                scan_limit = min(max(int(arg_str), 10), 1000)
            elif len(arg_str) >= 2:
                kw = arg_str

        kw_lower = kw.strip().lower()
        target_channels = guild.text_channels if all_channels else [ctx.channel]
        location_desc = "ALL channels" if all_channels else f"#{ctx.channel.name}"

        status_msg = await ctx.send(
            f"🧹 **Purging spam...** Target: `{location_desc}` | Keyword: `{kw}` | Limit: `{scan_limit}`"
        )

        total_deleted = 0
        for ch in target_channels:
            if ch.permissions_for(guild.me).manage_messages:
                try:
                    deleted = await ch.purge(
                        limit=scan_limit,
                        check=lambda m: is_spam_message_entry(m, kw_lower),
                        bulk=True
                    )
                    total_deleted += len(deleted)
                except Exception as e:
                    logger.warning(f"Error executing !cleanspam in #{ch.name}: {e}")

        location_str = "across all channels" if all_channels else f"in {ctx.channel.mention}"
        await status_msg.edit(
            content=(
                f"✅ **Spam Cleanup Finished!**\n"
                f"• Cleaned **{total_deleted}** spam message(s) {location_str}.\n"
                f"*(The collapsed 'blocked messages' bars will now be completely gone)*"
            )
        )

        if total_deleted > 0:
            audit_embed = discord.Embed(
                title="🧹 [SECURITY] Spam Purged via !cleanspam",
                description=(
                    f"**Moderator:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                    f"**Target:** {location_str}\n"
                    f"**Keyword:** `{kw}`\n"
                    f"**Messages Deleted:** {total_deleted}"
                ),
                color=config.EMBED_COLOR_SUCCESS
            )
            await send_mod_log(guild, audit_embed)

    @app_commands.command(name="serverinfo", description="Display community member counts and role statistics.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        total_members = guild.member_count
        unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
        member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
        premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)

        unverified_count = len(unverified_role.members) if unverified_role else 0
        member_count = len(member_role.members) if member_role else 0
        premium_count = len(premium_role.members) if premium_role else 0

        embed = discord.Embed(
            title=f"📊 Server Statistics: {guild.name}",
            color=config.EMBED_COLOR_DEFAULT
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="Total Members", value=str(total_members), inline=True)
        embed.add_field(name="Channels / Categories", value=f"{len(guild.channels)} / {len(guild.categories)}", inline=True)

        embed.add_field(
            name="Role Breakdown",
            value=(
                f"• `{config.UNVERIFIED_ROLE_NAME}`: **{unverified_count}**\n"
                f"• `{config.MEMBER_ROLE_NAME}`: **{member_count}**\n"
                f"• `{config.PREMIUM_ROLE_NAME}`: **{premium_count}**"
            ),
            inline=False
        )

        embed.set_footer(text=f"Server ID: {guild.id}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
