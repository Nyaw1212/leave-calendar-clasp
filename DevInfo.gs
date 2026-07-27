const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.4.0',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: 'ada1a6f',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}
