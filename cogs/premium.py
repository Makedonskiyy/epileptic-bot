import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config
from cogs.verification import find_role_by_key
from cogs.security import is_staff, is_owner, send_mod_log

logger = logging.getLogger("epileptic.premium")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SUBS_FILE = DATA_DIR / "premium_subscriptions.json"


def load_subscriptions() -> dict[str, dict]:
    """Загрузка активных премиум-подписок из JSON."""
    if not SUBS_FILE.exists():
        return {}
    try:
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading subscriptions: {e}")
        return {}


def save_subscriptions(data: dict[str, dict]):
    """Сохранение премиум-подписок в JSON."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(SUBS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving subscriptions: {e}")


class PremiumCog(commands.Cog, name="Premium Manager"):
    """Управление премиум-подписками с автоматическим таймером и снятием ролей."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.check_expired_subscriptions.start()

    async def cog_unload(self):
        self.check_expired_subscriptions.cancel()

    @tasks.loop(minutes=2)
    async def check_expired_subscriptions(self):
        """Фоновая проверка истекших подписок каждые 2 минуты."""
        if not self.bot.is_ready():
            return

        subs = load_subscriptions()
        if not subs:
            return

        now = time.time()
        expired_ids = []

        for user_id_str, info in list(subs.items()):
            expires_at = info.get("expires_at", 0)
            if now >= expires_at:
                expired_ids.append(user_id_str)

        if not expired_ids:
            return

        guild = self.bot.get_guild(config.GUILD_ID) if config.GUILD_ID else (self.bot.guilds[0] if self.bot.guilds else None)
        if not guild:
            return

        premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)
        if not premium_role:
            return

        for uid_str in expired_ids:
            uid = int(uid_str)
            info = subs.pop(uid_str, {})
            save_subscriptions(subs)

            try:
                member = guild.get_member(uid) or await guild.fetch_member(uid)
                if member and premium_role in member.roles:
                    await member.remove_roles(premium_role, reason="Premium subscription expired")
                    logger.info(f"Premium role removed from {member} (subscription expired).")

                    # Отправляем вежливое уведомление в ЛС пользователю
                    try:
                        expire_embed = discord.Embed(
                            title="💎 Premium Access Expired",
                            description=(
                                f"Hello **{member.display_name}**,\n\n"
                                f"Your **Premium Member** subscription on **{guild.name}** has reached its expiration date.\n\n"
                                f"📌 **What changed:**\n"
                                f"Access to the `PREMIUM` section (`#premium-prompts`, `#exclusive-tools`, etc.) has been closed.\n\n"
                                f"To renew your subscription and continue enjoying exclusive resources, please open a ticket in `#support-tickets`."
                            ),
                            color=config.EMBED_COLOR_WARNING
                        )
                        expire_embed.set_footer(text="Epileptic Community • Thank you for your support!")
                        await member.send(embed=expire_embed)
                    except Exception:
                        pass # ЛС закрыто

                    # Логирование в mod-logs
                    log_embed = discord.Embed(
                        title="💎 [PREMIUM] Subscription Expired",
                        description=(
                            f"**User:** {member.mention} (`{member.id}`)\n"
                            f"**Plan:** `{info.get('days', '?')} days`\n"
                            f"**Granted At:** <t:{int(info.get('granted_at', 0))}:f>\n"
                            f"**Action:** Role @{premium_role.name} revoked automatically."
                        ),
                        color=config.EMBED_COLOR_WARNING
                    )
                    await send_mod_log(guild, log_embed)

            except Exception as e:
                logger.error(f"Error handling expired premium for user {uid}: {e}")

    @check_expired_subscriptions.before_loop
    async def before_check_subs(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            pass

    @app_commands.command(
        name="grant_premium",
        description="Grant Premium Member role to a user for a specific number of days."
    )
    @app_commands.describe(
        member="Target server member to receive premium",
        days="Duration in days (e.g. 30, 60, 365)",
        reason="Optional reason / payment reference"
    )
    @is_staff()
    async def grant_premium(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        days: int,
        reason: str = "Premium Purchase"
    ):
        if days < 1 or days > 3650:
            await interaction.response.send_message("Days duration must be between 1 and 3650.", ephemeral=True)
            return

        guild = interaction.guild
        premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)

        if not premium_role:
            await interaction.response.send_message(f"❌ Role `{config.PREMIUM_ROLE_NAME}` not found.", ephemeral=True)
            return

        if guild.me.top_role.position <= premium_role.position:
            await interaction.response.send_message(
                f"⚠️ The bot's role (**{guild.me.top_role.name}**) is below **{premium_role.name}**!\n"
                "Please raise the bot's role in Server Settings -> Roles.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        now = time.time()
        subs = load_subscriptions()
        user_key = str(member.id)

        # Если уже есть активная подписка, продлеваем её
        if user_key in subs and subs[user_key].get("expires_at", 0) > now:
            new_expires = subs[user_key]["expires_at"] + (days * 86400)
            total_days = subs[user_key].get("days", 0) + days
        else:
            new_expires = now + (days * 86400)
            total_days = days

        subs[user_key] = {
            "expires_at": new_expires,
            "granted_at": now,
            "days": total_days,
            "granted_by": interaction.user.id,
            "reason": reason
        }
        save_subscriptions(subs)

        # Выдаем роль
        if premium_role not in member.roles:
            await member.add_roles(premium_role, reason=f"Premium granted by {interaction.user}: {reason}")

        expire_dt = datetime.fromtimestamp(new_expires, tz=timezone.utc)

        # Уведомление в ЛС пользователю
        try:
            user_embed = discord.Embed(
                title="💎 Congratulations! Premium Access Activated!",
                description=(
                    f"Hello **{member.display_name}**,\n\n"
                    f"You have been granted **Premium Member** status on **{guild.name}**!\n\n"
                    f"🌟 **Your Benefits:**\n"
                    f"• Access to `💎・premium-prompts`\n"
                    f"• Access to `🔐・exclusive-tools`\n"
                    f"• Access to `⭐・vip-resources` & `🎁・member-benefits`\n"
                    f"• Distinguished Premium role styling in chat\n\n"
                    f"📅 **Access valid until:** <t:{int(new_expires)}:F> (<t:{int(new_expires)}:R>)"
                ),
                color=config.RULES_EMBED_COLOR
            )
            if guild.icon:
                user_embed.set_thumbnail(url=guild.icon.url)
            user_embed.set_footer(text="Thank you for supporting Epileptic Community!")
            await member.send(embed=user_embed)
        except Exception:
            pass

        # Ответ модератору
        confirm_embed = discord.Embed(
            title="💎 Premium Access Granted Successfully",
            description=(
                f"**User:** {member.mention} (`{member.id}`)\n"
                f"**Duration:** `{days} days`\n"
                f"**Expires:** <t:{int(new_expires)}:F> (<t:{int(new_expires)}:R>)\n"
                f"**Reason:** {reason}"
            ),
            color=config.EMBED_COLOR_SUCCESS
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

        # Логирование в mod-logs
        log_embed = discord.Embed(
            title="💎 [PREMIUM] Role Granted",
            description=(
                f"**Recipient:** {member.mention} (`{member.id}`)\n"
                f"**Granted By:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**Duration:** `{days} days`\n"
                f"**Expires:** <t:{int(new_expires)}:f> (<t:{int(new_expires)}:R>)\n"
                f"**Reason:** {reason}"
            ),
            color=config.RULES_EMBED_COLOR
        )
        await send_mod_log(guild, log_embed)

    @app_commands.command(
        name="revoke_premium",
        description="Revoke Premium Member status immediately."
    )
    @app_commands.describe(member="Member to revoke premium from")
    @is_staff()
    async def revoke_premium(self, interaction: discord.Interaction, member: discord.Member):
        guild = interaction.guild
        premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)

        subs = load_subscriptions()
        user_key = str(member.id)

        if user_key in subs:
            subs.pop(user_key)
            save_subscriptions(subs)

        if premium_role and premium_role in member.roles:
            try:
                await member.remove_roles(premium_role, reason=f"Premium revoked manually by {interaction.user}")
            except Exception as e:
                await interaction.response.send_message(f"Failed to remove role: {e}", ephemeral=True)
                return

        await interaction.response.send_message(
            f"✅ Revoked Premium status from {member.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="check_premium",
        description="Check premium expiration date for yourself or another member."
    )
    @app_commands.describe(member="Member to inspect (optional)")
    async def check_premium(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        subs = load_subscriptions()
        user_key = str(target.id)

        info = subs.get(user_key)
        if not info:
            await interaction.response.send_message(
                f"ℹ️ {target.mention} does not have an active tracked Premium subscription.",
                ephemeral=True
            )
            return

        expires_at = info.get("expires_at", 0)
        granted_at = info.get("granted_at", 0)

        embed = discord.Embed(
            title=f"💎 Premium Status: {target.display_name}",
            color=config.RULES_EMBED_COLOR
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Granted At", value=f"<t:{int(granted_at)}:D>", inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(expires_at)}:R>", inline=True)
        embed.add_field(name="Total Duration", value=f"{info.get('days', '?')} days", inline=True)
        if info.get("reason"):
            embed.add_field(name="Note", value=info["reason"], inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PremiumCog(bot))
