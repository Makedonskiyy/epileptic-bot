# 🛡️ Epileptic Discord Bot (Security Reinforced)

A robust, English-first Discord community administration bot built with Python (**discord.py 2.x**), an authenticated Web Dashboard (**FastAPI**), automated channel permission isolation, and layered anti-abuse / anti-raid security guards.

---

## 🌟 Key Features

1. **Automated Verification System**:
   - New members immediately receive the `@Not Verified` role upon joining.
   - Non-verified users can only view the **INFORMATION** category (`📜・rules`, `📢・announcements`, `👋・welcome`, `⚡・get-access`) and cannot send messages.
   - Posts a clean rules embed with a persistent **«Accept Rules & Get Access»** button (and fallback `✅` reaction support).
   - Upon verification: grants `@Member` role, strips `@Not Verified`, unlocks the community channels, and audits the event to `📊・mod-logs`.

2. **Multi-Layer Anti-Abuse & Anti-Raid Protection**:
   - 🛡️ **Account Age Filter (`MIN_ACCOUNT_AGE_HOURS=24`)**: Blocks freshly created throwaway alt/raid accounts from verifying automatically. Young accounts are notified and logged in `#mod-logs`.
   - ⏳ **Interaction Rate Limiting (`VERIFY_COOLDOWN_SECONDS=10`)**: Enforces per-user cooldowns to prevent event loop starvation and Discord API spamming.
   - 🚨 **Join Flood / Anti-Raid Guard**: Detects rapid bursts of member joins and sounds an emergency alert in `📊・mod-logs`.
   - 🔒 **Staff Privilege Guard (`@is_staff()`)**: Double-checks administrative commands on the bot side against `Owner`, `Administrator`, and `Moderator` roles, preventing permission bypasses.
   - 📊 **Audit Logging**: Logs verifications, role syncs, purges, and security events to `📊・mod-logs`.

3. **Secure Web Control Dashboard (Port 8080)**:
   - Protected by timing-safe session authentication (`admin` / `epileptic_admin_2026`).
   - Unauthorized POST actions and dashboard views are blocked (HTTP 401).
   - Real-time member statistics, bot gateway latency, and one-click rules dispatch.

4. **One-Click Server Configuration**:
   - `/setup_permissions` — automatically configures channel overwrites for INFORMATION, COMMUNITY, RESOURCES, PREMIUM, LOUNGE, SUPPORT, and STAFF.
   - `/post_verification` — dispatches the rules embed and interactive verification button.
   - `/assign_unverified_all` — bulk-assigns `@Not Verified` to members who don't have `@Member` yet.
   - `/purge` — cleans up messages with audit logging.
   - `/serverinfo` — server statistics overview.

---

## 📋 Step 1: Discord Developer Portal Setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, name it **Epileptic**, and click **Create**.
3. **App Avatar**:
   - Under **General Information**, upload an avatar (assets are available in `upload/styles/Detroit/images/`).
4. **Bot Configuration**:
   - Go to the **Bot** tab.
   - Click **Reset Token** and copy the token into your `.env` file (`DISCORD_TOKEN`).
   - Scroll down to **Privileged Gateway Intents** and enable:
     - ✅ **SERVER MEMBERS INTENT** (Mandatory for tracking joins and role assignments).
     - ✅ **MESSAGE CONTENT INTENT** (Mandatory for command processing).
   - Click **Save Changes**.
5. **Invite the Bot to your Server**:
   - Go to **OAuth2 -> URL Generator**.
   - Check `bot` and `applications.commands`.
   - Under **Bot Permissions**, select `Administrator` (or *Manage Roles, Manage Channels, View Channels, Send Messages, Embed Links*).
   - Open the generated URL and invite the bot to your server.

---

## ⚠️ CRITICAL: Role Hierarchy Setup

For the bot to assign and remove roles:
1. Open Discord: **Server Settings -> Roles**.
2. Drag the **Epileptic** role **ABOVE** the `Member` and `Not Verified` roles (ideally right under `Administrator` or `Owner`).
*(Discord forbids bots from managing roles placed higher than their own top role).*

---

## ⚙️ Configuration (.env)

Edit the `.env` file in the project directory:
```env
# Discord Token
DISCORD_TOKEN=your_real_bot_token_here

# Optional: Guild ID for instant command sync
GUILD_ID=

# Server Role Names (matches your server)
UNVERIFIED_ROLE_NAME=Not Verified
MEMBER_ROLE_NAME=Member
PREMIUM_ROLE_NAME=Premium Member
AI_CONTRIBUTOR_ROLE_NAME=AI Contributor
STAFF_ROLE_NAMES=Owner,Administrator,Moderator,admin,staff

# Security Controls
MIN_ACCOUNT_AGE_HOURS=24
VERIFY_COOLDOWN_SECONDS=10
ANTI_RAID_JOIN_THRESHOLD=10
ANTI_RAID_WINDOW_SECONDS=15

# Web Dashboard Login
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_USERNAME=admin
WEB_PASSWORD=epileptic_admin_2026
WEB_SECRET=epileptic_secret_change_me_super_secure
```

---

## 💻 Local Launch (Windows / macOS)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the bot:
   ```bash
   python bot.py
   ```
3. Access the dashboard:
   Open `http://localhost:8080` and log in with your credentials (`admin` / `epileptic_admin_2026`).

---

## 🚀 Ubuntu VPS 24/7 Deployment

1. Transfer the project files to your VPS.
2. Run the automated installer:
   ```bash
   chmod +x deploy/setup_vps.sh
   sudo ./deploy/setup_vps.sh
   ```
3. Edit your token in `/opt/epileptic-bot/.env`:
   ```bash
   sudo nano /opt/epileptic-bot/.env
   ```
4. Restart the service:
   ```bash
   sudo systemctl restart epileptic.service
   ```
5. Check status & logs:
   ```bash
   sudo systemctl status epileptic.service
   sudo journalctl -u epileptic.service -f
   ```

---

## 🛠️ Discord First-Time Setup

1. Run `/setup_permissions` to lock and unlock categories appropriately.
2. Run `/post_verification` in your rules channel (`📜・rules`).
3. If you have existing unverified members, run `/assign_unverified_all`.
