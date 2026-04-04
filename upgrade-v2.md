# Note Agent Upgrade: Narration Store & Build-in-Public Pipeline

## Context

This note agent is part of a personal assistant system coordinated by a Hayekian router. Daniel is building a "build-in-public" workflow where he narrates what he's working on throughout the day. These narrations need to be captured, stored, and periodically synthesized into publishable content.

The router now sends Daniel an evening prompt at 17:00: "What did you build or move forward today?" His reply is routed to this note agent. The weekly digest (Sunday 18:00) also queries this agent for the week's narrations to identify threads and offer to draft posts.

Read the existing Claude.md / instruction file in this repo carefully to understand current capabilities and Obsidian integration before making changes.

## Current State

- Agent handles note capture, search, and Obsidian integration
- Invoked via `uv run python query.py "<message>"` by the router
- Can also receive handshake calls: `query.py --handshake '{"action": "...", ...}'`
- Returns JSON following the coordination protocol (v2.1)
- Notes are stored in Obsidian vault (markdown files)

## What To Build

### 1. Narration Note Type

Add a dedicated narration format. When the router sends a narration (Daniel's reply to the evening prompt), the note agent should save it as a specific note type:

**Filename**: `narrations/YYYY-MM-DD.md`

**Format**:
```markdown
---
type: narration
date: 2026-02-26
day_type: pipeline
---

# Narration — February 26, 2026 (Pipeline Day)

Worked on XBRL parser, got tag mapping working for 200 fields. Also upgraded the task agent with day-type queues and the email agent with obligation detection. Router now has scheduled prompts.
```

The `day_type` in frontmatter comes from the router's current day-type state, which should be passed to the note agent either via:
- The message itself (router prepends context)
- A handshake context field
- Or the note agent reads `state/current_day_type.json` from the router's state directory (simplest if file paths are accessible)

Pick whichever approach is most consistent with the existing architecture. If the day type isn't available, just omit it from the frontmatter — don't block on it.

### 2. Narration Retrieval Commands

The note agent needs to support queries about narrations:

- **"What did I narrate this week?"** → Retrieve all narrations from current week (Monday–Sunday), return as formatted summary
- **"Show me narrations from last week"** → Previous week's narrations
- **"What have I been working on?"** → Last 7 narrations regardless of week boundary
- **"Narrations about XBRL"** → Search narration content for keyword

Implementation: scan the `narrations/` directory, parse dates from filenames, read content. Simple filesystem operations.

### 3. Weekly Thread Detection

When queried for a weekly synthesis (by the scheduled prompts weekly digest, or by Daniel directly), the note agent should:

1. Collect all narrations from the past 7 days
2. Extract recurring topics/keywords across narrations
3. Group mentions into threads

**Simple v1 approach**: Extract nouns and noun phrases that appear in 2+ narrations during the week. No NLP library needed — the agent is a Claude instance and can do this reasoning in-context.

Return format:
```json
{
  "response": "This week's narrations (4 days):\n\n**Threads forming:**\n• XBRL parsing (mentioned 3x)\n• Agent system upgrades (mentioned 2x)\n\n**One-off mentions:**\n• Grant application\n• Remote work data",
  "status": "complete",
  "narration_count": 4,
  "threads": [
    {"topic": "XBRL parsing", "count": 3, "dates": ["2026-02-24", "2026-02-25", "2026-02-26"]},
    {"topic": "Agent system upgrades", "count": 2, "dates": ["2026-02-25", "2026-02-26"]}
  ]
}
```

The `threads` field in the JSON is structured data the weekly digest (in the router's scheduled_prompts.py) can use to format the Telegram message. The `response` field is the human-readable version.

### 4. Draft Post Generation

When Daniel says "draft a post from this week's narrations" or "turn my narrations into a blog post" or the weekly digest offers and he accepts:

1. Retrieve the week's narrations
2. Identify the dominant thread
3. Draft a short post (300-500 words) in Daniel's voice — informal, technical but accessible, lab-notes style, not polished essay
4. The post should read like a "building in public" update: what he tried, what worked, what surprised him
5. Save the draft as `drafts/YYYY-MM-DD-[topic-slug].md`
6. Return the draft in the response for Daniel to review

**Draft format**:
```markdown
---
type: draft
date: 2026-02-26
source: narrations
thread: XBRL parsing
status: draft
---

# [Title — agent generates based on content]

[Body — synthesized from narrations, written in first person, building-in-public tone]
```

Daniel will edit before publishing. The agent's job is to get him 70% of the way so he's editing existing text rather than staring at a blank page.

### 5. Handshake Support

The note agent should handle these handshake patterns:

**From router (evening narration)**:
```json
{
  "action": "save_narration",
  "content": "Worked on XBRL parser, got tag mapping working...",
  "day_type": "pipeline",
  "date": "2026-02-26"
}
```

**From router (weekly digest requesting synthesis)**:
```json
{
  "action": "weekly_synthesis",
  "week_start": "2026-02-17",
  "week_end": "2026-02-23"
}
```

Response includes the thread analysis and narration summaries for the digest to format.

**Handshake to task agent** (optional, stretch goal):
When a draft is generated, the note agent could signal:
```json
{
  "coordination_needed": ["task"],
  "handshake_context": {
    "action": "create_task",
    "title": "Review and publish draft: XBRL parsing progress",
    "day_type": "outward",
    "source": "note agent draft generation"
  }
}
```

This creates a task in the outward queue to actually publish the draft. Closes the loop from narration → draft → publish.

### 6. Narration Directory Setup

Ensure the `narrations/` and `drafts/` directories exist within the Obsidian vault (or wherever notes are stored). Create them if they don't exist on first use. Add `.gitkeep` files if the vault is version controlled.

### 7. Update Agent Instruction File

Update the Claude.md / instruction file to include:
- Narration as a core note type with its format and storage location
- Narration retrieval query patterns
- Weekly synthesis behavior
- Draft post generation capabilities and tone guidelines
- Handshake handlers for `save_narration` and `weekly_synthesis`
- The principle that drafts are 70% done — Daniel finishes them, the agent doesn't aim for perfection

## What NOT To Build

- Don't build X/Twitter integration (posting, scraping) — that's a future agent or separate tool
- Don't build a full blog publishing pipeline — just generate markdown drafts
- Don't add complex NLP libraries for thread detection — Claude's in-context reasoning is sufficient
- Don't modify the router or other agents from this repo
- Don't change how existing non-narration notes work — this is additive

## Design Principles

- **Local knowledge drives decisions** — The note agent knows about content, themes, and writing. The task agent knows about queues. The router coordinates.
- **Agents signal coordination** — If a draft generates a publish task, that goes through the router via handshake
- **Failures surface visibly** — If narration save fails or the vault path is wrong, tell Daniel explicitly
- **Low friction capture** — Saving a narration should be near-instant. Don't over-process on write; do synthesis on read.

## Testing

1. `uv run python query.py "Save this narration: Worked on XBRL parser today, got 200 tags mapped"` → should create `narrations/2026-02-26.md`
2. `uv run python query.py --handshake '{"action": "save_narration", "content": "Built out the email agent obligation detection", "day_type": "pipeline", "date": "2026-02-26"}'` → should create/append narration
3. `uv run python query.py "what did I narrate this week?"` → should return this week's narrations
4. `uv run python query.py --handshake '{"action": "weekly_synthesis", "week_start": "2026-02-17", "week_end": "2026-02-23"}'` → should return thread analysis
5. `uv run python query.py "draft a post from this week's narrations"` → should generate a draft in `drafts/`
6. Verify narration files have correct frontmatter and formatting
7. Verify multiple narrations in a week produce sensible thread detection
8. Test with zero narrations → should handle gracefully ("No narrations this week")