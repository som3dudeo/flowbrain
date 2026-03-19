const sqlite3 = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const db = new sqlite3.Database('/home/node/.n8n/database.sqlite');

const WF_ID = '281f9636-b373-427d-bf2f-825baf36defe';
const VERSION_ID = 'a4105161-a175-4b22-a636-995799461107';

// Also update the activeVersionId on the workflow entity
db.serialize(() => {
  db.run(
    "UPDATE workflow_entity SET activeVersionId = ?, active = 1 WHERE id = ?",
    [VERSION_ID, WF_ID],
    function(err) {
      if (err) console.log('UPDATE ERR:', err.message);
      else console.log('activeVersionId set, rows:', this.changes);
    }
  );

  db.run(
    "INSERT OR REPLACE INTO workflow_published_version (workflowId, publishedVersionId, createdAt, updatedAt) VALUES (?, ?, STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW'), STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW'))",
    [WF_ID, VERSION_ID],
    function(err) {
      if (err) console.log('PUBLISH INSERT ERR:', err.message);
      else console.log('published version inserted OK');
      db.close();
    }
  );
});
