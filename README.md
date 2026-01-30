# Note Agent

A specialized agent for conversational note-taking with Obsidian vault integration.

## Philosophy

**Single Responsibility:** This agent handles ONLY note capture, search, and retrieval. Obsidian handles visualization (graph view, backlinks).

**Hayekian Knowledge Distribution:**
- **Router** maintains conversation history
- **Note agent** uses context to auto-tag and organize notes
- **Obsidian** provides UI, graph view, and manual curation

## Architecture

```
note-agent/
├── query.py                  # Conversational interface (called by router)
├── scripts/
│   └── note.py              # Obsidian vault operations
├── state/                    # Local state (future)
├── templates/                # Note templates (future)
├── config.yaml              # Configuration (vault path)
└── CLAUDE.md                # Note-taking instructions
```

## Features (MVP)

✅ **Quick Capture** - "Note: had great idea about X"
✅ **Daily Notes** - "Add to today: met with Sarah"
✅ **Search** - "What did I note about Canadian?"
✅ **Auto-Organization** - Detects people, projects, tags
✅ **Conversation Context** - "Note that" refers to recent discussion
✅ **Frontmatter Metadata** - YAML frontmatter with timestamps, tags

## Vault Structure

The agent expects this Obsidian vault structure:

```
obsidian-vault/
├── Daily/              # Daily notes (YYYY-MM-DD.md)
│   └── 2026-01-28.md
├── Inbox/              # Quick captures (default)
│   └── *.md
├── People/             # People-related notes
│   ├── Dennis.md
│   └── Sarah.md
├── Projects/           # Project notes
│   ├── Canadian.md
│   └── OpenAdam.md
└── Templates/          # Note templates (future)
```

## Setup

### 1. Install dependencies

```bash
cd ~/server-projects/note-agent
uv venv
uv pip install -r requirements.txt
```

### 2. Create Obsidian vault

```bash
# Create vault directory
mkdir -p ~/obsidian-vault/{Daily,Inbox,People,Projects,Templates}

# Or use existing vault - just update config.yaml
```

### 3. Configure

```bash
cp config.example.yaml config.yaml
nano config.yaml  # Set vault_path
```

### 4. Test it

```bash
# Make executable
chmod +x query.py scripts/note.py

# Test operations
python3 query.py "Note: Testing the note agent"
python3 query.py "Add to today: Setup completed"
python3 query.py "What did I note today?"
```

## Usage Examples

### Quick Captures

```bash
python3 query.py "Note: had great idea about using AI for X"
python3 query.py "Capture: follow up with Dennis about Canadian"
python3 query.py "Remember: Sarah mentioned budget approval"
```

**Result:** Saves to `Inbox/` with auto-detected tags and metadata.

### Daily Notes

```bash
python3 query.py "Add to today: Met with team, discussed Q1 goals"
python3 query.py "Log: Completed DO-files task"
python3 query.py "Journal: Feeling productive today"
```

**Result:** Appends to `Daily/2026-01-28.md` with timestamp.

### Search & Retrieval

```bash
python3 query.py "What did I note about Canadian contract?"
python3 query.py "Find notes about Dennis"
python3 query.py "Show my notes from today"
```

**Result:** Returns matching notes with paths and snippets.

### Direct Script Usage

For batch operations or testing:

```bash
# Create note
uv run scripts/note.py create "Meeting Notes" "Discussed budget with Sarah" "meeting,budget,sarah" "Inbox"

# Append to daily
uv run scripts/note.py append-daily "Completed task X" "tasks,completion"

# Search
uv run scripts/note.py search "Canadian" "Projects"

# List recent
uv run scripts/note.py list "Daily" 5
```

## Integration with Router

The note-agent integrates with personal-assistant router for Telegram access:

**Router keywords:** "note", "capture", "remember", "add to today", "what did I note"

**Request flow:**
```
User (Telegram) → Router → Note Agent → Obsidian Vault
                                    ↓
                              Response (confirmation)
```

### Add to router config:

```yaml
agents:
  note:
    path: "/home/server_lama/server-projects/note-agent"
    query_command: "python query.py"
    model: "haiku"
```

## Conversation Context

The note-agent receives conversation history, enabling context-aware captures:

```
User: "I just talked to Dennis about the Canadian contract"
Assistant: "How did it go?"
User: "Note that"
Agent: ✓ Saved to Projects/Canadian.md
       • Content: "Talked to Dennis about Canadian contract"
       • Tagged: #dennis #canadian
       • Detected: Dennis (person), Canadian (project)
```

## Auto-Detection Features

### People Detection
- Recognizes capitalized names: Dennis, Sarah, John
- Adds to `people:` frontmatter
- Can auto-file to `People/` folder if primarily about one person

### Project Detection
- Recognizes all-caps keywords: CANADIAN, OPENAI
- Adds to `projects:` frontmatter
- Can auto-file to `Projects/` folder

### Tag Extraction
- Hashtags in content: #meeting #decision
- Content-based: mentions "deadline" → #deadline
- Context-based: after calendar event → #meeting

## Note Format

All notes use frontmatter for metadata:

```markdown
---
created: 2026-01-28T14:30:00
modified: 2026-01-28T14:30:00
tags: [meeting, canadian, dennis]
people: [Dennis]
projects: [Canadian]
---

# DO-files for Canadian

Dennis mentioned we need to prepare DO-files for Canadian project by Friday.

Action items:
- [ ] Gather required documents
- [ ] Review with legal
- [ ] Submit by Friday
```

## Comparison with Other Agents

| Feature | calendar-agent | email-agent | task-agent | **note-agent** |
|---------|---------------|-------------|------------|----------------|
| **Purpose** | Events/meetings | Email triage | To-dos | Knowledge capture |
| **Actions** | Create/modify | Read/classify | CRUD tasks | Create/search notes |
| **Model** | Sonnet | Haiku | Haiku | Haiku |
| **Storage** | Google Calendar | Gmail | Google Tasks | Local Obsidian vault |
| **State** | Stateless | Classification history | Stateless | File-based (markdown) |

## Future Enhancements

**Phase 2 (Post-MVP):**
- [ ] Meeting note templates (auto-create from calendar events)
- [ ] Extract action items → task-agent integration
- [ ] Periodic notes (weekly, monthly summaries)
- [ ] Smart folder organization (ML-based)
- [ ] Link suggestions (based on content similarity)

**Phase 3:**
- [ ] Voice note transcription
- [ ] Image/attachment handling
- [ ] Note versioning (git integration)
- [ ] Collaborative notes (shared vault support)

## Troubleshooting

**Notes not appearing in Obsidian:**
- Check vault path in config.yaml
- Verify Obsidian is pointed to same vault directory
- Refresh Obsidian vault (Cmd/Ctrl + R)

**Auto-detection not working:**
- People names must be capitalized
- Projects must be all-caps or explicitly mentioned
- Check CLAUDE.md for detection patterns

**Search returns no results:**
- Notes must contain query text
- Case-insensitive search
- Try broader search terms

## Development

Run tests:
```bash
# Test note creation
uv run scripts/note.py create "Test" "Test content" "test"

# Test daily append
uv run scripts/note.py append-daily "Test entry"

# Test search
uv run scripts/note.py search "test"
```

## Philosophy Notes

**Why file-based (not database)?**
- Obsidian uses markdown files
- User owns their data
- Works with any text editor
- Git-friendly
- No vendor lock-in

**Why Inbox-first?**
- Capture > organize
- Reduces friction
- User curates later in Obsidian
- Agent focuses on speed

**Why auto-detect vs ask?**
- Faster capture
- Uses conversation context
- User can override in Obsidian
- Wrong folder < missed capture
