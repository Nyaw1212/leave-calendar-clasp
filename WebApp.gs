function doGet() {
  return HtmlService.createHtmlOutputFromFile('WebAppPage')
    .setTitle('Leave History Recorder')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function getWebAppBootstrap() {
  return {
    employees: getEmployees(),
    appInfo: typeof getAppInfo === 'function' ? getAppInfo() : null
  };
}