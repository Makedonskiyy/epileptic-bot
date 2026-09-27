import re
import time
import asyncio
import logging
from collections import deque
from datetime import datetime, timezone, timedelta
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
    """Менеджер безопасности: защита от рейдов, флуда, бот-спама и несанкционированных вебхуков."""

    def __init__(self):
        # Хранение времени последнего взаимодействия для ограничения скорости (rate limit)
        self.user_cooldowns: dict[int, float] = {}
        # Очередь временных меток входа для обнаружения рейдов (join flood)
        self.recent_joins: deque[float] = deque()
        # История сообщений для обнаружения флуда и повторов: sender_id -> deque of (timestamp, content)
        self.message_history: dict[int, deque[tuple[float, str]]] = {}

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

    def register_message_and_check_spam(self, sender_id: int, content: str) -> tuple[bool, str]:
        """
        Проверка на флуд и повторение сообщений per sender (user ID или webhook ID):
        1. Высокая частота: более 3 сообщений за 3.0 секунды
        2. Повторяющийся спам: 3 одинаковых сообщения за 6 секунд
        """
        now = time.time()
        if sender_id not in self.message_history:
            self.message_history[sender_id] = deque()

        history = self.message_history[sender_id]
        history.append((now, content))

        # Оставляем только записи за последние 8 секунд
        cutoff = now - 8.0
        while history and history[0][0] < cutoff:
            history.popleft()

        # Периодическая очистка словаря при большом размере
        if len(self.message_history) > 3000:
            threshold = now - 15.0
            self.message_history = {k: v for k, v in self.message_history.items() if v and v[-1][0] > threshold}

        # 1. Проверка частоты (3+ сообщения за 3.0 сек)
        recent_3s = [t for t, _ in history if now - t <= 3.0]
        if len(recent_3s) >= 4:
            return True, "Fast Message Flooding (>3 msgs / 3s)"

        # 2. Проверка дубликатов (3 одинаковых за 6 сек)
        if len(content) >= 3:
            duplicate_count = sum(1 for t, c in history if c == content and (now - t <= 6.0))
            if duplicate_count >= 3:
                return True, "Repeated Message Flood"

        return False, ""

    def check_spam_content(self, content: str, embeds: list[discord.Embed]) -> tuple[bool, str]:
        """
        Проверка содержимого и эмбедов на известные сигнатуры бот-спамеров, рейд-тулов и вебхук-спама.
        """
        embed_parts = []
        for e in embeds:
            if e.title:
                embed_parts.append(e.title)
            if e.description:
                embed_parts.append(e.description)
            for f in e.fields:
                embed_parts.append(f"{f.name} {f.value}")
            if e.footer and e.footer.text:
                embed_parts.append(e.footer.text)
            if e.author and e.author.name:
                embed_parts.append(e.author.name)

        full_text = f"{content} {' '.join(embed_parts)}".lower()

        # Сигнатуры известных спамеров и рейд-инструментов
        spam_signatures = [
            ("spired", "Spired Spammer signature detected"),
            ("spammed by", "Rogue bot spam pattern ('spammed by')"),
            ("raided by", "Raid tool signature ('raided by')"),
            ("nuked by", "Server nuke signature ('nuked by')"),
            ("crash discord", "Malicious exploit signature"),
            ("webhook spam", "Webhook raid signature"),
        ]

        for pattern, reason in spam_signatures:
            if pattern in full_text:
                return True, reason

        return False, ""


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

        # 1. Anti-Rogue-Bot Shield: Check if an unauthorized bot account joined
        if member.bot:
            try:
                authorized = False
                inviter = None
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                    if entry.target and entry.target.id == member.id:
                        inviter = entry.user
                        if inviter and (inviter.id == guild.owner_id or inviter.guild_permissions.administrator):
                            authorized = True
                        break

                # If bot was invited by someone who is not owner/admin, ban it immediately
                if not authorized and inviter and inviter.id != guild.owner_id and not inviter.guild_permissions.administrator:
                    await member.ban(reason=f"Anti-Raid: Unauthorized bot invited by {inviter} ({inviter.id})")
                    alert_embed = discord.Embed(
                        title="🚨 [SECURITY] Rogue Bot Blocked & Banned",
                        description=(
                            f"**Rogue Bot:** {member.mention} (`{member.id}`)\n"
                            f"**Invited By:** {inviter.mention} (`{inviter.id}`)\n"
                            f"**Action:** Bot was immediately banned from the server."
                        ),
                        color=config.EMBED_COLOR_ERROR
                    )
                    await send_mod_log(guild, alert_embed)
                    logger.warning(f"Banned unauthorized bot {member} added by {inviter}.")
                    return
            except Exception as e:
                logger.debug(f"Audit log check error for joining bot: {e}")

        # 2. Check for human user mass join raid
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
        """
        Anti-Spam & Rogue Bot/Webhook Interceptor:
        - Intercepts webhook spam (e.g. Spired Spammer) -> deletes message, destroys the webhook, purges channel
        - Intercepts rogue bot spam -> bans the bot, purges messages
        - Intercepts member flood / repeated messages -> timeouts member for 1 hour, purges messages
        - Filters unauthorized invite links
        """
        if not message.guild:
            return

        # 1. Never filter our own bot
        if message.author.id == self.bot.user.id:
            return

        guild = message.guild
        channel = message.channel
        is_webhook = message.webhook_id is not None
        sender_id = message.webhook_id if is_webhook else message.author.id

        # 2. Allow server staff through filter
        is_staff_author = False
        if not is_webhook and isinstance(message.author, discord.Member):
            is_staff_author = (
                message.author.id == guild.owner_id
                or message.author.guild_permissions.administrator
                or any(r.name.lower() in config.STAFF_ROLE_NAMES for r in message.author.roles)
            )

        if is_staff_author:
            return

        # 3. Content Inspection (Spam signatures, Spired Spammer, raid patterns)
        is_spam_text, spam_reason = security_manager.check_spam_content(message.content, message.embeds)

        # 4. Rate-limit & Repetition Flood Inspection
        clean_content = message.content.strip().lower()
        if not clean_content and message.embeds:
            clean_content = " ".join([e.title or '' for e in message.embeds]).strip().lower()
        is_flood, flood_reason = security_manager.register_message_and_check_spam(sender_id, clean_content)

        if is_spam_text or is_flood:
            trigger_reason = spam_reason or flood_reason
            logger.warning(f"Spam detected from {'Webhook' if is_webhook else 'Sender'} {sender_id} in #{channel.name}: {trigger_reason}")

            # A. Delete offending spam message
            try:
                await message.delete()
            except Exception as d_err:
                logger.debug(f"Could not delete spam message: {d_err}")

            # B. WEBHOOK SPAM (e.g. Spired Spammer): Destroy the webhook immediately
            if is_webhook:
                webhook_name = message.author.name
                try:
                    webhooks = await channel.webhooks()
                    for wh in webhooks:
                        if wh.id == message.webhook_id:
                            await wh.delete(reason=f"Epileptic Anti-Spam: Destroyed rogue spam webhook ({trigger_reason})")
                            logger.info(f"DESTROYED ROGUE WEBHOOK '{wh.name}' (ID: {wh.id}) in #{channel.name}")
                except Exception as wh_err:
                    logger.warning(f"Error destroying rogue webhook: {wh_err}")

                # Purge recent spam messages from this webhook in the channel
                try:
                    def is_offending_webhook_msg(m: discord.Message) -> bool:
                        if m.webhook_id == message.webhook_id:
                            return True
                        if "spired" in m.content.lower():
                            return True
                        for e in m.embeds:
                            if "spired" in (e.title or "").lower() or "spired" in (e.description or "").lower():
                                return True
                        return False

                    deleted = await channel.purge(limit=50, check=is_offending_webhook_msg)
                    logger.info(f"Purged {len(deleted)} spam messages from webhook in #{channel.name}")
                except Exception as p_err:
                    logger.debug(f"Error purging webhook messages: {p_err}")

                # Alert staff in mod-logs
                alert_embed = discord.Embed(
                    title="🚨 [SECURITY] Rogue Webhook Spam Destroyed",
                    description=(
                        f"**Channel:** {channel.mention}\n"
                        f"**Webhook:** `{webhook_name}` (ID: `{message.webhook_id}`)\n"
                        f"**Reason:** `{trigger_reason}`\n"
                        f"**Action Taken:** Webhook permanently deleted from channel, messages purged."
                    ),
                    color=config.EMBED_COLOR_ERROR
                )
                await send_mod_log(guild, alert_embed)
                return

            # C. MEMBER SPAM (Bot account or human user)
            if isinstance(message.author, discord.Member):
                member = message.author

                # If an unauthorized BOT account is spamming -> Ban it immediately
                if member.bot:
                    try:
                        await member.ban(
                            reason=f"Epileptic Anti-Spam: Rogue bot spamming ({trigger_reason})",
                            delete_message_days=1
                        )
                        logger.info(f"BANNED ROGUE BOT {member} ({member.id})")
                        alert_embed = discord.Embed(
                            title="🚨 [SECURITY] Rogue Bot Banned",
                            description=(
                                f"**Bot:** {member.mention} (`{member.id}`)\n"
                                f"**Channel:** {channel.mention}\n"
                                f"**Reason:** `{trigger_reason}`\n"
                                f"**Action Taken:** Bot permanently banned, recent messages purged."
                            ),
                            color=config.EMBED_COLOR_ERROR
                        )
                        await send_mod_log(guild, alert_embed)
                        return
                    except Exception as b_err:
                        logger.warning(f"Could not ban rogue bot {member}: {b_err}")

                # If human user -> Timeout for 1 hour
                try:
                    await member.timeout(
                        datetime.now(timezone.utc) + timedelta(hours=1),
                        reason=f"Epileptic Anti-Spam: {trigger_reason}"
                    )
                    logger.info(f"Timed out spammer {member} ({member.id}) for 1 hour.")
                except Exception as t_err:
                    logger.debug(f"Could not timeout member: {t_err}")

                # Purge recent messages from this member
                try:
                    deleted = await channel.purge(limit=30, check=lambda m: m.author.id == member.id)
                    logger.info(f"Purged {len(deleted)} messages from spammer {member.id}")
                except Exception:
                    pass

                # Temporary warning in chat
                try:
                    warn = await channel.send(
                        f"🛡️ {member.mention} has been muted for spamming ({trigger_reason})."
                    )
                    await asyncio.sleep(6)
                    await warn.delete()
                except Exception:
                    pass

                alert_embed = discord.Embed(
                    title="🛡️ [SECURITY] Spammer Muted & Purged",
                    description=(
                        f"**User:** {member.mention} (`{member.id}`)\n"
                        f"**Channel:** {channel.mention}\n"
                        f"**Reason:** `{trigger_reason}`\n"
                        f"**Action Taken:** 1-hour timeout applied, recent messages purged."
                    ),
                    color=config.EMBED_COLOR_WARNING
                )
                await send_mod_log(guild, alert_embed)
                return

        # 5. Anti-Invite Link Filter (for non-flood messages)
        match = DISCORD_INVITE_REGEX.search(message.content)
        if match:
            try:
                await message.delete()
            except Exception:
                pass

            try:
                warn_msg = await channel.send(
                    f"⚠️ {message.author.mention}, posting Discord invite links is strictly prohibited by server rules!"
                )
                await asyncio.sleep(7)
                await warn_msg.delete()
            except Exception:
                pass

            log_embed = discord.Embed(
                title="🚫 [ANTI-INVITE] Invite Link Deleted",
                description=(
                    f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                    f"**Channel:** {channel.mention}\n"
                    f"**Detected Link:** `{match.group(0)}`\n"
                    f"**Message:** ```{message.content[:500]}```"
                ),
                color=config.EMBED_COLOR_ERROR
            )
            await send_mod_log(guild, log_embed)
            logger.info(f"Deleted unauthorized invite link from {message.author} in #{channel.name}")

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """Prevents thread creation in read-only / closed information channels."""
        parent = thread.parent
        if not parent or not isinstance(parent, discord.TextChannel):
            return

        guild = thread.guild
        if not guild:
            return

        creator = None
        if thread.owner_id:
            creator = guild.get_member(thread.owner_id)

        is_staff_creator = False
        if creator:
            is_staff_creator = (
                creator.id == guild.owner_id
                or creator.guild_permissions.administrator
                or any(r.name.lower() in config.STAFF_ROLE_NAMES for r in creator.roles)
            )

        if is_staff_creator:
            return

        read_only_keywords = [
            "rules", "правил", "announc", "объявлен", "welcome", "приветств",
            "access", "доступ", "faq", "инфо", "info"
        ]
        p_name = parent.name.lower()
        is_locked_channel = any(kw in p_name for kw in read_only_keywords)

        if not is_locked_channel:
            if parent.category and any(kw in parent.category.name.upper() for kw in ["INFO", "ИНФО"]):
                is_locked_channel = True
            else:
                ow = parent.overwrites_for(guild.default_role)
                if ow.send_messages is False:
                    is_locked_channel = True

        if is_locked_channel:
            thread_name = thread.name
            try:
                await thread.delete()
                logger.info(f"Auto-deleted unauthorized thread '{thread_name}' in #{parent.name}")
            except Exception as e:
                logger.warning(f"Failed to auto-delete thread '{thread_name}': {e}")
                return

            alert_embed = discord.Embed(
                title="🔒 [SECURITY] Unauthorized Thread Deleted",
                description=(
                    f"**Channel:** {parent.mention}\n"
                    f"**Thread:** `{thread_name}`\n"
                    f"**User:** {creator.mention if creator else f'ID: {thread.owner_id}'}\n"
                    f"**Action:** Thread was automatically deleted (threads forbidden in read-only channels)."
                ),
                color=config.EMBED_COLOR_WARNING
            )
            await send_mod_log(guild, alert_embed)

            if creator and not creator.bot:
                try:
                    await creator.send(
                        f"⚠️ Creating threads in {parent.mention} is disabled.\n"
                        f"Please ask your question in our community chat or open a support ticket in **#support-tickets**."
                    )
                except Exception:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(SecurityCog(bot))

