function doGet() {
  const base = HtmlService.createHtmlOutputFromFile('WebAppPage').getContent();
  const enhancements = HtmlService.createHtmlOutputFromFile('WebUxEnhancements').getContent();
  const draftMarkers = HtmlService.createHtmlOutputFromFile('DraftMarkers').getContent();
  const workflowEnhancements = HtmlService.createHtmlOutputFromFile('WebWorkflowEnhancements').getContent();
  const magclipUxFixes = HtmlService.createHtmlOutputFromFile('MagclipUxFixes').getContent();
  const draftHoverHelper = HtmlService.createHtmlOutputFromFile('DraftHoverHelper').getContent();
  return HtmlService.createHtmlOutput(
    base.replace(
      '</body>',
      enhancements + '\n' + draftMarkers + '\n' + workflowEnhancements + '\n' + magclipUxFixes + '\n' + draftHoverHelper + '\n</body>'
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

function completeWebAppDraft(payload) {
  payload = payload || {};
  const employeeId = String(payload.employeeId || '').trim();
  const name = String(payload.name || '').trim();
  const entries = Array.isArray(payload.entries) ? payload.entries : [];

  if (!employeeId) throw new Error('Select an employee.');
  if (!entries.length) throw new Error('Add at least one leave entry to the draft.');

  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    let recordsAdded = 0;
    let datesAdded = 0;

    entries.forEach(entry => {
      const dates = Array.isArray(entry.dates) ? entry.dates : [];
      if (!dates.length) return;

      const entryType = String(entry.leaveType || 'Other');
      const normalizedType = entryType.trim().toUpperCase();
      const carriesCredit = normalizedType === 'VL' || normalizedType === 'VACATION LEAVE' ||
        normalizedType === 'SL' || normalizedType === 'SICK LEAVE';

      const result = saveLeaveRecords({
        employeeId,
        name,
        leaveType: entryType,
        remarks: String(entry.remarks || ''),
        dates: dates.map(item => ({
          date: String(item.date || ''),
          credits: carriesCredit ? (Number(item.credits) || 0) : 0
        }))
      });

      if (result && result.success) {
        recordsAdded += Number(result.recordsAdded) || 0;
        datesAdded += Number(result.datesAdded) || dates.length;
      }
    });

    return {
      success: true,
      added: recordsAdded,
      message: `${recordsAdded} grouped leave record(s) saved from ${datesAdded} selected date(s).`
    };
  } finally {
    lock.releaseLock();
  }
}
