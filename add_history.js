const sqlite3 = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const db = new sqlite3.Database('/home/node/.n8n/database.sqlite');

const WF_ID = '281f9636-b373-427d-bf2f-825baf36defe';
const VERSION_ID = 'a4105161-a175-4b22-a636-995799461107';

const nodes = JSON.stringify([
  {
    parameters: { httpMethod: 'POST', path: 'flowbrain', responseMode: 'responseNode', options: {} },
    id: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    name: 'Webhook',
    type: 'n8n-nodes-base.webhook',
    typeVersion: 2,
    position: [250, 300]
  },
  {
    parameters: { respondWith: 'json', options: {} },
    id: 'b2c3d4e5-f6a7-8901-bcde-f12345678901',
    name: 'Respond to Webhook',
    type: 'n8n-nodes-base.respondToWebhook',
    typeVersion: 1,
    position: [500, 300]
  }
]);

const connections = JSON.stringify({
  Webhook: { main: [[{ node: 'Respond to Webhook', type: 'main', index: 0 }]] }
});

db.run(
  "INSERT OR REPLACE INTO workflow_history (versionId, workflowId, authors, nodes, connections, name, autosaved, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?, 0, STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW'), STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW'))",
  [VERSION_ID, WF_ID, 'FlowBrain', nodes, connections, '\u26a1 FlowBrain Dispatcher'],
  function(err) {
    if (err) console.log('HISTORY INSERT ERR:', err.message);
    else console.log('workflow_history inserted OK');
    db.close();
  }
);
