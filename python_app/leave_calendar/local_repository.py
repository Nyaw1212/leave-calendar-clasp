from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

from .leave_types import LeaveTypeOption
from .credits import calculate_credit_entry
from .models import (
    CreditEntry,
    DraftEntry,
    Employee,
    EmployeeProfile,
    LeaveDay,
    LeaveRecord,
    MandatoryLeaveRecord,
    SaveResult,
)
from .philippine_holidays import local_holidays
from .rules import (
    carries_credit,
    compute_monthly_accrual_through_month,
    compute_opening_credit,
    credit_for_day,
    group_consecutive_dates,
    inclusive_dates,
    is_sl_charge,
    is_mone_charge,
    is_vl_charge,
    prorated_usage,
)
from .settings import app_data_dir


class LocalRepositoryError(RuntimeError):
    pass


LOCAL_LEAVE_TYPES = (
    LeaveTypeOption("Vacation Leave", "VL", "4", "Vacation Leave (VL)"),
    LeaveTypeOption("Forced Leave", "FL", "3", "Mandatory / Forced Leave (FL)"),
    LeaveTypeOption("Sick Leave", "SL", "5", "Sick Leave (SL)"),
    LeaveTypeOption("Maternity Leave", "ML", "6", "Maternity Leave"),
    LeaveTypeOption("Paternity Leave", "PL", "P", "Paternity Leave"),
    LeaveTypeOption("Special Privilege Leave", "SPL", "1", "Special Privilege Leave (SPL)"),
    LeaveTypeOption("Solo Parent Leave", "Solo Parent", "S", "Solo Parent Leave"),
    LeaveTypeOption("Study Leave", "Study", "Z", "Study Leave"),
    LeaveTypeOption("10-Day VAWC Leave", "VAWC", "9", "10-Day VAWC Leave"),
    LeaveTypeOption("Rehabilitation Privilege", "RP", "", "Rehabilitation Privilege"),
    LeaveTypeOption(
        "Special Leave Benefits for Women",
        "SLBW",
        "",
        "Special Leave Benefits for Women",
    ),
    LeaveTypeOption(
        "Special Emergency (Calamity) Leave",
        "SEL",
        "",
        "Special Emergency (Calamity) Leave",
    ),
    LeaveTypeOption("Adoption Leave", "AL", "", "Adoption Leave"),
    LeaveTypeOption("Wellness Leave", "WL", "2", "Wellness Leave (WL)"),
    LeaveTypeOption("Others", "Others", "", "Others"),
)


class LocalRepository:
    """SQLite-backed repository for fully offline desktop operation."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "leave_calendar.db"
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    @property
    def spreadsheet_title(self) -> str:
        return "Local Database ✓"

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try: