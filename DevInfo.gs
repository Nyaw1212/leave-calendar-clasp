const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.9.1',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: 'be32a5f',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}