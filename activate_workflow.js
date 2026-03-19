const sqlite3 = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const db = new sqlite3.Database('/home/node/.n8n/database.sqlite');

const WF_ID = '281f9636-b373-427d-bf2f-825baf36defe';

db.run(
  'UPDATE workflow_entity SET active = 1 WHERE id = ?',
  [WF_ID],
  function(err) {
    if (err) console.log('ERR:', err.message);
    else console.log('activated, rows changed:', this.changes);
    db.close();
  }
);
