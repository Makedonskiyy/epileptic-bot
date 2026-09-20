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


def fit_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    initial_size: int,
    min_size: int = 14,
    bold: bool = True
) -> tuple[str, ImageFont.ImageFont]:
    """Dynamically scales down font size and truncates if necessary to fit within max_width."""
    size = initial_size
    font = load_font(size, bold=bold)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]

    while width > max_width and size > min_size:
        size -= 1
        font = load_font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]

    # If still too long at minimum font size, truncate cleanly with ellipsis
    if width > max_width:
        while len(text) > 4 and width > max_width:
            text = text[:-4] + "..."
            bbox = draw.textbbox((0, 0), text, font=font)
            width = bbox[2] - bbox[0]

    return text, font


def create_welcome_card(
    avatar_bytes: bytes | None,
    username: str,
    member_count: int,
    server_name: str = "Epileptic"
) -> io.BytesIO:
    """
    Generates a sleek, high-resolution welcome card image (matching Welcomer style).
    - Guaranteed zero text overflow via dynamic font auto-fitting
    - High-quality circular avatar with smooth antialiased mask
    - Perfectly centered typography with clean borders
    """
    W, H = 900, 270

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
    av_size = 150
    av_x = 50
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

    # 4. Text Layout & Auto-Fitting
    text_x = av_x + av_size + 35
    max_text_width = (W - 45) - text_x

    ordinal_str = get_ordinal(member_count)
    clean_server = server_name.upper()

    raw_line1 = f"Welcome {username}"
    raw_line2 = f"to {clean_server} you are the {ordinal_str} member!"

    # Dynamically fit both lines so they never touch or cross the frame border
    line1_text, font_line1 = fit_text_to_width(draw, raw_line1, max_text_width, initial_size=36, min_size=16, bold=True)
    line2_text, font_line2 = fit_text_to_width(draw, raw_line2, max_text_width, initial_size=23, min_size=13, bold=True)

    # Measure exact rendered heights to center vertically relative to the card
    bbox1 = draw.textbbox((0, 0), line1_text, font=font_line1)
    bbox2 = draw.textbbox((0, 0), line2_text, font=font_line2)
    h1 = bbox1[3] - bbox1[1]
    h2 = bbox2[3] - bbox2[1]
    line_gap = 14
    total_text_h = h1 + line_gap + h2

    start_y = (H - total_text_h) // 2

    # Draw Text safely inside the card
    draw.text((text_x, start_y), line1_text, fill=(255, 255, 255, 255), font=font_line1)
    draw.text((text_x, start_y + h1 + line_gap), line2_text, fill=(240, 240, 245, 235), font=font_line2)

    # Export to memory buffer
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer
