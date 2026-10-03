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

        # Enforce mention_everyone=False on @everyone and member roles
        try:
            if guild.default_role.permissions.mention_everyone:
                d_perms = guild.default_role.permissions
                d_perms.update(mention_everyone=False)
                await guild.default_role.edit(permissions=d_perms, reason="Setup: Disable @everyone for regular users")
        except Exception:
            pass

        for gr in general_members:
            if gr and gr.permissions.mention_everyone:
                try:
                    gr_perms = gr.permissions
                    gr_perms.update(mention_everyone=False)
                    await gr.edit(permissions=gr_perms, reason="Setup: Disable @everyone for regular roles")
                except Exception:
                    pass

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
                        send_messages_in_threads=True,
                        create_public_threads=True,
                        create_private_threads=False,
                        read_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True,
                        connect=True,
                        speak=True,
                        mention_everyone=False,
                        manage_webhooks=False
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

    @commands.Cog.listener()
    async def on_ready(self):
        """Auto-ensures necessary community discussion channels and forum conversions exist."""
        for guild in self.bot.guilds:
            try:
                await ensure_jailbreak_open_channel(guild)
                await auto_convert_tutorials_forum(guild)
            except Exception as e:
                logger.debug(f"Auto-check channels error on {guild.name}: {e}")

    @app_commands.command(
        name="create_jailbreak_chat",
        description="Creates #🔓・jailbreak-open in the COMMUNITY category with full member write and thread access."
    )
    @is_owner()
    async def create_jailbreak_chat(self, interaction: discord.Interaction):
        """Creates or verifies #🔓・jailbreak-open in COMMUNITY category."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        ch = await ensure_jailbreak_open_channel(guild)
        if ch:
            await interaction.followup.send(
                f"✅ Open discussion channel ready: {ch.mention}\n"
                f"• **Category:** `{ch.category.name if ch.category else 'None'}`\n"
                f"• **Permissions:** All verified members (`@Member`) can write, embed links, attach files, and create topics/threads.",
                ephemeral=True
            )
        else:
            await interaction.followup.send("❌ Could not create channel. Check bot permissions.", ephemeral=True)

    @commands.command(name="jailbreak_open", aliases=["createjailbreak", "jailbreakopen"])
    async def jailbreak_open_cmd(self, ctx: commands.Context):
        """Prefix command fallback: !jailbreak_open"""
        user_is_staff = (
            ctx.author.id == ctx.guild.owner_id
            or ctx.author.guild_permissions.administrator
            or any(r.name.lower() in config.STAFF_ROLE_NAMES for r in ctx.author.roles)
        )
        if not user_is_staff:
            await ctx.send("⛔ You do not have permission to execute this command.", delete_after=5)
            return

        ch = await ensure_jailbreak_open_channel(ctx.guild)
        if ch:
            await ctx.send(f"✅ Open community channel ready: {ch.mention} (Category: `{ch.category.name if ch.category else 'None'}`)")
        else:
            await ctx.send("❌ Failed to create channel. Check bot permissions.")

    @app_commands.command(
        name="convert_to_forum",
        description="Converts a channel (like #tutorials) into a native Discord Forum channel for topics."
    )
    @app_commands.describe(
        channel="Text channel to convert (defaults to #tutorials)"
    )
    @is_staff()
    async def convert_to_forum(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None
    ):
        """Converts an existing text channel into a native Discord Forum channel."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        if "COMMUNITY" not in guild.features:
            embed = discord.Embed(
                title="⚠️ Discord Community Not Enabled",
                description=(
                    "Discord Forum channels require the **Community** feature to be enabled on this server.\n\n"
                    "**To enable Community in 30 seconds:**\n"
                    "1. In Discord, open **Server Settings** (Настройки сервера).\n"
                    "2. Scroll down in the left menu and click **Enable Community** (Включить сообщество).\n"
                    "3. Click **Get Started**, keep defaults, and finish.\n"
                    "4. Re-run `/convert_to_forum`!"
                ),
                color=config.EMBED_COLOR_WARNING
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        target_ch = channel or discord.utils.find(
            lambda c: "tutorial" in c.name.lower(),
            guild.text_channels
        )

        if not target_ch:
            if hasattr(guild, "forums") and discord.utils.find(lambda f: "tutorial" in f.name.lower(), guild.forums):
                await interaction.followup.send("ℹ️ `#tutorials` is already a native Forum channel!", ephemeral=True)
                return
            await interaction.followup.send("❌ Channel not found. Please specify the text channel to convert.", ephemeral=True)
            return

        forum, err = await convert_text_to_forum(guild, target_ch)
        if forum:
            embed = discord.Embed(
                title="✅ Forum Channel Created",
                description=(
                    f"Successfully converted #{target_ch.name} to forum {forum.mention}!\n\n"
                    f"• **Type:** Forum (`discord.ChannelType.forum`)\n"
                    f"• **Tags added:** `Guide`, `Tutorial`, `Prompt`, `Tool`, `Question`\n"
                    f"• **Permissions:** All members can create topics/threads and participate."
                ),
                color=config.EMBED_COLOR_SUCCESS
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            audit = discord.Embed(
                title="📚 [FORUM] Converted Channel to Forum",
                description=f"Channel {forum.mention} converted to native Forum by {interaction.user.mention}.",
                color=config.EMBED_COLOR_SUCCESS
            )
            await send_mod_log(guild, audit)
        else:
            await interaction.followup.send(f"❌ Failed to convert channel: `{err}`", ephemeral=True)

    @commands.command(name="convert_forum", aliases=["converttoforum", "makeforum", "forum"])
    async def convert_forum_cmd(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Prefix fallback: !convert_forum [channel]"""
        user_is_staff = (
            ctx.author.id == ctx.guild.owner_id
            or ctx.author.guild_permissions.administrator
            or any(r.name.lower() in config.STAFF_ROLE_NAMES for r in ctx.author.roles)
        )
        if not user_is_staff:
            await ctx.send("⛔ You do not have permission to execute this command.", delete_after=5)
            return

        guild = ctx.guild
        if "COMMUNITY" not in guild.features:
            await ctx.send("⚠️ Discord Community must be enabled in Server Settings before forum channels can be created.")
            return

        target_ch = channel or discord.utils.find(
            lambda c: "tutorial" in c.name.lower(),
            guild.text_channels
        )
        if not target_ch:
            if hasattr(guild, "forums") and discord.utils.find(lambda f: "tutorial" in f.name.lower(), guild.forums):
                await ctx.send("ℹ️ `#tutorials` is already a native Forum channel!")
                return
            await ctx.send("❌ Channel not found or already a forum channel.")
            return

        msg = await ctx.send("⏳ Converting channel to Forum channel...")
        forum, err = await convert_text_to_forum(guild, target_ch)
        if forum:
            await msg.edit(content=f"✅ Successfully converted to forum channel: {forum.mention}")
        else:
            await msg.edit(content=f"❌ Failed to convert channel: `{err}`")


async def ensure_jailbreak_open_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """
    Checks if #🔓・jailbreak-open exists in COMMUNITY category.
    If missing, creates it with optimized permissions (all @Members can write & create topics) and an intro guide.
    """
    if not guild or not guild.me.guild_permissions.manage_channels:
        return None

    # Check if channel already exists
    existing = discord.utils.find(
        lambda c: "jailbreak-open" in c.name.lower() or "jailbreak_open" in c.name.lower(),
        guild.text_channels
    )
    if existing:
        return existing

    # Find COMMUNITY category
    comm_category = discord.utils.find(
        lambda c: any(kw in c.name.upper() for kw in ["COMMUNITY", "КОМЬЮНИТИ"]),
        guild.categories
    )

    not_verified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
    member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
    premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)
    ai_contrib_role = discord.utils.find(lambda r: r.name.lower() == config.AI_CONTRIBUTOR_ROLE_NAME.lower(), guild.roles)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    if not_verified_role:
        overwrites[not_verified_role] = discord.PermissionOverwrite(view_channel=False)

    general_members = [r for r in [member_role, premium_role, ai_contrib_role] if r]
    for r in general_members:
        overwrites[r] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            send_messages_in_threads=True,
            create_public_threads=True,
            create_private_threads=False,
            read_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            connect=True,
            speak=True,
            mention_everyone=False,
            manage_webhooks=False
        )

    for role in guild.roles:
        r_name = role.name.lower()
        if (
            r_name in config.STAFF_ROLE_NAMES
            or any(alias in r_name for alias in config.ROLE_ALIASES.get("staff", []))
            or role.permissions.administrator
        ):
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                manage_threads=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

    try:
        channel = await guild.create_text_channel(
            name="🔓・jailbreak-open",
            category=comm_category,
            overwrites=overwrites,
            topic="🔓 Open community jailbreak discussion, prompt testing, and AI research hub. Be respectful!",
            slowmode_delay=3,
            reason="Epileptic Bot: Creating #jailbreak-open community discussion channel"
        )
        logger.info(f"Created #🔓・jailbreak-open in {guild.name} (Category: {comm_category.name if comm_category else 'None'})")

        # Send introductory pinned guide embed
        intro_embed = discord.Embed(
            title="🔓 Welcome to #jailbreak-open!",
            description=(
                "**Welcome to the open community jailbreak & prompt experimentation hub!**\n\n"
                "💬 **Everyone with the `@Member` role can write, share prompts, and collaborate here.**\n\n"
                "**Channel Guidelines:**\n"
                "• 🧪 Share and discuss new prompt techniques, jailbreak experiments, and LLM safety research.\n"
                "• 💡 Post snippets, test outputs, and collaborate with other prompt engineers.\n"
                "• ⚠️ Keep it clean: no text flooding, no self-promo, and no toxic attacks.\n"
                "• 🧵 For large prompt datasets or long test logs, feel free to create a thread!\n"
            ),
            color=config.RULES_EMBED_COLOR
        )
        if guild.icon:
            intro_embed.set_thumbnail(url=guild.icon.url)
        intro_embed.set_footer(text="Epileptic Community • #jailbreak-open")
        msg = await channel.send(embed=intro_embed)
        try:
            await msg.pin(reason="Channel introduction guide")
        except Exception:
            pass

        return channel
    except Exception as e:
        logger.error(f"Failed to create #jailbreak-open channel in {guild.name}: {e}")
        return None


async def convert_text_to_forum(
    guild: discord.Guild,
    channel: discord.TextChannel
) -> tuple[discord.ForumChannel | None, str]:
    """
    Converts an existing text channel (e.g. #tutorials) to a Discord Forum channel.
    Copies category, position, name, and configures tags and full member posting permissions.
    """
    if not guild or not guild.me.guild_permissions.manage_channels:
        return None, "Bot lacks `Manage Channels` permission."

    if "COMMUNITY" not in guild.features:
        return None, "Server does not have Discord Community enabled. Enable Community in Server Settings first."

    name = channel.name
    category = channel.category
    position = channel.position
    topic = channel.topic or "📚 Guides, tutorials, prompt techniques, and AI research hub."

    member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
    not_verified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
    premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)
    ai_contrib_role = discord.utils.find(lambda r: r.name.lower() == config.AI_CONTRIBUTOR_ROLE_NAME.lower(), guild.roles)

    overwrites = dict(channel.overwrites)
    overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
    if not_verified_role:
        overwrites[not_verified_role] = discord.PermissionOverwrite(view_channel=False)

    general_members = [r for r in [member_role, premium_role, ai_contrib_role] if r]
    for r in general_members:
        overwrites[r] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            send_messages_in_threads=True,
            create_public_threads=True,
            create_private_threads=False,
            read_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            add_reactions=True,
            use_application_commands=True,
            mention_everyone=False,
            manage_webhooks=False
        )

    for role in guild.roles:
        r_name = role.name.lower()
        if (
            r_name in config.STAFF_ROLE_NAMES
            or any(alias in r_name for alias in config.ROLE_ALIASES.get("staff", []))
            or role.permissions.administrator
        ):
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                manage_threads=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

    tags = [
        discord.ForumTag(name="Guide", emoji="📖"),
        discord.ForumTag(name="Tutorial", emoji="📚"),
        discord.ForumTag(name="Prompt", emoji="⚡"),
        discord.ForumTag(name="Tool", emoji="🛠️"),
        discord.ForumTag(name="Question", emoji="❓"),
    ]

    try:
        # Delete old text channel
        await channel.delete(reason="Converting to Forum Channel")
    except Exception as d_err:
        logger.warning(f"Could not delete old text channel #{name}: {d_err}")

    try:
        forum = await guild.create_forum(
            name=name,
            category=category,
            position=position,
            topic=topic,
            overwrites=overwrites,
            available_tags=tags,
            default_layout=discord.ForumLayoutType.list_view,
            reason="Epileptic Bot: Converted text channel to native forum channel"
        )
        logger.info(f"Created forum channel #{name} in {guild.name}")

        guide_embed = discord.Embed(
            title="📚 Welcome to the Tutorials & Guides Forum!",
            description=(
                "**Welcome to the community knowledge base!**\n\n"
                "Here anyone with the `@Member` role can create new topics, post tutorials, or ask questions.\n\n"
                "**How to post a topic:**\n"
                "1. Click **New Post** (Новый пост) at the top.\n"
                "2. Choose an appropriate tag (`Guide`, `Tutorial`, `Prompt`, `Tool`, or `Question`).\n"
                "3. Give your post a descriptive title and detailed instructions.\n"
                "4. Attach code snippets, prompts, or screenshots as needed.\n\n"
                "⚠️ *Please check if a similar tutorial or question already exists before creating a duplicate post!*"
            ),
            color=config.RULES_EMBED_COLOR
        )
        if guild.icon:
            guide_embed.set_thumbnail(url=guild.icon.url)
        guide_embed.set_footer(text="Epileptic Community • Tutorials Forum")

        try:
            thread_with_msg = await forum.create_thread(
                name="📌 [GUIDE] How to Post Tutorials & Prompts",
                content="Welcome everyone! Read below before posting your first guide:",
                embed=guide_embed,
                applied_tags=[tags[0], tags[1]] if len(tags) >= 2 else []
            )
            await thread_with_msg.thread.edit(pinned=True)
        except Exception as pin_err:
            logger.debug(f"Could not pin initial forum guide post: {pin_err}")

        return forum, "Success"
    except Exception as f_err:
        logger.error(f"Failed to create forum channel: {f_err}")
        return None, str(f_err)


async def auto_convert_tutorials_forum(guild: discord.Guild) -> bool:
    """
    Checks if #tutorials exists. If it's a TextChannel and server has COMMUNITY feature,
    automatically converts it to a native Discord Forum channel.
    If it's already a Forum channel, ensures @Member has thread creation permissions.
    """
    if not guild or not guild.me.guild_permissions.manage_channels:
        return False

    # Check if a forum channel already exists
    if hasattr(guild, "forums"):
        forum = discord.utils.find(lambda f: "tutorial" in f.name.lower(), guild.forums)
        if forum:
            member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
            if member_role:
                ow = forum.overwrites.get(member_role, discord.PermissionOverwrite())
                if ow.create_public_threads is not True or ow.send_messages is not True:
                    new_ow = dict(forum.overwrites)
                    ow.create_public_threads = True
                    ow.send_messages = True
                    ow.send_messages_in_threads = True
                    ow.view_channel = True
                    ow.read_message_history = True
                    new_ow[member_role] = ow
                    try:
                        await forum.edit(overwrites=new_ow)
                    except Exception:
                        pass
            return True

    # Check if a text channel exists to convert
    text_ch = discord.utils.find(lambda c: "tutorial" in c.name.lower(), guild.text_channels)
    if text_ch:
        if "COMMUNITY" in guild.features:
            forum, err = await convert_text_to_forum(guild, text_ch)
            return forum is not None
        else:
            # Community not enabled: ensure members can at least create threads in this text channel
            member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
            if member_role:
                ow = text_ch.overwrites.get(member_role, discord.PermissionOverwrite())
                if ow.create_public_threads is not True or ow.send_messages_in_threads is not True:
                    new_ow = dict(text_ch.overwrites)
                    ow.create_public_threads = True
                    ow.send_messages_in_threads = True
                    ow.create_private_threads = False
                    new_ow[member_role] = ow
                    try:
                        await text_ch.edit(overwrites=new_ow)
                    except Exception:
                        pass

    return False


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupServerCog(bot))
