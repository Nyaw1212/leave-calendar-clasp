# Leave Calendar Sidebar — clasp project

A Google Sheets-bound Apps Script sidebar for selecting leave dates and saving
one row per date into a `Leave Records` sheet.

## Included files

- `Code.gs` — Apps Script server functions
- `Sidebar.html` — calendar sidebar UI
- `appsscript.json` — Apps Script manifest
- `.claspignore` — files pushed by clasp

## Important: create the bound script first

`clasp` can clone and edit a spreadsheet-bound Apps Script project, but it
cannot directly create a new bound script.

1. Open the target Google Sheet.
2. Go to **Extensions → Apps Script**.
3. Rename the project, for example `Leave Calendar`.
4. Open **Project Settings** and copy the **Script ID**.

## Local setup

Install Node.js first, then run:

```bash
npm install -g @google/clasp
clasp login
```

Enable the **Google Apps Script API** in your Apps Script user settings:

https://script.google.com/home/usersettings

Extract this project, open the folder in VS Code, then connect it:

```bash
clasp clone YOUR_SCRIPT_ID
```

Because `clasp clone` may pull the empty online files, copy these starter files
back into the folder afterward if they were overwritten.

A cleaner alternative is:

```bash
clasp create
```

for a standalone project, but the sidebar menu only works as intended when the
script is bound to the target spreadsheet.

## Push the project

```bash
clasp push
clasp open
```

Reload the Google Sheet. You should see:

**Leave Encoder → Set up sheets**

Run it once, add employees to the `Employees` tab, and then choose:

**Leave Encoder → Open Calendar**

## Expected Employees sheet

| Employee ID | Name |
|---|---|
| EMP-001 | Juan Dela Cruz |

## Generated Leave Records sheet

| Record ID | Employee ID | Name | Date | Type of Leave | Credits | Remarks | Timestamp |
|---|---|---|---|---|---:|---|---|

## Development loop

```bash
clasp push
```

Then reload the Google Sheet to test changes.
