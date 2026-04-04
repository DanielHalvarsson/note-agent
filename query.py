#!/usr/bin/env python3
"""
Note Agent - Query Interface

CLI interface for conversational note-taking and wiki queries against Obsidian vault.
Used by the personal-assistant router for conversational note management.

Usage:
    uv run python query.py "Note: had great idea about X"
    uv run python query.py "Add to today: met with Sarah"
    uv run python query.py "What did I note about Canadian?"
    uv run python query.py "Wiki status"
    uv run python query.py "What does the wiki know about firm dynamics?"
    uv run python query.py --handshake '{"action": "compile_source", "source_path": "raw/papers/..."}'
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
    Process user's note or wiki request using Claude CLI.

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

    prompt = f"""You are the note-taking and wiki specialist agent for Daniel's personal assistant.

Your role: Capture notes into Obsidian vault AND answer queries against the wiki knowledge base.
{conversation_context}
User request: "{user_request}"

CRITICAL - Using Conversation Context:
- If conversation context shows recently discussed topics, USE THEM for context
- When user says "note that", "capture it", "add that to today" - refer to what was just discussed
- Auto-tag with people/projects from conversation context

Note-taking instructions:
- CRITICAL: Always use 'uv run' when running scripts
- Use scripts/note.py for vault operations (create, append-daily, search, read, list)
- Be concise and format for Telegram using HTML: <b>bold</b> for emphasis, plain bullets (•) for lists
- Auto-detect people, projects, and meaningful tags from content
- Default to Inbox/ for captures unless context suggests Projects/ or People/

Common note patterns:
- "Note: X" → uv run scripts/note.py create "Title" "X" [] "Inbox"
- "Add to today: X" → uv run scripts/note.py append-daily "X"
- "Capture: X" → quick capture to Inbox
- "What did I note about X?" → uv run scripts/note.py search "X"
- "Show my notes from today" → uv run scripts/note.py list "Daily" 10

Wiki query instructions:
- "Wiki status" → run: uv run python registry.py --context
- "What does the wiki know about X?" → run: uv run python registry.py --context, then check for matching articles, then read relevant article files from wiki/{{section}}/{{slug}}.md
- "What's in the wiki about X?" → same as above
- "Compile new sources" → run: uv run python intake.py --scan then uv run python intake.py --process
- "Compile [file]" → uv run python compile.py [file]
- For wiki queries, after loading the registry context, read the specific article file if the user wants detail

Tools available: Bash (to run scripts), Read (for file contents).
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
            timeout=90,
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
    import yaml
    context = json.loads(context_json)
    action = context.get("action")

    config = load_config()
    vault_path = Path(config["obsidian"]["vault_path"])

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

    if action == "compile_source":
        # Another agent (e.g., research agent) drops a source for compilation
        source_path = context.get("source_path", "")
        source_type = context.get("source_type", "paper")

        if not source_path:
            return json.dumps({"response": "No source_path provided.", "status": "blocked"})

        from intake import register_source
        from registry import load_registry

        abs_path = vault_path / source_path if not Path(source_path).is_absolute() else Path(source_path)
        registry = load_registry(vault_path)
        known = {s["path"] for s in registry.get("pending_sources", [])}

        try:
            rel_path = str(abs_path.relative_to(vault_path))
        except ValueError:
            rel_path = source_path

        if rel_path not in known:
            result = register_source(abs_path, source_type)
            title = result.get("title", source_path)
        else:
            title = source_path

        return json.dumps({
            "response": f"Source registered for compilation: {title}",
            "status": "complete",
            "actions": [{"type": "source_registered", "path": rel_path}]
        })

    if action == "query_wiki":
        # Another agent asks what the wiki knows about a topic
        topic = context.get("topic", "")
        if not topic:
            return json.dumps({"response": "No topic provided.", "status": "blocked"})

        from indexer import find_related_articles, get_article_summary

        tags = topic.lower().split()
        articles = find_related_articles(vault_path, tags)

        if articles:
            summaries = []
            for section, slug, title, overlap_tags in articles[:5]:
                summary = get_article_summary(vault_path, section, slug) or ""
                summaries.append(f"[{section}/{slug}] {title}: {summary[:200]}")

            return json.dumps({
                "response": "\n\n".join(summaries),
                "status": "complete",
                "articles_found": len(articles)
            })
        else:
            return json.dumps({
                "response": f"No wiki articles found matching '{topic}'",
                "status": "complete",
                "articles_found": 0
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
