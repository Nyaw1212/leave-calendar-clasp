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
- MAGCLIP Mode prepends an editable `NAME` round. Double-click a name in the
  clip table to replace it manually without changing the saved employee. NAME
  is the first value fired for every clip.
- **MAGCLIP Mode** is built into the Leave Calendar window; no second app or
  inbox handoff is needed.
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
- **Fast Encode** accepts dates with spaces: enter `9 1`, press Enter, enter `3`,
  and press Enter again to select September 1–3 in the chosen working year.
  The year is selected manually at the start. During chronological encoding,
  entering an earlier month than the previous start automatically advances to
  the next year; changing Working Year manually resets that rollover baseline.
- **VL Lock** keeps Vacation Leave active. While it is on, completed Fast Encode,
  click, and drag ranges go directly to the draft without reopening the
  leave-type picker.
- **MONE** supports mixed charging. After selecting MONE, enter either the VL
  or SL allocation and the other amount is calculated automatically from the
  selected range's calendar-day total (for example, 15 total and 5 VL becomes
  10 SL). MONE counts weekends and holidays; the saved history and MAGCLIP
  rounds retain both amounts.
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
  assumption date, a missing assumption date, and zero-credit weekends or
  holidays—are added immediately and show a temporary non-blocking amber
  warning banner. No warning acknowledgement is required.
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

Use **Paste History Data** to import rows copied from Excel or Google Sheets.
The header is optional; the default order is:

```text
NAME | TYPE | START | END | VL | SL | LWOP | STATUS
```

Exact duplicates are skipped. Seven-column rows without NAME use the currently
selected employee. Dates accept `M/D/YYYY`, and imported credits are preserved
without recalculation.

Google Sheets synchronization is currently disabled. Data already present in
the old Google Sheet is not copied into SQLite automatically; it can be imported
later with a separate one-time migration.

The linked Apps Script project still includes a small `SIMPLE`-sheet helper.
After entering START, it prefills END and moves the active cell there. START
accepts `M/D` or a day-only shortcut using the preceding chronological entry;
END accepts a day number using START's month and year. TYPE uses the
`LEAVE_TYPE` list as a dropdown. Completing a MONE row prompts for its VL
allocation and automatically assigns the remaining calendar days to SL.

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

Click **MAGCLIP Mode** to open the selected employee's saved leave history as an
eight-column table:

```text
NAME | TYPE | START | END | VL | SL | LWOP | STATUS
```

Each saved history row is one clip, and all eight cells are fired rounds. NAME
is fired first and STATUS is fired last.
Double-click a `NAME` cell to edit it manually. Double-click any other cell or
use **Load Selected Clip from Round 1** to chamber a specific clip. The
integrated controls provide a 40-slot custom sequence, adjustable delay, and
round count. The requested ENTER/PASTE/TAB pattern is loaded by default. `TYPE`
types the next round as real keystrokes; `PASTE` uses the clipboard. A trailing
STATUS is typed and followed by Tab automatically after the visible sequence;
LWOP presses Space only when it is nonzero.

The sequence selector includes **POCES APPOVE**, a 32-action preset. Its first
`ENTER`, first `PASTE`, and second `ENTER` each wait 700 ms. It includes two
`ARROW DOWN` actions before literal `TYPE A`; other actions use the normal Delay
setting. `TYPE P` and `TYPE A` type literal letters without consuming MAGCLIP
rounds. After this form-specific sequence succeeds, MAGCLIP advances to the next
history clip. Commands 31 and 32 are both `TAB`. The editor provides 40 command
slots, leaving eight empty slots after this preset for later additions.

`ARROW UP` and `ARROW DOWN` are also available in every command slot. They send
the corresponding keyboard navigation key without consuming a MAGCLIP round.

Hotkeys are active only while MAGCLIP Mode is open:

- **F1** — fire
- **R** — reload the last round
- **F4** — reload the last completed clip
- **F3** — abort

**Save + Open MAGCLIP Mode** saves the draft locally, refreshes the history,
and opens the integrated magazine. **Copy Draft TSV** remains available as a
fallback.

## Troubleshooting

Click **Open Logs** inside the app. The main log is:

```text
%APPDATA%\LeaveCalendar\leave_calendar.log
```

The SQLite database is in the same folder as the log.
