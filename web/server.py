import os
import math
import time
import secrets
from pathlib import Path
import discord
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import config
from cogs.verification import find_role_by_key

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Epileptic Bot Dashboard", docs_url=None, redoc_url=None)

# Template and Static Directories
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

START_TIME = time.time()
# In-memory active session tokens
ACTIVE_SESSIONS: set[str] = set()


def get_bot(request: Request):
    """Retrieve bot instance from application state."""
    return getattr(request.app.state, "bot", None)


def get_safe_latency(bot) -> float:
    """Safely retrieves latency without producing NaN/Inf (compliant with JSON)."""
    if bot and hasattr(bot, "latency"):
        try:
            lat = bot.latency
            if lat is not None and not math.isnan(lat) and not math.isinf(lat):
                return round(lat * 1000, 1)
        except Exception:
            pass
    return 0.0


def is_authenticated(request: Request) -> bool:
    """Checks if request has a valid session cookie."""
    token = request.cookies.get("epileptic_session")
    return token in ACTIVE_SESSIONS if token else False


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...)
):
    # Constant-time comparison against brute-force timing attacks
    user_ok = secrets.compare_digest(username.strip(), config.WEB_USERNAME)
    pass_ok = secrets.compare_digest(password.strip(), config.WEB_PASSWORD)

    if user_ok and pass_ok:
        session_token = secrets.token_urlsafe(32)
        ACTIVE_SESSIONS.add(session_token)
        redirect = RedirectResponse(url="/", status_code=303)
        redirect.set_cookie(
            key="epileptic_session",
            value=session_token,
            httponly=True,
            samesite="lax",
            max_age=86400 # 24 hours
        )
        return redirect

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid username or password."}
    )


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("epileptic_session")
    if token in ACTIVE_SESSIONS:
        ACTIVE_SESSIONS.remove(token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("epileptic_session")
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)

    bot = get_bot(request)
    uptime_seconds = int(time.time() - START_TIME)
    uptime_str = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m {uptime_seconds % 60}s"

    guild_data = None
    if bot and bot.is_ready() and bot.guilds:
        guild = bot.get_guild(config.GUILD_ID) if config.GUILD_ID else bot.guilds[0]
        if guild:
            unverified_role = find_role_by_key(guild, "unverified", config.UNVERIFIED_ROLE_NAME)
            member_role = find_role_by_key(guild, "member", config.MEMBER_ROLE_NAME)
            premium_role = find_role_by_key(guild, "premium", config.PREMIUM_ROLE_NAME)

            guild_data = {
                "name": guild.name,
                "id": str(guild.id),
                "icon": str(guild.icon.url) if guild.icon else None,
                "total_members": guild.member_count,
                "unverified_count": len(unverified_role.members) if unverified_role else 0,
                "member_count": len(member_role.members) if member_role else 0,
                "premium_count": len(premium_role.members) if premium_role else 0,
                "channels_count": len(guild.channels),
                "roles_count": len(guild.roles),
                "categories": [c.name for c in guild.categories]
            }

    status_info = {
        "is_ready": bot.is_ready() if bot else False,
        "latency_ms": get_safe_latency(bot),
        "uptime": uptime_str,
        "bot_user": str(bot.user) if bot and bot.user else "Disconnected"
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "status": status_info,
            "guild": guild_data,
            "config": {
                "unverified_role": config.UNVERIFIED_ROLE_NAME,
                "member_role": config.MEMBER_ROLE_NAME,
                "premium_role": config.PREMIUM_ROLE_NAME,
                "min_account_age": config.MIN_ACCOUNT_AGE_HOURS,
                "cooldown_sec": config.VERIFY_COOLDOWN_SECONDS
            }
        }
    )


@app.get("/api/status")
async def api_status(request: Request):
    bot = get_bot(request)
    return {
        "status": "online" if bot and bot.is_ready() else "connecting",
        "latency_ms": get_safe_latency(bot),
        "guilds_count": len(bot.guilds) if bot else 0
    }


@app.post("/api/action/post_verify")
async def api_post_verify(request: Request, channel_name: str = Form("rules")):
    if not is_authenticated(request):
        return JSONResponse({"success": False, "error": "Unauthorized. Please log in."}, status_code=401)

    bot = get_bot(request)
    if not bot or not bot.is_ready():
        return JSONResponse({"success": False, "error": "Bot is not yet connected to Discord."}, status_code=503)

    guild = bot.get_guild(config.GUILD_ID) if config.GUILD_ID else (bot.guilds[0] if bot.guilds else None)
    if not guild:
        return JSONResponse({"success": False, "error": "Server not found."}, status_code=404)

    target_channel = discord.utils.find(lambda c: channel_name.lower() in c.name.lower(), guild.text_channels)
    if not target_channel:
        return JSONResponse({"success": False, "error": f"Channel containing '{channel_name}' not found."}, status_code=404)

    try:
        embed = discord.Embed(
            description=config.OFFICIAL_RULES_DESCRIPTION,
            color=config.RULES_EMBED_COLOR
        )

        msg = await target_channel.send(embed=embed)
        try:
            await msg.add_reaction("✅")
        except Exception:
            pass
        return {"success": True, "message": f"Server rules successfully posted to #{target_channel.name} with reaction verification!"}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
