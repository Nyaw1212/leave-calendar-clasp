const APP_INFO = Object.freeze({
  name: 'Leave History Recorder',
  version: '0.9.0',
  buildDate: '2026-07-27',
  branch: 'main',
  sourceCommit: '7165f15',
  repository: 'Nyaw1212/leave-calendar-clasp'
});

function getAppInfo() {
  return { ...APP_INFO };
}
