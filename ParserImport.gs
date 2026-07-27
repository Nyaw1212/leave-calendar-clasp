function getNextHolidayImportYear() {
  const sheet = ensureHolidaySheet_();
  if (sheet.getLastRow() < 2) return 1980;

  const values = sheet
    .getRange(2, 1, sheet.getLastRow() - 1, CONFIG.HOLIDAY_HEADERS.length)
    .getValues();

  const years = values
    .map(row => {
      const storedYear = Number(row[3]);
      if (Number.isInteger(storedYear)) return storedYear;
      return row[0] instanceof Date ? row[0].getFullYear() : null;
    })
    .filter(year => Number.isInteger(year) && year >= 1980 && year <= 2100);

  if (!years.length) return 1980;
  return Math.min(Math.max(...years) + 1, 2100);
}

function parseHolidayPaste(payload) {
  payload = payload || {};
  const year = Number(payload.year);
  const text = String(payload.text || '').trim();
  const regularOnly = payload.regularOnly !== false;

  if (!Number.isInteger(year) || year < 1980 || year > 2100) {
    throw new Error('Year must be between 1980 and 2100.');
  }
  if (!text) throw new Error('Paste the holiday table first.');

  const parsed = [];
  const rejected = [];
  const seen = new Set();

  text.split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) return;

    const fields = splitHolidayPasteLine_(line);
    if (!fields || fields.length < 4) {
      rejected.push({ line: index + 1, text: rawLine, reason: 'Could not identify date, weekday, name, and type.' });
      return;
    }

    const date = parsePastedHolidayDate_(fields[0], year);
    const weekday = fields[1].trim();
    const name = fields.slice(2, -1).join(' ').trim();
    const type = fields[fields.length - 1].trim();

    if (!date) {
      rejected.push({ line: index + 1, text: rawLine, reason: 'Invalid date.' });
      return;
    }
    if (!name || !type) {
      rejected.push({ line: index + 1, text: rawLine, reason: 'Missing holiday name or type.' });
      return;
    }
    if (regularOnly && !/^Regular Holiday$/i.test(type)) return;

    const key = Utilities.formatDate(date, Session.getScriptTimeZone(), 'yyyy-MM-dd') + '|' + name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);

    parsed.push({
      date: Utilities.formatDate(date, Session.getScriptTimeZone(), 'yyyy-MM-dd'),
      weekday,
      name,
      type
    });
  });

  parsed.sort((a, b) => a.date.localeCompare(b.date));
  return { year, parsed, rejected, regularOnly };
}

function importHolidayPaste(payload) {
  payload = payload || {};
  const preview = parseHolidayPaste(payload);
  const year = preview.year;
  const replaceYear = Boolean(payload.replaceYear);

  if (!preview.parsed.length) {
    throw new Error('No matching holiday rows were found.');
  }

  const sheet = ensureHolidaySheet_();
  const existingRows = getHolidayRowsForYear_(sheet, year);

  if (replaceYear && existingRows.length) {
    deleteHolidayRows_(sheet, existingRows.map(item => item.row));
  }

  const tz = Session.getScriptTimeZone();
  const existingKeys = new Set();
  if (!replaceYear && sheet.getLastRow() >= 2) {
    sheet.getRange(2, 1, sheet.getLastRow() - 1, CONFIG.HOLIDAY_HEADERS.length)
      .getValues()
      .forEach(row => {
        const date = row[0];
        const name = String(row[1] || '').trim().toLowerCase();
        if (date instanceof Date) {
          existingKeys.add(Utilities.formatDate(date, tz, 'yyyy-MM-dd') + '|' + name);
        }
      });
  }

  const importedAt = new Date();
  const source = 'Timeanddate (manual paste)';
  let skipped = 0;

  const rows = preview.parsed.filter(item => {
    const key = item.date + '|' + item.name.toLowerCase();
    if (existingKeys.has(key)) {
      skipped++;
      return false;
    }
    existingKeys.add(key);
    return true;
  }).map(item => [
    parseLocalDate_(item.date),
    item.name,
    item.type,
    year,
    source,
    importedAt
  ]);

  if (rows.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, CONFIG.HOLIDAY_HEADERS.length).setValues(rows);
    sheet.getRange('A:A').setNumberFormat('mm/dd/yyyy');
    sheet.getRange('F:F').setNumberFormat('mm/dd/yyyy hh:mm:ss');
  }

  clearHolidayCacheForYear_(year);

  return {
    success: true,
    year,
    nextYear: Math.min(year + 1, 2100),
    added: rows.length,
    skipped,
    rejected: preview.rejected.length,
    message: `${year}: added ${rows.length} holiday row(s), skipped ${skipped} duplicate(s), ${preview.rejected.length} rejected line(s).`
  };
}

function splitHolidayPasteLine_(line) {
  let fields = line.split('\t').map(value => value.trim()).filter(Boolean);
  if (fields.length >= 4) return fields;

  fields = line.split(/\s{2,}/).map(value => value.trim()).filter(Boolean);
  if (fields.length >= 4) return fields;

  const match = line.match(/^(\d{1,2}\s+[A-Za-z]+)\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(.+?)\s+(Regular Holiday|Special Non-working Holiday|Muslim, Common Local Holiday|Observance|Season)$/i);
  return match ? [match[1], match[2], match[3], match[4]] : null;
}

function parsePastedHolidayDate_(text, year) {
  const match = String(text).trim().match(/^(\d{1,2})\s+([A-Za-z]+)/);
  if (!match) return null;

  const day = Number(match[1]);
  const monthMap = {
    jan: 0, january: 0, feb: 1, february: 1, mar: 2, march: 2,
    apr: 3, april: 3, may: 4, jun: 5, june: 5, jul: 6, july: 6,
    aug: 7, august: 7, sep: 8, sept: 8, september: 8,
    oct: 9, october: 9, nov: 10, november: 10, dec: 11, december: 11
  };
  const month = monthMap[match[2].toLowerCase()];
  if (month === undefined) return null;

  const date = new Date(year, month, day);
  return date.getFullYear() === year && date.getMonth() === month && date.getDate() === day
    ? date
    : null;
}