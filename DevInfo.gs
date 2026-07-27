const APP_INFO = Object.freeze({
  name: 'Leave Encoder',
  version: '0.1.0',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: '0e0a2de',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}
