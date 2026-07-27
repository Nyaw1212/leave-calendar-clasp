const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.9.5',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: '6c0d325',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}
