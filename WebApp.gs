function doGet() {
  const base = HtmlService.createHtmlOutputFromFile('WebAppPage').getContent();
  const enhancements = HtmlService.createHtmlOutputFromFile('WebUxEnhancements').getContent();
  const draftMarkers = HtmlService.createHtmlOutputFromFile('DraftMarkers').getContent();
  const workflowEnhancements = HtmlService.createHtmlOutputFromFile('WebWorkflowEnhancements').getContent();
  const magclipUxFixes = HtmlService.createHtmlOutputFromFile('MagclipUxFixes').getContent();
  const creditRulesHelper = HtmlService.createHtmlOutputFromFile('CreditRulesHelper').getContent();
  const draftHoverHelper = HtmlService.createHtmlOutputFromFile('DraftHoverHelper').getContent();
  const enterLeaveGuard = HtmlService.createHtmlOutputFromFile('EnterLeaveGuard').getContent();
  return HtmlService.createHtmlOutput(
    base.replace(
      '</body>',
      enhancements + '\n' + draftMarkers + '\n' + workflowEnhancements + '\n' + magclipUxFixes + '\n' + creditRulesHelper + '\n' + draftHoverHelper + '\n' + enterLeaveGuard + '\n</body>'
    )
  )
    .setTitle('Leave History Recorder')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function getWebAppBootstrap() {
  const today = new Date();
  return {
    employees: getEmployees(),
    appInfo: typeof getAppInfo === 'function' ? getAppInfo() : null,
    today: Utilities.formatDate(today, Session.getScriptTimeZone(), 'yyyy-MM-dd')
  };
}

function getWebAppCalendarData(employeeId, startYear, startMonth, monthCount) {
  startYear = Number(startYear);
  startMonth = Number(startMonth);
  monthCount = Math.max(1, Math.min(Number(monthCount) || 3, 12));

  const firstMonth = new Date(startYear, startMonth, 1);
  const endExclusive = new Date(startYear, startMonth + monthCount, 1);
  const tz = Session.getScriptTimeZone();
  const ss = SpreadsheetApp.getActive();

  const monthMap = new Map();
  const months = [];
  for (let offset = 0; offset < monthCount; offset++) {
    const date = new Date(startYear, startMonth + offset, 1);
    const item = {
      year: date.getFullYear(),
      month: date.getMonth(),
      holidays: [],
      existingRecords: []
    };
    months.push(item);
    monthMap.set(`${item.year}-${item.month}`, item);
  }

  const holidaySheet = ss.getSheetByName(CONFIG.HOLIDAYS_SHEET);
  if (holidaySheet && holidaySheet.getLastRow() >= 2) {
    const rows = holidaySheet
      .getRange(2, 1, holidaySheet.getLastRow() - 1, 3)
      .getValues();

    rows.forEach(row => {
      const date = row[0];
      const type = String(row[2] || '').trim();
      if (!(date instanceof Date)) return;
      if (date < firstMonth || date >= endExclusive) return;
      if (!type.toLowerCase().includes('regular')) return;

      const bucket = monthMap.get(`${date.getFullYear()}-${date.getMonth()}`);
      if (!bucket) return;
      bucket.holidays.push({
        date: Utilities.formatDate(date, tz, 'yyyy-MM-dd'),
        name: row[1] || 'Regular Holiday',
        type: type || 'Regular Holiday'
      });
    });
  }

  if (employeeId) {
    const recordsSheet = ensureLeaveRecordsSheet_();
    if (recordsSheet.getLastRow() >= 2) {
      const rows = recordsSheet
        .getRange(2, 1, recordsSheet.getLastRow() - 1, CONFIG.HEADERS.length)
        .getValues();

      rows.forEach(row => {
        if (String(row[8]) !== String(employeeId)) return;
        if (!(row[1] instanceof Date) || !(row[2] instanceof Date)) return;

        const recordStart = stripDateTime_(row[1]);
        const recordEnd = stripDateTime_(row[2]);
        if (recordEnd < firstMonth || recordStart >= endExclusive) return;

        for (let date = new Date(Math.max(recordStart.getTime(), firstMonth.getTime()));
          date <= recordEnd && date < endExclusive;
          date.setDate(date.getDate() + 1)) {
          const bucket = monthMap.get(`${date.getFullYear()}-${date.getMonth()}`);
          if (!bucket) continue;
          bucket.existingRecords.push({
            date: Utilities.formatDate(date, tz, 'yyyy-MM-dd'),
            leaveType: row[0],
            credits: 0
          });
        }
      });
    }
  }

  let profile = null;
  if (employeeId) {
    try {
      profile = getEmployeeProfile(employeeId);
    } catch (error) {
      profile = null;
    }
  }

  return { months, profile };
}

/**
 * Fast web-app save path.
 *
 * The old implementation called saveLeaveRecords() once per draft entry. That
 * caused repeated full-sheet reads, repeated holiday reads, repeated formatting,
 * and one sheet write per entry. This version prepares the entire draft in
 * memory and commits it with a single setValues() call.
 */
function completeWebAppDraft(payload) {
  const totalStarted = Date.now();
  payload = payload || {};

  const employeeId = String(payload.employeeId || '').trim();
  const name = String(payload.name || '').trim();
  const entries = Array.isArray(payload.entries) ? payload.entries : [];

  if (!employeeId) throw new Error('Select an employee.');
  if (!name) throw new Error('Employee name is missing.');
  if (!entries.length) throw new Error('Add at least one leave entry to the draft.');

  const lock = LockService.getDocumentLock();
  const lockStarted = Date.now();
  lock.waitLock(30000);
  const lockMs = Date.now() - lockStarted;

  try {
    const setupStarted = Date.now();
    const sheet = ensureLeaveRecordsSheet_();
    const setupMs = Date.now() - setupStarted;

    const existingStarted = Date.now();
    const existingKeys = getExistingRecordKeys_(sheet);
    const existingReadMs = Date.now() - existingStarted;

    const holidayStarted = Date.now();
    const regularHolidayKeys = getRegularHolidayKeys_();
    const holidayReadMs = Date.now() - holidayStarted;

    const buildStarted = Date.now();
    const timestamp = new Date();
    const rows = [];
    let datesAdded = 0;
    let skippedExisting = 0;
    let zeroCreditDates = 0;

    entries.forEach(entry => {
      const rawDates = Array.isArray(entry.dates) ? entry.dates : [];
      if (!rawDates.length) return;

      const leaveType = normalizeLeaveTypeName_(entry.leaveType || 'Other');
      const typeKey = String(leaveType).trim().toUpperCase();
      const isVl = typeKey === 'VL' || typeKey === 'VACATION LEAVE';
      const isSl = typeKey === 'SL' || typeKey === 'SICK LEAVE';
      const carriesCredit = isVl || isSl;
      const remarks = String(entry.remarks || '');

      const accepted = rawDates
        .map(item => ({
          date: String(item.date || ''),
          credits: carriesCredit ? (Number(item.credits) || 0) : 0
        }))
        .filter(item => /^\d{4}-\d{2}-\d{2}$/.test(item.date))
        .sort((a, b) => a.date.localeCompare(b.date))
        .filter(item => {
          const key = `${employeeId}|${item.date}`;
          if (existingKeys.has(key)) {
            skippedExisting++;
            return false;
          }
          // Reserve the date immediately so duplicate dates inside the same
          // submitted draft cannot be written twice.
          existingKeys.add(key);
          return true;
        })
        .map(item => {
          const dateValue = parseLocalDate_(item.date);
          const isWeekend = dateValue.getDay() === 0 || dateValue.getDay() === 6;
          const isRegularHoliday = regularHolidayKeys.has(item.date);
          const credits = carriesCredit && !isWeekend && !isRegularHoliday
            ? item.credits
            : 0;
          if (credits === 0) zeroCreditDates++;
          return { date: item.date, dateValue, credits };
        });

      if (!accepted.length) return;
      datesAdded += accepted.length;

      groupConsecutiveDates_(accepted).forEach(group => {
        const credits = group.reduce((sum, item) => sum + Number(item.credits || 0), 0);
        rows.push([
          leaveType,
          group[0].dateValue,
          group[group.length - 1].dateValue,
          'A',
          isVl ? credits : 0,
          isSl ? credits : 0,
          0,
          Utilities.getUuid(),
          employeeId,
          name,
          remarks,
          timestamp
        ]);
      });
    });

    const buildMs = Date.now() - buildStarted;

    if (!rows.length) {
      return {
        success: false,
        added: 0,
        message: 'No new leave records were saved. The selected dates may already exist.',
        performance: {
          totalMs: Date.now() - totalStarted,
          lockMs,
          setupMs,
          existingReadMs,
          holidayReadMs,
          buildMs,
          writeMs: 0
        }
      };
    }

    const writeStarted = Date.now();
    const firstRow = sheet.getLastRow() + 1;
    sheet.getRange(firstRow, 1, rows.length, CONFIG.HEADERS.length).setValues(rows);

    // Format only the rows just appended. Avoid reformatting whole columns on
    // every save, which becomes increasingly expensive as the sheet grows.
    sheet.getRange(firstRow, 2, rows.length, 2).setNumberFormat('mm/dd/yyyy');
    sheet.getRange(firstRow, 5, rows.length, 3).setNumberFormat('0.000');
    sheet.getRange(firstRow, 12, rows.length, 1).setNumberFormat('mm/dd/yyyy hh:mm:ss');
    const writeMs = Date.now() - writeStarted;

    const totalMs = Date.now() - totalStarted;
    return {
      success: true,
      added: rows.length,
      message: [
        `${rows.length} grouped leave record(s) saved from ${datesAdded} selected date(s).`,
        skippedExisting ? `${skippedExisting} existing date(s) skipped.` : '',
        `Server save: ${(totalMs / 1000).toFixed(2)}s.`
      ].filter(Boolean).join(' '),
      performance: {
        totalMs,
        lockMs,
        setupMs,
        existingReadMs,
        holidayReadMs,
        buildMs,
        writeMs,
        rowsWritten: rows.length,
        datesAccepted: datesAdded,
        zeroCreditDates,
        skippedExisting
      }
    };
  } finally {
    lock.releaseLock();
  }
}
