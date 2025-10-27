# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an AI-powered automation agent system that monitors a Notion database for queued tasks, processes them using OpenAI's LLM, creates proof documents in Google Docs, and updates Notion with results. The system runs autonomously via GitHub Actions every 15 minutes or can be triggered manually.

**Core Technologies:**
- Python 3.11
- Notion API (v2022-06-28)
- OpenAI API (default model: gpt-4o-mini)
- Google Drive API v3 and Google Docs API v1

## RaNemoOS System Prompt

This agent uses the **RaNemoOS Alignment Preamble** to ensure all generated content matches Will Nemo's voice and strategic vision. The system prompt is defined in `.ranemos/system-prompt.json` and automatically loaded at runtime.

**Core Identity:**
- **Role**: RaNemoOS - Strategist and sovereign-systems coach
- **Voice**: Philosopher × Operator × Coach
- **Persona**: Builder energy — practical, battle-tested, future-oriented
- **Mission**: Deliver signal, not noise. Help build, ship, and scale sovereign systems

**Voice Characteristics:**
- Straight-shooting, confident, data-anchored
- Witty but grounded
- Encouraging but real (no feel-good filler)
- Millennial-skeptic (dismantle hype with data, logic, humor)

**Behavioral Anchors:**
- Focus on autonomy, clarity, systems thinking, long-term wealth & freedom
- Link every short-term move to long-term sovereignty (3-10 year lens)
- Replace "You got this" with "Here's how to win"

**Forbidden:**
- Hedging, over-apologizing, corporate jargon
- Feel-good filler, disclaimers (unless safety-critical)
- Academic throat-clearing

**How It Works:**
The `load_ranemos_prompt()` function (agents/run.py:28-72) reads the JSON file and constructs a system prompt that's injected into every OpenAI API call. This ensures all agent outputs maintain consistent voice, tone, and strategic focus.

To modify the agent's voice, edit `.ranemos/system-prompt.json`. The agent will automatically use the updated prompt on next run.

## Development Commands

### Setup and Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables (see .env.example for template)
export NOTION_TOKEN=secret_...
export NOTION_AGENT_DB=database_id
export OPENAI_API_KEY=sk-...
export OPENAI_MODEL=gpt-4o-mini  # Optional
export DRIVE_SA_JSON='{"type":"service_account",...}'  # Full JSON string
export GDRIVE_PARENT_FOLDER_ID=folder_id  # Optional
export GOOGLE_WORKSPACE_IMPERSONATE=user@domain.com  # Optional
```

### Running the Agent
```bash
# Run locally
python agents/run.py

# The agent also runs automatically via GitHub Actions:
# - Every 15 minutes via cron schedule
# - Manual trigger via workflow_dispatch in GitHub Actions UI
```

## Architecture

### Event-Driven Agent Pattern

The system follows a query → process → update cycle:

1. **Query Phase** (`notion_query_queued()` at agents/run.py:87):
   - Polls Notion for tasks with `Status="Queued"` AND `Due <= today`
   - Returns matching pages for processing

2. **Processing Phase** (main loop at agents/run.py:271):
   - Extract task metadata from Notion properties
   - Update status to "Running"
   - Build prompt from task context (`build_prompt()`)
   - Call OpenAI model (`call_model()` at agents/run.py:193)
   - Create Google Doc with generated content (`create_google_doc()`)
   - Determine final status based on confidence gate

3. **Update Phase** (`notion_update_status()`):
   - Write ProofURL (Google Doc link) to Notion
   - Set Status to "Done" or "Needs Review" based on confidence
   - Record confidence score and notes

### Key Components

**Notion Integration:**
- Query database with date and status filters
- Extract typed properties (title, select, rich_text, number, date, url, files, people)
- Update page properties atomically

**OpenAI Integration:**
- Expects structured JSON output: `{"text": "...", "confidence": 0.0-1.0, "title": "..."}`
- Fallback to offline dummy output if API unavailable (for testing)
- Robust JSON extraction from model responses with error handling

**Google Workspace Integration:**
- Service account authentication with optional domain-wide delegation
- Creates Google Docs with generated content
- Moves docs to specified folder (if `GDRIVE_PARENT_FOLDER_ID` set)
- Sets public "anyone with link can view" permissions (hardcoded)

**Safety Gates:**
- Auto-publish only if `PublishMode=Auto` AND `confidence >= ConfidenceGate`
- All outputs persisted to Google Docs regardless of confidence
- Errors/failures leave tasks in "Needs Review" state

### File Organization

```
ranemos_agents_starter/
├── agents/
│   └── run.py              # Main execution script - all logic here
├── .github/workflows/
│   └── ranemos-agents.yml  # GitHub Actions automation (15-min cron)
├── .ranemos/
│   └── system-prompt.json  # RaNemoOS alignment preamble (defines agent voice)
├── notion_db_schema.json   # Schema for creating Agent Queue database
├── requirements.txt        # Python dependencies (4 core libraries)
├── .env.example           # Environment variable template
└── CLAUDE.md              # This file - guidance for Claude Code
```

## Notion Database Schema

The Agent Queue database has 14 properties. Key fields:

- **Name** (title): Task title
- **AgentType** (select): Content, LeadGen, Research, Ops, Finance
- **Prompt / Context** (rich_text): Instructions and source notes for the agent
- **Inputs** (files): Attachments/links to reference
- **PublishMode** (select): "Auto" vs "Needs Review"
- **ConfidenceGate** (number): Threshold (0-1) for auto-publishing
- **Status** (select): Queued, Running, Needs Review, Done, Blocked
- **Due** (date): Task is processed when `Due <= today`
- **ProofURL** (url): Generated Google Doc link (filled by agent)
- **Confidence** (number): Model's confidence score (filled by agent)
- **ProofNote** (rich_text): Status notes from execution (filled by agent)

To create the database: POST to Notion's `/v1/databases` API with parent.page_id and the JSON from notion_db_schema.json, or build it manually in the UI matching property names and types exactly.

## Customization Points

### Adding Agent Skills
Edit `build_prompt()` (agents/run.py:252) to customize task instructions. You can branch logic by `AgentType` to create specialized agent behaviors with different prompts, tools, or processing steps.

### Model Selection
Set `OPENAI_MODEL` environment variable to use different models:
- `gpt-4o-mini` (default, cost-effective)
- `gpt-4o`
- `gpt-4.1`
- `gpt-5`

### Extending the System
The code uses a simple functional structure. Key extension patterns:
- Add new agent types by modifying the `build_prompt()` function
- Branch on `AgentType` property for specialized processing
- Add tools/APIs by creating new functions and calling them in the main loop
- Modify Google Docs formatting in `create_google_doc()` (currently plain text only)

## Current Limitations

- `BudgetTokens` field exists in schema but is not enforced in code
- Markdown in generated text is not parsed for Google Docs formatting
- All created docs have public "anyone with link" permissions (hardcoded)
- No retry logic for failed API calls
- No persistent logging (logs only visible in GitHub Actions runs)
- No unit tests or linting configuration

## Required Setup

**Notion:**
1. Create integration at https://www.notion.so/my-integrations
2. Share a parent page with the integration
3. Create Agent Queue database using notion_db_schema.json schema

**Google Cloud:**
1. Create service account with Drive and Docs API access
2. Download JSON credentials (set as `DRIVE_SA_JSON`)
3. Share target folder with service account email
4. (Optional) Configure domain-wide delegation for `GOOGLE_WORKSPACE_IMPERSONATE`

**OpenAI:**
1. Get API key from https://platform.openai.com
2. Set as `OPENAI_API_KEY`

**GitHub Actions:**
All environment variables should be configured as repository secrets for automated execution.
