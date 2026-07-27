function previewEmployeeCscCredits(payload) {
  payload = payload || {};
  const employeeId = String(payload.employeeId || '').trim();
  if (!employeeId) throw new Error('Select an employee.');

  const assumptionDate = parseProfileDate_(payload.assumptionDate);
  if (!assumptionDate) throw new Error('Enter a valid Date of Assumption / Entry.');

  const today = stripTime_(new Date());
  if (stripTime_(assumptionDate) > today) {
    throw new Error('Date of Assumption cannot be in the future.');
  }

  return computeCscLeaveCredits_(employeeId, assumptionDate, today);
}

/**
 * Overrides the normal sidebar renderer and injects the live accrual listener.
 * The entered date is previewed immediately but is only stored after Save.
 */
function showLeaveSidebar() {
  const liveScript = `
<script>
(function () {
  let timer = null;
  let requestToken = 0;

  function displayPreview(profile) {
    const vl = document.getElementById('openingVl');
    const sl = document.getElementById('openingSl');
    const status = document.getElementById('profileStatus');
    if (!vl || !sl || !status) return;

    vl.value = Number(profile.balanceVl || 0).toFixed(3);
    sl.value = Number(profile.balanceSl || 0).toFixed(3);
    status.textContent =
      'Preview as of ' + profile.asOfDate + ': earned ' +
      Number(profile.earnedVl || 0).toFixed(3) + ' each; used VL ' +
      Number(profile.usedVl || 0).toFixed(3) + ', SL ' +
      Number(profile.usedSl || 0).toFixed(3) + '. Save to keep this date.';
    status.className = 'success';
  }

  function previewNow() {
    const employee = document.getElementById('employee');
    const date = document.getElementById('assumptionDate');
    const vl = document.getElementById('openingVl');
    const sl = document.getElementById('openingSl');
    const status = document.getElementById('profileStatus');
    if (!employee || !date || !status) return;

    if (!employee.value || !date.value) {
      if (vl) vl.value = '0.000';
      if (sl) sl.value = '0.000';
      status.textContent = employee.value
        ? 'Enter the Date of Assumption / Entry.'
        : 'Select an employee.';
      status.className = employee.value ? 'warning' : '';
      return;
    }

    const token = ++requestToken;
    status.textContent = 'Calculating CSC leave credits...';
    status.className = '';

    google.script.run
      .withSuccessHandler(function (profile) {
        if (token !== requestToken) return;
        displayPreview(profile || {});
      })
      .withFailureHandler(function (error) {
        if (token !== requestToken) return;
        if (vl) vl.value = '0.000';
        if (sl) sl.value = '0.000';
        status.textContent = error && error.message ? error.message : String(error);
        status.className = 'error';
      })
      .previewEmployeeCscCredits({
        employeeId: employee.value,
        assumptionDate: date.value
      });
  }

  function schedulePreview() {
    clearTimeout(timer);
    timer = setTimeout(previewNow, 150);
  }

  function attach() {
    const date = document.getElementById('assumptionDate');
    if (!date || date.dataset.liveAccrualAttached === 'yes') return;
    date.dataset.liveAccrualAttached = 'yes';
    date.addEventListener('input', schedulePreview);
    date.addEventListener('change', schedulePreview);
  }

  attach();
  setTimeout(attach, 300);
})();
</script>`;

  const base = HtmlService.createHtmlOutputFromFile('Sidebar').getContent();
  const html = HtmlService.createHtmlOutput(base.replace('</body>', liveScript + '\n</body>'))
    .setTitle('Leave History Recorder');
  SpreadsheetApp.getUi().showSidebar(html);
}
