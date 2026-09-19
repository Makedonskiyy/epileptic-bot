import logging
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.security import security_manager, send_mod_log, is_staff

logger = logging.getLogger("epileptic.verification")


def find_role_by_key(guild: discord.Guild, key: str, configured_name: str) -> discord.Role | None:
    """Finds a role on the guild by configured name or aliases."""
    if not guild:
        return None
    conf_lower = configured_name.lower()
    for role in guild.roles:
        if role.name.lower() == conf_lower:
            return role

    aliases = config.ROLE_ALIASES.get(key, [])
    for role in guild.roles:
        if role.name.lower() in aliases:
            return role

    return None


async def execute_verification(guild: discord.Guild, member: discord.Member) -> tuple[bool, str]:
    """
    Executes verification with anti-abuse and security guards:
    - Rate limit check
    - Account age check (anti-alt / anti-bot)
    - Role hierarchy check
    - Adds Member, removes Not Verified
    - Logs to mod-logs
    """
    # 1. Rate Limit Cooldown Check
    allowed, remaining = security_manager.check_user_cooldown(member.id)
    if not allowed:
        return False, f"⏳ **Slow down:** Please wait `{remaining}s` before trying again."

    # 2. Minimum Account Age Check (Anti-Bot / Anti-Raid)
    age_ok, age_err = security_manager.check_account_age(member)
    if not age_ok:
        # Log blocked attempt to mod-logs
        audit_embed = discord.Embed(
            title="🛡️ [SECURITY] Verification Blocked (New Account)",
            description=(
                f"**User:** {member.mention} (`{member.id}`)\n"
                f"**Created:** <t:{int(member.created_at.timestamp())}:R>\n"
                f"**Threshold:** Minimum {config.MIN_ACCOUNT_AGE_HOURS} hours required."
            ),
            color=config.EMBED_COLOR_WARNING
        )
        await send_mod_log(guild, audit_embed)
        return False, age_err

    # 3. Role Discovery
    member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
    unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)

    if not member_role:
        return False, f"⚠️ Server configuration error: Role `{config.MEMBER_ROLE_NAME}` was not found. Please contact an admin."

    # 4. Role Hierarchy Safety Check
    if guild.me.top_role.position <= member_role.position:
        logger.error(f"Bot role '{guild.me.top_role.name}' is below '{member_role.name}'.")
        return False, (
            "⚠️ **Discord Role Hierarchy Error:**\n"
            f"The bot's role (**{guild.me.top_role.name}**) is positioned BELOW **{member_role.name}** in Server Settings.\n"
            "Server Administrator: Go to *Server Settings -> Roles* and drag the bot's role higher!"
        )

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
        guild = member.guild
        unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)

        # 1. Assign Not Verified role
        if unverified_role:
            try:
                if guild.me.top_role.position > unverified_role.position:
                    await member.add_roles(unverified_role, reason="Auto-assign Not Verified on join")
                    logger.info(f"Assigned {unverified_role.name} to {member} ({member.id}).")
                else:
                    logger.warning(f"Bot role is below {unverified_role.name} in role hierarchy.")
            except discord.Forbidden:
                logger.error(f"Cannot assign {unverified_role.name} to {member}: missing permissions.")
            except Exception as e:
                logger.exception(f"Error assigning unverified role to {member}: {e}")

        # 2. Post welcome message to welcome channel
        welcome_channel = discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["welcome", "приветств"]),
            guild.text_channels
        )
        rules_channel = discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["rules", "правил"]),
            guild.text_channels
        )
        access_channel = discord.utils.find(
            lambda c: any(kw in c.name.lower() for kw in ["get-access", "access", "premium", "платн"]),
            guild.text_channels
        )

        rules_mention = rules_channel.mention if rules_channel else "📜・rules"
        access_mention = access_channel.mention if access_channel else "⚡・get-access"

        if welcome_channel:
            try:
                welcome_text = (
                    f"Hey {member.mention}, welcome to **Epileptic Community**! 👋\n\n"
                    f"Glad to have you here! Before diving in, take a second to look around:\n\n"
                    f"📜 Make sure to check out {rules_mention} to keep things chill.\n"
                    f"🧭 Feel free to explore the server, we have tons of useful resources, tools, and info waiting for you.\n"
                    f"💬 Drop by the general chats to vibe and connect with like-minded people!\n\n"
                    f"💎 **Looking for exclusive stuff?**\n"
                    f"Grab premium access right here ➔ {access_mention}\n\n"
                    f"Enjoy your stay!"
                )

                embed = discord.Embed(
                    description=welcome_text,
                    color=config.RULES_EMBED_COLOR
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(
                    text=f"Member #{guild.member_count}",
                    icon_url=guild.icon.url if guild.icon else None
                )

                await welcome_channel.send(embed=embed)
            except Exception as e:
                logger.warning(f"Failed to post welcome message in {welcome_channel.name}: {e}")

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
        if success:
            try:
                await member.send(
                    f"✅ **You have been verified on {guild.name}!**\n"
                    f"All community channels are now unlocked for you. Welcome aboard!"
                )
            except Exception:
                pass

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


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
