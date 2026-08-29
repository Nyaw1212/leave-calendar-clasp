# Leave Calendar — Python Desktop

This is the local Windows version of the Leave History Recorder. Employees and
leave history are stored in a SQLite database on the same computer, so normal
use does not need Google Sheets, a Google account, or an internet connection.

## What changed

- The Employee box is editable. Select an existing employee or type any name.
- A manually entered name receives a unique `MAN-XXXXXXXX` Employee ID and is
  saved for reuse.
- Employees, assumption dates, and saved leave records persist in local SQLite.
- Leave Records retain the MAGCLIP column order:
  `TYPE | START | END | STATUS | VL | SL | LWOP`.
- **Save + Send to MAGCLIP** removes the copy/paste handoff.
- Drafts and a troubleshooting log survive application restarts.
- Calendar history can jump directly to any month from 1975 onward without
  clicking Previous one month at a time.
- The 12-month view uses a compact 4-column × 3-row calendar so the full year
  fits in one maximized 1080p window. It always runs from January through
  December, and Previous/Next moves by a full year.
- Hover over the Month or Year control and use the mouse wheel to navigate;
  the calendar updates immediately without pressing Go. In the January–December
  view, scroll the Year control because Month is fixed to January.
- Leave types and keyboard shortcuts are bundled locally. The shortcut legend
  stays visible beside the leave-entry controls.
- Pressing a configured shortcut selects that leave type. Use **Add Selected
  Dates to Draft** once after choosing the dates; shortcuts do not auto-add or
  create duplicate draft entries.
- Calendar selection supports both drag/click selection and a two-click
  **Start → End** range mode.
- Completing a drag selection—or clicking the end date in **Start → End**
  mode—opens the live leave-type picker automatically. Choosing a type adds the
  range to Draft Leave History exactly once; Cancel keeps the dates selected.
- Every row in Draft Leave History has its own **×** remove button.
- Audit hover links the draft and calendar in both directions. Hover a draft
  or saved row to jump to and outline all of its dates in gold; hover a calendar
  date to highlight and scroll to every matching leave row. Saved records appear
  read-only beside new drafts, whose individual × controls remain available.
- Unusual historical entries—including duplicate dates, entries before an
  assumption date, and a missing or future assumption date—show a warning but
  can still be saved.
- Philippine holidays are bundled locally for every calendar year from 1975
  through 2026. They appear automatically without reading or writing the
  `Holidays` sheet. The **PH Holidays · Local ✓** button confirms the displayed
  year's local holiday count.
  Regular holidays are red and retain the existing VL/SL credit rule; special
  non-working holidays are amber and special working holidays are teal for
  calendar reference only. Hover a colored date to see its name and type.

## Local database

The app creates its SQLite database automatically at:

```text
%APPDATA%\LeaveCalendar\leave_calendar.db
```

Use **Open Local Data** in the app to open that folder. SQLite writes are
transactional, and the database remains available after restarting the app.
Back up the `.db` file to back up the locally saved employees and leave history.

Google Sheets synchronization is currently disabled. Data already present in
the old Google Sheet is not copied into SQLite automatically; it can be imported
later with a separate one-time migration.

## Run from source on Windows

From PowerShell:

```powershell
cd python_app
.\run_windows.ps1
```

## Build the `.exe`

From PowerShell:

```powershell
cd python_app
.\build_windows.ps1
```

The executable is created at:

```text
python_app\dist\LeaveCalendar.exe
```

## MAGCLIP integration

Install/build the updated MAGCLIP version that includes the Leave Calendar
inbox watcher. When **Save + Send to MAGCLIP** is clicked, Leave Calendar writes
an atomic JSON magazine to:

```text
%LOCALAPPDATA%\MAGCLIP\inbox
```

MAGCLIP loads it automatically. If MAGCLIP is already firing another magazine,
the new one remains queued. **Copy TSV** remains available as a fallback.

## Troubleshooting

Click **Open Logs** inside the app. The main log is:

```text
%APPDATA%\LeaveCalendar\leave_calendar.log
```

The SQLite database is in the same folder as the log.
