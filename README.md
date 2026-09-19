# 🛡️ Epileptic Discord Community Bot

An advanced, English-first Discord community management & security bot built with Python (**discord.py 2.x**), featuring an authenticated Web Control Dashboard (**FastAPI**), automated category permission isolation, interactive verification, a private support ticket desk, and layered anti-abuse / anti-raid protection.

---

## 📁 Project Architecture & Components Map

| Directory / File | Component | Description |
| :--- | :--- | :--- |
| [`bot.py`](file:///d:/ds%20bot/bot.py) | **Core Engine** | Main entrypoint. Initializes Discord intents, registers persistent interactive Views (survives reboots), registers slash commands, and runs both Discord Bot and FastAPI Web Server concurrently in asyncio. |
| [`config.py`](file:///d:/ds%20bot/config.py) | **Central Config** | Holds all server role configurations (`Not Verified`, `Member`, `Premium Member`), exact rules text, category mappings, colors, and security limits. |
| [`cogs/verification.py`](file:///d:/ds%20bot/cogs/verification.py) | **Verification & Welcome** | Manages member onboarding: auto-assigns `@Not Verified` on join, posts dynamic welcome in `👋・welcome`, listens for `✅` reaction clicks, verifies account age, assigns `@Member`, and strips `@Not Verified`. |
| [`cogs/tickets.py`](file:///d:/ds%20bot/cogs/tickets.py) | **Support Desk** | Handles private 1-on-1 support tickets in `SUPPORT`: button to create ticket, sets private channel overwrites (User + Staff), embeds greeting, limits 1 ticket per user, and provides a 5-second countdown `🔒 Close Ticket` button. |
| [`cogs/security.py`](file:///d:/ds%20bot/cogs/security.py) | **Anti-Abuse Guard** | Multi-layer protection: **Anti-Invite link filter** (auto-deletes external Discord invites from non-staff), **Anti-Raid join flood monitor**, **Account age filter** (blocks throwaway bots), and role security decorators (`@is_owner()`, `@is_staff()`). |
| [`cogs/setup_server.py`](file:///d:/ds%20bot/cogs/setup_server.py) | **Architecture Setup** | Owner-only command suite to configure category permissions, channel overrides, and bulk unverified member synchronization. |
| [`cogs/moderation.py`](file:///d:/ds%20bot/cogs/moderation.py) | **Moderation & Stats** | Staff commands: `/purge` (bulk message cleanup with audit logging) and `/serverinfo` (live member & role breakdown). |
| [`web/server.py`](file:///d:/ds%20bot/web/server.py) | **Web Dashboard API** | FastAPI web server on port `8080` with timing-safe login authentication, CSRF/session cookies, server stats, and remote rules dispatch. |
| [`web/templates/`](file:///d:/ds%20bot/web/templates/) | **Dashboard UI** | Modern dark-themed dashboard (`index.html`) and login screen (`login.html`) built with Tailwind CSS and FontAwesome. |
| [`deploy/`](file:///d:/ds%20bot/deploy/) | **VPS Deployment** | Systemd unit configuration (`epileptic.service`), automated bash installer (`setup_vps.sh`), and Docker setup. |

---

## 📜 Complete Command Reference

| Slash Command | Access Level | Recommended Channel | What It Does & How to Use |
| :--- | :--- | :--- | :--- |
| **`/setup_permissions`** | 👑 **Owner Only** | Any staff / admin channel | Automatically isolates all categories (**INFORMATION**, **COMMUNITY**, **RESOURCES**, **PREMIUM**, **LOUNGE**, **SUPPORT**, **STAFF**). Configures `@everyone`, `@Not Verified`, `@Member`, `@Premium Member`, and Staff overwrites in 1 click. |
| **`/post_verification`** | 🛡️ **Staff / Owner** | `📜・rules` | Posts the 12 official server rules in a sleek purple embed and automatically adds the **`✅` reaction**. Users click `✅` to verify. Option `with_button: True` also adds a green UI button if desired. |
| **`/post_ticket_panel`** | 🛡️ **Staff / Owner** | `🎫・support-tickets` | Publishes the persistent **«🎫 Open Support Ticket»** panel. When clicked, creates a private channel (e.g. `#ticket-username`) visible only to that member and staff. |
| **`/assign_unverified_all`** | 👑 **Owner Only** | Any staff channel | Scans the server and assigns `@Not Verified` to any existing members who do not currently possess `@Member` or Staff roles. Ideal for server setup synchronization. |
| **`/purge <amount>`** | 🛡️ **Staff / Owner** | Any text channel | Bulk deletes `1-100` recent messages in the channel and sends an audit log to `📊・mod-logs`. |
| **`/serverinfo`** | 👥 **Everyone** | Any text channel | Displays a live summary: owner, total member count, and breakdown of `@Not Verified`, `@Member`, and `@Premium Member` roles. |

---

## 🔒 Security & Anti-Abuse Systems

1. **Owner-Only Guard (`@is_owner()`)**:
   - Critical server structure commands (`/setup_permissions`, `/assign_unverified_all`) are strictly locked to the **Server Owner**. Even administrators or rogue bots cannot trigger them.
2. **Anti-Invite Link Filter**:
   - Automatically detects and deletes unauthorized Discord server invites (`discord.gg/...`, `discord.com/invite/...`) sent by regular members.
   - Posts a 7-second self-destructing warning in chat and logs the infraction to `📊・mod-logs`.
   - Staff members are exempt and can post links freely.
3. **Anti-Alt Account Age Guard (`MIN_ACCOUNT_AGE_HOURS=24`)**:
   - Accounts younger than 24 hours cannot instantly self-verify. This prevents raid bots from creating throwaways to bypass verification.
4. **Interaction Rate Limiting (10s Cooldown)**:
   - Prevents button and reaction spamming from flooding the Discord API or freezing the bot.
5. **Anti-Raid Join Burst Detector**:
   - If more than 10 accounts join within 15 seconds, sounds an emergency alert in `📊・mod-logs`.
6. **Web Dashboard Authentication**:
   - Web interface (`http://IP:8080`) is locked behind username & password authentication with timing-safe comparison to prevent brute-force attacks.

---

## 🚀 Setup & Deployment Guide

### 1. Developer Portal Setup
1. Open [Discord Developer Portal](https://discord.com/developers/applications) -> Your Bot -> **Bot** tab.
2. Enable **Privileged Gateway Intents**:
   - ✅ **SERVER MEMBERS INTENT** *(Required for join events)*
   - ✅ **MESSAGE CONTENT INTENT** *(Required for command parsing & anti-invite)*
3. Go to **OAuth2 -> URL Generator**:
   - Check `bot` and `applications.commands`.
   - Permissions: `Administrator`.
   - Copy URL and authorize on your server.
4. **CRITICAL:** In Discord *Server Settings -> Roles*, drag the **Epileptic** role **ABOVE** `Member` and `Not Verified`.

### 2. VPS Deployment (Ubuntu Linux)
On your VPS terminal, execute:
```bash
# 1. Clone repository
git clone https://github.com/Makedonskiyy/epileptic-bot.git /opt/epileptic-bot
cd /opt/epileptic-bot

# 2. Run automated installer
chmod +x deploy/setup_vps.sh
sudo ./deploy/setup_vps.sh

# 3. Add bot token
sudo nano /opt/epileptic-bot/.env
# Paste DISCORD_TOKEN=your_token, save with Ctrl+O, Enter, Ctrl+X

# 4. Restart service
sudo systemctl restart epileptic.service
```

### 3. Updating the Bot on VPS
Whenever you push changes to GitHub:
```bash
cd /opt/epileptic-bot && git pull && sudo systemctl restart epileptic.service
```

### 4. Discord First-Time Walkthrough
1. Run `/setup_permissions` in any channel (Owner only).
2. Run `/post_verification` in `📜・rules`.
3. Run `/post_ticket_panel` in `🎫・support-tickets`.
4. Run `/assign_unverified_all` if you have existing members.
