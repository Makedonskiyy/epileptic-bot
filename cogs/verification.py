import re
import time
import logging
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.security import security_manager, send_mod_log, is_staff
from cogs.welcome_card import create_welcome_card, get_ordinal

logger = logging.getLogger("epileptic.verification")

# Deduplication cache to prevent duplicate welcomes for the same member (member_id -> timestamp)
_recently_welcomed: dict[int, float] = {}


def find_role_by_key(guild: discord.Guild, key: str, configured_name: str) -> discord.Role | None:
    """
    Finds a role on the guild with resilient multi-stage matching:
    1. Exact case-insensitive match with configured_name
    2. Exact match with known aliases
    3. Stripped alphanumeric match (ignoring emojis, symbols, spaces, bullets)
    4. Keyword containment fuzzy match (e.g. 'unverif', 'unveriv', 'member', 'premium')
    """
    if not guild or not guild.roles:
        return None

    conf_lower = configured_name.strip().lower()
    raw_aliases = [a.strip().lower() for a in config.ROLE_ALIASES.get(key, [])]

    # 1. Exact match
    for role in guild.roles:
        if role.name.strip().lower() == conf_lower:
            return role

    # 2. Aliases exact match
    for role in guild.roles:
        if role.name.strip().lower() in raw_aliases:
            return role

    # 3. Alphanumeric stripped match (handles emojis like "❌・Not Verified", "👥 Member", etc.)
    conf_clean = re.sub(r'[^a-zA-Z0-9а-яА-Я]', '', conf_lower)
    aliases_clean = [re.sub(r'[^a-zA-Z0-9а-яА-Я]', '', a) for a in raw_aliases if a]

    for role in guild.roles:
        r_clean = re.sub(r'[^a-zA-Z0-9а-яА-Я]', '', role.name).lower()
        if r_clean and (r_clean == conf_clean or r_clean in aliases_clean):
            return role

    # 4. Keyword containment match (handles typos or partial names like "unveriv", "unverif", "member")
    keywords = {
        "unverified": ["unverif", "unveriv", "notverified", "not verified", "guest", "гость", "невериф"],
        "member": ["member", "участник", "verified"],
        "premium": ["premium", "премиум", "vip"],
        "staff": ["owner", "admin", "moder", "staff"]
    }.get(key, [conf_clean])

    for role in guild.roles:
        r_lower = role.name.lower()
        if any(kw in r_lower for kw in keywords if len(kw) >= 3):
            return role

    return None


async def execute_verification(
    guild: discord.Guild,
    member: discord.Member,
    ignore_account_age: bool = False
) -> tuple[bool, str]:
    """
    Executes verification with anti-abuse and security guards:
    - Rate limit check
    - Account age check (anti-alt / anti-bot, can be bypassed via ignore_account_age)
    - Role hierarchy check
    - Adds Member, removes Not Verified
    - Logs to mod-logs
    """
    # 1. Rate Limit Cooldown Check
    allowed, remaining = security_manager.check_user_cooldown(member.id)
    if not allowed:
        return False, f"⏳ **Slow down:** Please wait `{remaining}s` before trying again."

    # 2. Minimum Account Age Check (Anti-Bot / Anti-Raid)
    if not ignore_account_age:
        age_ok, age_err = security_manager.check_account_age(member)
        if not age_ok:
            audit_embed = discord.Embed(
                title="🛡️ [SECURITY] Verification Blocked (New Account)",
                description=(
                    f"**User:** {member.mention} (`{member.id}`)\n"
                    f"**Created:** <t:{int(member.created_at.timestamp())}:R>\n"
                    f"**Threshold:** Minimum {config.MIN_ACCOUNT_AGE_HOURS} hours required.\n"
                    f"💡 *To allow all accounts to verify immediately, run `/set_min_account_age hours:0`.*"
                ),
                color=config.EMBED_COLOR_WARNING
            )
            await send_mod_log(guild, audit_embed)
            return False, age_err

    # 3. Role Discovery
    member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
    unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)

    if not member_role:
        err_msg = f"⚠️ Server configuration error: Role `{config.MEMBER_ROLE_NAME}` was not found. Please contact an admin."
        alert_embed = discord.Embed(
            title="🚨 [CONFIG ERROR] Member Role Missing",
            description=(
                f"The bot cannot verify members because the role **`{config.MEMBER_ROLE_NAME}`** was not found!\n\n"
                f"**Fix:** Create a role named **`{config.MEMBER_ROLE_NAME}`** in *Server Settings -> Roles*."
            ),
            color=config.EMBED_COLOR_ERROR
        )
        await send_mod_log(guild, alert_embed)
        return False, err_msg

    # 4. Role Hierarchy Safety Check
    if guild.me.top_role.position <= member_role.position:
        logger.error(f"Bot role '{guild.me.top_role.name}' is below '{member_role.name}'.")
        err_msg = (
            "⚠️ **Discord Role Hierarchy Error:**\n"
            f"The bot's role (**{guild.me.top_role.name}**) is positioned BELOW **{member_role.name}** in Server Settings.\n"
            "Server Administrator: Go to *Server Settings -> Roles* and drag the bot's role higher!"
        )
        alert_embed = discord.Embed(
            title="🚨 [CONFIG ERROR] Role Hierarchy Issue",
            description=err_msg,
            color=config.EMBED_COLOR_ERROR
        )
        await send_mod_log(guild, alert_embed)
        return False, err_msg

    # 5. Check if already verified
    if member_role in member.roles:
        return True, "ℹ️ You are already verified and have full access to community channels!"

    try:
        roles_to_remove = []
        if unverified_role and unverified_role in member.roles:
            roles_to_remove.append(unverified_role)

        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Verification: removing unverified role")

        await member.add_roles(member_role, reason="Verification: accepted community rules")
        logger.info(f"User {member} ({member.id}) verified successfully.")

        # 6. Audit Log to mod-logs
        log_embed = discord.Embed(
            title="✅ [AUDIT] Member Verified",
            description=(
                f"**User:** {member.mention} (`{member.id}`)\n"
                f"**Account Age:** <t:{int(member.created_at.timestamp())}:R>\n"
                f"**Role Assigned:** @{member_role.name}"
            ),
            color=config.EMBED_COLOR_SUCCESS
        )
        log_embed.set_thumbnail(url=member.display_avatar.url)
        await send_mod_log(guild, log_embed)

        return True, f"✅ Verification successful! Granted role **@{member_role.name}**."
    except discord.Forbidden:
        return False, "❌ Permission denied: The bot lacks permission to manage roles. Please verify bot permissions."
    except Exception as e:
        logger.exception(f"Unexpected error during verification of {member.id}: {e}")
        return False, f"An unexpected error occurred: `{e}`"


def build_premium_pitch_dm(guild: discord.Guild, member: discord.Member) -> discord.Embed:
    """Builds an authentic, casual US youth slang welcome & premium pitch DM embed."""
    access_channel = discord.utils.find(
        lambda c: any(kw in c.name.lower() for kw in ["get-access", "access", "premium", "платн"]),
        guild.text_channels
    )
    support_channel = discord.utils.find(
        lambda c: any(kw in c.name.lower() for kw in ["ticket", "support", "помощь"]),
        guild.text_channels
    )

    access_mention = access_channel.mention if access_channel else "⚡・get-access"
    support_mention = support_channel.mention if support_channel else "🎫・support-tickets"

    description = (
        f"Yo **{member.display_name}**, glad to have you on the server.\n\n"
        f"**Wanna get the absolute most out of the server?**\n"
        f"Our **Premium Member** pass is live, hooking you up with the real good stuff:\n\n"
        f"• **Secret & unpatched jailbreaks** (DeepSeek, Gemini, Muse Spark)\n"
        f"• **Exclusive pro prompts & custom AI tools**\n"
        f"• **Priority 1-on-1 help & private VIP chats**\n"
        f"• **Daily drops & fresh database updates**\n\n"
        f"**How to cop access:**\n"
        f"Slide over to {access_mention} or open a quick ticket in {support_mention} to get hooked up.\n\n"
        f"Enjoy your stay and go crazy in the chats! ⚡"
    )

    embed = discord.Embed(
        title="💎 Welcome to Epileptic Community!",
        description=description,
        color=config.RULES_EMBED_COLOR
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(
        text="Epileptic Community • Level Up Your AI Game",
        icon_url=guild.me.display_avatar.url if guild.me else None
    )
    return embed


class PersistentVerificationView(discord.ui.View):
    """Persistent Discord UI Button View."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label=config.VERIFY_BUTTON_LABEL,
        style=discord.ButtonStyle.success,
        emoji=config.VERIFY_BUTTON_EMOJI,
        custom_id=config.VERIFY_CUSTOM_ID,
    )
    async def verify_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This action is only available in servers.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)

        success, message = await execute_verification(guild, member)

        if success and "already verified" not in message.lower():
            # Send the casual US youth slang Premium pitch DM
            try:
                dm_embed = build_premium_pitch_dm(guild, member)
                await member.send(embed=dm_embed)
            except Exception:
                pass

            embed = discord.Embed(
                title="🎉 Welcome to the Community!",
                description=(
                    f"Welcome, **{member.display_name}**!\n\n"
                    f"You have been granted access to our channels:\n"
                    f"• **COMMUNITY** — General discussion, off-topic, and ideas\n"
                    f"• **RESOURCES** — Prompts library, AI news, tutorials, and jailbreaks\n"
                    f"• **LOUNGE** — Chill music stream and chats\n"
                    f"• **SUPPORT** — Community support & tickets\n\n"
                    f"Enjoy your stay!"
                ),
                color=config.EMBED_COLOR_SUCCESS
            )
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            embed.set_footer(text="Epileptic Community Bot", icon_url=interaction.client.user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class VerificationCog(commands.Cog, name="Verification"):
    """Handles member join events, auto-assigning unverified role, and verification interactions."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Automatically assigns Not Verified role and posts welcome message."""
        now = time.time()
        last_welcome = _recently_welcomed.get(member.id, 0.0)
        if (now - last_welcome) < 60.0:
            logger.info(f"Skipping duplicate welcome event for {member} ({member.id}) - welcomed {now - last_welcome:.1f}s ago.")
            return
        _recently_welcomed[member.id] = now

        # Prune old cache entries if cache grows large
        if len(_recently_welcomed) > 500:
            cutoff = now - 300.0
            for uid in [k for k, v in _recently_welcomed.items() if v < cutoff]:
                _recently_welcomed.pop(uid, None)

        guild = member.guild
        unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)

        # 1. Assign Not Verified role (with auto-create fallback and hierarchy alert)
        if not unverified_role:
            try:
                if guild.me.guild_permissions.manage_roles:
                    unverified_role = await guild.create_role(
                        name="Not Verified",
                        reason="Epileptic Bot: Auto-creating missing unverified role for onboarding",
                        color=discord.Color.from_rgb(140, 140, 140)
                    )
                    logger.info(f"Auto-created missing unverified role '{unverified_role.name}' on {guild.name}.")
            except Exception as cr_err:
                logger.warning(f"Could not auto-create unverified role: {cr_err}")

        if unverified_role:
            try:
                if guild.me.top_role.position > unverified_role.position:
                    await member.add_roles(unverified_role, reason="Auto-assign Not Verified on join")
                    logger.info(f"Assigned {unverified_role.name} to {member} ({member.id}).")
                else:
                    logger.warning(f"Bot role '{guild.me.top_role.name}' is below {unverified_role.name} in role hierarchy.")
                    alert_embed = discord.Embed(
                        title="🚨 [CONFIG ERROR] Cannot Assign Unverified Role",
                        description=(
                            f"The bot cannot assign **@{unverified_role.name}** to new members!\n\n"
                            f"**Reason:** The bot's role (**@{guild.me.top_role.name}**) is below **@{unverified_role.name}** in Server Settings.\n\n"
                            f"**Fix:** Open **Server Settings -> Roles** and drag the bot's role (**@{guild.me.top_role.name}**) ABOVE **@{unverified_role.name}**!"
                        ),
                        color=config.EMBED_COLOR_ERROR
                    )
                    await send_mod_log(guild, alert_embed)
            except discord.Forbidden:
                logger.error(f"Cannot assign {unverified_role.name} to {member}: missing permissions.")
            except Exception as e:
                logger.exception(f"Error assigning unverified role to {member}: {e}")

        # 2. Post visual welcome banner card to welcome channel
        welcome_channel = discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["welcome", "приветств"]),
            guild.text_channels
        )

        if welcome_channel:
            try:
                # Read member avatar bytes
                avatar_bytes = None
                try:
                    avatar_bytes = await member.display_avatar.with_format("png").with_size(256).read()
                except Exception as av_err:
                    logger.warning(f"Could not fetch avatar for {member}: {av_err}")

                # Retrieve the most accurate live count available
                count = guild.member_count or len(guild.members) or 1
                try:
                    fresh_guild = await self.bot.fetch_guild(guild.id, with_counts=True)
                    if fresh_guild and fresh_guild.approximate_member_count:
                        count = fresh_guild.approximate_member_count
                except Exception as cnt_err:
                    logger.debug(f"Could not fetch fresh approximate count: {cnt_err}")

                card_buffer = create_welcome_card(
                    avatar_bytes=avatar_bytes,
                    username=member.display_name,
                    member_count=count,
                    server_name=guild.name
                )

                ordinal_str = get_ordinal(count)
                content_text = f"Welcome {member.mention} to **{guild.name}**! You are the {ordinal_str} member!"
                welcome_file = discord.File(fp=card_buffer, filename="welcome.png")

                await welcome_channel.send(content=content_text, file=welcome_file)
                logger.info(f"Sent visual welcome card for {member} in #{welcome_channel.name} (count: {count}).")
            except Exception as e:
                logger.warning(f"Failed to post welcome card in {welcome_channel.name}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Internal logging of member departures (batched daily/weekly summaries handle chat reporting)."""
        guild = member.guild
        current_count = guild.member_count or len(guild.members)
        logger.info(f"Member left {guild.name}: {member} ({member.id}). Current count: {current_count}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Reaction-based verification fallback (reacting with ✅ in rules channel)."""
        if payload.user_id == self.bot.user.id:
            return

        if str(payload.emoji.name) not in ["✅", "✔", "☑️"]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        channel = guild.get_channel(payload.channel_id)
        if not channel or not any(kw in channel.name.lower() for kw in ["rules", "verify", "правил"]):
            return

        member = payload.member
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                return

        if member.bot:
            return

        success, message = await execute_verification(guild, member)
        if success and "already verified" not in message.lower():
            # Send the casual US youth slang Premium pitch DM
            try:
                dm_embed = build_premium_pitch_dm(guild, member)
                await member.send(embed=dm_embed)
                logger.info(f"Sent Premium pitch DM to newly verified member {member} ({member.id}).")
            except discord.Forbidden:
                logger.info(f"Could not send welcome DM to {member} (DMs closed by user).")
            except Exception as e:
                logger.warning(f"Failed to send welcome DM to {member}: {e}")
        elif not success and "already verified" not in message.lower():
            # Send DM feedback explaining why verification failed
            try:
                warn_embed = discord.Embed(
                    title="⚠️ Verification Notice",
                    description=(
                        f"Hello {member.mention},\n\n"
                        f"{message}\n\n"
                        f"If you need assistance, please open a ticket in **#support-tickets**."
                    ),
                    color=config.EMBED_COLOR_WARNING
                )
                await member.send(embed=warn_embed)
            except Exception:
                pass

    @app_commands.command(
        name="test_welcome_dm",
        description="Send a test copy of the Premium Welcome DM directly to your private messages."
    )
    @is_staff()
    async def test_welcome_dm(self, interaction: discord.Interaction):
        """Allows staff to preview and test the Premium pitch DM in their own messages."""
        dm_embed = build_premium_pitch_dm(interaction.guild, interaction.user)
        try:
            await interaction.user.send(embed=dm_embed)
            await interaction.response.send_message(
                "✅ Test welcome DM successfully sent! Check your private messages.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Could not send DM! Please enable direct messages in *User Settings -> Privacy & Safety*.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error sending test DM: `{e}`",
                ephemeral=True
            )

    @app_commands.command(
        name="test_welcome_card",
        description="Preview and test the dynamic visual welcome card in the channel."
    )
    @app_commands.describe(
        target_channel="Channel to post test card in (optional, defaults to current channel)",
        member="Member to preview on the card (optional, defaults to yourself)"
    )
    @is_staff()
    async def test_welcome_card(
        self,
        interaction: discord.Interaction,
        target_channel: discord.TextChannel = None,
        member: discord.Member = None
    ):
        """Allows staff to preview and test the Welcomer visual banner card."""
        target_user = member or interaction.user
        channel = target_channel or interaction.channel
        guild = interaction.guild

        await interaction.response.defer(ephemeral=True)

        try:
            avatar_bytes = None
            try:
                avatar_bytes = await target_user.display_avatar.with_format("png").with_size(256).read()
            except Exception as av_err:
                logger.warning(f"Could not fetch avatar for test card: {av_err}")

            card_buffer = create_welcome_card(
                avatar_bytes=avatar_bytes,
                username=target_user.display_name,
                member_count=guild.member_count,
                server_name=guild.name
            )

            ordinal_str = get_ordinal(guild.member_count)
            content_text = f"Welcome {target_user.mention} to **{guild.name}**! You are the {ordinal_str} member!"
            welcome_file = discord.File(fp=card_buffer, filename="welcome_card.png")

            msg = await channel.send(content=content_text, file=welcome_file)
            await interaction.followup.send(
                f"✅ Visual welcome card successfully sent to {channel.mention}! [View Message]({msg.jump_url})",
                ephemeral=True
            )
        except Exception as e:
            logger.exception(f"Failed to generate test welcome card: {e}")
            await interaction.followup.send(f"❌ Failed to create card: `{e}`", ephemeral=True)

    @app_commands.command(
        name="post_verification",
        description="Publish official server rules with the ✅ reaction verification (matching community design)."
    )
    @app_commands.describe(
        channel="Channel to publish in (defaults to #rules or current channel)",
        with_button="Also include interactive button below rules (default: False, reaction only)",
        title="Optional custom title (leave empty for clean look like in screenshot)"
    )
    @is_staff()
    async def post_verification(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        with_button: bool = False,
        title: str = None
    ):
        """Posts the official community rules and adds the ✅ reaction."""
        target_channel = channel
        if not target_channel:
            rules_ch = discord.utils.find(
                lambda c: any(kw in c.name.lower() for kw in ["rules", "правил"]),
                interaction.guild.text_channels
            )
            target_channel = rules_ch or interaction.channel

        embed_desc = config.OFFICIAL_RULES_DESCRIPTION

        # Create sleek embed with purple accent matching community screenshot
        if title:
            embed = discord.Embed(
                title=title,
                description=embed_desc,
                color=config.RULES_EMBED_COLOR
            )
        else:
            embed = discord.Embed(
                description=embed_desc,
                color=config.RULES_EMBED_COLOR
            )

        view = PersistentVerificationView() if with_button else None
        msg = await target_channel.send(embed=embed, view=view)

        # Add the checkmark reaction
        try:
            await msg.add_reaction("✅")
        except Exception as e:
            logger.warning(f"Could not add reaction to rules message: {e}")

        await interaction.response.send_message(
            f"✅ Server rules successfully published to {target_channel.mention} with reaction verification!",
            ephemeral=True
        )

    @app_commands.command(
        name="diagnose_roles",
        description="Diagnose server roles, bot hierarchy, permissions, and member verification breakdown."
    )
    @is_staff()
    async def diagnose_roles(self, interaction: discord.Interaction):
        """Diagnostic report of server roles, hierarchy, and onboarding configuration."""
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
        member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
        premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)

        bot_top_role = guild.me.top_role
        has_manage_roles = guild.me.guild_permissions.manage_roles
        has_admin = guild.me.guild_permissions.administrator

        total_members = guild.member_count or len(guild.members)
        m_count = len(member_role.members) if member_role else 0
        u_count = len(unverified_role.members) if unverified_role else 0
        p_count = len(premium_role.members) if premium_role else 0

        # Count members with neither role
        neither_count = 0
        for m in guild.members:
            if not m.bot:
                has_m = member_role in m.roles if member_role else False
                has_u = unverified_role in m.roles if unverified_role else False
                if not has_m and not has_u:
                    neither_count += 1

        def role_status(r: discord.Role | None, label: str) -> str:
            if not r:
                return f"❌ **Not Found!** (configured: `{label}`)"
            can_manage = bot_top_role.position > r.position
            h_icon = "🟢 OK" if can_manage else "🔴 **BELOW BOT ROLE!**"
            return f"`@{r.name}` (ID: `{r.id}`) — Hierarchy: {h_icon}"

        embed = discord.Embed(
            title="🔍 Role & Verification Diagnostics",
            color=config.EMBED_COLOR_DEFAULT
        )

        embed.add_field(
            name="🤖 Bot Permissions & Hierarchy",
            value=(
                f"• Top Role: **@{bot_top_role.name}** (Position: `{bot_top_role.position}`)\n"
                f"• Manage Roles Permission: {'✅ Yes' if has_manage_roles else '❌ **NO (Cannot assign roles!)**'}\n"
                f"• Administrator: {'✅ Yes' if has_admin else '⚪ No'}"
            ),
            inline=False
        )

        embed.add_field(
            name="🎭 Role Detection Status",
            value=(
                f"• **Unverified Role:** {role_status(unverified_role, config.UNVERIFIED_ROLE_NAME)}\n"
                f"• **Member Role:** {role_status(member_role, config.MEMBER_ROLE_NAME)}\n"
                f"• **Premium Role:** {role_status(premium_role, config.PREMIUM_ROLE_NAME)}"
            ),
            inline=False
        )

        embed.add_field(
            name="👥 Member Distribution",
            value=(
                f"• Total Members: **{total_members}**\n"
                f"• Verified (@{member_role.name if member_role else 'Member'}): **{m_count}**\n"
                f"• Unverified (@{unverified_role.name if unverified_role else 'Not Verified'}): **{u_count}**\n"
                f"• Neither Role: **{neither_count}**\n"
                f"• Premium (@{premium_role.name if premium_role else 'Premium'}): **{p_count}**"
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Security Settings",
            value=(
                f"• Min Account Age: **{config.MIN_ACCOUNT_AGE_HOURS} hours** "
                f"({'⚠️ Blocks accounts < 24h old' if config.MIN_ACCOUNT_AGE_HOURS > 0 else '🟢 Disabled, allows all accounts'})\n"
                f"• Click Cooldown: **{config.VERIFY_COOLDOWN_SECONDS}s**"
            ),
            inline=False
        )

        recommendations = []
        if not unverified_role:
            recommendations.append("⚠️ Role `Not Verified` was not found. The bot will auto-create it on next join, or you can create it in Server Settings.")
        elif bot_top_role.position <= unverified_role.position:
            recommendations.append(f"🚨 **Critical:** Drag bot role (`@{bot_top_role.name}`) ABOVE `@{unverified_role.name}` in Server Settings -> Roles!")

        if not member_role:
            recommendations.append(f"⚠️ Role `Member` was not found. Please create role `Member` in Server Settings.")
        elif bot_top_role.position <= member_role.position:
            recommendations.append(f"🚨 **Critical:** Drag bot role (`@{bot_top_role.name}`) ABOVE `@{member_role.name}` in Server Settings -> Roles!")

        if config.MIN_ACCOUNT_AGE_HOURS > 0:
            recommendations.append("💡 To verify all new accounts immediately without waiting 24h, run `/set_min_account_age hours:0`.")

        if neither_count > 0:
            recommendations.append(f"💡 Run `/assign_unverified_all` to give `@Not Verified` to the {neither_count} members with no roles.")

        recommendations.append("💡 Run `/verify_all_reactors` to verify everyone who clicked ✅ on the rules message!")

        embed.add_field(name="📋 Recommendations & Actions", value="\n".join(recommendations), inline=False)
        embed.set_footer(text="Epileptic Server Guard")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="verify_all_reactors",
        description="Verify all members who clicked ✅ on the rules message (bypassing account age check)."
    )
    @app_commands.describe(
        rules_channel="Channel where rules message is posted (defaults to #rules)",
        ignore_age_check="Allow accounts newer than 24h to verify (default: True)"
    )
    @is_staff()
    async def verify_all_reactors(
        self,
        interaction: discord.Interaction,
        rules_channel: discord.TextChannel = None,
        ignore_age_check: bool = True
    ):
        """Bulk verifies everyone who clicked the ✅ reaction on the rules message."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
        unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)

        if not member_role:
            await interaction.followup.send(
                f"❌ Role `{config.MEMBER_ROLE_NAME}` was not found. Please create it first.",
                ephemeral=True
            )
            return

        if guild.me.top_role.position <= member_role.position:
            await interaction.followup.send(
                f"🚨 **Role Hierarchy Error:** The bot's role (**{guild.me.top_role.name}**) is below **{member_role.name}**!\n"
                f"Open Server Settings -> Roles and drag the bot's role higher.",
                ephemeral=True
            )
            return

        r_ch = rules_channel or discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["rules", "правил"]),
            guild.text_channels
        )
        if not r_ch:
            await interaction.followup.send("❌ Rules channel not found. Please specify it in command arguments.", ephemeral=True)
            return

        # Find message with checkmark reaction
        target_message = None
        async for msg in r_ch.history(limit=50):
            for rx in msg.reactions:
                if str(rx.emoji) in ["✅", "✔", "☑️"] and rx.count > 0:
                    target_message = msg
                    break
            if target_message:
                break

        if not target_message:
            await interaction.followup.send(f"❌ No message with ✅ reaction found in {r_ch.mention}.", ephemeral=True)
            return

        # Fetch all users who reacted with ✅
        reactors = []
        for rx in target_message.reactions:
            if str(rx.emoji) in ["✅", "✔", "☑️"]:
                async for user in rx.users():
                    if not user.bot:
                        reactors.append(user)

        verified_count = 0
        already_verified = 0
        skipped_age = 0
        failed_count = 0

        for user in reactors:
            member = guild.get_member(user.id)
            if not member:
                try:
                    member = await guild.fetch_member(user.id)
                except Exception:
                    continue

            if member_role in member.roles:
                already_verified += 1
                continue

            # Account age check if enabled
            if not ignore_age_check:
                age_ok, _ = security_manager.check_account_age(member)
                if not age_ok:
                    skipped_age += 1
                    continue

            try:
                roles_to_remove = []
                if unverified_role and unverified_role in member.roles:
                    roles_to_remove.append(unverified_role)
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Bulk reaction verification")
                await member.add_roles(member_role, reason="Bulk reaction verification from rules checkmark")
                verified_count += 1
            except Exception as e:
                logger.warning(f"Could not bulk verify {member}: {e}")
                failed_count += 1

        embed = discord.Embed(
            title="✅ Bulk Reaction Verification Complete",
            color=config.EMBED_COLOR_SUCCESS
        )
        embed.add_field(name="Newly Verified", value=f"**{verified_count}** members", inline=True)
        embed.add_field(name="Already Verified", value=f"**{already_verified}** members", inline=True)
        if skipped_age > 0:
            embed.add_field(name="Skipped (<24h old)", value=f"**{skipped_age}** members", inline=True)
        if failed_count > 0:
            embed.add_field(name="Failed (Permissions)", value=f"**{failed_count}** members", inline=True)

        embed.set_footer(text=f"Processed {len(reactors)} total reaction clicks from #{r_ch.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="set_min_account_age",
        description="Set minimum account age in hours required to verify (set 0 to allow all accounts)."
    )
    @app_commands.describe(hours="Minimum account age in hours (e.g. 0 to disable, 1, 24)")
    @is_staff()
    async def set_min_account_age(self, interaction: discord.Interaction, hours: int):
        """Live updates MIN_ACCOUNT_AGE_HOURS threshold."""
        if hours < 0:
            await interaction.response.send_message("Hours cannot be negative.", ephemeral=True)
            return

        config.MIN_ACCOUNT_AGE_HOURS = hours
        if hours == 0:
            msg = "🟢 **Account age check disabled!** All Discord accounts (including brand new accounts) can now self-verify instantly."
        else:
            msg = f"🛡️ **Minimum account age set to {hours} hour(s).** Accounts newer than this will be blocked from self-verifying."

        embed = discord.Embed(
            title="⚙️ Verification Security Setting Updated",
            description=msg,
            color=config.EMBED_COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
