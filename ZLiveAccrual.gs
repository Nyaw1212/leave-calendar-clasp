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

function showLeaveSidebar() {
  const enhancementScript = `
<script>
(function () {
  const DRAFT_KEY = 'leave-history-recorder-draft-v1';
  let previewTimer = null;
  let requestToken = 0;
  let draftRestored = false;

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
  }

  function ensureFullScreenButton() {
    if (document.getElementById('fullScreenButton')) return;

    const saveButton = document.getElementById('saveButton');
    if (!saveButton) return;

    const button = document.createElement('button');
    button.id = 'fullScreenButton';
    button.type = 'button';
    button.textContent = '↗ Full Screen Mode';
    button.style.width = '100%';
    button.style.marginTop = '8px';
    button.style.padding = '10px';
    button.style.border = '1px solid #1a73e8';
    button.style.borderRadius = '6px';
    button.style.background = '#ffffff';
    button.style.color = '#1a73e8';
    button.style.fontWeight = '700';
    button.style.cursor = 'pointer';

    button.addEventListener('click', function () {
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = 'Opening web app...';

      google.script.run
        .withSuccessHandler(function (url) {
          button.disabled = false;
          button.textContent = originalText;
          if (!url) {
            setStatus('Deploy the web app first, then try again.', 'error');
            return;
          }
          window.open(url, '_blank');
        })
        .withFailureHandler(function (error) {
          button.disabled = false;
          button.textContent = originalText;
          setStatus(error && error.message ? error.message : String(error), 'error');
        })
        .getWebAppUrl();
    });

    saveButton.insertAdjacentElement('afterend', button);
  }

  function applyWorkflowLabels() {
    const leaveTypeLabel = document.querySelector('label[for="leaveType"]');
    if (leaveTypeLabel) leaveTypeLabel.textContent = 'Leave Type';

    const saveButton = document.getElementById('saveButton');
    if (saveButton && !saveButton.disabled) saveButton.textContent = 'Add Leave';
  }

  function setBalanceValues(profile) {
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

  function resetBalances() {
    ['openingVl', 'openingSl', 'currentVl', 'currentSl'].forEach(function (id) {
      const element = document.getElementById(id);
      if (element) element.value = '0.000';
    });
  }

  function previewAccrual() {
    ensureCurrentBalanceFields();
    const employee = document.getElementById('employee');
    const date = document.getElementById('assumptionDate');
    const status = document.getElementById('profileStatus');
    if (!employee || !date || !status) return;

    if (!employee.value || !date.value) {
      resetBalances();
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
        setBalanceValues(profile || {});
      })
      .withFailureHandler(function (error) {
        if (token !== requestToken) return;
        resetBalances();
        status.textContent = error && error.message ? error.message : String(error);
        status.className = 'error';
      })
      .previewEmployeeCscCredits({
        employeeId: employee.value,
        assumptionDate: date.value
      });
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(previewAccrual, 150);
  }

  function saveDraft() {
    try {
      const employee = document.getElementById('employee');
      const leaveType = document.getElementById('leaveType');
      const credit = document.getElementById('credit');
      const remarks = document.getElementById('remarks');
      const month = document.getElementById('monthSelect');
      const year = document.getElementById('yearSelect');

      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        employeeId: employee ? employee.value : '',
        leaveType: leaveType ? leaveType.value : 'VL',
        credit: credit ? credit.value : '1',
        remarks: remarks ? remarks.value : '',
        month: month ? Number(month.value) : null,
        year: year ? Number(year.value) : null,
        selectedDates: typeof selectedDates !== 'undefined' ? Array.from(selectedDates) : []
      }));
    } catch (error) {
      console.warn('Could not save leave draft.', error);
    }
  }

  function readDraft() {
    try {
      return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}');
    } catch (error) {
      return {};
    }
  }

  function restoreDraft() {
    if (draftRestored) return true;
    const employee = document.getElementById('employee');
    if (!employee || employee.options.length <= 1) return false;

    const draft = readDraft();
    const leaveType = document.getElementById('leaveType');
    const credit = document.getElementById('credit');
    const remarks = document.getElementById('remarks');

    if (draft.employeeId && Array.from(employee.options).some(function (option) {
      return option.value === String(draft.employeeId);
    })) employee.value = String(draft.employeeId);

    if (leaveType && draft.leaveType) leaveType.value = draft.leaveType;
    if (credit && draft.credit) credit.value = String(draft.credit);
    if (remarks && typeof draft.remarks === 'string') remarks.value = draft.remarks;
    if (Number.isInteger(draft.month) && draft.month >= 0 && draft.month <= 11) viewMonth = draft.month;
    if (Number.isInteger(draft.year) && draft.year >= START_YEAR) viewYear = draft.year;
    syncSelectors();

    if (typeof selectedDates !== 'undefined') {
      selectedDates.clear();
      (draft.selectedDates || []).forEach(function (date) { selectedDates.add(date); });
    }

    draftRestored = true;
    if (employee.value) loadEmployeeDetails();
    loadCalendarData();
    updateSummary();
    return true;
  }

  function attachListeners() {
    ['employee', 'leaveType', 'credit', 'remarks', 'monthSelect', 'yearSelect'].forEach(function (id) {
      const element = document.getElementById(id);
      if (!element || element.dataset.draftAttached === 'yes') return;
      element.dataset.draftAttached = 'yes';
      element.addEventListener(id === 'remarks' ? 'input' : 'change', function () {
        setTimeout(saveDraft, 0);
      });
    });

    const date = document.getElementById('assumptionDate');
    if (date && date.dataset.liveAccrualAttached !== 'yes') {
      date.dataset.liveAccrualAttached = 'yes';
      date.addEventListener('input', schedulePreview);
      date.addEventListener('change', schedulePreview);
    }
  }

  function wrapFunctions() {
    if (window.__leaveWorkflowWrapped) return;
    window.__leaveWorkflowWrapped = true;

    const originalRenderCalendar = renderCalendar;
    renderCalendar = function () {
      originalRenderCalendar.apply(this, arguments);
      saveDraft();
    };

    const originalSetLoading = setLoading;
    setLoading = function (value) {
      originalSetLoading(value);
      const button = document.getElementById('saveButton');
      if (button) button.textContent = value ? 'Adding Leave...' : 'Add Leave';
    };
  }

  function initialize() {
    ensureCurrentBalanceFields();
    ensureFullScreenButton();
    applyWorkflowLabels();
    attachListeners();
    wrapFunctions();
    restoreDraft();
  }

  initialize();
  const startupTimer = setInterval(function () {
    initialize();
    if (draftRestored && document.getElementById('fullScreenButton')) clearInterval(startupTimer);
  }, 250);
  setTimeout(function () { clearInterval(startupTimer); }, 8000);
  window.addEventListener('beforeunload', saveDraft);
})();
</script>`;

  const base = HtmlService.createHtmlOutputFromFile('Sidebar').getContent();
  const html = HtmlService.createHtmlOutput(
    base.replace('</body>', enhancementScript + '\n</body>')
  ).setTitle('Leave History Recorder');

  SpreadsheetApp.getUi().showSidebar(html);
}
