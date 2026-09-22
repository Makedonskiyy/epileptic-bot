import logging
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.verification import find_role_by_key
from cogs.security import is_staff, is_owner, send_mod_log

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
        description="Apply permission isolation to existing categories (Owner only)."
    )
    @is_owner()
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
                        send_messages_in_threads=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=False
                    )
                }
                if not_verified_role:
                    overwrites[not_verified_role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        send_messages_in_threads=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=False
                    )

                for r in general_members:
                    overwrites[r] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        send_messages_in_threads=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        read_messages=True,
                        read_message_history=True,
                        add_reactions=False
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
                updated_categories.append(f"📁 **{category.name}** (Strict read-only for members, no writing)")

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

            # 4. SUPPORT category (FAQ and Ticket panel read-only for members, staff can post)
            elif "SUPPORT" in cat_name or "САППОРТ" in cat_name:
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
                        attach_files=True
                    )

                for s in staff_roles:
                    overwrites[s] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True
                    )

                await category.edit(overwrites=overwrites)
                # Specific channel locks inside SUPPORT
                for ch in category.channels:
                    ch_name_lower = ch.name.lower()
                    if "faq" in ch_name_lower or "ticket" in ch_name_lower:
                        # Members can view & read history, but cannot send messages
                        ch_overwrites = dict(ch.overwrites)
                        for r in general_members:
                            ch_overwrites[r] = discord.PermissionOverwrite(
                                view_channel=True,
                                send_messages=False,
                                read_messages=True,
                                read_message_history=True
                            )
                        await ch.edit(overwrites=ch_overwrites)
                    else:
                        await ch.edit(sync_permissions=True)

                updated_categories.append(f"🎫 **{category.name}** (FAQ/Tickets read-only for members, staff managed)")

            # 5. Community categories: COMMUNITY, RESOURCES, LOUNGE
            elif any(kw in cat_name for kw in ["COMMUNITY", "КОМЬЮНИТИ", "RESOURCES", "РЕСУРСЫ", "LOUNGE", "ЛАУНЖ"]):
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
        description="Assign the Not Verified role to all members who currently lack the Member role (Owner only)."
    )
    @is_owner()
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

    @app_commands.command(
        name="setup_community_channels",
        description="Configures official Rules [✓📖] and Announcement [📢] channels (requires Community feature)."
    )
    @app_commands.describe(
        rules_channel="Channel to designate as official Rules channel (defaults to #rules)",
        announcements_channel="Channel to convert to Announcement/News channel with Follow button (defaults to #announcements)",
        match_screenshot_style="Rename channels with ▸ styling matching screenshot (e.g. 📜▸rules, 📢▸announcements)"
    )
    @is_owner()
    async def setup_community_channels(
        self,
        interaction: discord.Interaction,
        rules_channel: discord.TextChannel = None,
        announcements_channel: discord.TextChannel = None,
        match_screenshot_style: bool = True
    ):
        """Sets up the official Rules channel (with the book-checkmark badge) and News channel (with Follow button)."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Check if Discord Community is enabled on this server
        has_community = "COMMUNITY" in guild.features

        if not has_community:
            guide_embed = discord.Embed(
                title="⚠️ Discord Community Not Enabled Yet",
                description=(
                    "The **[✓📖] Rules badge** and **[📢] Announcement channel (with 'Follow' button)** "
                    "are exclusive features of **Discord Community** servers.\n\n"
                    "**How to enable it in 30 seconds:**\n"
                    "1. In Discord, open **Server Settings** (Настройки сервера).\n"
                    "2. Scroll down in the left menu and click **Enable Community** (Включить сообщество).\n"
                    "3. Click **Get Started** (Начать), leave default security checks, and click **Next**.\n"
                    "4. In *Rules or guidelines channel*, select your rules channel.\n"
                    "5. In *Community updates channel*, select your announcements channel.\n"
                    "6. Click **Finish Setup**.\n\n"
                    "💡 *After enabling Community, run this command (`/setup_community_channels`) again, and the bot will finish configuring everything!*"
                ),
                color=config.EMBED_COLOR_WARNING
            )
            await interaction.followup.send(embed=guide_embed, ephemeral=True)
            return

        # 1. Resolve Rules Channel
        r_ch = rules_channel or discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["rules", "правил"]),
            guild.text_channels
        )

        # 2. Resolve Announcements Channel
        a_ch = announcements_channel or discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["announcement", "объявлен"]),
            guild.text_channels
        )

        actions_taken = []

        # Configure Rules Channel
        if r_ch:
            try:
                new_name = "📜▸rules" if match_screenshot_style else r_ch.name
                await guild.edit(rules_channel=r_ch)
                if match_screenshot_style and r_ch.name != new_name:
                    await r_ch.edit(name=new_name)
                actions_taken.append(f"✅ **Rules Channel:** Set {r_ch.mention} as official Rules channel (granted **[✓📖]** badge)!")
            except Exception as e:
                actions_taken.append(f"❌ Failed to set rules channel: `{e}`")
        else:
            actions_taken.append("⚠️ Rules channel not found (specify manually in command argument).")

        # Configure Announcement Channel
        if a_ch:
            try:
                new_name = "📢▸announcements" if match_screenshot_style else a_ch.name
                # Convert to news channel type
                if a_ch.type != discord.ChannelType.news:
                    await a_ch.edit(type=discord.ChannelType.news)
                if match_screenshot_style and a_ch.name != new_name:
                    await a_ch.edit(name=new_name)
                actions_taken.append(f"✅ **Announcement Channel:** Converted {a_ch.mention} to **News/Announcement channel** (granted **[📢]** icon and **'Follow'** button)!")
            except Exception as e:
                actions_taken.append(f"❌ Failed to convert announcement channel: `{e}`")
        else:
            actions_taken.append("⚠️ Announcements channel not found (specify manually in command argument).")

        embed = discord.Embed(
            title="✨ Community Channels Configured",
            description="\n\n".join(actions_taken),
            color=config.EMBED_COLOR_SUCCESS
        )
        embed.set_footer(text="Epileptic Server Guard")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="convert_to_announcement",
        description="Convert any text channel into an Announcement channel with a Follow button (requires Community)."
    )
    @app_commands.describe(
        channel="Target text channel to convert into Announcement/News channel"
    )
    @is_owner()
    async def convert_to_announcement(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Converts a standard text channel into a News channel."""
        if "COMMUNITY" not in interaction.guild.features:
            await interaction.response.send_message(
                "❌ This server does not have **Discord Community** enabled yet. Enable it in Server Settings first.",
                ephemeral=True
            )
            return

        try:
            await channel.edit(type=discord.ChannelType.news)
            await interaction.response.send_message(
                f"✅ Channel {channel.mention} is now an **Announcement Channel**! Users can now follow it to receive updates.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to convert channel: `{e}`",
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Automatically crossposts/publishes staff announcements sent in News channels."""
        if not message.guild or message.author.bot:
            return

        if message.channel.type == discord.ChannelType.news:
            try:
                await message.publish()
                logger.info(f"Auto-published announcement message {message.id} in #{message.channel.name}.")
            except discord.Forbidden:
                logger.debug(f"Missing permissions to publish message in #{message.channel.name}.")
            except Exception as e:
                logger.warning(f"Could not auto-publish announcement: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupServerCog(bot))
