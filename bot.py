import os
import sys
import asyncio
import logging
from pathlib import Path
import discord
from discord.ext import commands
import uvicorn

# Fix Windows console UTF-8 stream encoding for clean emoji output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config
from cogs.verification import PersistentVerificationView
from cogs.tickets import TicketLaunchView, TicketControlView
from web.server import app as web_app

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("epileptic.main")


class EpilepticBot(commands.Bot):
    """Core Epileptic Community Discord Bot."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True          # Required for join tracking and auto-roles
        intents.message_content = True  # Required for message content / commands
        intents.guilds = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        """Pre-connection initialization hook."""
        logger.info("Registering persistent UI views...")
        self.add_view(PersistentVerificationView())
        self.add_view(TicketLaunchView())
        self.add_view(TicketControlView())

        # Load Cogs
        initial_extensions = [
            "cogs.security",
            "cogs.verification",
            "cogs.tickets",
            "cogs.setup_server",
            "cogs.moderation"
        ]

        for ext in initial_extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.exception(f"Failed to load extension {ext}: {e}")

        # Synchronize Application Slash Commands
        try:
            if config.GUILD_ID:
                guild_obj = discord.Object(id=config.GUILD_ID)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                logger.info(f"Synchronized {len(synced)} slash commands for guild {config.GUILD_ID}.")
            else:
                synced = await self.tree.sync()
                logger.info(f"Globally synchronized {len(synced)} slash commands.")
        except Exception as e:
            logger.warning(f"Initial command sync warning: {e}")

    async def on_ready(self):
        """Gateway ready event."""
        logger.info("==================================================")
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s).")
        logger.info(f"Gateway Latency: {round(self.latency * 1000, 1)} ms")
        logger.info("==================================================")

        # Clean online status without custom activity text
        await self.change_presence(status=discord.Status.online, activity=None)


def is_valid_token(token: str) -> bool:
    """Validates that token is not an empty template string."""
    if not token:
        return False
    token = token.strip()
    if token in ("YOUR_BOT_TOKEN_HERE", "ВСТАВЬТЕ_СЮДА_ТОКЕН_БОТА"):
        return False
    if "ТОКЕН" in token or "TOKEN" in token or len(token) < 25:
        return False
    return True


async def run_bot_and_web():
    """Starts Discord bot and Web Dashboard concurrently."""
    token = config.DISCORD_TOKEN.strip()
    has_token = is_valid_token(token)

    bot = EpilepticBot()
    web_app.state.bot = bot

    tasks = []

    # Web Dashboard Task
    if config.WEB_ENABLED:
        uvi_config = uvicorn.Config(
            app=web_app,
            host=config.WEB_HOST,
            port=config.WEB_PORT,
            log_level="warning",
            access_log=False
        )
        server = uvicorn.Server(uvi_config)
        logger.info(f"[Web Dashboard] Live at: http://localhost:{config.WEB_PORT}")
        tasks.append(asyncio.create_task(server.serve()))

    # Discord Bot Task
    if has_token:
        async def start_bot():
            try:
                async with bot:
                    await bot.start(token)
            except discord.LoginFailure:
                logger.error("❌ Authentication failure: Invalid Discord bot token in .env!")
                print("\n[ERROR] Check DISCORD_TOKEN in .env — Discord rejected the token.\n")
            except Exception as e:
                logger.exception(f"Fatal error while running bot: {e}")

        tasks.append(asyncio.create_task(start_bot()))
    else:
        logger.warning(
            "[Notice] Discord token is not configured or is a placeholder in .env!\n"
            "Open .env and set your real DISCORD_TOKEN to connect the bot to Discord."
        )

    if tasks:
        await asyncio.gather(*tasks)


def main():
    try:
        asyncio.run(run_bot_and_web())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution terminated by user.")


if __name__ == "__main__":
    main()
