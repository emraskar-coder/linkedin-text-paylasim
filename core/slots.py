"""Slot zamanlayici — "bir sonraki bos slot" (TR 11:00 / 13:00 / 15:30).

Typefully gocu (2026-06-18). Eskiden Typefully'nin "next-free-slot" sihrini bizim
onay servisi cagiriyordu; Typefully'den cikinca bu mantik BIZIM. Saatler Typefully
hesabinin schedule'undaki TR slotlariydi.

Kural: bugunden baslayarak, gecmemis VE dolu olmayan ilk slotu sec. Gunun tum
slotlari gecti/doluysa ertesi gune gec. Cikti UTC (Supabase'e UTC yazariz).

KANONIK KAYNAK: Twitter_Text_Paylasim/core/slots.py (ve Sosyal_Slot_Yayinci).
Bu dosya LinkedIn_Text otonom yayin yolu icin MIRROR kopyadir; kanonik degisirse
buraya da uygulanir.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

try:
    TR = ZoneInfo("Europe/Istanbul")
except Exception:
    TR = _dt.timezone(_dt.timedelta(hours=3))
UTC = _dt.timezone.utc

# TR saat dilimine gore gunluk slotlar (saat, dakika)
SLOT_TIMES = [(11, 0), (13, 0), (15, 30)]


def _parse(dt_val) -> _dt.datetime:
    """ISO string veya datetime -> aware UTC datetime."""
    if isinstance(dt_val, _dt.datetime):
        d = dt_val
    else:
        d = _dt.datetime.fromisoformat(str(dt_val).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def next_free_slot(
    occupied: list | None = None,
    *,
    now: _dt.datetime | None = None,
    horizon_days: int = 30,
) -> _dt.datetime:
    """Bir sonraki bos slotu UTC datetime olarak doner.

    occupied: dolu slotlarin publish_at degerleri (ISO str veya datetime; UTC/aware).
    now: test icin enjekte edilebilir; verilmezse gercek su an (UTC).
    """
    now = (now or _dt.datetime.now(UTC)).astimezone(UTC)
    taken = set()
    for o in (occupied or []):
        try:
            taken.add(_parse(o).replace(second=0, microsecond=0))
        except (ValueError, TypeError):
            continue

    today_tr = now.astimezone(TR).date()
    for day_offset in range(horizon_days):
        day = today_tr + _dt.timedelta(days=day_offset)
        for hh, mm in SLOT_TIMES:
            slot_tr = _dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=TR)
            slot_utc = slot_tr.astimezone(UTC).replace(second=0, microsecond=0)
            if slot_utc <= now:
                continue
            if slot_utc in taken:
                continue
            return slot_utc
    # Horizon doldu (cok nadir): son carenin bir sonrasi
    fallback = now + _dt.timedelta(hours=1)
    return fallback.replace(second=0, microsecond=0)
