import logging
import discord
from discord import app_commands
from discord.ext import commands
import config
from cogs.security import is_staff, send_mod_log

logger = logging.getLogger("epileptic.broadcast")

COLOR_MAP = {
    "purple": config.RULES_EMBED_COLOR,     # 0xA855F7
    "gold": 0xFEE75C,                       # Yellow / Gold
    "green": 0x57F287,                      # Emerald Green
    "red": 0xED4245,                        # Crimson Red
    "blue": 0x5865F2,                       # Discord Blurple
    "cyan": 0x00F0FF,                       # Cyber Cyan
    "dark": 0x2B2D31                        # Dark Minimal
}


class RichPostModal(discord.ui.Modal, title="Create Custom Community Post"):
    """Интерактивное модальное окно Discord для создания красивых постов."""

    post_title = discord.ui.TextInput(
        label="Post Title",
        placeholder="e.g. 🚀 New Jailbreak Released: Muse Spark 1.3",
        required=False,
        max_length=256
    )

    post_content = discord.ui.TextInput(
        label="Content (Supports **bold**, *italic*, lists)",
        style=discord.TextStyle.paragraph,
        placeholder="Write your post content here using standard Discord markdown...",
        required=True,
        max_length=4000
    )

    image_url = discord.ui.TextInput(
        label="Banner Image URL (optional)",
        placeholder="https://example.com/banner.png",
        required=False,
        max_length=512
    )

    def __init__(self, target_channel: discord.TextChannel, color_hex: int, mention_role: str):
        super().__init__()
        self.target_channel = target_channel
        self.color_hex = color_hex
        self.mention_role = mention_role

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            description=self.post_content.value,
            color=self.color_hex
        )
        if self.post_title.value.strip():
            embed.title = self.post_title.value.strip()

        if self.image_url.value.strip():
            embed.set_image(url=self.image_url.value.strip())

        embed.set_footer(
            text=f"Posted by {interaction.user.display_name} • Epileptic Community",
            icon_url=interaction.user.display_avatar.url
        )

        content_mention = None
        if self.mention_role == "everyone":
            content_mention = "@everyone"
        elif self.mention_role == "here":
            content_mention = "@here"
        elif self.mention_role == "member":
            m_role = discord.utils.find(lambda r: r.name.lower() == config.MEMBER_ROLE_NAME.lower(), interaction.guild.roles)
            content_mention = m_role.mention if m_role else None
        elif self.mention_role == "premium":
            p_role = discord.utils.find(lambda r: r.name.lower() == config.PREMIUM_ROLE_NAME.lower(), interaction.guild.roles)
            content_mention = p_role.mention if p_role else None

        try:
            sent_msg = await self.target_channel.send(content=content_mention, embed=embed)
            await interaction.followup.send(
                f"✅ Post successfully published to {self.target_channel.mention}! [View Message]({sent_msg.jump_url})",
                ephemeral=True
            )

            # Аудит в mod-logs
            log_embed = discord.Embed(
                title="📢 [AUDIT] Custom Post Published",
                description=(
                    f"**Author:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                    f"**Channel:** {self.target_channel.mention}\n"
                    f"**Title:** {self.post_title.value or 'None'}\n"
                    f"**Mention:** `{self.mention_role}`"
                ),
                color=self.color_hex
            )
            await send_mod_log(interaction.guild, log_embed)

        except Exception as e:
            logger.exception(f"Failed to post custom message: {e}")
            await interaction.followup.send(f"❌ Failed to publish post: `{e}`", ephemeral=True)


class BroadcastCog(commands.Cog, name="Post Broadcaster"):
    """Инструмент для создания красивых форматированных постов в любые каналы."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="post_builder",
        description="Open rich post builder modal to publish styled embeds in any channel."
    )
    @app_commands.describe(
        channel="Target channel to publish into",
        color="Theme color accent for the embed plate",
        ping="Role or audience to mention"
    )
    @app_commands.choices(
        color=[
            app_commands.Choice(name="🟣 Purple (Community Signature)", value="purple"),
            app_commands.Choice(name="🟡 Gold (Premium VIP)", value="gold"),
            app_commands.Choice(name="🟢 Green (Update / Success)", value="green"),
            app_commands.Choice(name="🔴 Red (Important / Alert)", value="red"),
            app_commands.Choice(name="🔵 Blurple (Info)", value="blue"),
            app_commands.Choice(name="🌐 Cyan (Cyber)", value="cyan"),
            app_commands.Choice(name="⚫ Dark Minimal", value="dark")
        ],
        ping=[
            app_commands.Choice(name="No mention", value="none"),
            app_commands.Choice(name="@everyone", value="everyone"),
            app_commands.Choice(name="@here", value="here"),
            app_commands.Choice(name="@Member", value="member"),
            app_commands.Choice(name="@Premium Member", value="premium")
        ]
    )
    @is_staff()
    async def post_builder(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        color: app_commands.Choice[str] = None,
        ping: app_commands.Choice[str] = None
    ):
        chosen_color = COLOR_MAP.get(color.value if color else "purple", config.RULES_EMBED_COLOR)
        chosen_ping = ping.value if ping else "none"

        modal = RichPostModal(
            target_channel=channel,
            color_hex=chosen_color,
            mention_role=chosen_ping
        )
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="post_quick",
        description="Quickly post a formatted embed message with title and description in one command."
    )
    @app_commands.describe(
        channel="Target channel",
        title="Post title",
        description="Formatted message content (supports markdown)",
        color="Color accent (e.g. purple, gold, green, red, blue)",
        banner_url="Optional banner image URL"
    )
    @is_staff()
    async def post_quick(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        description: str,
        color: str = "purple",
        banner_url: str = None
    ):
        hex_color = COLOR_MAP.get(color.lower(), config.RULES_EMBED_COLOR)

        embed = discord.Embed(
            title=title,
            description=description.replace("\\n", "\n"),
            color=hex_color
        )
        if banner_url:
            embed.set_image(url=banner_url)

        embed.set_footer(
            text=f"Posted by {interaction.user.display_name} • Epileptic Community",
            icon_url=interaction.user.display_avatar.url
        )

        msg = await channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Message sent to {channel.mention}: [View Message]({msg.jump_url})",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BroadcastCog(bot))
