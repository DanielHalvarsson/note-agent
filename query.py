#!/usr/bin/env python3
"""
Note Agent - Query Interface

CLI interface for conversational note-taking with Obsidian vault.
Used by the personal-assistant router for conversational note management.

Usage:
    uv run python query.py "Note: had great idea about X"
    uv run python query.py "Add to today: met with Sarah"
    uv run python query.py "What did I note about Canadian?"
"""

import sys
import os
import subprocess
import json
from pathlib import Path

import argparse

AGENT_DIR = Path(__file__).parent
STATE_DIR = AGENT_DIR / "state"


def load_config():
    """Load configuration from config.yaml."""
    import yaml
    config_path = AGENT_DIR / "config.yaml"
    if not config_path.exists():
        print("ERROR: config.yaml not found", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def query_with_claude(user_request):
    """
    Process user's note request using Claude CLI.

    Returns: Plain text response
    """
    config = load_config()
    claude_bin = config.get("claude_cli", {}).get("bin", "claude")
    model = config.get("claude_cli", {}).get("model", "haiku")

    # Read conversation context from environment
    conversation_context = ""
    if "CONVERSATION_CONTEXT" in os.environ:
        try:
            context_data = json.loads(os.environ["CONVERSATION_CONTEXT"])
            if context_data:
                conversation_context = "\n\nRecent conversation:\n"
                for msg in context_data:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    conversation_context += f"{role}: {msg['content'][:150]}\n"
        except:
            pass

    prompt = f"""You are the note-taking specialist agent for Daniel's personal assistant.

Your role: Capture notes, thoughts, and information into Obsidian vault.
{conversation_context}
User request: "{user_request}"

CRITICAL - Using Conversation Context:
- If conversation context shows recently discussed topics, USE THEM for context
- When user says "note that", "capture it", "add that to today" - refer to what was just discussed
- Auto-tag with people/projects from conversation context

Instructions:
- CRITICAL: Always use 'uv run' when running scripts (e.g., uv run scripts/note.py create "Title" "Content")
- Use note.py for vault operations (create, append-daily, search, read, list)
- Be concise and format for Telegram using HTML: <b>bold</b> for emphasis, plain bullets (•) for lists
- Auto-detect people, projects, and meaningful tags from content
- Default to Inbox/ for captures unless context suggests Projects/ or People/
- For "add to today" requests, use append-daily command
- For quick captures without specific structure, use create command
- After creating/appending notes, confirm what you did

Common patterns:
- "Note: X" → create note in Inbox with title extracted from X
- "Add to today: X" → append to daily note with timestamp
- "Capture: X" → quick capture to Inbox
- "What did I note about X?" → search for X
- "Show my notes from today" → list from Daily/

Use the tools available (Bash to run note.py, Read for CLAUDE.md) as needed.
Respond conversationally and directly to the user's request.
"""

    try:
        cmd = [
            claude_bin,
            "--print",
            prompt,
            "--allowedTools", "Bash,Read"
        ]

        if model:
            cmd.extend(["--model", model])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(AGENT_DIR),
            timeout=60,
            env={**os.environ, "LANG": "en_US.UTF-8"}
        )

        response = result.stdout.strip()

        if not response:
            return "I couldn't process that request. Try rephrasing?"

        return response

    except subprocess.TimeoutExpired:
        return "⚠️ Request timed out. Try a simpler request."
    except FileNotFoundError:
        return "⚠️ Claude CLI not found. Check configuration."
    except Exception as e:
        return f"⚠️ Error: {str(e)}"


def handle_handshake(context_json):
    """Handle coordination handshake from another agent."""
    context = json.loads(context_json)
    action = context.get("action")

    if action == "citation_results":
        # Research agent sent back papers — integrate into note
        papers = context.get("papers", [])
        note_path = context.get("note_path", "")
        response = query_with_claude(
            f"Add these citation results to the note at {note_path}: {json.dumps(papers[:5])}"
        )
        return json.dumps({
            "response": response,
            "status": "complete",
            "actions": [{"type": "citations_integrated", "count": len(papers)}]
        })

    return json.dumps({
        "response": f"Unknown handshake action: {action}",
        "status": "blocked"
    })


def main():
    parser = argparse.ArgumentParser(description="Note Agent")
    parser.add_argument("query", nargs="*", help="User request")
    parser.add_argument("--handshake", help="Handshake context JSON")
    args = parser.parse_args()

    if args.handshake:
        print(handle_handshake(args.handshake))
        return

    if not args.query:
        print(__doc__)
        sys.exit(1)

    request = " ".join(args.query)
    response = query_with_claude(request)

    # If response is already JSON (coordination), pass through
    # Otherwise wrap plain text with HTML parse mode
    try:
        json.loads(response)
        print(response)
    except (json.JSONDecodeError, TypeError):
        print(json.dumps({
            "response": response,
            "parse_mode": "HTML",
            "status": "complete"
        }, indent=2))


if __name__ == "__main__":
    main()
