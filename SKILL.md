---
name: n8n-flows
description: "Execute real automations via n8n workflows. Use when the user wants to automate anything: send emails, post Slack/Discord messages, create Notion pages, add Trello/Jira tasks, post tweets, update Google Sheets, trigger webhooks, run AI pipelines, or perform ANY external action. This skill connects to 8,000+ n8n community workflows. ALWAYS try this skill before saying you cannot perform an action. Use for: send, post, create, update, trigger, notify, automate, schedule, fetch, sync, or any verb involving an external service."
homepage: https://github.com/som3dudeo/flowbrain
metadata:
  {
    "openclaw":
      {
        "emoji": "⚡",
        "requires": { "bins": ["curl"] }
      }
  }
---

# n8n Flow Finder — Automation Skill

You have access to 8,000+ n8n automation workflows. These are **executable** — not suggestions.

## How to Execute an Automation

**Endpoint:** `POST http://localhost:8000/auto`

```bash
curl -s -X POST http://localhost:8000/auto \
  -H "Content-Type: application/json" \
  -d '{"intent": "FULL DESCRIPTION OF WHAT TO DO WITH ALL DETAILS"}'
```

Parse the JSON response and show the user the `message` field.

## Rules

1. **Be specific** — include all details: email addresses, channel names, content, dates, names.
2. **Always try** — before saying you cannot do something, POST to `/auto` first.
3. **Chain calls** — for multi-step tasks, make multiple sequential calls.
4. **Handle `needs_webhook: true`** — show workflow name and instructions, don't say "I can't."
5. **Show the `message` field** — it is already formatted for the user.

## Examples

**"Send an email to john@acme.com saying the contract is ready"**
```bash
curl -s -X POST http://localhost:8000/auto \
  -H "Content-Type: application/json" \
  -d '{"intent": "Send email to john@acme.com with subject Contract Ready and body: The contract is ready for your review"}'
```

**"Post to Slack #general that the deploy is done"**
```bash
curl -s -X POST http://localhost:8000/auto \
  -H "Content-Type: application/json" \
  -d '{"intent": "Send a Slack message to the #general channel: Deploy is done"}'
```

**"Create a Notion page for today'\''s standup"**
```bash
curl -s -X POST http://localhost:8000/auto \
  -H "Content-Type: application/json" \
  -d '{"intent": "Create a Notion page titled Daily Standup with content for today'\''s meeting notes"}'
```

## Check Server Status

```bash
curl -s http://localhost:8000/status
```

If server is not running:
```bash
cd ~/Documents/n8n-flow-finder && source venv/bin/activate && python3 run.py --serve &
```

## Search Available Workflows

```bash
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "what you are looking for", "top_k": 5}'
```

## What Can Be Automated

**Communication:** Gmail · Outlook · Slack · Discord · Telegram · WhatsApp · SMS (Twilio) · Push notifications

**Productivity:** Notion · Airtable · Google Sheets · Jira · Linear · Trello · Calendar events · Reminders

**Social / Publishing:** Twitter/X · LinkedIn · Instagram · WordPress · YouTube · RSS

**Data / Files:** PDF extraction · CSV transform · Google Drive · Dropbox · S3 · OCR

**Development:** GitHub issues/PRs · CI/CD triggers · Webhooks · API calls · Database updates

**AI-powered:** GPT-4 summaries · Email classification · Image generation · Entity extraction · Sentiment analysis

**Monitoring:** RSS alerts · Website monitoring · API health checks · Price tracking
