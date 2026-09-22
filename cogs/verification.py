import re
import time
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
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
    ignore_account_age: bool = True
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
    if not ignore_account_age and config.MIN_ACCOUNT_AGE_HOURS > 0:
        age_ok, age_err = security_manager.check_account_age(member)
        if not age_ok:
            logger.info(f"Verification blocked for {member} ({member.id}) due to account age threshold.")
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
        self.auto_sync_task.start()

    def cog_unload(self):
        self.auto_sync_task.cancel()

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

    async def _run_full_auto_sync(self, guild: discord.Guild):
        """
        Completely automated role synchronization:
        1. Checks bot permissions and Discord role hierarchy.
        2. Auto-verifies anyone who already reacted with ✅ under the rules message.
        3. Auto-assigns @Not Verified to any member who lacks Member and is not Staff.
        """
        if not guild or not guild.me.guild_permissions.manage_roles:
            return

        unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
        member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)

        # Auto-create Not Verified role if completely missing from server
        if not unverified_role:
            try:
                unverified_role = await guild.create_role(
                    name="Not Verified",
                    reason="Epileptic Bot: Auto-creating missing unverified role",
                    color=discord.Color.from_rgb(140, 140, 140)
                )
                logger.info(f"Auto-created Not Verified role on {guild.name}.")
            except Exception as cr_err:
                logger.warning(f"Could not auto-create unverified role: {cr_err}")

        if not unverified_role or not member_role:
            return

        # Discord Hierarchy Check: Bot must be placed ABOVE Member and Not Verified
        if guild.me.top_role.position <= member_role.position or guild.me.top_role.position <= unverified_role.position:
            logger.debug(
                f"Bot role '{guild.me.top_role.name}' is below Member/Not Verified in {guild.name}. "
                "Waiting for server admin to drag bot role higher."
            )
            return

        # Ensure guild members cache is populated
        if not guild.chunked:
            try:
                await guild.chunk()
            except Exception:
                pass

        # 1. Auto-verify all members who reacted with ✅ in rules channel
        rules_channel = discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["rules", "правил"]),
            guild.text_channels
        )
        if rules_channel:
            try:
                async for msg in rules_channel.history(limit=25):
                    for rx in msg.reactions:
                        if str(rx.emoji) in ["✅", "✔", "☑️"] and rx.count > 0:
                            async for user in rx.users():
                                if user.bot:
                                    continue
                                m = guild.get_member(user.id)
                                if not m:
                                    try:
                                        m = await guild.fetch_member(user.id)
                                    except Exception:
                                        continue
                                if m and member_role not in m.roles:
                                    try:
                                        roles_to_remove = [r for r in [unverified_role] if r in m.roles]
                                        if roles_to_remove:
                                            await m.remove_roles(*roles_to_remove, reason="Auto-sync: rules reaction accepted")
                                        await m.add_roles(member_role, reason="Auto-sync: rules reaction accepted")
                                        logger.info(f"Auto-verified reactor {m} ({m.id}) with Member role.")
                                        await asyncio.sleep(0.3)
                                    except Exception as e:
                                        logger.warning(f"Auto-sync reactor error for {m}: {e}")
            except Exception as e:
                logger.debug(f"Auto-sync rules reactions scan error: {e}")

        # 2. Auto-assign Not Verified role to all members who have neither Member nor Staff roles
        staff_names = set(config.STAFF_ROLE_NAMES)
        for m in guild.members:
            if m.bot:
                continue
            is_staff = any(r.name.lower() in staff_names for r in m.roles) or m.guild_permissions.administrator
            has_member = member_role in m.roles
            has_unverified = unverified_role in m.roles

            if not has_member and not is_staff and not has_unverified:
                try:
                    await m.add_roles(unverified_role, reason="Auto-sync: onboarding unverified role")
                    logger.info(f"Auto-assigned Not Verified to {m} ({m.id})")
        # 3. Enforce thread locks & clean up unauthorized threads in read-only channels
        await self._lock_and_clean_threads(guild, member_role, unverified_role)

    async def _lock_and_clean_threads(
        self,
        guild: discord.Guild,
        member_role: discord.Role | None,
        unverified_role: discord.Role | None
    ):
        """
        Disables thread creation across all read-only channels and deletes any existing threads.
        """
        if not guild.me.guild_permissions.manage_channels:
            return

        roles_to_restrict = [guild.default_role]
        if member_role:
            roles_to_restrict.append(member_role)
        if unverified_role:
            roles_to_restrict.append(unverified_role)

        read_only_keywords = [
            "rules", "правил", "announc", "объявлен", "welcome", "приветств",
            "access", "доступ", "faq", "инфо", "info"
        ]

        for channel in guild.text_channels:
            p_name = channel.name.lower()
            is_info_cat = channel.category and any(kw in channel.category.name.upper() for kw in ["INFO", "ИНФО"])
            is_readonly = is_info_cat or any(kw in p_name for kw in read_only_keywords)

            if not is_readonly:
                ow = channel.overwrites_for(guild.default_role)
                if ow.send_messages is False:
                    is_readonly = True

            if is_readonly:
                # 1. Update channel permissions to deny thread creation
                changed = False
                new_overwrites = dict(channel.overwrites)
                for r in roles_to_restrict:
                    current_ow = new_overwrites.get(r, discord.PermissionOverwrite())
                    if (
                        current_ow.create_public_threads is not False
                        or current_ow.create_private_threads is not False
                        or current_ow.send_messages_in_threads is not False
                    ):
                        current_ow.create_public_threads = False
                        current_ow.create_private_threads = False
                        current_ow.send_messages_in_threads = False
                        new_overwrites[r] = current_ow
                        changed = True

                if changed:
                    try:
                        await channel.edit(overwrites=new_overwrites)
                        logger.info(f"Enforced thread locks on #{channel.name}")
                    except Exception as e:
                        logger.warning(f"Could not update thread overwrites for #{channel.name}: {e}")

                # 2. Delete any existing threads in this channel (e.g. 'helloo', 'Muse 1.3 jail break needed')
                try:
                    for th in channel.threads:
                        try:
                            t_name = th.name
                            await th.delete()
                            logger.info(f"Auto-deleted existing thread '{t_name}' in #{channel.name}")
                        except Exception as th_err:
                            logger.warning(f"Could not delete thread {th.name}: {th_err}")
                except Exception as e:
                    logger.debug(f"Error checking active threads in #{channel.name}: {e}")

                try:
                    async for th in channel.archived_threads(limit=25):
                        try:
                            t_name = th.name
                            await th.delete()
                            logger.info(f"Auto-deleted archived thread '{t_name}' in #{channel.name}")
                        except Exception:
                            pass
                except Exception:
                    pass

    @tasks.loop(seconds=30)
    async def auto_sync_task(self):
        """Runs periodic automatic role synchronization across all guilds."""
        for guild in self.bot.guilds:
            try:
                await self._run_full_auto_sync(guild)
            except Exception as e:
                logger.debug(f"Error in auto_sync_task for guild {guild.id}: {e}")

    @auto_sync_task.before_loop
    async def before_auto_sync_task(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        """Immediately syncs roles when admin drags roles in Discord Server Settings."""
        await self._run_full_auto_sync(after.guild)

    @commands.Cog.listener()
    async def on_ready(self):
        """Run sync as soon as bot connects."""
        for guild in self.bot.guilds:
            await self._run_full_auto_sync(guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
