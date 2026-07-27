const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.2.0',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: '57a9676',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}
