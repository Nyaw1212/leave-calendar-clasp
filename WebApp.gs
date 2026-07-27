function doGet() {
  const base = HtmlService.createHtmlOutputFromFile('WebAppPage').getContent();
  const enhancements = HtmlService.createHtmlOutputFromFile('WebUxEnhancements').getContent();
  return HtmlService.createHtmlOutput(base.replace('</body>', enhancements + '\n</body>'))
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

  const months = [];
  for (let offset = 0; offset < monthCount; offset++) {
    const date = new Date(startYear, startMonth + offset, 1);
    months.push({
      year: date.getFullYear(),
      month: date.getMonth(),
      holidays: getHolidays(date.getFullYear(), date.getMonth()),
      existingRecords: employeeId
        ? getExistingLeaveDates(employeeId, date.getFullYear(), date.getMonth())
        : []
    });
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
    let added = 0;
    entries.forEach(entry => {
      const dates = Array.isArray(entry.dates) ? entry.dates : [];
      if (!dates.length) return;
      const result = saveLeaveRecords({
        employeeId,
        name,
        leaveType: String(entry.leaveType || 'Other'),
        remarks: String(entry.remarks || ''),
        dates: dates.map(item => ({
          date: String(item.date || ''),
          credits: Number(item.credits) || 0
        }))
      });
      if (result && result.success) added += dates.length;
    });

    return {
      success: true,
      added,
      message: `${added} leave-history date(s) were saved.`
    };
  } finally {
    lock.releaseLock();
  }
}