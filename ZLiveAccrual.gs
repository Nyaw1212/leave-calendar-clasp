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

  function ensureCurrentBalanceFields() {
    const openingSl = document.getElementById('openingSl');
    if (!openingSl) return;
    const grid = openingSl.closest('.profile-grid');
    if (!grid || document.getElementById('currentVl')) return;

    const vlWrap = document.createElement('div');
    vlWrap.innerHTML = '<label for="currentVl">Current VL</label><input id="currentVl" type="number" value="0.000" step="0.001" readonly disabled>';
    const slWrap = document.createElement('div');
    slWrap.innerHTML = '<label for="currentSl">Current SL</label><input id="currentSl" type="number" value="0.000" step="0.001" readonly disabled>';
    grid.appendChild(vlWrap);
    grid.appendChild(slWrap);

    const openingVlLabel = document.querySelector('label[for="openingVl"]');
    const openingSlLabel = document.querySelector('label[for="openingSl"]');
    if (openingVlLabel) openingVlLabel.textContent = 'Opening VL';
    if (openingSlLabel) openingSlLabel.textContent = 'Opening SL';
  }

  function displayPreview(profile) {
    ensureCurrentBalanceFields();
    const openingVl = document.getElementById('openingVl');
    const openingSl = document.getElementById('openingSl');
    const currentVl = document.getElementById('currentVl');
    const currentSl = document.getElementById('currentSl');
    const status = document.getElementById('profileStatus');
    if (!openingVl || !openingSl || !status) return;

    openingVl.value = Number(profile.openingVl || 0).toFixed(3);
    openingSl.value = Number(profile.openingSl || 0).toFixed(3);
    if (currentVl) currentVl.value = Number(profile.balanceVl || 0).toFixed(3);
    if (currentSl) currentSl.value = Number(profile.balanceSl || 0).toFixed(3);

    status.textContent =
      'Opening credit ' + Number(profile.openingVl || 0).toFixed(3) +
      ' each. Current as of ' + profile.asOfDate + ': VL ' +
      Number(profile.balanceVl || 0).toFixed(3) + ', SL ' +
      Number(profile.balanceSl || 0).toFixed(3) + '. Save to keep this date.';
    status.className = 'success';
  }

  function resetValues() {
    ['openingVl', 'openingSl', 'currentVl', 'currentSl'].forEach(function (id) {
      const element = document.getElementById(id);
      if (element) element.value = '0.000';
    });
  }

  function previewNow() {
    ensureCurrentBalanceFields();
    const employee = document.getElementById('employee');
    const date = document.getElementById('assumptionDate');
    const status = document.getElementById('profileStatus');
    if (!employee || !date || !status) return;

    if (!employee.value || !date.value) {
      resetValues();
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
        resetValues();
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
    ensureCurrentBalanceFields();
    const date = document.getElementById('assumptionDate');
    if (!date || date.dataset.liveAccrualAttached === 'yes') return;
    date.dataset.liveAccrualAttached = 'yes';
    date.addEventListener('input', schedulePreview);
    date.addEventListener('change', schedulePreview);
  }

  attach();
  setTimeout(attach, 300);
  setTimeout(ensureCurrentBalanceFields, 600);
})();
</script>`;

  const base = HtmlService.createHtmlOutputFromFile('Sidebar').getContent();
  const html = HtmlService.createHtmlOutput(base.replace('</body>', liveScript + '\n</body>'))
    .setTitle('Leave History Recorder');
  SpreadsheetApp.getUi().showSidebar(html);
}
