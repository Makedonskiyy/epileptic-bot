import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Discord Bot Core Settings
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") and os.getenv("GUILD_ID").isdigit() else None

# Exact Role Names from your server
UNVERIFIED_ROLE_NAME = os.getenv("UNVERIFIED_ROLE_NAME", "Not Verified").strip()
MEMBER_ROLE_NAME = os.getenv("MEMBER_ROLE_NAME", "Member").strip()
PREMIUM_ROLE_NAME = os.getenv("PREMIUM_ROLE_NAME", "Premium Member").strip()
AI_CONTRIBUTOR_ROLE_NAME = os.getenv("AI_CONTRIBUTOR_ROLE_NAME", "AI Contributor").strip()

# Staff roles
_staff_raw = os.getenv("STAFF_ROLE_NAMES", "Owner,Administrator,Moderator,admin,staff")
STAFF_ROLE_NAMES = [name.strip().lower() for name in _staff_raw.split(",") if name.strip()]

# Role Aliases for resilient matching
ROLE_ALIASES = {
    "unverified": ["not verified", "unverified", "not-verified", "guest"],
    "member": ["member", "members", "verified"],
    "premium": ["premium member", "premium", "vip", "supporter"],
    "staff": ["owner", "administrator", "moderator", "admin", "staff"]
}

# Security & Anti-Abuse Settings
MIN_ACCOUNT_AGE_HOURS = int(os.getenv("MIN_ACCOUNT_AGE_HOURS", "24")) # Minimum Discord account age to self-verify (0 to disable)
VERIFY_COOLDOWN_SECONDS = int(os.getenv("VERIFY_COOLDOWN_SECONDS", "10")) # Cooldown between verification clicks per user
ANTI_RAID_JOIN_THRESHOLD = int(os.getenv("ANTI_RAID_JOIN_THRESHOLD", "10")) # Number of joins in window to trigger raid alert
ANTI_RAID_WINDOW_SECONDS = int(os.getenv("ANTI_RAID_WINDOW_SECONDS", "15"))

# Web Dashboard Settings & Authentication
WEB_ENABLED = os.getenv("WEB_ENABLED", "true").lower() in ("true", "1", "yes")
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "epileptic_admin_2026")
WEB_SECRET = os.getenv("WEB_SECRET", "epileptic_secret_change_me_super_secure")

# Embed Colors
EMBED_COLOR_DEFAULT = 0x5865F2    # Blurple
EMBED_COLOR_SUCCESS = 0x57F287    # Green
EMBED_COLOR_WARNING = 0xFEE75C    # Yellow
EMBED_COLOR_ERROR = 0xED4245      # Red
EMBED_COLOR_PREMIUM = 0xFEE75C    # Gold

# Verification Embed & Button Settings (English)
VERIFY_BUTTON_LABEL = "Accept Rules & Get Access"
VERIFY_BUTTON_EMOJI = "✅"
VERIFY_CUSTOM_ID = "epileptic:persistent:verify_button"

DEFAULT_VERIFICATION_TITLE = "📜 Server Rules & Verification"
DEFAULT_VERIFICATION_DESCRIPTION = (
    "Welcome to the **Epileptic** Community!\n\n"
    "To access all public community channels, resources, and chats, please review and agree to our guidelines:\n\n"
    "**1. Respect Everyone:** Treat fellow members and staff with dignity and courtesy.\n"
    "**2. No Spam or Flooding:** Keep chats readable. Self-promotion and mass mentions are prohibited.\n"
    "**3. Stay on Topic:** Post questions and content in the appropriate channels.\n"
    "**4. Safety & Security:** Do not share malicious files, harmful links, or unauthorized advertisements.\n\n"
    "Click the green **«Accept Rules & Get Access»** button below or react with ✅ to receive the **Member** role!"
)

# Server Categories and Channel Structure
SERVER_STRUCTURE = {
    "INFORMATION": {
        "access": "info",
        "channels": [
            {"name": "📜・rules", "type": "text"},
            {"name": "📢・announcements", "type": "text"},
            {"name": "👋・welcome", "type": "text"},
            {"name": "⚡・get-access", "type": "text"}
        ]
    },
    "COMMUNITY": {
        "access": "member",
        "channels": [
            {"name": "💬・general", "type": "text"},
            {"name": "💬・general-ru", "type": "text"},
            {"name": "😂・off-topic", "type": "text"},
            {"name": "💡・ideas-feedback", "type": "text"}
        ]
    },
    "RESOURCES": {
        "access": "member",
        "channels": [
            {"name": "📄・jailbreak", "type": "text"},
            {"name": "🔗・prompts-library", "type": "text"},
            {"name": "💾・software-tools", "type": "text"},
            {"name": "📚・tutorials", "type": "text"},
            {"name": "🎯・best-practices", "type": "text"},
            {"name": "🔍・prompt-engineering", "type": "text"},
            {"name": "📰・ai-news", "type": "text"}
        ]
    },
    "PREMIUM": {
        "access": "premium",
        "channels": [
            {"name": "💎・premium-prompts", "type": "text"},
            {"name": "🔐・exclusive-tools", "type": "text"},
            {"name": "⭐・vip-resources", "type": "text"},
            {"name": "🎁・member-benefits", "type": "text"}
        ]
    },
    "LOUNGE": {
        "access": "member",
        "channels": [
            {"name": "🎵・music-lounge", "type": "text"},
            {"name": "🔊・live-stream", "type": "voice"}
        ]
    },
    "SUPPORT": {
        "access": "support",
        "channels": [
            {"name": "🎫・support-tickets", "type": "text"},
            {"name": "❓・faq", "type": "text"},
            {"name": "📋・feedback", "type": "text"}
        ]
    },
    "STAFF": {
        "access": "staff",
        "channels": [
            {"name": "💪・staff-chat", "type": "text"},
            {"name": "📊・mod-logs", "type": "text"},
            {"name": "🔊・staff-voice", "type": "voice"}
        ]
    }
}
