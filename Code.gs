const CONFIG = {
  RECORDS_SHEET: 'Leave Records',
  EMPLOYEES_SHEET: 'Employees',
  HOLIDAYS_SHEET: 'Holidays',
  HEADERS: [
    'Record ID',
    'Employee ID',
    'Name',
    'Date',
    'Type of Leave',
    'Credits',
    'Remarks',
    'Timestamp'
  ]
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Leave Encoder')
    .addItem('Open Calendar', 'showLeaveSidebar')
    .addSeparator()
    .addItem('Set up sheets', 'setupSheets')
    .addToUi();
}

function showLeaveSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setTitle('Leave Encoder');
  SpreadsheetApp.getUi().showSidebar(html);
}

function setupSheets() {
  const ss = SpreadsheetApp.getActive();

  let records = ss.getSheetByName(CONFIG.RECORDS_SHEET);
  if (!records) records = ss.insertSheet(CONFIG.RECORDS_SHEET);

  if (records.getLastRow() === 0) {
    records.getRange(1, 1, 1, CONFIG.HEADERS.length)
      .setValues([CONFIG.HEADERS])
      .setFontWeight('bold');
    records.setFrozenRows(1);
    records.getRange('D:D').setNumberFormat('mm/dd/yyyy');
    records.getRange('F:F').setNumberFormat('0.00');
    records.getRange('H:H').setNumberFormat('mm/dd/yyyy hh:mm:ss');
  }

  let employees = ss.getSheetByName(CONFIG.EMPLOYEES_SHEET);
  if (!employees) employees = ss.insertSheet(CONFIG.EMPLOYEES_SHEET);

  if (employees.getLastRow() === 0) {
    employees.getRange(1, 1, 1, 2)
      .setValues([['Employee ID', 'Name']])
      .setFontWeight('bold');
    employees.setFrozenRows(1);
  }

  let holidays = ss.getSheetByName(CONFIG.HOLIDAYS_SHEET);
  if (!holidays) holidays = ss.insertSheet(CONFIG.HOLIDAYS_SHEET);

  if (holidays.getLastRow() === 0) {
    holidays.getRange(1, 1, 1, 3)
      .setValues([['Date', 'Holiday Name', 'Holiday Type']])
      .setFontWeight('bold');
    holidays.setFrozenRows(1);
    holidays.getRange('A:A').setNumberFormat('mm/dd/yyyy');
  }

  SpreadsheetApp.getUi().alert(
    'Setup complete. Add employees and holidays, then open Leave Encoder.'
  );
}

function getEmployees() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.EMPLOYEES_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return [];

  return sheet.getRange(2, 1, sheet.getLastRow() - 1, 2)
    .getDisplayValues()
    .filter(row => row[0] || row[1])
    .map(row => ({ employeeId: row[0], name: row[1] }));
}

function getCalendarData(employeeId, year, month) {
  return {
    holidays: getHolidays(year, month),
    existingRecords: employeeId
      ? getExistingLeaveDates(employeeId, year, month)
      : []
  };
}

function getHolidays(year, month) {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.HOLIDAYS_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return [];

  const tz = Session.getScriptTimeZone();
  const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, 3).getValues();

  return values
    .filter(row => {
      const date = row[0];
      return date instanceof Date &&
        date.getFullYear() === Number(year) &&
        date.getMonth() === Number(month) &&
        String(row[2]).trim().toLowerCase().includes('regular');
    })
    .map(row => ({
      date: Utilities.formatDate(row[0], tz, 'yyyy-MM-dd'),
      name: row[1] || 'Regular Holiday',
      type: row[2] || 'Regular Holiday'
    }));
}

function getExistingLeaveDates(employeeId, year, month) {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.RECORDS_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return [];

  const tz = Session.getScriptTimeZone();
  const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, CONFIG.HEADERS.length).getValues();

  return values
    .filter(row => {
      const date = row[3];
      return String(row[1]) === String(employeeId) &&
        date instanceof Date &&
        date.getFullYear() === Number(year) &&
        date.getMonth() === Number(month);
    })
    .map(row => ({
      date: Utilities.formatDate(row[3], tz, 'yyyy-MM-dd'),
      leaveType: row[4],
      credits: Number(row[5]) || 0
    }));
}

function saveLeaveRecords(payload) {
  validatePayload_(payload);

  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.RECORDS_SHEET);
  if (!sheet) {
    throw new Error('Leave Records sheet is missing. Run "Set up sheets" first.');
  }

  const existingKeys = getExistingRecordKeys_(sheet);
  const regularHolidayKeys = getRegularHolidayKeys_();
  const timestamp = new Date();
  let zeroCreditDates = 0;
  let skippedExisting = 0;

  const rows = payload.dates
    .filter(item => {
      if (existingKeys.has(`${payload.employeeId}|${item.date}`)) {
        skippedExisting++;
        return false;
      }
      return true;
    })
    .map(item => {
      const date = parseLocalDate_(item.date);
      const isWeekend = date.getDay() === 0 || date.getDay() === 6;
      const isRegularHoliday = regularHolidayKeys.has(item.date);
      const credits = isWeekend || isRegularHoliday
        ? 0
        : Number(item.credits);

      if (credits === 0) zeroCreditDates++;

      return [
        Utilities.getUuid(),
        payload.employeeId,
        payload.name,
        date,
        payload.leaveType,
        credits,
        payload.remarks || '',
        timestamp
      ];
    });

  if (!rows.length) {
    return {
      success: false,
      recordsAdded: 0,
      message: 'No records were added. The selected dates may already exist.'
    };
  }

  sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, CONFIG.HEADERS.length)
    .setValues(rows);

  return {
    success: true,
    recordsAdded: rows.length,
    message: [
      `${rows.length} leave record(s) saved.`,
      zeroCreditDates
        ? `${zeroCreditDates} weekend/regular holiday date(s) were saved with 0.00 credits.`
        : '',
      skippedExisting ? `${skippedExisting} existing date(s) skipped.` : ''
    ].filter(Boolean).join(' ')
  };
}

function getRegularHolidayKeys_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.HOLIDAYS_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return new Set();

  const tz = Session.getScriptTimeZone();
  const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, 3).getValues();

  return new Set(
    values
      .filter(row => row[0] instanceof Date &&
        String(row[2]).trim().toLowerCase().includes('regular'))
      .map(row => Utilities.formatDate(row[0], tz, 'yyyy-MM-dd'))
  );
}

function getExistingRecordKeys_(sheet) {
  if (sheet.getLastRow() < 2) return new Set();

  const tz = Session.getScriptTimeZone();
  const rows = sheet.getRange(2, 2, sheet.getLastRow() - 1, 3).getValues();

  return new Set(rows.map(row => {
    const employeeId = row[0];
    const date = row[2];
    const dateText = date instanceof Date
      ? Utilities.formatDate(date, tz, 'yyyy-MM-dd')
      : String(date);
    return `${employeeId}|${dateText}`;
  }));
}

function validatePayload_(payload) {
  if (!payload) throw new Error('Missing leave data.');
  if (!payload.employeeId) throw new Error('Select an employee.');
  if (!payload.name) throw new Error('Employee name is missing.');
  if (!payload.leaveType) throw new Error('Select a leave type.');
  if (!Array.isArray(payload.dates) || payload.dates.length === 0) {
    throw new Error('Select at least one date.');
  }

  payload.dates.forEach(item => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(item.date)) {
      throw new Error(`Invalid date: ${item.date}`);
    }
    const credits = Number(item.credits);
    if (!Number.isFinite(credits) || credits < 0) {
      throw new Error(`Invalid credits for ${item.date}`);
    }
  });
}

function parseLocalDate_(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return new Date(year, month - 1, day);
}
