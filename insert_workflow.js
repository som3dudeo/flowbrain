const sqlite3 = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const db = new sqlite3.Database('/home/node/.n8n/database.sqlite');

const WF_ID = '281f9636-b373-427d-bf2f-825baf36defe';
const VERSION_ID = 'a4105161-a175-4b22-a636-995799461107';
const WEBHOOK_ID = 'c7d8e9f0-1234-5678-abcd-ef0123456789';
const PROJECT_ID = '61HsBmI9iRHTFwMC';

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

const settings = JSON.stringify({ executionOrder: 'v1' });

db.serialize(() => {
  db.run(
    'INSERT OR REPLACE INTO workflow_entity (id, name, active, nodes, connections, settings, versionId, triggerCount, isArchived, versionCounter) VALUES (?, ?, 0, ?, ?, ?, ?, 1, 0, 1)',
    [WF_ID, '\u26a1 FlowBrain Dispatcher', nodes, connections, settings, VERSION_ID],
    function(err) {
      if (err) console.log('WF INSERT ERR:', err.message);
      else console.log('workflow inserted OK');
    }
  );
  db.run(
    "INSERT OR REPLACE INTO shared_workflow (workflowId, projectId, role, createdAt, updatedAt) VALUES (?, ?, 'workflow:owner', STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW'), STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW'))",
    [WF_ID, PROJECT_ID],
    function(err) {
      if (err) console.log('SHARE INSERT ERR:', err.message);
      else console.log('shared inserted OK');
    }
  );
  db.run(
    'INSERT OR REPLACE INTO webhook_entity (workflowId, webhookPath, method, node, webhookId, pathLength) VALUES (?, ?, ?, ?, ?, ?)',
    [WF_ID, 'flowbrain', 'POST', 'Webhook', WEBHOOK_ID, 1],
    function(err) {
      if (err) console.log('WEBHOOK INSERT ERR:', err.message);
      else console.log('webhook inserted OK');
      db.close();
    }
  );
});
