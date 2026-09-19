import logging
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.verification import find_role_by_key
from cogs.security import is_staff, send_mod_log

logger = logging.getLogger("epileptic.setup")


class SetupServerCog(commands.Cog, name="Server Setup"):
    """Automated category, channel, and permission isolation module."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_staff_roles(self, guild: discord.Guild) -> list[discord.Role]:
        """Returns all staff roles (Owner, Administrator, Moderator)."""
        roles = []
        for role in guild.roles:
            r_name = role.name.lower()
            if (
                r_name in config.STAFF_ROLE_NAMES
                or any(alias in r_name for alias in config.ROLE_ALIASES.get("staff", []))
                or role.permissions.administrator
            ):
                if role not in roles:
                    roles.append(role)
        return roles

    @app_commands.command(
        name="setup_permissions",
        description="Apply permission isolation to existing categories (INFORMATION, COMMUNITY, PREMIUM, STAFF, etc.)."
    )
    @is_staff()
    async def setup_permissions(self, interaction: discord.Interaction):
        """Synchronizes permissions across all categories based on community access levels."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        not_verified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
        member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
        premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)
        ai_contrib_role = discord.utils.find(lambda r: r.name.lower() == config.AI_CONTRIBUTOR_ROLE_NAME.lower(), guild.roles)
        staff_roles = self._get_staff_roles(guild)

        if not member_role:
            await interaction.followup.send(
                f"❌ The member role (`{config.MEMBER_ROLE_NAME}`) was not found on the server.\n"
                f"Please ensure the role name matches your .env configuration.",
                ephemeral=True
            )
            return

        updated_categories = []
        general_members = [r for r in [member_role, premium_role, ai_contrib_role] if r]

        for category in guild.categories:
            cat_name = category.name.strip().upper()

            # 1. INFORMATION category
            if "INFORMATION" in cat_name or "ИНФОРМАЦИЯ" in cat_name or "INFO" in cat_name:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=False
                    )
                }
                if not_verified_role:
                    overwrites[not_verified_role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=False
                    )
                if member_role:
                    overwrites[member_role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=True
                    )
                for s in staff_roles:
                    overwrites[s] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True
                    )

                await category.edit(overwrites=overwrites)
                for ch in category.channels:
                    await ch.edit(sync_permissions=True)
                updated_categories.append(f"📁 **{category.name}** (Public read-only, locked from chatter)")

            # 2. PREMIUM category
            elif "PREMIUM" in cat_name or "ПРЕМИУМ" in cat_name or "VIP" in cat_name:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                }
                if not_verified_role:
                    overwrites[not_verified_role] = discord.PermissionOverwrite(view_channel=False)
                if member_role:
                    overwrites[member_role] = discord.PermissionOverwrite(view_channel=False)
                if ai_contrib_role:
                    overwrites[ai_contrib_role] = discord.PermissionOverwrite(view_channel=False)
                if premium_role:
                    overwrites[premium_role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True
                    )
                for s in staff_roles:
                    overwrites[s] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True
                    )

                await category.edit(overwrites=overwrites)
                for ch in category.channels:
                    await ch.edit(sync_permissions=True)
                role_label = f"@{premium_role.name}" if premium_role else "@Premium Member"
                updated_categories.append(f"💎 **{category.name}** (Locked to {role_label} & Staff)")

            # 3. STAFF category
            elif "STAFF" in cat_name or "СТАФФ" in cat_name or "ADMIN" in cat_name or "МОДЕРАЦИЯ" in cat_name:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                }
                if not_verified_role:
                    overwrites[not_verified_role] = discord.PermissionOverwrite(view_channel=False)
                if member_role:
                    overwrites[member_role] = discord.PermissionOverwrite(view_channel=False)
                if premium_role:
                    overwrites[premium_role] = discord.PermissionOverwrite(view_channel=False)
                if ai_contrib_role:
                    overwrites[ai_contrib_role] = discord.PermissionOverwrite(view_channel=False)

                for s in staff_roles:
                    overwrites[s] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True,
                        connect=True,
                        speak=True
                    )

                await category.edit(overwrites=overwrites)
                for ch in category.channels:
                    await ch.edit(sync_permissions=True)
                updated_categories.append(f"🛡️ **{category.name}** (Private to Staff only)")

            # 4. Community categories: COMMUNITY, RESOURCES, LOUNGE, SUPPORT
            elif any(kw in cat_name for kw in ["COMMUNITY", "КОМЬЮНИТИ", "RESOURCES", "РЕСУРСЫ", "LOUNGE", "ЛАУНЖ", "SUPPORT", "САППОРТ"]):
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                }
                if not_verified_role:
                    overwrites[not_verified_role] = discord.PermissionOverwrite(view_channel=False)

                for r in general_members:
                    overwrites[r] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True,
                        connect=True,
                        speak=True
                    )

                for s in staff_roles:
                    overwrites[s] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True,
                        connect=True,
                        speak=True
                    )

                await category.edit(overwrites=overwrites)
                for ch in category.channels:
                    await ch.edit(sync_permissions=True)
                updated_categories.append(f"💬 **{category.name}** (Unlocked for @{member_role.name} & above)")

        embed = discord.Embed(
            title="🔒 Permissions Configured Successfully",
            description="Category permissions have been synchronized according to your community layout.",
            color=config.EMBED_COLOR_SUCCESS
        )
        if updated_categories:
            embed.add_field(name="Synchronized Categories", value="\n".join(updated_categories), inline=False)
        else:
            embed.description = "No matching categories found (INFORMATION, COMMUNITY, RESOURCES, PREMIUM, LOUNGE, SUPPORT, STAFF)."

        embed.set_footer(text="Epileptic Server Guard")
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Audit log to mod-logs
        audit_embed = discord.Embed(
            title="⚙️ [AUDIT] Channel Permissions Synchronized",
            description=f"Executed by {interaction.user.mention} (`{interaction.user.id}`).",
            color=config.EMBED_COLOR_DEFAULT
        )
        await send_mod_log(guild, audit_embed)

    @app_commands.command(
        name="assign_unverified_all",
        description="Assign the Not Verified role to all members who currently lack the Member role."
    )
    @is_staff()
    async def assign_unverified_all(self, interaction: discord.Interaction):
        """Assigns Not Verified role to existing unverified members."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        not_verified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
        member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
        staff_roles = self._get_staff_roles(guild)

        if not not_verified_role:
            await interaction.followup.send(
                f"❌ Role `{config.UNVERIFIED_ROLE_NAME}` was not found on the server.",
                ephemeral=True
            )
            return

        if guild.me.top_role.position <= not_verified_role.position:
            await interaction.followup.send(
                f"⚠️ The bot's role (**{guild.me.top_role.name}**) is below **{not_verified_role.name}**!\n"
                "Please raise the bot's role higher in Server Settings.",
                ephemeral=True
            )
            return

        assigned_count = 0
        skipped_count = 0

        for member in guild.members:
            if member.bot:
                continue
            is_staff_mem = any(r in staff_roles for r in member.roles)
            has_member = member_role and (member_role in member.roles)

            if not has_member and not is_staff_mem and not_verified_role not in member.roles:
                try:
                    await member.add_roles(not_verified_role, reason="Bulk synchronization of Not Verified role")
                    assigned_count += 1
                except Exception as e:
                    logger.warning(f"Could not assign role to {member}: {e}")
            else:
                skipped_count += 1

        embed = discord.Embed(
            title="👥 Unverified Role Synchronization Complete",
            color=config.EMBED_COLOR_SUCCESS
        )
        embed.add_field(name="Assigned @Not Verified", value=f"**{assigned_count}** members", inline=True)
        embed.add_field(name="Already Verified / Staff", value=f"**{skipped_count}** members", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupServerCog(bot))
