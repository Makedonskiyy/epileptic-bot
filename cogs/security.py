import re
import time
import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands
import config

logger = logging.getLogger("epileptic.security")

# Регулярное выражение для поиска ссылок-приглашений Discord (discord.gg, discord.com/invite, etc.)
DISCORD_INVITE_REGEX = re.compile(
    r"(?:https?:\/\/)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discordapp\.com\/invite|discord\.com\/invite)\/[a-zA-Z0-9\-]+",
    re.IGNORECASE
)


class SecurityManager:
    """Менеджер безопасности: защита от рейдов, флуда и спама верификацией."""

    def __init__(self):
        # Хранение времени последнего взаимодействия для ограничения скорости (rate limit)
        self.user_cooldowns: dict[int, float] = {}
        # Очередь временных меток входа для обнаружения рейдов (join flood)
        self.recent_joins: deque[float] = deque()

    def check_user_cooldown(self, user_id: int) -> tuple[bool, float]:
        """
        Проверяет кулдаун пользователя на нажатие кнопок / реакции.
        Возвращает (разрешено: bool, оставшееся_время: float)
        """
        now = time.time()
        cooldown = config.VERIFY_COOLDOWN_SECONDS
        last_time = self.user_cooldowns.get(user_id, 0.0)

        if now - last_time < cooldown:
            remaining = round(cooldown - (now - last_time), 1)
            return False, remaining

        # Очищаем устаревшие записи, чтобы словарь не разрастался бесконечно
        if len(self.user_cooldowns) > 2000:
            threshold = now - 60
            self.user_cooldowns = {uid: t for uid, t in self.user_cooldowns.items() if t > threshold}

        self.user_cooldowns[user_id] = now
        return True, 0.0

    def check_account_age(self, member: discord.Member) -> tuple[bool, str]:
        """
        Проверка возраста аккаунта Discord (защита от рейдерских ботов-однодневок).
        """
        if config.MIN_ACCOUNT_AGE_HOURS <= 0:
            return True, ""

        now = datetime.now(timezone.utc)
        created_at = member.created_at
        age_delta = now - created_at
        age_hours = age_delta.total_seconds() / 3600

        if age_hours < config.MIN_ACCOUNT_AGE_HOURS:
            hours_left = round(config.MIN_ACCOUNT_AGE_HOURS - age_hours, 1)
            msg = (
                f"🛡️ **Security Alert:** Your Discord account is too new (< {config.MIN_ACCOUNT_AGE_HOURS}h old).\n"
                f"Created: <t:{int(created_at.timestamp())}:R>.\n"
                f"For anti-raid security, please wait **{hours_left} more hour(s)** or contact staff for manual review."
            )
            return False, msg

        return True, ""

    def register_join_and_check_raid(self) -> bool:
        """
        Регистрирует вход нового участника и проверяет превышение порога рейдов.
        Возвращает True, если обнаружен рейд.
        """
        now = time.time()
        self.recent_joins.append(now)

        # Удаляем метки за пределами окна времени
        cutoff = now - config.ANTI_RAID_WINDOW_SECONDS
        while self.recent_joins and self.recent_joins[0] < cutoff:
            self.recent_joins.popleft()

        return len(self.recent_joins) >= config.ANTI_RAID_JOIN_THRESHOLD


security_manager = SecurityManager()


async def send_mod_log(guild: discord.Guild, embed: discord.Embed) -> bool:
    """Отправка логов в канал mod-logs (например 📊・mod-logs). Возвращает True при успешной отправке."""
    if not guild:
        return False
    log_channel = discord.utils.find(
        lambda c: any(kw in c.name.lower() for kw in ["mod-logs", "mod_logs", "logs", "audit"]),
        guild.text_channels
    )
    if log_channel:
        try:
            await log_channel.send(embed=embed)
            return True
        except Exception as e:
            logger.warning(f"Could not send log to {log_channel.name}: {e}")
            return False
    return False


def is_staff():
    """Кастомный предикат безопасности для слэш-команд бота."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        # Владелец сервера всегда имеет доступ
        if interaction.user.id == interaction.guild.owner_id:
            return True
        # Проверка прав администратора
        if interaction.user.guild_permissions.administrator:
            return True
        # Проверка наличия любой роли из STAFF_ROLE_NAMES
        user_role_names = [r.name.lower() for r in interaction.user.roles]
        for staff_role in config.STAFF_ROLE_NAMES:
            if staff_role in user_role_names:
                return True
        for alias in config.ROLE_ALIASES.get("staff", []):
            if any(alias in r_name for r_name in user_role_names):
                return True

        await interaction.response.send_message(
            "⛔ **Access Denied:** You do not have staff permissions to execute this command.",
            ephemeral=True
        )
        return False

    return app_commands.check(predicate)


def is_owner():
    """Кастомный предикат безопасности: команда доступна ИСКЛЮЧИТЕЛЬНО владельцу сервера."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        if interaction.user.id == interaction.guild.owner_id:
            return True
        await interaction.response.send_message(
            "⛔ **Access Denied:** Only the Server Owner can execute this critical setup command.",
            ephemeral=True
        )
        return False

    return app_commands.check(predicate)



class SecurityCog(commands.Cog, name="Security"):
    """Модуль безопасности: аудит действий и защита от рейдов."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        # Проверка на рейд
        is_raid = security_manager.register_join_and_check_raid()
        if is_raid:
            alert_embed = discord.Embed(
                title="🚨 [SECURITY] Potential Server Raid Detected!",
                description=(
                    f"⚠️ High influx of new accounts detected: **{len(security_manager.recent_joins)} joins** "
                    f"within **{config.ANTI_RAID_WINDOW_SECONDS}s**!\n\n"
                    f"Latest account: {member.mention} (`{member.id}`)\n"
                    f"Account created: <t:{int(member.created_at.timestamp())}:R>"
                ),
                color=config.EMBED_COLOR_ERROR
            )
            alert_embed.set_footer(text="Epileptic Anti-Raid Guard")
            await send_mod_log(guild, alert_embed)
            logger.warning(f"Raid alert triggered on guild {guild.name} ({guild.id})!")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Anti-Invite Link Filter: Deletes unauthorized Discord invite links from non-staff."""
        if not message.guild or message.author.bot:
            return

        # Разрешено персоналу
        is_staff_author = (
            message.author.id == message.guild.owner_id
            or message.author.guild_permissions.administrator
            or any(r.name.lower() in config.STAFF_ROLE_NAMES for r in message.author.roles)
        )
        if is_staff_author:
            return

        # Проверка на наличие ссылок-приглашений Discord
        match = DISCORD_INVITE_REGEX.search(message.content)
        if match:
            try:
                await message.delete()
            except discord.Forbidden:
                logger.warning(f"Failed to delete invite from {message.author}: missing permissions.")
                return
            except Exception as e:
                logger.error(f"Error deleting invite message: {e}")
                return

            # Временное предупреждение в чате с автоудалением
            try:
                warn_msg = await message.channel.send(
                    f"⚠️ {message.author.mention}, posting Discord invite links is strictly prohibited by server rules!"
                )
                await asyncio.sleep(7)
                await warn_msg.delete()
            except Exception:
                pass

            # Логирование в mod-logs
            log_embed = discord.Embed(
                title="🚫 [ANTI-INVITE] Invite Link Deleted",
                description=(
                    f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Detected Link:** `{match.group(0)}`\n"
                    f"**Message:** ```{message.content[:500]}```"
                ),
                color=config.EMBED_COLOR_ERROR
            )
            await send_mod_log(message.guild, log_embed)
            logger.info(f"Deleted unauthorized invite link from {message.author} in #{message.channel.name}")


async def setup(bot: commands.Bot):
    await bot.add_cog(SecurityCog(bot))

