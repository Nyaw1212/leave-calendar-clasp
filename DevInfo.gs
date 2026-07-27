const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.6.1',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: 'd7850f1',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}