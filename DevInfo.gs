const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.3.0',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: '1ad24c0',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}
