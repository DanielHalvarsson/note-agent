# Note Agent Setup & Testing

## Quick Start

The note-agent is ready for development and testing!

### 1. Verify Setup

```bash
cd ~/server-projects/note-agent

# Check vault was created
ls -la ~/obsidian-vault

# Test note creation
uv run scripts/note.py create "Test Note" "This is a test" "test" "Inbox"

# Test daily append
uv run scripts/note.py append-daily "Testing daily notes"

# Test search
uv run scripts/note.py search "test"

# Test list
uv run scripts/note.py list "Inbox" 5
```

### 2. Test Conversational Interface

```bash
# Quick captures
uv run python query.py "Note: Testing the note agent setup"
uv run python query.py "Capture: Remember to integrate with router"

# Daily notes
uv run python query.py "Add to today: Setup completed successfully"

# Search
uv run python query.py "What did I note about setup?"
```

### 3. Open Dedicated Session

**To continue development in a focused session:**

1. Open new Claude Code session
2. Set working directory: `/home/server_lama/server-projects/note-agent`
3. Context: "I'm working on the note-agent for Obsidian integration. This is part of a personal assistant system with specialized agents following Hayekian philosophy."

This gives you a clean slate focused solely on note-agent development without the context of the full personal-assistant system.

## Integration with Router

Once note-agent is tested and ready, integrate with router:

### Add to router config:

Edit `/home/server_lama/server-projects/personal-assistant/config.yaml`:

```yaml
agents:
  note:
    path: "/home/server_lama/server-projects/note-agent"
    query_command: "uv run python query.py"
    model: "haiku"
```

### Update router classification:

Edit `telegram_router.py` to recognize note-related keywords:
- "note", "capture", "remember", "add to today"
- "what did I note", "find notes", "show notes"

### Restart router:

```bash
cd ~/server-projects/personal-assistant
systemctl --user restart personal-assistant.service
```

## Next Steps

**In dedicated note-agent session:**

1. Test all core operations
2. Refine auto-detection logic
3. Add more sophisticated tagging
4. Implement smart folder organization
5. Add meeting note templates
6. Test conversation context integration
7. Add comprehensive error handling

**Later (after router integration):**

1. Test end-to-end via Telegram
2. Refine prompts based on real usage
3. Add task extraction (→ task-agent)
4. Add calendar event linking (→ calendar-agent)
5. Implement periodic notes (weekly/monthly)

## Obsidian Integration

### Open vault in Obsidian:

1. Open Obsidian
2. "Open folder as vault"
3. Select `/home/server_lama/obsidian-vault`

You'll see the folder structure with your captured notes!

### Recommended Obsidian Plugins:

- **Templater** - For advanced note templates
- **Dataview** - Query notes with metadata
- **Calendar** - Visual daily notes interface
- **Tag Wrangler** - Manage tags
- **Advanced Tables** - Better markdown tables

## Development Tips

**Testing auto-detection:**
```bash
# Test people detection
uv run scripts/note.py create "Meeting" "Met with Dennis and Sarah about Canadian project" "" "Inbox"

# Check the generated note for auto-detected metadata
cat ~/obsidian-vault/Inbox/Meeting.md
```

**Testing conversation context:**

Set CONVERSATION_CONTEXT env var:
```bash
export CONVERSATION_CONTEXT='[{"role":"user","content":"I just talked to Dennis about Canadian"},{"role":"assistant","content":"How did it go?"}]'
uv run python query.py "Note that"
```

**Debugging:**

Add `--debug` to query.py calls or check Claude CLI output directly.

## Current Status

✅ Repository initialized
✅ Core operations implemented (create, append, search, read, list)
✅ Conversational interface ready
✅ Auto-detection for people/projects
✅ Frontmatter metadata generation
✅ Vault structure created
✅ Configuration examples provided
✅ Comprehensive documentation written

🔲 Router integration (pending)
🔲 End-to-end testing via Telegram (pending)
🔲 Advanced features (templates, task extraction, etc.)

Ready for dedicated development session!
