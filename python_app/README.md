# Leave Calendar — Python Desktop

This is the Windows/PyInstaller version of the Leave History Recorder. It uses
the same Google Sheet as the Apps Script version but is not restricted to names
already present in the `Employees` sheet.

## What changed

- The Employee box is editable. Select an existing employee or type any name.
- A manually entered name receives a unique `MAN-XXXXXXXX` Employee ID and is
  saved for reuse.
- Sheet reads are cached, while saves remain direct and batched.
- Leave Records retain the MAGCLIP column order:
  `TYPE | START | END | STATUS | VL | SL | LWOP`.
- **Save + Send to MAGCLIP** removes the copy/paste handoff.
- Drafts and a troubleshooting log survive application restarts.
- Calendar history can jump directly to any month from 1975 onward without
  clicking Previous one month at a time.
- The 12-month view uses a compact 4-column × 3-row calendar so the full year
  fits in one maximized 1080p window.
- Leave types and keyboard shortcuts are loaded from the existing `LEAVE_TYPE`
  tab every time the app connects. The shortcut legend stays visible beside
  the leave-entry controls.
- Pressing a configured shortcut selects that leave type. Use **Add Selected
  Dates to Draft** once after choosing the dates; shortcuts do not auto-add or
  create duplicate draft entries.
- Calendar selection supports both drag/click selection and a two-click
  **Start → End** range mode.
- Completing a drag selection—or clicking the end date in **Start → End**
  mode—opens the live leave-type picker automatically. Choosing a type adds the
  range to Draft Leave History exactly once; Cancel keeps the dates selected.
- Every row in Draft Leave History has its own **×** remove button.
- Unusual historical entries—including duplicate dates, entries before an
  assumption date, and a missing or future assumption date—show a warning but
  can still be saved.

## Google setup

The Apps Script Script ID is not the Spreadsheet ID. Open the actual Google
Sheet and copy its URL; the app extracts the Spreadsheet ID automatically.

1. In Google Cloud, create or select a project.
2. Enable **Google Sheets API** and **Google Drive API**.
3. Create a service account and download its JSON key.
4. Open the JSON and copy its `client_email` value.
5. Share the Leave Calendar Google Sheet with that email as **Editor**.
6. Open Leave Calendar and select **Google Sheets Settings**.
7. Paste the Google Sheet URL and select the JSON key.

The JSON key is stored only at the local path you select. Do not commit it to
GitHub and do not place it inside the PyInstaller source folder.

The `LEAVE_TYPE` tab may use headers such as `LEAVE_TYPE`, `CODE`, and
`SHORTCUT KEY` (header order does not matter). Shortcuts can be a single key
such as `V`, or a combination such as `Ctrl+V`. Duplicate or invalid shortcuts
are ignored and noted in the troubleshooting log.

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

The Google credentials file is not copied to the log.
