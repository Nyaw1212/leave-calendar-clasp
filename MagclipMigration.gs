function migrateLeaveRecordsToMagclip() {
  const sheet = ensureLeaveRecordsSheet_();
  SpreadsheetApp.getActive().setActiveSheet(sheet);
  SpreadsheetApp.getUi().alert(
    'Leave Records is now MAGCLIP-ready.\n\n' +
    'Columns: TYPE | START | END | STATUS | VL | SL | LWOP | Record ID | Employee ID | Name | Remarks | Timestamp'
  );
}