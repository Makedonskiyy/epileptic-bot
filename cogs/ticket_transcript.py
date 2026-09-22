import io
import html
from datetime import datetime, timezone
from pathlib import Path
import discord

TRANSCRIPTS_DIR = Path("data/transcripts")


def generate_ticket_transcripts(
    guild: discord.Guild,
    channel: discord.TextChannel,
    messages: list[discord.Message],
    closed_by: discord.User | discord.Member,
    owner: discord.User | discord.Member | None = None
) -> tuple[io.BytesIO, io.BytesIO]:
    """
    Generates both HTML (dark-theme Discord styled) and plain text transcripts of a ticket channel.
    Returns (html_buffer, txt_buffer).
    """
    now = datetime.now(timezone.utc)
    formatted_now = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    owner_str = f"{owner.display_name} ({owner.id})" if owner else (channel.topic or "Unknown")
    closed_by_str = f"{closed_by.display_name} ({closed_by.id})"

    # ---------------------------------------------------------
    # 1. Plain Text Transcript Generation
    # ---------------------------------------------------------
    txt_lines = [
        "=" * 80,
        f"TICKET TRANSCRIPT: #{channel.name}",
        f"Server: {guild.name} (ID: {guild.id})",
        f"Ticket Owner: {owner_str}",
        f"Closed By: {closed_by_str}",
        f"Closed At: {formatted_now}",
        f"Total Messages: {len(messages)}",
        "=" * 80,
        ""
    ]

    for msg in messages:
        msg_time = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author_name = msg.author.display_name
        is_bot = " [BOT]" if msg.author.bot else ""
        txt_lines.append(f"[{msg_time}] {author_name}{is_bot}:")

        if msg.content:
            txt_lines.append(f"  {msg.content}")

        for att in msg.attachments:
            txt_lines.append(f"  [Attachment: {att.filename} -> {att.url}]")

        for emb in msg.embeds:
            if emb.title:
                txt_lines.append(f"  [Embed Title: {emb.title}]")
            if emb.description:
                txt_lines.append(f"  [Embed Description: {emb.description}]")

        txt_lines.append("")

    txt_lines.append("=" * 80)
    txt_lines.append("END OF TRANSCRIPT")
    txt_lines.append("=" * 80)

    txt_content = "\n".join(txt_lines)
    txt_buffer = io.BytesIO(txt_content.encode("utf-8"))
    txt_buffer.seek(0)

    # ---------------------------------------------------------
    # 2. Rich Dark HTML Transcript Generation
    # ---------------------------------------------------------
    html_messages = []

    for msg in messages:
        time_str = msg.created_at.strftime("%d.%m.%Y %H:%M")
        safe_author = html.escape(msg.author.display_name)
        safe_content = html.escape(msg.content or "").replace("\n", "<br>")

        avatar_url = msg.author.display_avatar.url if msg.author.display_avatar else None
        if avatar_url:
            avatar_html = f'<img class="avatar" src="{avatar_url}" alt="{safe_author}" onerror="this.style.display=\'none\'">'
        else:
            initial = safe_author[:1].upper() if safe_author else "?"
            avatar_html = f'<div class="avatar-placeholder">{initial}</div>'

        badge_html = ""
        if msg.author.bot:
            badge_html = '<span class="badge badge-bot">BOT</span>'
        elif hasattr(msg.author, "guild_permissions") and (msg.author.guild_permissions.administrator or msg.author.id == guild.owner_id):
            badge_html = '<span class="badge badge-staff">STAFF</span>'

        # Attachments rendering
        attachments_html = ""
        if msg.attachments:
            att_items = []
            for att in msg.attachments:
                safe_fn = html.escape(att.filename)
                is_image = any(att.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"])
                if is_image:
                    att_items.append(
                        f'<div class="attachment-item">'
                        f'<a href="{att.url}" target="_blank" rel="noopener">'
                        f'<img class="attachment-img" src="{att.url}" alt="{safe_fn}">'
                        f'</a><br>'
                        f'<a class="attachment-link" href="{att.url}" target="_blank" rel="noopener">📎 {safe_fn} ({round(att.size / 1024, 1)} KB)</a>'
                        f'</div>'
                    )
                else:
                    att_items.append(
                        f'<div class="attachment-item">'
                        f'<a class="attachment-link" href="{att.url}" target="_blank" rel="noopener">📄 {safe_fn} ({round(att.size / 1024, 1)} KB)</a>'
                        f'</div>'
                    )
            attachments_html = f'<div class="attachments">{"".join(att_items)}</div>'

        # Embeds rendering
        embeds_html = ""
        if msg.embeds:
            emb_items = []
            for emb in msg.embeds:
                title_part = f'<div class="embed-title">{html.escape(emb.title)}</div>' if emb.title else ""
                desc_part = f'<div class="embed-desc">{html.escape(emb.description or "").replace(chr(10), "<br>")}</div>' if emb.description else ""
                color_hex = f"#{emb.color.value:06x}" if emb.color else "#5865F2"
                emb_items.append(f'<div class="embed" style="border-left-color: {color_hex};">{title_part}{desc_part}</div>')
            embeds_html = f'<div class="embeds-container">{"".join(emb_items)}</div>'

        msg_body = f'<div class="text">{safe_content}</div>' if safe_content else ""

        html_messages.append(
            f'<div class="message">'
            f'  {avatar_html}'
            f'  <div class="msg-content">'
            f'    <div class="msg-header">'
            f'      <span class="author">{safe_author}</span>'
            f'      {badge_html}'
            f'      <span class="timestamp">{time_str}</span>'
            f'    </div>'
            f'    {msg_body}'
            f'    {attachments_html}'
            f'    {embeds_html}'
            f'  </div>'
            f'</div>'
        )

    guild_icon_html = f'<img src="{guild.icon.url}" class="guild-icon" alt="{html.escape(guild.name)}">' if guild.icon else ""

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Transcript - #{html.escape(channel.name)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    background: #1e1f22;
    color: #dbdee1;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 24px;
  }}
  .container {{
    max-width: 960px;
    margin: 0 auto;
  }}
  .header {{
    background: #2b2d31;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
    border-left: 6px solid #5865f2;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
  }}
  .header-top {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 16px;
  }}
  .guild-icon {{
    width: 48px;
    height: 48px;
    border-radius: 12px;
  }}
  .header h1 {{
    margin: 0;
    font-size: 22px;
    color: #f2f3f5;
  }}
  .header-sub {{
    font-size: 13px;
    color: #949ba4;
    margin-top: 4px;
  }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    background: #1e1f22;
    padding: 14px 18px;
    border-radius: 8px;
    font-size: 13px;
  }}
  .meta-item {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}
  .meta-label {{
    color: #949ba4;
    font-size: 11px;
    text-transform: uppercase;
    font-weight: 600;
  }}
  .meta-value {{
    color: #f2f3f5;
    font-weight: 500;
  }}
  .chat-box {{
    background: #2b2d31;
    border-radius: 12px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
  }}
  .message {{
    display: flex;
    gap: 14px;
    padding: 8px 12px;
    border-radius: 6px;
    transition: background 0.15s ease;
  }}
  .message:hover {{
    background: #313338;
  }}
  .avatar {{
    width: 40px;
    height: 40px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
  }}
  .avatar-placeholder {{
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: #5865f2;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    font-size: 16px;
    flex-shrink: 0;
  }}
  .msg-content {{
    display: flex;
    flex-direction: column;
    gap: 4px;
    overflow: hidden;
    flex-grow: 1;
  }}
  .msg-header {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .author {{
    font-weight: 600;
    color: #f2f3f5;
    font-size: 14px;
  }}
  .badge {{
    font-size: 10px;
    color: #fff;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: bold;
  }}
  .badge-bot {{
    background: #5865f2;
  }}
  .badge-staff {{
    background: #23a55a;
  }}
  .timestamp {{
    font-size: 11px;
    color: #949ba4;
    margin-left: 2px;
  }}
  .text {{
    font-size: 14px;
    line-height: 1.45;
    color: #dbdee1;
    word-break: break-word;
  }}
  .attachments {{
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 6px;
  }}
  .attachment-item {{
    margin-top: 4px;
  }}
  .attachment-img {{
    max-width: 460px;
    max-height: 320px;
    border-radius: 8px;
    border: 1px solid #383a40;
    display: block;
    margin-bottom: 4px;
  }}
  .attachment-link {{
    font-size: 12px;
    color: #00a8fc;
    text-decoration: none;
  }}
  .attachment-link:hover {{
    text-decoration: underline;
  }}
  .embeds-container {{
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 6px;
  }}
  .embed {{
    background: #1e1f22;
    border-left: 4px solid #5865f2;
    padding: 12px 16px;
    border-radius: 6px;
    max-width: 580px;
  }}
  .embed-title {{
    font-weight: 600;
    color: #f2f3f5;
    font-size: 13px;
    margin-bottom: 4px;
  }}
  .embed-desc {{
    font-size: 13px;
    line-height: 1.4;
    color: #dbdee1;
  }}
  .footer {{
    text-align: center;
    margin-top: 24px;
    font-size: 12px;
    color: #80848e;
  }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="header-top">
        {guild_icon_html}
        <div>
          <h1>Support Ticket #{html.escape(channel.name)}</h1>
          <div class="header-sub">{html.escape(guild.name)} • Official Support Transcript</div>
        </div>
      </div>
      <div class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">Ticket Creator</span>
          <span class="meta-value">{html.escape(owner_str)}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Closed By</span>
          <span class="meta-value">{html.escape(closed_by_str)}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Closed Date</span>
          <span class="meta-value">{formatted_now}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Messages</span>
          <span class="meta-value">{len(messages)} messages</span>
        </div>
      </div>
    </div>

    <div class="chat-box">
      {"".join(html_messages) if html_messages else '<div style="padding: 20px; text-align: center; color: #949ba4;">No messages were sent in this ticket.</div>'}
    </div>

    <div class="footer">
      Epileptic Community Support Desk • Transcript Archive Generated Automatically
    </div>
  </div>
</body>
</html>
"""

    html_buffer = io.BytesIO(html_doc.encode("utf-8"))
    html_buffer.seek(0)

    # Also persist to disk in data/transcripts
    try:
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        file_base = f"transcript_{channel.name}_{int(now.timestamp())}"
        with open(TRANSCRIPTS_DIR / f"{file_base}.html", "w", encoding="utf-8") as f:
            f.write(html_doc)
        with open(TRANSCRIPTS_DIR / f"{file_base}.txt", "w", encoding="utf-8") as f:
            f.write(txt_content)
    except Exception:
        pass

    return html_buffer, txt_buffer
