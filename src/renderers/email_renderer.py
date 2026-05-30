from __future__ import annotations

from datetime import date, datetime
from html import escape

from ..digest import group_by_day
from ..models import Digest, Event

TRAFFIC_UNAVAILABLE_BANNER = "Traffic data unavailable today — calendar only."


def render_email(digest: Digest) -> tuple[str, str]:
    subject = _subject(digest.generated_at)
    return subject, _render_html(digest)


def render_text(digest: Digest) -> str:
    return _render_text(digest)


def _subject(now: datetime) -> str:
    return f"Morning digest — {now.strftime('%A, %B ').replace(' 0', ' ')}{now.day}".rstrip()


def _day_label(day: date, today: date) -> str:
    delta = (day - today).days
    base = f"{day.strftime('%A')}, {day.strftime('%B')} {day.day}"
    if delta == 0:
        return f"TODAY — {base}"
    if delta == 1:
        return f"TOMORROW — {base}"
    return base


def _format_time_range(event: Event) -> str:
    if event.all_day:
        return "All day"
    return f"{_fmt_time(event.start)} – {_fmt_time(event.end)}"


def _fmt_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    if dt.minute == 0:
        return f"{hour}:00 {suffix}"
    return f"{hour}:{dt.minute:02d} {suffix}"


# ---------------------------------------------------------------------------
# Text rendering


def _render_text(digest: Digest) -> str:
    today = digest.generated_at.date()
    lines: list[str] = []
    lines.append("☀  MORNING DIGEST")
    lines.append(f"   {digest.generated_at.strftime('%A, %B')} {digest.generated_at.day}, {digest.generated_at.year}")
    lines.append("   " + "─" * 34)
    lines.append("")

    if not digest.traffic_data_available:
        lines.append(f"   {TRAFFIC_UNAVAILABLE_BANNER}")
        lines.append("")

    grouped = group_by_day(digest.events)
    for day_start, day_events in grouped:
        lines.append(f"   ▌{_day_label(day_start.date(), today)}")
        lines.append("")
        for event in day_events:
            lines.append(f"   {event.summary}")
            lines.append(f"   {_format_time_range(event)}")
            if not event.is_virtual and event.location:
                lines.append(f"   📍 {event.location}")
            if digest.traffic_data_available:
                for _alert, note in digest.matches_by_event_id.get(event.id, []):
                    lines.append(f"   ⚠️  {note}")
            lines.append("")
        lines.append("")

    lines.append("   " + "─" * 34)
    lines.append(
        f"   Generated {_fmt_time(digest.generated_at)}, {digest.generated_at.strftime('%a %b')} {digest.generated_at.day}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML rendering — inline styles for Gmail-friendliness.


def _render_html(digest: Digest) -> str:
    today = digest.generated_at.date()
    parts: list[str] = []
    parts.append(
        '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif; '
        'color: #222; max-width: 640px; margin: 0 auto; padding: 24px; line-height: 1.5;">'
    )
    parts.append(
        '<div style="font-size: 14px; letter-spacing: 0.08em; color: #888;">☀ MORNING DIGEST</div>'
    )
    parts.append(
        f'<div style="font-size: 18px; font-weight: 600; margin-top: 4px;">{escape(digest.generated_at.strftime("%A, %B"))} {digest.generated_at.day}, {digest.generated_at.year}</div>'
    )
    parts.append('<hr style="border: none; border-top: 1px solid #ddd; margin: 16px 0 24px;">')

    if not digest.traffic_data_available:
        parts.append(
            '<div style="background: #fff8e1; border-left: 4px solid #f0c000; '
            'padding: 10px 14px; margin-bottom: 24px; font-size: 14px;">'
            f'{escape(TRAFFIC_UNAVAILABLE_BANNER)}'
            "</div>"
        )

    grouped = group_by_day(digest.events)
    for day_start, day_events in grouped:
        label = _day_label(day_start.date(), today)
        parts.append(
            '<div style="border-left: 4px solid #4a78b8; padding: 4px 0 4px 12px; '
            'margin: 28px 0 12px; font-weight: 600; color: #2c4870; font-size: 15px;">'
            f"{escape(label)}"
            "</div>"
        )
        for event in day_events:
            parts.append('<div style="margin: 12px 0 20px 16px;">')
            parts.append(
                f'<div style="font-weight: 600; font-size: 16px;">{escape(event.summary)}</div>'
            )
            parts.append(
                f'<div style="color: #555; font-size: 14px;">{escape(_format_time_range(event))}</div>'
            )
            if not event.is_virtual and event.location:
                parts.append(
                    f'<div style="color: #555; font-size: 14px;">📍 {escape(event.location)}</div>'
                )
            if digest.traffic_data_available:
                for _alert, note in digest.matches_by_event_id.get(event.id, []):
                    parts.append(
                        '<div style="color: #b04a00; font-size: 14px; margin-top: 4px;">'
                        f'⚠️ {escape(note)}'
                        "</div>"
                    )
            parts.append("</div>")

    parts.append('<hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0 12px;">')
    parts.append(
        '<div style="font-size: 12px; color: #999;">'
        f'Generated {_fmt_time(digest.generated_at)}, {escape(digest.generated_at.strftime("%a %b"))} {digest.generated_at.day}'
        "</div>"
    )
    parts.append("</div>")
    return "".join(parts)
