const CONFIG = {
  RECORDS_SHEET: 'Leave Records',
  EMPLOYEES_SHEET: 'Employees',
  HOLIDAYS_SHEET: 'Holidays',
  HOLIDAY_HEADERS: [
    'Date',
    'Holiday Name',
    'Holiday Type',
    'Year',
    'Source',
    'Imported At'
  ],
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
    .createMenu('Leave History Recorder')
    .addItem('Open Calendar', 'showLeaveSidebar')
    .addSeparator()
    .addItem('Import Holiday Range', 'showHolidayImportDialog')
    .addItem('Set up sheets', 'setupSheets')
    .addToUi();
}

function showLeaveSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setTitle('Leave History Recorder');
  SpreadsheetApp.getUi().showSidebar(html);
}

function showHolidayImportDialog() {
  const html = HtmlService.createHtmlOutputFromFile('ImportHolidays')
    .setWidth(430)
    .setHeight(520);
  SpreadsheetApp.getUi().showModalDialog(html, 'Import Philippine Holidays');
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

  ensureHolidaySheet_();

  SpreadsheetApp.getUi().alert(
    'Setup complete. Add employees or import holidays, then open Leave History Recorder.'
  );
}

function ensureHolidaySheet_() {
  const ss = SpreadsheetApp.getActive();
  let sheet = ss.getSheetByName(CONFIG.HOLIDAYS_SHEET);
  if (!sheet) sheet = ss.insertSheet(CONFIG.HOLIDAYS_SHEET);

  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, CONFIG.HOLIDAY_HEADERS.length)
      .setValues([CONFIG.HOLIDAY_HEADERS])
      .setFontWeight('bold');
  } else {
    const currentHeaders = sheet
      .getRange(1, 1, 1, Math.max(sheet.getLastColumn(), CONFIG.HOLIDAY_HEADERS.length))
      .getDisplayValues()[0];

    CONFIG.HOLIDAY_HEADERS.forEach((header, index) => {
      if (!currentHeaders[index]) sheet.getRange(1, index + 1).setValue(header);
    });
    sheet.getRange(1, 1, 1, CONFIG.HOLIDAY_HEADERS.length).setFontWeight('bold');
  }

  sheet.setFrozenRows(1);
  sheet.getRange('A:A').setNumberFormat('mm/dd/yyyy');
  sheet.getRange('F:F').setNumberFormat('mm/dd/yyyy hh:mm:ss');
  return sheet;
}

function getInitialData(year, month) {
  return {
    employees: getEmployees(),
    appInfo: typeof getAppInfo === 'function' ? getAppInfo() : null,
    calendar: getCalendarData('', year, month)
  };
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
  const cache = CacheService.getDocumentCache();
  const cacheKey = `regular-holidays-${year}-${month}`;
  const cached = cache.get(cacheKey);
  if (cached) return JSON.parse(cached);

  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.HOLIDAYS_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return [];

  const tz = Session.getScriptTimeZone();
  const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, 3).getValues();
  const holidays = values
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

  cache.put(cacheKey, JSON.stringify(holidays), 21600);
  return holidays;
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

/**
 * Imports one year at a time. The dialog calls this repeatedly for a range so
 * each Apps Script execution stays short and progress can be displayed.
 */
function importHolidayYear(year, forceRefresh) {
  year = Number(year);
  if (!Number.isInteger(year) || year < 1980 || year > 2100) {
    throw new Error('Year must be between 1980 and 2100.');
  }

  const sheet = ensureHolidaySheet_();
  const existing = getHolidayRowsForYear_(sheet, year);

  if (existing.length && !forceRefresh) {
    return {
      year,
      status: 'skipped',
      added: 0,
      removed: 0,
      message: `${year}: already stored (${existing.length} row(s)).`
    };
  }

  const sourceUrl = `https://www.timeanddate.com/holidays/philippines/${year}`;
  const response = UrlFetchApp.fetch(sourceUrl, {
    muteHttpExceptions: true,
    followRedirects: true,
    headers: {
      'User-Agent': 'Mozilla/5.0 (compatible; LeaveHistoryRecorder/0.3; GoogleAppsScript)'
    }
  });

  const statusCode = response.getResponseCode();
  if (statusCode !== 200) {
    return {
      year,
      status: 'error',
      added: 0,
      removed: 0,
      message: `${year}: Timeanddate returned HTTP ${statusCode}.`
    };
  }

  const holidays = parseTimeAndDateRegularHolidays_(response.getContentText(), year);
  if (!holidays.length) {
    return {
      year,
      status: 'warning',
      added: 0,
      removed: 0,
      message: `${year}: no rows explicitly classified as Regular Holiday were found.`
    };
  }

  let removed = 0;
  if (forceRefresh && existing.length) {
    deleteHolidayRows_(sheet, existing.map(item => item.row));
    removed = existing.length;
  }

  const importedAt = new Date();
  const rows = holidays.map(item => [
    item.date,
    item.name,
    item.type,
    year,
    sourceUrl,
    importedAt
  ]);

  sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, CONFIG.HOLIDAY_HEADERS.length)
    .setValues(rows);
  sheet.getRange(2, 1, Math.max(sheet.getLastRow() - 1, 1), 1).setNumberFormat('mm/dd/yyyy');
  sheet.getRange(2, 6, Math.max(sheet.getLastRow() - 1, 1), 1).setNumberFormat('mm/dd/yyyy hh:mm:ss');

  clearHolidayCacheForYear_(year);

  return {
    year,
    status: 'imported',
    added: rows.length,
    removed,
    message: `${year}: imported ${rows.length} regular holiday(s).`
  };
}

function getHolidayRowsForYear_(sheet, year) {
  if (sheet.getLastRow() < 2) return [];

  const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, CONFIG.HOLIDAY_HEADERS.length).getValues();
  return values.reduce((matches, row, index) => {
    const date = row[0];
    const storedYear = Number(row[3]);
    const dateYear = date instanceof Date ? date.getFullYear() : null;
    if (storedYear === year || dateYear === year) {
      matches.push({ row: index + 2, values: row });
    }
    return matches;
  }, []);
}

function deleteHolidayRows_(sheet, rowNumbers) {
  rowNumbers
    .slice()
    .sort((a, b) => b - a)
    .forEach(row => sheet.deleteRow(row));
}

function parseTimeAndDateRegularHolidays_(html, year) {
  const rows = [];
  const seen = new Set();
  const rowRegex = /<tr\b[^>]*>([\s\S]*?)<\/tr>/gi;
  let rowMatch;

  while ((rowMatch = rowRegex.exec(html)) !== null) {
    const cells = [];
    const cellRegex = /<t[hd]\b[^>]*>([\s\S]*?)<\/t[hd]>/gi;
    let cellMatch;

    while ((cellMatch = cellRegex.exec(rowMatch[1])) !== null) {
      cells.push(cleanHtmlText_(cellMatch[1]));
    }

    const typeIndex = cells.findIndex(cell => /^Regular Holiday$/i.test(cell.trim()));
    if (typeIndex < 0 || cells.length < 3) continue;

    const dateText = cells[0];
    const date = parseTimeAndDateDate_(dateText, year);
    if (!date) continue;

    const name = cells[typeIndex - 1] || 'Regular Holiday';
    const key = Utilities.formatDate(date, Session.getScriptTimeZone(), 'yyyy-MM-dd');
    if (seen.has(key)) continue;
    seen.add(key);

    rows.push({
      date,
      name,
      type: 'Regular Holiday'
    });
  }

  return rows.sort((a, b) => a.date - b.date);
}

function parseTimeAndDateDate_(text, year) {
  const normalized = String(text)
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+/i, '');

  const match = normalized.match(/^(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})/i);
  if (!match) return null;

  const monthKey = match[1].slice(0, 3).toLowerCase();
  const monthMap = {
    jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5,
    jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11
  };
  const month = monthMap[monthKey];
  const day = Number(match[2]);
  if (month === undefined || day < 1 || day > 31) return null;

  const date = new Date(year, month, day);
  return date.getFullYear() === year && date.getMonth() === month && date.getDate() === day
    ? date
    : null;
}

function cleanHtmlText_(html) {
  return decodeHtmlEntities_(String(html)
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim());
}

function decodeHtmlEntities_(text) {
  const entities = {
    '&amp;': '&', '&quot;': '"', '&#39;': "'", '&apos;': "'",
    '&lt;': '<', '&gt;': '>', '&nbsp;': ' ', '&ndash;': '–', '&mdash;': '—'
  };
  return text
    .replace(/&(amp|quot|#39|apos|lt|gt|nbsp|ndash|mdash);/g, match => entities[match] || match)
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCharCode(parseInt(code, 16)));
}

function clearHolidayCacheForYear_(year) {
  const cache = CacheService.getDocumentCache();
  for (let month = 0; month < 12; month++) {
    cache.remove(`regular-holidays-${year}-${month}`);
  }
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
      const credits = isWeekend || isRegularHoliday ? 0 : Number(item.credits);

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
      message: 'No history records were added. The selected dates may already exist.'
    };
  }

  sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, CONFIG.HEADERS.length)
    .setValues(rows);

  return {
    success: true,
    recordsAdded: rows.length,
    message: [
      `${rows.length} leave history record(s) saved.`,
      zeroCreditDates
        ? `${zeroCreditDates} weekend/regular holiday date(s) were recorded with 0.00 credits.`
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
  if (!payload) throw new Error('Missing leave history data.');
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
