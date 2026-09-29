import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.security import is_staff, send_mod_log
from cogs.ticket_transcript import generate_ticket_transcripts

logger = logging.getLogger("epileptic.tickets")


async def execute_ticket_close(channel: discord.TextChannel, closed_by: discord.User | discord.Member, client: discord.Client):
    """Generates a single .txt transcript, delivers to mod-logs, and deletes the ticket channel."""
    guild = channel.guild

    # 1. Fetch conversation history
    messages = [msg async for msg in channel.history(limit=1000, oldest_first=True)]

    # 2. Detect ticket owner from channel topic
    owner = None
    owner_id = None
    topic = channel.topic or ""
    for part in topic.split():
        if part.isdigit() and len(part) >= 17:
            owner_id = int(part)
            break
    if owner_id:
        try:
            owner = guild.get_member(owner_id) or await client.fetch_user(owner_id)
        except Exception:
            pass

    # 3. Generate plain text transcript only (.txt)
    _, txt_buf = generate_ticket_transcripts(guild, channel, messages, closed_by, owner)
    filename_txt = f"transcript-{channel.name}.txt"
    txt_file = discord.File(fp=txt_buf, filename=filename_txt)

    # 4. Send Transcript to mod-logs channel (Single compact message with .txt file)
    log_embed = discord.Embed(
        title="🎫 Support Ticket Closed",
        description=(
            f"**Channel:** `#{channel.name}`\n"
            f"**Ticket Creator:** {owner.mention if owner else 'Unknown'} (`{owner_id or 'N/A'}`)\n"
            f"**Closed By:** {closed_by.mention} (`{closed_by.id}`)\n"
            f"**Total Messages:** `{len(messages)}`"
        ),
        color=config.EMBED_COLOR_DEFAULT
    )
    log_embed.set_footer(text="Transcript attached (.txt)")

    log_channel = discord.utils.find(
        lambda c: any(kw in c.name.lower() for kw in ["mod-logs", "mod_logs", "logs", "audit", "transcripts"]),
        guild.text_channels
    )
    if log_channel:
        try:
            await log_channel.send(embed=log_embed, file=txt_file)
            logger.info(f"Delivered ticket transcript (.txt) for #{channel.name} to #{log_channel.name}.")
        except Exception as e:
            logger.warning(f"Could not send ticket transcript to mod-logs: {e}")

    # 5. Send single .txt transcript to Ticket Creator in DM if open
    if owner:
        try:
            txt_buf.seek(0)
            dm_txt_file = discord.File(fp=txt_buf, filename=filename_txt)
            dm_embed = discord.Embed(
                title="🎫 Your Support Ticket has been Closed",
                description=(
                    f"Hello **{owner.display_name}**,\n\n"
                    f"Your support ticket **#{channel.name}** on **{guild.name}** has been closed by {closed_by.mention}.\n\n"
                    f"A transcript (.txt) of the ticket is attached below."
                ),
                color=config.RULES_EMBED_COLOR
            )
            if guild.icon:
                dm_embed.set_thumbnail(url=guild.icon.url)
            dm_embed.set_footer(text="Epileptic Community Support Desk")
            await owner.send(embed=dm_embed, file=dm_txt_file)
            logger.info(f"Delivered ticket transcript DM to {owner}.")
        except Exception:
            logger.info(f"Could not send ticket transcript DM to {owner} (DMs closed).")

    # 6. Clean channel deletion
    await asyncio.sleep(1)
    try:
        await channel.delete(reason=f"Ticket closed by {closed_by} (transcript saved)")
    except Exception as e:
        logger.error(f"Failed to delete ticket channel #{channel.name}: {e}")


class TicketControlView(discord.ui.View):
    """Панель управления внутри открытого тикета (Persistent View)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="epileptic:persistent:ticket_close"
    )
    async def close_ticket_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        guild = interaction.guild

        if not guild or not channel or not channel.name.startswith("ticket-"):
            await interaction.response.send_message("This command can only be used inside an active ticket channel.", ephemeral=True)
            return

        # Проверка прав: закрыть может создатель тикета или любой сотрудник стаффа
        is_staff_member = (
            interaction.user.id == guild.owner_id
            or interaction.user.guild_permissions.administrator
            or any(r.name.lower() in config.STAFF_ROLE_NAMES for r in interaction.user.roles)
        )
        is_owner = str(interaction.user.id) in (channel.topic or "")

        if not is_staff_member and not is_owner:
            await interaction.response.send_message("⛔ Only staff or the ticket creator can close this ticket.", ephemeral=True)
            return

        await interaction.response.defer()
        await execute_ticket_close(channel, interaction.user, interaction.client)


class TicketLaunchView(discord.ui.View):
    """Панель с кнопкой создания тикета в канале #support-tickets (Persistent View)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Support Ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="epileptic:persistent:ticket_open"
    )
    async def open_ticket_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        if not guild:
            return

        # 1. Проверяем, нет ли уже открытого тикета у пользователя
        existing_ticket = discord.utils.find(
            lambda c: c.name.startswith("ticket-") and str(user.id) in (c.topic or ""),
            guild.text_channels
        )
        if existing_ticket:
            await interaction.response.send_message(
                f"⚠️ You already have an active ticket open: {existing_ticket.mention}",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # 2. Находим категорию SUPPORT
        support_category = discord.utils.find(
            lambda c: "SUPPORT" in c.name.upper() or "САППОРТ" in c.name.upper(),
            guild.categories
        )
        if not support_category and interaction.channel.category:
            support_category = interaction.channel.category

        # 3. Настраиваем приватные права доступа для тикета
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )
        }

        # Выдаем доступ всем сотрудникам стаффа
        for role in guild.roles:
            r_name = role.name.lower()
            if r_name in config.STAFF_ROLE_NAMES or role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                    manage_messages=True
                )

        clean_username = "".join(c for c in user.name.lower() if c.isalnum() or c in "-_")[:14]
        channel_name = f"ticket-{clean_username}"

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=support_category,
                overwrites=overwrites,
                topic=f"Ticket Owner: {user.id} | Opened by {user} ({user.id})",
                reason=f"Support ticket opened by {user}"
            )

            # Приветственное сообщение внутри тикета
            welcome_embed = discord.Embed(
                title=f"🎫 Support Ticket — {user.display_name}",
                description=(
                    f"Hello {user.mention}, welcome to your private support channel!\n\n"
                    f"Staff has been notified. Please describe your issue, question, or inquiry below:\n"
                    f"• **General Support:** Ask any questions regarding the server or community.\n"
                    f"• **Premium Access:** Inquire about purchasing or activating **Premium Member** access.\n"
                    f"• **Feedback:** Share constructive feedback with the management team.\n\n"
                    f"To close this ticket when finished, click the **Close Ticket** button below."
                ),
                color=config.RULES_EMBED_COLOR
            )
            welcome_embed.set_thumbnail(url=user.display_avatar.url)
            welcome_embed.set_footer(text="Epileptic Support Desk • Confidential")

            # Упоминаем стафф для быстрого ответа
            staff_mentions = []
            for r in guild.roles:
                if r.name.lower() in ("owner", "administrator", "moderator"):
                    staff_mentions.append(r.mention)
            mention_line = " ".join(staff_mentions) if staff_mentions else "Staff Team"

            control_view = TicketControlView()
            await ticket_channel.send(
                content=f"{user.mention} | {mention_line}",
                embed=welcome_embed,
                view=control_view
            )

            await interaction.followup.send(
                f"✅ Your ticket has been created: {ticket_channel.mention}",
                ephemeral=True
            )

        except Exception as e:
            logger.exception(f"Failed to create ticket for {user}: {e}")
            await interaction.followup.send(f"❌ Failed to create ticket channel: `{e}`", ephemeral=True)


class TicketsCog(commands.Cog, name="Tickets"):
    """Модуль тикетов поддержки."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="post_ticket_panel",
        description="Publish the ticket creation panel in #support-tickets."
    )
    @app_commands.describe(channel="Target channel (defaults to #support-tickets or current channel)")
    @is_staff()
    async def post_ticket_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_ch = channel
        if not target_ch:
            target_ch = discord.utils.find(
                lambda c: "ticket" in c.name.lower() or "support" in c.name.lower(),
                interaction.guild.text_channels
            ) or interaction.channel

        embed = discord.Embed(
            title="🎫 Community Support & Assistance",
            description=(
                "Need help, have a question, or looking to unlock **Premium Member** access?\n\n"
                "Click the button below to open a private 1-on-1 support ticket with our staff team.\n\n"
                "📌 **Topics handled:**\n"
                "• Account and role assistance\n"
                "• Premium access & subscriptions\n"
                "• Community feedback & suggestions\n"
                "• Reporting issues or rule violations"
            ),
            color=config.RULES_EMBED_COLOR
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text="Click below to open a ticket", icon_url=interaction.client.user.display_avatar.url)

        view = TicketLaunchView()
        await target_ch.send(embed=embed, view=view)

        await interaction.response.send_message(
            f"✅ Ticket panel published to {target_ch.mention}!",
            ephemeral=True
        )

    @app_commands.command(
        name="close_ticket",
        description="Close the current ticket, save full transcripts (HTML & TXT), and archive it."
    )
    async def close_ticket(self, interaction: discord.Interaction):
        """Allows staff or the ticket creator to close the ticket and generate transcripts."""
        channel = interaction.channel
        guild = interaction.guild

        if not guild or not channel or not channel.name.startswith("ticket-"):
            await interaction.response.send_message("This command can only be used inside an active ticket channel.", ephemeral=True)
            return

        is_staff_member = (
            interaction.user.id == guild.owner_id
            or interaction.user.guild_permissions.administrator
            or any(r.name.lower() in config.STAFF_ROLE_NAMES for r in interaction.user.roles)
        )
        is_owner = str(interaction.user.id) in (channel.topic or "")

        if not is_staff_member and not is_owner:
            await interaction.response.send_message("⛔ Only staff or the ticket creator can close this ticket.", ephemeral=True)
            return

        await interaction.response.defer()
        await execute_ticket_close(channel, interaction.user, interaction.client)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
