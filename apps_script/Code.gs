/**
 * Receives heart rate readings from the Pico 2 W and logs them to the sheet.
 * Expected POST body: {"boot": <number>, "bpm": <number>, "token": "<secret>"}
 *
 * Setup:
 *  1. Project Settings > Script properties: add "token" = same value as SHEETS_TOKEN in secrets.h
 *  2. Deploy > New deployment > Web app, Execute as: Me, Who has access: Anyone
 *  3. After any edit: Deploy > Manage deployments > Edit > Version: New version
 */
function doPost(e) {
  if (!e || !e.postData) return text_('no data');

  let d;
  try {
    d = JSON.parse(e.postData.contents);
  } catch (err) {
    return text_('bad json');
  }

  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('token');
  if (!token || d.token !== token) return text_('unauthorized');

  const bpm = Number(d.bpm);
  if (!Number.isFinite(bpm) || bpm < 30 || bpm > 250) return text_('skipped');
  if (d.boot === undefined || d.boot === null) return text_('missing boot');

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const tz = ss.getSpreadsheetTimeZone();

    let sheet = ss.getSheetByName(props.getProperty('sheetName') || '') || ss.getSheets()[0];

    // New boot ID = Pico was reset -> duplicate current tab and place it next
    const lastBoot = props.getProperty('bootId');
    if (lastBoot !== null && lastBoot !== String(d.boot)) {
      const copy = sheet.copyTo(ss);
      copy.setName('Run ' + Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH-mm-ss'));
      ss.setActiveSheet(copy);
      ss.moveActiveSheet(sheet.getIndex() + 1); // right after the previous tab
      if (copy.getLastRow() >= 3) {
        copy.getRange(3, 1, copy.getLastRow() - 2, copy.getMaxColumns())
          .clearContent()
          .setBackground(null); // drop highlights copied from the old tab
      }
      sheet = copy;
    }
    props.setProperty('bootId', String(d.boot));
    props.setProperty('sheetName', sheet.getName());

    // Newest reading always goes in row 3, right below the A2/B2 headers;
    // older readings get pushed down one row.
    if (sheet.getMaxRows() >= 3) {
      sheet.insertRowBefore(3);
      // Give the new row the same formatting as the previous newest reading
      if (sheet.getLastRow() >= 4) {
        sheet.getRange(4, 1, 1, sheet.getMaxColumns())
          .copyTo(sheet.getRange(3, 1, 1, sheet.getMaxColumns()), { formatOnly: true });
      }
    } else {
      sheet.insertRowAfter(2);
    }
    sheet.getRange(3, 1, 1, 2).setValues([[new Date(), bpm]]);
    sheet.getRange(3, 1).setNumberFormat('yyyy-mm-dd hh:mm:ss');

    // Highlight against the HRR target zone:
    //   red    = above HRR (upper) in N1
    //   yellow = below HRR (lower) in L1
    //   green  = from L1 to N1 (inclusive)
    const lowCell = sheet.getRange('L1').getValue();
    const highCell = sheet.getRange('N1').getValue();
    const low = Number(lowCell);
    const high = Number(highCell);
    const hasLow = lowCell !== '' && Number.isFinite(low);
    const hasHigh = highCell !== '' && Number.isFinite(high);
    let color = null;
    if (hasHigh && bpm > high) {
      color = '#ff0000';
    } else if (hasLow && bpm < low) {
      color = '#ffff00';
    } else if (hasLow && hasHigh) {
      color = '#00ff00';
    }
    sheet.getRange(3, 1, 1, sheet.getMaxColumns()).setBackground(color);

    return text_('ok');
  } finally {
    lock.releaseLock();
  }
}

function text_(msg) {
  return ContentService.createTextOutput(msg);
}
