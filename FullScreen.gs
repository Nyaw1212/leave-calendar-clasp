function getWebAppUrl() {
  const url = ScriptApp.getService().getUrl();
  if (!url) {
    throw new Error('The web app has not been deployed yet. Deploy it first, then try again.');
  }
  return url;
}
