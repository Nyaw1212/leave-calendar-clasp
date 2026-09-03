/**
 * Fast chronological date entry for the SIMPLE sheet.
 *
 * YEAR is located by its header, so it may be placed anywhere on row 1.
 *
 * START (column C):
 *   - Full date: keeps the entered date.
 *   - M/D: uses YEAR from the same row when available.
 *   - Day only: reuses the preceding START month/year and rolls to the next
 *     month when needed.
 *
 * END (column D):
 *   - Is prefilled from START when blank.
 *   - Day only: uses the START month/year.
 *   - M/D: uses the START year and rolls to the next year when needed.
 */
function onEdit(e) {
  if (!e || !e.range || e.range.getNumRows() !== 1 || e.range.getNumColumns() !== 1) {
    return;
  }

  const range = e.range;
  const sheet = range.getSheet();
  const row = range.getRow();
  const column = range.getColumn();
  if (sheet.getName() !== 'SIMPLE' || row < 2) {
    return;
  }

  const columns = getSimpleColumnMap_(sheet);
  const watchedColumns = [columns.type, columns.start, columns.end, columns.year]
    .filter(function(value) { return Boolean(value); });
  if (!watchedColumns.includes(column)) {
    return;
  }
  if (typeof e.value === 'undefined' || String(e.value).trim() === '') {
    return;
  }

  const spreadsheet = e.source || sheet.getParent();
  const timeZone = spreadsheet.getSpreadsheetTimeZone();
  if (column === columns.year) {
    handleSimpleYearEdit_(spreadsheet, sheet, row, e.value, timeZone, columns);
    return;
  }

  const rowYear = readSimpleRowYear_(sheet, row, columns.year);
  if (column === columns.type) {
    handleSimpleTypeEdit_(spreadsheet, sheet, row, e.value, timeZone);
  } else if (column === columns.start) {
    handleSimpleStartEdit_(spreadsheet, sheet, range, e.value, timeZone, rowYear);
  } else {
    const enteredEnd = handleSimpleEndEdit_(spreadsheet, range, e.value, timeZone, rowYear);
    if (enteredEnd) promptSimpleMoneAllocation_(spreadsheet, sheet, row, timeZone);
  }
}

function getSimpleColumnMap_(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const columns = {};
  headers.forEach(function(header, index) {
    const key = String(header || '').trim().toUpperCase();
    if (key === 'TYPE') columns.type = index + 1;
    if (key === 'START') columns.start = index + 1;
    if (key === 'END') columns.end = index + 1;
    if (key === 'YEAR') columns.year = index + 1;
  });
  return columns;
}

function readSimpleRowYear_(sheet, row, yearColumn) {
  if (!yearColumn) return null;
  const value = Number(sheet.getRange(row, yearColumn).getValue());
  return Number.isInteger(value) && value >= 1900 && value <= 9999 ? value : null;
}

function handleSimpleYearEdit_(spreadsheet, sheet, row, rawValue, timeZone, columns) {
  const year = Number(String(rawValue).trim());
  if (!Number.isInteger(year) || year < 1900 || year > 9999) {
    spreadsheet.toast('Enter YEAR as four digits, for example 2014.', 'SIMPLE year', 5);
    return;
  }

  [columns.start, columns.end].filter(function(value) { return Boolean(value); })
    .forEach(function(dateColumn) {
      const cell = sheet.getRange(row, dateColumn);
      const value = cell.getValue();
      if (!isSimpleDate_(value)) return;
      const parts = simpleDateParts_(value, timeZone);
      const corrected = makeSimpleDate_(year, parts.month, parts.day, timeZone);
      if (corrected) cell.setValue(corrected).setNumberFormat('m/d/yyyy');
    });
}

function handleSimpleTypeEdit_(spreadsheet, sheet, row, rawValue, timeZone) {
  if (isSimpleMone_(rawValue)) {
    promptSimpleMoneAllocation_(spreadsheet, sheet, row, timeZone);
    return;
  }
  restoreSimpleCreditFormulas_(sheet, row);
}

function handleSimpleStartEdit_(spreadsheet, sheet, startCell, rawValue, timeZone, rowYear) {
  const previousStart = findPreviousSimpleDate_(
    sheet,
    startCell.getRow(),
    startCell.getColumn()
  );
  const enteredStart = inferSimpleDate_(
    rawValue,
    startCell.getValue(),
    previousStart,
    'start',
    timeZone,
    rowYear
  );
  if (!enteredStart) {
    spreadsheet.toast('Enter START as M/D/YYYY, M/D, or a day number.', 'SIMPLE date', 5);
    return;
  }

  startCell.setValue(enteredStart).setNumberFormat('m/d/yyyy');
  const endCell = startCell.offset(0, 1);
  if (endCell.isBlank()) {
    endCell.setValue(enteredStart).setNumberFormat('m/d/yyyy');
  }
  spreadsheet.setActiveRange(endCell);
  spreadsheet.toast(
    'END was set to the START date. Type only the ending day if it is in the same month.',
    'SIMPLE date',
    5
  );
}

function handleSimpleEndEdit_(spreadsheet, endCell, rawValue, timeZone, rowYear) {
  const startValue = endCell.offset(0, -1).getValue();
  const startDate = isSimpleDate_(startValue) ? startValue : null;
  const enteredEnd = inferSimpleDate_(
    rawValue,
    endCell.getValue(),
    startDate,
    'end',
    timeZone,
    rowYear
  );
  if (!enteredEnd) {
    spreadsheet.toast('Enter END as M/D/YYYY, M/D, or a day number.', 'SIMPLE date', 5);
    return null;
  }

  endCell.setValue(enteredEnd).setNumberFormat('m/d/yyyy');
  if (startDate && enteredEnd.getTime() < startDate.getTime()) {
    spreadsheet.toast('Warning: END is earlier than START.', 'SIMPLE date', 6);
  }
  return enteredEnd;
}

function promptSimpleMoneAllocation_(spreadsheet, sheet, row, timeZone) {
  const values = sheet.getRange(row, 2, 1, 3).getValues()[0];
  const leaveType = values[0];
  const start = values[1];
  const end = values[2];
  if (!isSimpleMone_(leaveType) || !isSimpleDate_(start) || !isSimpleDate_(end)) return;

  const total = simpleInclusiveDays_(start, end, timeZone);
  if (total <= 0) {
    spreadsheet.toast('Warning: END must not be earlier than START for MONE.', 'MONE', 6);
    return;
  }

  const response = SpreadsheetApp.getUi().prompt(
    'MONE allocation',
    'Total: ' + total.toFixed(3) +
      ' days (weekends and holidays included).\n\nEnter the VL amount. ' +
      'The remaining amount will automatically go to SL.',
    SpreadsheetApp.getUi().ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== SpreadsheetApp.getUi().Button.OK) return;

  const vl = Number(String(response.getResponseText()).trim());
  if (!Number.isFinite(vl) || vl < 0 || vl > total) {
    SpreadsheetApp.getUi().alert(
      'MONE allocation',
      'Enter a VL amount from 0.000 through ' + total.toFixed(3) + '.',
      SpreadsheetApp.getUi().ButtonSet.OK
    );
    return;
  }

  const sl = Math.round((total - vl) * 1000) / 1000;
  sheet.getRange(row, 6, 1, 2)
    .setValues([[Math.round(vl * 1000) / 1000, sl]])
    .setNumberFormat('0.000');
  spreadsheet.toast(
    'MONE saved: VL ' + vl.toFixed(3) + ' · SL ' + sl.toFixed(3),
    'MONE allocation',
    5
  );
}

function restoreSimpleCreditFormulas_(sheet, row) {
  const vlFormula = '=IF(OR(RC[-4]="",RC[-3]="",RC[-2]="",RC[-2]<RC[-3]),"",' +
    'IF(REGEXMATCH(UPPER(TRIM(RC[-4])),"SICK LEAVE|\\(SL\\)|' +
    'SPECIAL PRIVILEGE LEAVE|\\(SPL\\)|SPECIAL EMERGENCY|CALAMITY|' +
    'WELLNESS LEAVE|\\(WL\\)"),0,' +
    'NETWORKDAYS.INTL(RC[-3],RC[-2],1,' +
    'FILTER(PH_HOLIDAYS_LOCAL!R2C1:R795C1,' +
    'PH_HOLIDAYS_LOCAL!R2C3:R795C3="Regular Holiday"))))';
  const slFormula = '=IF(OR(RC[-5]="",RC[-4]="",RC[-3]="",RC[-3]<RC[-4]),"",' +
    'IF(REGEXMATCH(UPPER(RC[-5]),"SICK LEAVE|\\(SL\\)"),' +
    'NETWORKDAYS.INTL(RC[-4],RC[-3],1,' +
    'FILTER(PH_HOLIDAYS_LOCAL!R2C1:R795C1,' +
    'PH_HOLIDAYS_LOCAL!R2C3:R795C3="Regular Holiday")),0))';
  sheet.getRange(row, 6).setFormulaR1C1(vlFormula).setNumberFormat('0.000');
  sheet.getRange(row, 7).setFormulaR1C1(slFormula).setNumberFormat('0.000');
}

function simpleInclusiveDays_(start, end, timeZone) {
  const startParts = simpleDateParts_(start, timeZone);
  const endParts = simpleDateParts_(end, timeZone);
  const startUtc = Date.UTC(startParts.year, startParts.month - 1, startParts.day);
  const endUtc = Date.UTC(endParts.year, endParts.month - 1, endParts.day);
  return Math.floor((endUtc - startUtc) / 86400000) + 1;
}

function isSimpleMone_(value) {
  return String(value || '').trim().toUpperCase().startsWith('MONE');
}

function inferSimpleDate_(rawValue, parsedValue, referenceDate, mode, timeZone, preferredYear) {
  const raw = String(rawValue).trim();
  const dayOnly = raw.match(/^(\d{1,2})$/);
  const monthDay = raw.match(/^(\d{1,2})[\/-](\d{1,2})$/);

  if (dayOnly) {
    const reference = referenceDate || new Date();
    const parts = simpleDateParts_(reference, timeZone);
    let year = preferredYear || parts.year;
    let month = parts.month;
    const day = Number(dayOnly[1]);
    let candidate = makeSimpleDate_(year, month, day, timeZone);
    if (!candidate) return null;

    if (mode === 'start' && referenceDate && candidate.getTime() < referenceDate.getTime()) {
      month += 1;
      if (month > 12) {
        month = 1;
        year += 1;
      }
      candidate = makeSimpleDate_(year, month, day, timeZone);
    }
    return candidate;
  }

  if (monthDay) {
    const reference = referenceDate || new Date();
    const referenceParts = simpleDateParts_(reference, timeZone);
    let year = preferredYear || referenceParts.year;
    const month = Number(monthDay[1]);
    const day = Number(monthDay[2]);
    let candidate = makeSimpleDate_(year, month, day, timeZone);
    if (!candidate) return null;

    if (!preferredYear && referenceDate && candidate.getTime() < referenceDate.getTime()) {
      year += 1;
      candidate = makeSimpleDate_(year, month, day, timeZone);
    }
    return candidate;
  }

  if (isSimpleDate_(parsedValue)) {
    const parts = simpleDateParts_(parsedValue, timeZone);
    return makeSimpleDate_(preferredYear || parts.year, parts.month, parts.day, timeZone);
  }
  return null;
}

function findPreviousSimpleDate_(sheet, currentRow, column) {
  if (currentRow <= 2) return null;
  const values = sheet.getRange(2, column, currentRow - 2, 1).getValues();
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (isSimpleDate_(values[index][0])) return values[index][0];
  }
  return null;
}

function makeSimpleDate_(year, month, day, timeZone) {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const text = [year, padSimpleDate_(month), padSimpleDate_(day)].join('-');
  const parsed = Utilities.parseDate(text, timeZone, 'yyyy-MM-dd');
  const parts = simpleDateParts_(parsed, timeZone);
  return parts.year === year && parts.month === month && parts.day === day ? parsed : null;
}

function simpleDateParts_(value, timeZone) {
  const text = Utilities.formatDate(value, timeZone, 'yyyy-M-d').split('-');
  return {year: Number(text[0]), month: Number(text[1]), day: Number(text[2])};
}

function padSimpleDate_(value) {
  return String(value).padStart(2, '0');
}

function isSimpleDate_(value) {
  return Object.prototype.toString.call(value) === '[object Date]' && !Number.isNaN(value.getTime());
}
