from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class MonePreset:
    order: str
    start: date
    end: date

    @property
    def key(self) -> tuple[str, date, date]:
        return self.order, self.start, self.end


# Fixed MONE order periods transcribed from the supplied MONE workbook.
# VL and SL are deliberately not stored here because they vary by employee.
MONE_PRESETS: tuple[MonePreset, ...] = (
    MonePreset("MC# 41-98", date(2003, 3, 1), date(2003, 3, 10)),
    MonePreset("MC# 41-98", date(2005, 4, 1), date(2005, 4, 10)),
    MonePreset("MC# 41-98", date(2006, 3, 1), date(2006, 3, 15)),
    MonePreset("MC# 41-98", date(2006, 12, 1), date(2006, 12, 15)),
    MonePreset("MC# 41-98", date(2007, 5, 1), date(2007, 5, 10)),
    MonePreset("MC# 41-98", date(2007, 7, 15), date(2007, 7, 31)),
    MonePreset("MC# 41-98", date(2008, 3, 1), date(2008, 3, 15)),
    MonePreset("MC# 41-98", date(2009, 3, 1), date(2009, 3, 20)),
    MonePreset("MC# 41-98", date(2010, 3, 1), date(2010, 3, 20)),
    MonePreset("MC# 41-98", date(2011, 2, 1), date(2011, 2, 20)),
    MonePreset("MC# 41-98", date(2012, 11, 1), date(2012, 11, 15)),
    MonePreset("MC# 41-98", date(2013, 4, 16), date(2013, 4, 30)),
    MonePreset("MC# 16", date(2020, 8, 1), date(2020, 8, 30)),
    MonePreset("MC# 41-98", date(2022, 11, 21), date(2022, 12, 20)),
    MonePreset("MC# 41-98", date(2023, 11, 1), date(2023, 11, 30)),
    MonePreset("MC# 41-98", date(2024, 10, 1), date(2024, 10, 30)),
    MonePreset("MC# 41-98", date(2025, 11, 16), date(2025, 11, 30)),
)


def mone_display_type(order: str) -> str:
    clean_order = " ".join(str(order or "").split())
    return f"MONE · {clean_order}" if clean_order else "MONE"

