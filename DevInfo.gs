const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.9.2',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: '83b4b1d',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}