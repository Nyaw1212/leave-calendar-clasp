const EMPLOYEE_PROFILE_HEADERS = [
  'Employee ID',
  'Name',
  'Date of Assumption',
  'Opening VL',
  'Opening SL'
];

function ensureEmployeeProfileHeaders_() {
  const ss = SpreadsheetApp.getActive();
  let sheet = ss.getSheetByName(CONFIG.EMPLOYEES_SHEET);
  if (!sheet) sheet = ss.insertSheet(CONFIG.EMPLOYEES_SHEET);

  const width = EMPLOYEE_PROFILE_HEADERS.length;
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, width)
      .setValues([EMPLOYEE_PROFILE_HEADERS])
      .setFontWeight('bold');
  } else {
    const current = sheet.getRange(1, 1, 1, width).getDisplayValues()[0];
    EMPLOYEE_PROFILE_HEADERS.forEach((header, index) => {
      if (!current[index]) sheet.getRange(1, index + 1).setValue(header);
    });
    sheet.getRange(1, 1, 1, width).setFontWeight('bold');
  }

  sheet.setFrozenRows(1);
  sheet.getRange('C:C').setNumberFormat('mm/dd/yyyy');
  sheet.getRange('D:E').setNumberFormat('0.000');
  return sheet;
}

function getEmployeeProfile(employeeId) {
  const sheet = ensureEmployeeProfileHeaders_();
  const id = String(employeeId || '').trim();
  if (!id) throw new Error('Select an employee.');

  if (sheet.getLastRow() < 2) {
    throw new Error('Employee was not found in the Employees sheet.');
  }

  const rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, EMPLOYEE_PROFILE_HEADERS.length).getValues();
  const index = rows.findIndex(row => String(row[0]).trim() === id);
  if (index < 0) throw new Error(`Employee ID ${id} was not found.`);

  const row = rows[index];
  const tz = Session.getScriptTimeZone();
  return {
    employeeId: String(row[0]),
    name: String(row[1] || ''),
    assumptionDate: row[2] instanceof Date
      ? Utilities.formatDate(row[2], tz, 'yyyy-MM-dd')
      : '',
    openingVl: Number(row[3]) || 0,
    openingSl: Number(row[4]) || 0
  };
}

function saveEmployeeProfile(payload) {
  payload = payload || {};
  const employeeId = String(payload.employeeId || '').trim();
  if (!employeeId) throw new Error('Select an employee.');

  const assumptionDate = parseProfileDate_(payload.assumptionDate);
  if (!assumptionDate) throw new Error('Enter a valid Date of Assumption / Entry.');

  const openingVl = Number(payload.openingVl);
  const openingSl = Number(payload.openingSl);
  if (!Number.isFinite(openingVl) || openingVl < 0) {
    throw new Error('Opening VL must be zero or a positive number.');
  }
  if (!Number.isFinite(openingSl) || openingSl < 0) {
    throw new Error('Opening SL must be zero or a positive number.');
  }

  const sheet = ensureEmployeeProfileHeaders_();
  if (sheet.getLastRow() < 2) throw new Error('Employee was not found in the Employees sheet.');

  const ids = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getDisplayValues().flat();
  const index = ids.findIndex(value => String(value).trim() === employeeId);
  if (index < 0) throw new Error(`Employee ID ${employeeId} was not found.`);

  const rowNumber = index + 2;
  sheet.getRange(rowNumber, 3, 1, 3).setValues([[
    assumptionDate,
    roundProfileCredit_(openingVl),
    roundProfileCredit_(openingSl)
  ]]);
  sheet.getRange(rowNumber, 3).setNumberFormat('mm/dd/yyyy');
  sheet.getRange(rowNumber, 4, 1, 2).setNumberFormat('0.000');

  return {
    success: true,
    employeeId,
    message: 'Employee service details saved.'
  };
}

function parseProfileDate_(value) {
  if (value instanceof Date && !isNaN(value)) return value;
  const text = String(value || '').trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);

  return date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
    ? date
    : null;
}

function roundProfileCredit_(value) {
  return Math.round(Number(value) * 1000) / 1000;
}
