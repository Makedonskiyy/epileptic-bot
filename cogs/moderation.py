import logging
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.verification import find_role_by_key
from cogs.security import is_staff, send_mod_log

logger = logging.getLogger("epileptic.moderation")


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
