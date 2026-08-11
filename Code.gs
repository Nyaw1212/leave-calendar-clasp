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
    'TYPE',
    'START',
    'END',
    'STATUS',
    'VL',
    'SL',
    'LWOP',
    'Record ID',
    'Employee ID',
    'Name',
    'Remarks',
    'Timestamp'
  ]
};

const LEGACY_RECORD_HEADERS = [
  'Record ID',
  'Employee ID',
  'Name',
  'Date',
  'Type of Leave',
  'Credits',
  'Remarks',
  'Timestamp'
];

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
  ensureLeaveRecordsSheet_();

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
    'Setup complete. Leave Records is MAGCLIP-ready: TYPE, START, END, STATUS, VL, SL, LWOP.'
  );
}

function ensureLeaveRecordsSheet_() {
  const ss = SpreadsheetApp.getActive();
  let sheet = ss.getSheetByName(CONFIG.RECORDS_SHEET);
  if (!sheet) sheet = ss.insertSheet(CONFIG.RECORDS_SHEET);

  if (sheet.getLastRow() === 0) {
    writeLeaveRecordHeaders_(sheet);
    return sheet;
  }

  const width = Math.max(sheet.getLastColumn(), LEGACY_RECORD_HEADERS.length, CONFIG.HEADERS.length);
  const headers = sheet.getRange(1, 1, 1, width).getDisplayValues()[0];
  const isLegacy = LEGACY_RECORD_HEADERS.every((header, index) => headers[index] === header);
  const isCurrent = CONFIG.HEADERS.slice(0, 7).every((header, index) => headers[index] === header);

  if (isLegacy) {
    migrateLegacyLeaveRecords_(sheet);
  } else if (!isCurrent) {
    throw new Error(
      'Leave Records has an unknown column layout. Expected either the old daily layout or the MAGCLIP layout.'
    );
  } else {
    sheet.getRange(1, 1, 1, CONFIG.HEADERS.length)
      .setValues([CONFIG.HEADERS])
      .setFontWeight('bold');
    formatLeaveRecordsSheet_(sheet);
  }

  return sheet;
}

function writeLeaveRecordHeaders_(sheet) {
  sheet.getRange(1, 1, 1, CONFIG.HEADERS.length)
    .setValues([CONFIG.HEADERS])
    .setFontWeight('bold');
  formatLeaveRecordsSheet_(sheet);
}

function formatLeaveRecordsSheet_(sheet) {
  sheet.setFrozenRows(1);
  sheet.getRange('B:C').setNumberFormat('mm/dd/yyyy');
  sheet.getRange('E:G').setNumberFormat('0.000');
  sheet.getRange('L:L').setNumberFormat('mm/dd/yyyy hh:mm:ss');
}

function migrateLegacyLeaveRecords_(sheet) {
  const ss = sheet.getParent();
  const backupName = 'Leave Records Backup ' + Utilities.formatDate(
    new Date(),
    Session.getScriptTimeZone(),
    'yyyyMMdd-HHmmss'
  );
  sheet.copyTo(ss).setName(backupName);

  const legacyRows = sheet.getLastRow() < 2
    ? []
    : sheet.getRange(2, 1, sheet.getLastRow() - 1, LEGACY_RECORD_HEADERS.length).getValues();

  const normalized = legacyRows
    .filter(row => row.some(value => value !== '' && value !== null))
    .map(row => ({
      recordId: String(row[0] || Utilities.getUuid()),
      employeeId: String(row[1] || ''),
      name: String(row[2] || ''),
      date: row[3] instanceof Date ? stripDateTime_(row[3]) : null,
      leaveType: normalizeLeaveTypeName_(row[4]),
      credits: Number(row[5]) || 0,
      remarks: String(row[6] || ''),
      timestamp: row[7] instanceof Date ? row[7] : new Date()
    }))
    .filter(item => item.employeeId && item.date)
    .sort((a, b) => {
      const keyA = [a.employeeId, a.leaveType, a.remarks].join('|');
      const keyB = [b.employeeId, b.leaveType, b.remarks].join('|');
      return keyA.localeCompare(keyB) || a.date - b.date;
    });

  const groups = [];
  normalized.forEach(item => {
    const previous = groups[groups.length - 1];
    const sameSeries = previous &&
      previous.employeeId === item.employeeId &&
      previous.name === item.name &&
      previous.leaveType === item.leaveType &&
      previous.remarks === item.remarks &&
      daysBetween_(previous.end, item.date) === 1;

    if (sameSeries) {
      previous.end = item.date;
      previous.credits += item.credits;
      if (item.timestamp > previous.timestamp) previous.timestamp = item.timestamp;
      return;
    }

    groups.push({
      recordId: item.recordId,
      employeeId: item.employeeId,
      name: item.name,
      leaveType: item.leaveType,
      start: item.date,
      end: item.date,
      credits: item.credits,
      remarks: item.remarks,
      timestamp: item.timestamp
    });
  });

  const rows = groups.map(group => buildMagclipRow_(group));
  sheet.clearContents();
  writeLeaveRecordHeaders_(sheet);
  if (rows.length) {
    sheet.getRange(2, 1, rows.length, CONFIG.HEADERS.length).setValues(rows);
  }
  formatLeaveRecordsSheet_(sheet);
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
  const sheet = ensureLeaveRecordsSheet_();
  if (sheet.getLastRow() < 2) return [];

  const tz = Session.getScriptTimeZone();
  const monthStart = new Date(Number(year), Number(month), 1);
  const monthEnd = new Date(Number(year), Number(month) + 1, 0);
  const values = sheet.getRange(2, 1, sheet.getLastRow() - 1, CONFIG.HEADERS.length).getValues();
  const result = [];

  values.forEach(row => {
    if (String(row[8]) !== String(employeeId)) return;
    if (!(row[1] instanceof Date) || !(row[2] instanceof Date)) return;

    const start = stripDateTime_(row[1]);
    const end = stripDateTime_(row[2]);
    if (end < monthStart || start > monthEnd) return;

    for (let date = new Date(Math.max(start.getTime(), monthStart.getTime()));
      date <= end && date <= monthEnd;
      date.setDate(date.getDate() + 1)) {
      result.push({
        date: Utilities.formatDate(date, tz, 'yyyy-MM-dd'),
        leaveType: row[0],
        credits: 0
      });
    }
  });

  return result;
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

  const sheet = ensureLeaveRecordsSheet_();
  const existingKeys = getExistingRecordKeys_(sheet);
  const regularHolidayKeys = getRegularHolidayKeys_();
  const timestamp = new Date();
  let skippedExisting = 0;
  let zeroCreditDates = 0;

  const dates = payload.dates
    .map(item => ({
      date: String(item.date || ''),
      credits: Number(item.credits) || 0
    }))
    .sort((a, b) => a.date.localeCompare(b.date))
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
      const credits = isWeekend || isRegularHoliday ? 0 : item.credits;
      if (credits === 0) zeroCreditDates++;
      return { date: item.date, dateValue: date, credits };
    });

  if (!dates.length) {
    return {
      success: false,
      recordsAdded: 0,
      message: 'No history records were added. The selected dates may already exist.'
    };
  }

  const groups = groupConsecutiveDates_(dates);
  const leaveType = normalizeLeaveTypeName_(payload.leaveType);
  const rows = groups.map(group => buildMagclipRow_({
    recordId: Utilities.getUuid(),
    employeeId: payload.employeeId,
    name: payload.name,
    leaveType,
    start: group[0].dateValue,
    end: group[group.length - 1].dateValue,
    credits: group.reduce((sum, item) => sum + item.credits, 0),
    remarks: payload.remarks || '',
    timestamp
  }));

  sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, CONFIG.HEADERS.length)
    .setValues(rows);
  formatLeaveRecordsSheet_(sheet);

  return {
    success: true,
    recordsAdded: rows.length,
    datesAdded: dates.length,
    message: [
      `${rows.length} grouped leave record(s) saved from ${dates.length} selected date(s).`,
      zeroCreditDates ? `${zeroCreditDates} weekend/regular holiday date(s) carried 0 credit.` : '',
      skippedExisting ? `${skippedExisting} existing date(s) skipped.` : ''
    ].filter(Boolean).join(' ')
  };
}

function buildMagclipRow_(item) {
  const credits = Number(item.credits) || 0;
  const type = normalizeLeaveTypeName_(item.leaveType);
  return [
    type,
    item.start,
    item.end,
    'A',
    isVlCharge_(type) ? credits : 0,
    isSlCharge_(type) ? credits : 0,
    0,
    item.recordId || Utilities.getUuid(),
    item.employeeId || '',
    item.name || '',
    item.remarks || '',
    item.timestamp || new Date()
  ];
}

function groupConsecutiveDates_(dates) {
  const groups = [];
  dates.forEach(item => {
    const group = groups[groups.length - 1];
    if (!group || daysBetween_(group[group.length - 1].dateValue, item.dateValue) !== 1) {
      groups.push([item]);
    } else {
      group.push(item);
    }
  });
  return groups;
}

function normalizeLeaveTypeName_(value) {
  const text = String(value || 'Other').trim();
  const key = text.toUpperCase();
  const map = {
    VL: 'Vacation Leave',
    'VACATION LEAVE': 'Vacation Leave',
    SL: 'Sick Leave',
    'SICK LEAVE': 'Sick Leave',
    FL: 'Forced Leave',
    'FORCED LEAVE': 'Forced Leave',
    SPL: 'Special Privilege Leave',
    'SPECIAL PRIVILEGE LEAVE': 'Special Privilege Leave',
    CTO: 'Compensatory Time Off',
    'COMPENSATORY TIME OFF': 'Compensatory Time Off',
    ML: 'Maternity Leave',
    'MATERNITY LEAVE': 'Maternity Leave',
    PL: 'Paternity Leave',
    'PATERNITY LEAVE': 'Paternity Leave'
  };
  return map[key] || text;
}

function isVlCharge_(leaveType) {
  const text = String(leaveType || '').toUpperCase();
  return text === 'VL' || text === 'VACATION LEAVE' || text === 'FL' || text === 'FORCED LEAVE';
}

function isSlCharge_(leaveType) {
  const text = String(leaveType || '').toUpperCase();
  return text === 'SL' || text === 'SICK LEAVE';
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
  const rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, CONFIG.HEADERS.length).getValues();
  const keys = new Set();

  rows.forEach(row => {
    const employeeId = String(row[8] || '');
    const start = row[1];
    const end = row[2];
    if (!employeeId || !(start instanceof Date) || !(end instanceof Date)) return;

    for (let date = stripDateTime_(start); date <= end; date.setDate(date.getDate() + 1)) {
      keys.add(`${employeeId}|${Utilities.formatDate(date, tz, 'yyyy-MM-dd')}`);
    }
  });

  return keys;
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

function stripDateTime_(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function daysBetween_(a, b) {
  return Math.round((stripDateTime_(b) - stripDateTime_(a)) / 86400000);
}