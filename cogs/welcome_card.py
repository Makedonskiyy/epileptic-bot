import os
import io
import logging
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger("epileptic.welcome_card")


def get_ordinal(n: int) -> str:
    """Returns English ordinal representation (e.g. 1st, 2nd, 3rd, 4th, 21st)."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Robust cross-platform font loader (supports Windows and Linux Ubuntu VPS)."""
    candidates = [
        # Windows Fonts
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        # Linux (Ubuntu / Debian VPS standard fonts)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    try:
        return ImageFont.truetype("arial.ttf", size=size)
    except Exception:
        return ImageFont.load_default()


def create_welcome_card(
    avatar_bytes: bytes | None,
    username: str,
    member_count: int,
    server_name: str = "Epileptic"
) -> io.BytesIO:
    """
    Generates a sleek, high-resolution welcome card image (matching Welcomer style).
    - Dark rectangular canvas with clean rounded frame
    - High-quality circular avatar with smooth antialiased mask
    - Styled dynamic welcome text with ordinal member count
    """
    W, H = 840, 260

    # 1. Base dark canvas (#0E0F14)
    img = Image.new("RGBA", (W, H), (14, 15, 20, 255))
    draw = ImageDraw.Draw(img)

    # 2. Outer rounded frame with crisp border stroke (matching screenshot)
    draw.rounded_rectangle(
        [(16, 16), (W - 16, H - 16)],
        radius=14,
        outline=(255, 255, 255, 240),
        width=3
    )

    # 3. Avatar dimensions & placement
    av_size = 140
    av_x = 55
    av_y = (H - av_size) // 2

    if avatar_bytes:
        try:
            av_raw = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

            # High quality 4x supersampled circular mask for clean edges
            scale = 4
            big_size = av_size * scale
            mask = Image.new("L", (big_size, big_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, big_size, big_size), fill=255)
            mask = mask.resize((av_size, av_size), Image.Resampling.LANCZOS)

            av_cropped = ImageOps.fit(av_raw, (av_size, av_size), centering=(0.5, 0.5))
            av_cropped.putalpha(mask)
            img.paste(av_cropped, (av_x, av_y), av_cropped)
        except Exception as e:
            logger.warning(f"Failed to process avatar bytes: {e}")
            draw.ellipse([(av_x, av_y), (av_x + av_size, av_y + av_size)], fill=(168, 85, 247, 255))
    else:
        # Fallback signature purple circle
        draw.ellipse([(av_x, av_y), (av_x + av_size, av_y + av_size)], fill=(168, 85, 247, 255))

    # Avatar white border ring
    draw.ellipse([(av_x, av_y), (av_x + av_size, av_y + av_size)], outline=(255, 255, 255, 255), width=4)

    # 4. Text Layout & Typography
    text_x = av_x + av_size + 40
    font_large = load_font(34, bold=True)
    font_sub = load_font(23, bold=True)

    # Truncate overly long usernames
    display_user = username if len(username) <= 22 else username[:19] + "..."
    ordinal_str = get_ordinal(member_count)

    clean_server = server_name.upper()
    line1 = f"Welcome {display_user}"
    line2 = f"to {clean_server} you are the {ordinal_str} member!"

    # Draw Text
    draw.text((text_x, 90), line1, fill=(255, 255, 255, 255), font=font_large)
    draw.text((text_x, 142), line2, fill=(240, 240, 245, 235), font=font_sub)

    # Export to memory buffer
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer
