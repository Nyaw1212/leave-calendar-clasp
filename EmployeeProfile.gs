const EMPLOYEE_PROFILE_HEADERS = [
  'Employee ID',
  'Name',
  'Date of Assumption',
  'Computed VL Earned',
  'Computed SL Earned'
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
    sheet.getRange(1, 1, 1, width)
      .setValues([EMPLOYEE_PROFILE_HEADERS])
      .setFontWeight('bold');
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
  if (sheet.getLastRow() < 2) throw new Error('Employee was not found in the Employees sheet.');

  const rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, EMPLOYEE_PROFILE_HEADERS.length).getValues();
  const index = rows.findIndex(row => String(row[0]).trim() === id);
  if (index < 0) throw new Error(`Employee ID ${id} was not found.`);

  const row = rows[index];
  const assumptionDate = row[2] instanceof Date ? stripTime_(row[2]) : null;
  const asOfDate = stripTime_(new Date());
  const computed = assumptionDate
    ? computeCscLeaveCredits_(id, assumptionDate, asOfDate)
    : emptyComputedProfile_(id, row[1]);

  if (assumptionDate) {
    sheet.getRange(index + 2, 4, 1, 2)
      .setValues([[computed.earnedVl, computed.earnedSl]])
      .setNumberFormat('0.000');
  }

  return {
    employeeId: String(row[0]),
    name: String(row[1] || ''),
    assumptionDate: assumptionDate
      ? Utilities.formatDate(assumptionDate, Session.getScriptTimeZone(), 'yyyy-MM-dd')
      : '',
    ...computed
  };
}

function saveEmployeeProfile(payload) {
  payload = payload || {};
  const employeeId = String(payload.employeeId || '').trim();
  if (!employeeId) throw new Error('Select an employee.');

  const assumptionDate = parseProfileDate_(payload.assumptionDate);
  if (!assumptionDate) throw new Error('Enter a valid Date of Assumption / Entry.');
  if (stripTime_(assumptionDate) > stripTime_(new Date())) {
    throw new Error('Date of Assumption cannot be in the future.');
  }

  const sheet = ensureEmployeeProfileHeaders_();
  if (sheet.getLastRow() < 2) throw new Error('Employee was not found in the Employees sheet.');

  const ids = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getDisplayValues().flat();
  const index = ids.findIndex(value => String(value).trim() === employeeId);
  if (index < 0) throw new Error(`Employee ID ${employeeId} was not found.`);

  const rowNumber = index + 2;
  const computed = computeCscLeaveCredits_(employeeId, assumptionDate, stripTime_(new Date()));

  sheet.getRange(rowNumber, 3, 1, 3).setValues([[
    assumptionDate,
    computed.earnedVl,
    computed.earnedSl
  ]]);
  sheet.getRange(rowNumber, 3).setNumberFormat('mm/dd/yyyy');
  sheet.getRange(rowNumber, 4, 1, 2).setNumberFormat('0.000');

  return {
    success: true,
    employeeId,
    message: 'Date of Assumption saved. CSC leave credits were recalculated automatically.',
    profile: getEmployeeProfile(employeeId)
  };
}

function computeCscLeaveCredits_(employeeId, assumptionDate, asOfDate) {
  const earned = computeCscAccrual_(assumptionDate, asOfDate);
  const opening = computeOpeningCredit_(assumptionDate);
  const used = getRecordedLeaveUsage_(employeeId, asOfDate);
  const earnedRounded = roundProfileCredit_(earned);
  const openingRounded = roundProfileCredit_(opening);
  const usedVl = roundProfileCredit_(used.vl);
  const usedSl = roundProfileCredit_(used.sl);
  const balanceVl = roundProfileCredit_(earned - used.vl);
  const balanceSl = roundProfileCredit_(earned - used.sl);

  return {
    asOfDate: Utilities.formatDate(asOfDate, Session.getScriptTimeZone(), 'yyyy-MM-dd'),
    earnedVl: earnedRounded,
    earnedSl: earnedRounded,
    openingVl: openingRounded,
    openingSl: openingRounded,
    usedVl,
    usedSl,
    balanceVl,
    balanceSl
  };
}

/** First credit posted for the partial month containing the assumption date. */
function computeOpeningCredit_(assumptionDate) {
  const start = stripTime_(assumptionDate);
  const monthEnd = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  return Math.min(inclusiveDays_(start, monthEnd) / 24, 1.25);
}

/**
 * CSC basis: 1 day VL and 1 day SL for every 24 days of actual service.
 * Complete calendar months earn 1.250. Partial first/current months use
 * daily accrual of 1/24, capped at 1.250 for a calendar month.
 */
function computeCscAccrual_(startDate, endDate) {
  const start = stripTime_(startDate);
  const end = stripTime_(endDate);
  if (end < start) return 0;

  if (start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth()) {
    return Math.min(inclusiveDays_(start, end) / 24, 1.25);
  }

  const firstMonthEnd = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  const firstPartial = Math.min(inclusiveDays_(start, firstMonthEnd) / 24, 1.25);

  const currentMonthStart = new Date(end.getFullYear(), end.getMonth(), 1);
  const currentPartial = Math.min(inclusiveDays_(currentMonthStart, end) / 24, 1.25);

  const firstFullMonth = new Date(start.getFullYear(), start.getMonth() + 1, 1);
  const monthsBetween = Math.max(
    0,
    (currentMonthStart.getFullYear() - firstFullMonth.getFullYear()) * 12 +
      currentMonthStart.getMonth() - firstFullMonth.getMonth()
  );

  return firstPartial + monthsBetween * 1.25 + currentPartial;
}

function getRecordedLeaveUsage_(employeeId, asOfDate) {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.RECORDS_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return { vl: 0, sl: 0 };

  const rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, CONFIG.HEADERS.length).getValues();
  return rows.reduce((totals, row) => {
    const id = String(row[1] || '').trim();
    const date = row[3];
    const type = String(row[4] || '').trim().toUpperCase();
    const credits = Number(row[5]) || 0;

    if (id !== String(employeeId) || !(date instanceof Date) || stripTime_(date) > asOfDate) return totals;
    if (type === 'VL' || type === 'FL') totals.vl += credits;
    if (type === 'SL') totals.sl += credits;
    return totals;
  }, { vl: 0, sl: 0 });
}

function emptyComputedProfile_(employeeId, name) {
  return {
    employeeId: String(employeeId || ''),
    name: String(name || ''),
    asOfDate: Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd'),
    earnedVl: 0,
    earnedSl: 0,
    openingVl: 0,
    openingSl: 0,
    usedVl: 0,
    usedSl: 0,
    balanceVl: 0,
    balanceSl: 0
  };
}

function inclusiveDays_(start, end) {
  return Math.floor((stripTime_(end) - stripTime_(start)) / 86400000) + 1;
}

function stripTime_(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function parseProfileDate_(value) {
  if (value instanceof Date && !isNaN(value)) return stripTime_(value);
  const text = String(value || '').trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);

  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day
    ? date
    : null;
}

function roundProfileCredit_(value) {
  return Math.round(Number(value) * 1000) / 1000;
}
