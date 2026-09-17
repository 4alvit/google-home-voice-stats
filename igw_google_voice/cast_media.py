"""Render gateway reports as a bounded, offline-generated Cast video snapshot."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

from PIL import Image, ImageDraw, ImageFont


REPORT_TITLES = {
    "status": "Energy status",
    "battery": "Battery",
    "solar": "Solar power",
    "solar_today": "Solar energy today",
    "alarms": "Alarms",
}
STATUS_COLORS = {
    "fresh": "#83E1B6",
    "stale": "#FFC979",
    "unavailable": "#FFABAB",
    "unconfigured": "#C2BFDC",
}
OVERVIEW_KEYS = ("battery", "solar", "solar_today", "alarms")
WIDTH, HEIGHT = 1280, 720
MAX_TEXT_LENGTH = 1200
MAX_DURATION_SECONDS = 120.0
READING_TAIL_SECONDS = 5.0


@dataclass(frozen=True)
class _Card:
    key: str
    status: str
    lines: tuple[str, ...]
    page: int
    pages: int


def _validate_reports(report_key: str, reports: dict) -> None:
    if not isinstance(report_key, str) or report_key not in REPORT_TITLES:
        raise ValueError("Unknown energy report")
    if not isinstance(reports, dict):
        raise ValueError("Energy reports must be an object")
    required = (report_key, *OVERVIEW_KEYS) if report_key == "status" else (report_key,)
    for key in required:
        report = reports.get(key)
        if not isinstance(report, dict):
            raise ValueError("A required energy report is missing")
        status, text = report.get("status"), report.get("text")
        if not isinstance(status, str) or status not in STATUS_COLORS:
            raise ValueError("Invalid energy report status")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Invalid energy report text length")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
            raise ValueError("Energy report text contains control characters")


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = (
        name,
        "/usr/share/fonts/truetype/dejavu/" + name,
        "/usr/share/fonts/dejavu/" + name,
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    raise RuntimeError("Install DejaVu Sans fonts to render energy reports")


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Wrap all text, splitting long tokens instead of clipping or dropping them."""
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if font.getlength(candidate) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
        while word and font.getlength(word) > width:
            split_at = 1
            while split_at < len(word) and font.getlength(word[:split_at + 1]) <= width:
                split_at += 1
            lines.append(word[:split_at])
            word = word[split_at:]
        line = word
    if line:
        lines.append(line)
    return lines


def _layout_pages(report_key: str, reports: dict) -> list[list[_Card]]:
    overview = report_key == "status"
    keys = OVERVIEW_KEYS if overview else (report_key,)
    body_font = _font(22 if overview else 32)
    width, lines_per_card = (520, 5) if overview else (1136, 9)
    chunks = {}
    for key in keys:
        lines = _wrap_text(reports[key]["text"], body_font, width)
        chunks[key] = [tuple(lines[index:index + lines_per_card])
                       for index in range(0, len(lines), lines_per_card)]
    pages = []
    for page_index in range(max(len(parts) for parts in chunks.values())):
        cards = []
        for key in keys:
            parts = chunks[key]
            # Keep shorter cards visible while longer reports continue onto later pages.
            part_index = min(page_index, len(parts) - 1)
            cards.append(_Card(key, reports[key]["status"], parts[part_index],
                               part_index + 1, len(parts)))
        pages.append(cards)
    return pages


def _draw_page(report_key: str, overall_status: str, cards: list[_Card],
               page_number: int, page_count: int, rendered_at: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0B1424")
    draw = ImageDraw.Draw(image)
    draw.text((48, 28), REPORT_TITLES[report_key], font=_font(44, bold=True), fill="#F4F7FD")
    overall_label = overall_status.upper()
    label_font = _font(18, bold=True)
    label_width = draw.textlength(overall_label, font=label_font)
    draw.text((WIDTH - 48 - label_width, 46), overall_label,
              font=label_font, fill=STATUS_COLORS[overall_status])
    draw.text((48, 90), "Inverter Gateway report", font=_font(20), fill="#AEBBD0")
    overview = report_key == "status"
    body_font, line_height = (_font(22), 28) if overview else (_font(32), 43)
    for index, card in enumerate(cards):
        if overview:
            left, top = 48 + (index % 2) * 604, 134 + (index // 2) * 260
            right, bottom = left + 580, top + 240
        else:
            left, top, right, bottom = 48, 134, 1232, 634
        draw.rounded_rectangle((left, top, right, bottom), radius=18, fill="#172338")
        draw.text((left + 24, top + 16), REPORT_TITLES[card.key],
                  font=_font(24, bold=True), fill="#F4F7FD")
        badge_font = _font(14, bold=True)
        badge = card.status.upper()
        badge_width = draw.textlength(badge, font=badge_font)
        draw.text((right - 24 - badge_width, top + 22), badge,
                  font=badge_font, fill=STATUS_COLORS[card.status])
        for line_index, line in enumerate(card.lines):
            draw.text((left + 24, top + 60 + line_index * line_height), line,
                      font=body_font, fill="#E1E8F3")
        if card.pages > 1:
            continuation = f"Text {card.page}/{card.pages}"
            small_font = _font(13)
            small_width = draw.textlength(continuation, font=small_font)
            draw.text((right - 24 - small_width, bottom - 20), continuation,
                      font=small_font, fill="#AEBBD0")
    footer = f"Snapshot rendered {rendered_at}  |  Freshness shown per report"
    draw.text((48, 670), footer, font=_font(17), fill="#AEBBD0")
    if page_count > 1:
        label = f"Page {page_number}/{page_count}"
        footer_font = _font(17)
        draw.text((WIDTH - 48 - draw.textlength(label, font=footer_font), 670), label,
                  font=footer_font, fill="#AEBBD0")
    return image


def _run(command: list[str], *, input_bytes: bytes | None = None, timeout: int) -> None:
    try:
        result = subprocess.run(command, input=input_bytes, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Offline media generation could not complete") from exc
    if result.returncode:
        # Tool output may include report text or private filesystem locations.
        raise RuntimeError("Offline media generation failed")


def _synthesize_speech(text: str, output_path: Path, executable: str) -> float:
    _run([executable, "--stdin", "-v", "en-us", "-s", "155", "-w", str(output_path)],
         input_bytes=text.encode("utf-8"), timeout=30)
    try:
        with wave.open(str(output_path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
    except (OSError, EOFError, wave.Error, ZeroDivisionError) as exc:
        raise RuntimeError("Speech synthesis produced invalid audio") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Speech synthesis produced empty audio")
    if duration + READING_TAIL_SECONDS > MAX_DURATION_SECONDS:
        raise ValueError("The spoken report exceeds the media duration limit")
    return duration


def render_report_video(report_key: str, reports: dict[str, dict[str, str]],
                        output_path: Path) -> dict[str, float]:
    """Write an H.264/AAC MP4 without network calls or truncating gateway warnings.

    The selected report is spoken verbatim. Its text is passed only on stdin,
    never as executable arguments. Long visual reports continue across pages.
    This is a snapshot: freshness remains the status supplied by the gateway.
    Existing output survives failures; a completed video replaces it atomically.
    """
    _validate_reports(report_key, reports)
    output_path = Path(output_path).absolute()
    if output_path.suffix.lower() != ".mp4" or not output_path.parent.is_dir():
        raise ValueError("The output must be an MP4 path in an existing directory")
    espeak, ffmpeg = shutil.which("espeak-ng"), shutil.which("ffmpeg")
    if not espeak or not ffmpeg:
        raise RuntimeError("Install espeak-ng and ffmpeg to render energy reports")
    pages = _layout_pages(report_key, reports)
    with tempfile.TemporaryDirectory(prefix=".igw-media-", dir=output_path.parent) as temporary:
        directory = Path(temporary)
        audio_path = directory / "speech.wav"
        speech_duration = _synthesize_speech(reports[report_key]["text"], audio_path, espeak)
        duration = max(speech_duration + READING_TAIL_SECONDS, len(pages) * 5.0)
        if duration > MAX_DURATION_SECONDS:
            raise ValueError("The visual report exceeds the media duration limit")
        rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        manifest = []
        for index, cards in enumerate(pages):
            frame_name = f"page-{index:03d}.png"
            frame = _draw_page(report_key, reports[report_key]["status"], cards,
                               index + 1, len(pages), rendered_at)
            frame.save(directory / frame_name)
            manifest.extend((f"file '{frame_name}'", f"duration {duration / len(pages):.6f}"))
        manifest.append(f"file 'page-{len(pages) - 1:03d}.png'")
        manifest_path = directory / "frames.txt"
        manifest_path.write_text("\n".join(manifest) + "\n", encoding="utf-8")
        temporary_output = directory / "report.mp4"
        _run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "concat", "-safe", "1", "-i", str(manifest_path), "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast",
            "-tune", "stillimage", "-crf", "24", "-pix_fmt", "yuv420p", "-r", "15",
            "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "1", "-af", "apad",
            "-t", f"{duration:.6f}", "-movflags", "+faststart", str(temporary_output),
        ], timeout=120)
        if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
            raise RuntimeError("Video encoding produced no output")
        temporary_output.chmod(0o600)
        os.replace(temporary_output, output_path)
    return {"duration_seconds": duration}
