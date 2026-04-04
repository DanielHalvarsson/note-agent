#!/usr/bin/env python3
"""
Obsidian Vault Operations

CLI interface for interacting with Obsidian vault (markdown notes).

Usage:
    python note.py create "<title>" "<content>" [--tags tag1,tag2] [--folder Inbox]
    python note.py append-daily "<content>" [--tags tag1,tag2]
    python note.py search "<query>" [--folder Daily] [--tags tag1,tag2]
    python note.py read "<filename>"
    python note.py list [--folder Daily] [--limit 10]
    python note.py save-narration "<content>" [day_type] [date YYYY-MM-DD]
    python note.py list-narrations [--week current|last] [--last N] [--keyword X]
    python note.py save-draft "<title>" "<content>"
"""

import sys
import os
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List

# Add parent directory to path for config
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_config():
    """Load configuration from config.yaml"""
    import yaml
    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        print("ERROR: config.yaml not found", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_vault_path() -> Path:
    """Get Obsidian vault path from config."""
    config = get_config()
    vault_path = Path(config['obsidian']['vault_path'])
    if not vault_path.exists():
        print(f"ERROR: Vault path does not exist: {vault_path}", file=sys.stderr)
        sys.exit(1)
    return vault_path


def sanitize_filename(title: str) -> str:
    """Convert title to safe filename."""
    # Replace unsafe characters with hyphen
    safe = re.sub(r'[^\w\s-]', '', title)
    safe = re.sub(r'[-\s]+', '-', safe)
    return safe.strip('-')


def generate_frontmatter(tags: Optional[List[str]] = None, metadata: Optional[dict] = None) -> str:
    """Generate YAML frontmatter for note."""
    now = datetime.now().isoformat()

    frontmatter = {
        'created': now,
        'modified': now,
    }

    if tags:
        frontmatter['tags'] = tags

    if metadata:
        frontmatter.update(metadata)

    # Format as YAML
    lines = ['---']
    for key, value in frontmatter.items():
        if isinstance(value, list):
            lines.append(f'{key}:')
            for item in value:
                lines.append(f'  - {item}')
        else:
            lines.append(f'{key}: {value}')
    lines.append('---')

    return '\n'.join(lines)


def extract_metadata(content: str) -> dict:
    """Extract people, projects, and other metadata from content."""
    metadata = {}

    # Extract people (capitalized names, simple heuristic)
    people_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b'
    people = list(set(re.findall(people_pattern, content)))
    if people:
        metadata['people'] = people[:5]  # Limit to 5

    # Extract potential project keywords (all caps words > 3 chars)
    projects = list(set(re.findall(r'\b[A-Z]{4,}\b', content)))
    if projects:
        metadata['projects'] = projects

    return metadata


def create_note(title: str, content: str, tags: Optional[List[str]] = None, folder: str = "Inbox") -> str:
    """Create a new note in the vault."""
    vault_path = get_vault_path()
    folder_path = vault_path / folder
    folder_path.mkdir(parents=True, exist_ok=True)

    # Generate filename
    filename = sanitize_filename(title)
    note_path = folder_path / f"{filename}.md"

    # Handle duplicates
    counter = 1
    while note_path.exists():
        note_path = folder_path / f"{filename}-{counter}.md"
        counter += 1

    # Extract metadata from content
    auto_metadata = extract_metadata(content)

    # Generate frontmatter
    frontmatter = generate_frontmatter(tags=tags, metadata=auto_metadata)

    # Write note
    full_content = f"{frontmatter}\n\n# {title}\n\n{content}\n"
    note_path.write_text(full_content, encoding='utf-8')

    result = {
        'status': 'created',
        'path': str(note_path.relative_to(vault_path)),
        'title': title,
        'tags': tags or [],
        'metadata': auto_metadata
    }

    print(json.dumps(result, indent=2))
    return str(note_path)


def get_daily_note_path(target_date: Optional[date] = None) -> Path:
    """Get path to daily note (creates folder if needed)."""
    vault_path = get_vault_path()
    daily_folder = vault_path / "Daily"
    daily_folder.mkdir(parents=True, exist_ok=True)

    if target_date is None:
        target_date = date.today()

    filename = target_date.strftime("%Y-%m-%d.md")
    return daily_folder / filename


def append_to_daily(content: str, tags: Optional[List[str]] = None, target_date: Optional[date] = None) -> str:
    """Append content to daily note (creates if doesn't exist)."""
    note_path = get_daily_note_path(target_date)

    if not note_path.exists():
        # Create new daily note
        if target_date is None:
            target_date = date.today()

        title = target_date.strftime("%Y-%m-%d")
        frontmatter = generate_frontmatter(tags=tags, metadata={'date': target_date.isoformat()})
        initial_content = f"{frontmatter}\n\n# {title}\n\n"
        note_path.write_text(initial_content, encoding='utf-8')

    # Append content with timestamp
    timestamp = datetime.now().strftime("%H:%M")
    append_text = f"\n## {timestamp}\n\n{content}\n"

    with open(note_path, 'a', encoding='utf-8') as f:
        f.write(append_text)

    vault_path = get_vault_path()
    result = {
        'status': 'appended',
        'path': str(note_path.relative_to(vault_path)),
        'timestamp': timestamp,
        'tags': tags or []
    }

    print(json.dumps(result, indent=2))
    return str(note_path)


def search_notes(query: str, folder: Optional[str] = None, tags: Optional[List[str]] = None, limit: int = 10) -> List[dict]:
    """Search notes by content or metadata."""
    vault_path = get_vault_path()

    if folder:
        search_path = vault_path / folder
    else:
        search_path = vault_path

    results = []

    # Search all .md files
    for note_path in search_path.rglob("*.md"):
        try:
            content = note_path.read_text(encoding='utf-8')

            # Check if query matches
            if query.lower() in content.lower():
                # Extract title (first # heading)
                title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                title = title_match.group(1) if title_match else note_path.stem

                # Extract snippet around match
                lines = content.split('\n')
                match_line = next((i for i, line in enumerate(lines) if query.lower() in line.lower()), 0)
                start = max(0, match_line - 1)
                end = min(len(lines), match_line + 2)
                snippet = ' '.join(lines[start:end]).strip()

                results.append({
                    'path': str(note_path.relative_to(vault_path)),
                    'title': title,
                    'snippet': snippet[:200] + '...' if len(snippet) > 200 else snippet,
                    'modified': datetime.fromtimestamp(note_path.stat().st_mtime).isoformat()
                })

                if len(results) >= limit:
                    break
        except Exception as e:
            continue

    print(json.dumps(results, indent=2))
    return results


def read_note(filename: str) -> dict:
    """Read a specific note."""
    vault_path = get_vault_path()

    # Try direct path first
    note_path = vault_path / filename
    if not note_path.exists():
        # Try with .md extension
        note_path = vault_path / f"{filename}.md"

    if not note_path.exists():
        # Search for it
        for found_path in vault_path.rglob(f"*{filename}*.md"):
            note_path = found_path
            break

    if not note_path.exists():
        print(json.dumps({'error': f'Note not found: {filename}'}))
        sys.exit(1)

    content = note_path.read_text(encoding='utf-8')

    result = {
        'path': str(note_path.relative_to(vault_path)),
        'content': content,
        'modified': datetime.fromtimestamp(note_path.stat().st_mtime).isoformat()
    }

    print(json.dumps(result, indent=2))
    return result


def list_notes(folder: Optional[str] = None, limit: int = 10) -> List[dict]:
    """List recent notes."""
    vault_path = get_vault_path()

    if folder:
        search_path = vault_path / folder
    else:
        search_path = vault_path

    # Get all .md files sorted by modification time
    notes = []
    for note_path in search_path.rglob("*.md"):
        try:
            content = note_path.read_text(encoding='utf-8')

            # Extract title
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            title = title_match.group(1) if title_match else note_path.stem

            notes.append({
                'path': str(note_path.relative_to(vault_path)),
                'title': title,
                'modified': note_path.stat().st_mtime
            })
        except:
            continue

    # Sort by modification time (newest first)
    notes.sort(key=lambda x: x['modified'], reverse=True)

    # Format timestamps
    results = []
    for note in notes[:limit]:
        results.append({
            'path': note['path'],
            'title': note['title'],
            'modified': datetime.fromtimestamp(note['modified']).isoformat()
        })

    print(json.dumps(results, indent=2))
    return results


def save_narration(content: str, day_type: Optional[str] = None, target_date: Optional[date] = None) -> str:
    """Save a narration to narrations/YYYY-MM-DD.md (creates or appends)."""
    vault_path = get_vault_path()
    narrations_folder = vault_path / "narrations"
    narrations_folder.mkdir(parents=True, exist_ok=True)

    if target_date is None:
        target_date = date.today()

    note_path = narrations_folder / f"{target_date.isoformat()}.md"

    if not note_path.exists():
        # Build frontmatter
        fm_lines = ['---', f'type: narration', f'date: {target_date.isoformat()}']
        if day_type:
            fm_lines.append(f'day_type: {day_type}')
        fm_lines.append('---')
        frontmatter = '\n'.join(fm_lines)

        # Build heading
        heading_date = target_date.strftime("%B %-d, %Y")
        if day_type:
            heading = f"# Narration — {heading_date} ({day_type.replace('-', ' ').title()} Day)"
        else:
            heading = f"# Narration — {heading_date}"

        note_path.write_text(f"{frontmatter}\n\n{heading}\n\n{content}\n", encoding='utf-8')
    else:
        # Append to existing narration with timestamp separator
        timestamp = datetime.now().strftime("%H:%M")
        with open(note_path, 'a', encoding='utf-8') as f:
            f.write(f"\n---\n\n*{timestamp}*\n\n{content}\n")

    result = {
        'status': 'saved',
        'path': str(note_path.relative_to(vault_path)),
        'date': target_date.isoformat(),
        'day_type': day_type
    }
    print(json.dumps(result, indent=2))
    return str(note_path)


def list_narrations(week: Optional[str] = None, last_n: Optional[int] = None, keyword: Optional[str] = None) -> List[dict]:
    """List narrations by week, last N, or keyword search."""
    vault_path = get_vault_path()
    narrations_folder = vault_path / "narrations"

    if not narrations_folder.exists():
        print(json.dumps([]))
        return []

    today = date.today()

    # Determine date range
    start_date = None
    end_date = None

    if week == "current":
        # Monday to Sunday of current week
        monday = today - timedelta(days=today.weekday())
        start_date = monday
        end_date = monday + timedelta(days=6)
    elif week == "last":
        monday = today - timedelta(days=today.weekday() + 7)
        start_date = monday
        end_date = monday + timedelta(days=6)

    # Collect narration files
    narration_files = sorted(narrations_folder.glob("*.md"), reverse=True)

    results = []
    for nf in narration_files:
        # Parse date from filename
        try:
            file_date = date.fromisoformat(nf.stem)
        except ValueError:
            continue

        # Apply date filter
        if start_date and not (start_date <= file_date <= end_date):
            continue

        content = nf.read_text(encoding='utf-8')

        # Apply keyword filter
        if keyword and keyword.lower() not in content.lower():
            continue

        results.append({
            'path': str(nf.relative_to(vault_path)),
            'date': file_date.isoformat(),
            'content': content
        })

    # Apply last N limit (after date filter)
    if last_n is not None:
        results = results[:last_n]

    print(json.dumps(results, indent=2))
    return results


def save_draft(title: str, content: str) -> str:
    """Save a draft post to drafts/YYYY-MM-DD-<topic-slug>.md."""
    vault_path = get_vault_path()
    drafts_folder = vault_path / "drafts"
    drafts_folder.mkdir(parents=True, exist_ok=True)

    today = date.today()
    slug = sanitize_filename(title).lower()
    filename = f"{today.isoformat()}-{slug}.md"
    draft_path = drafts_folder / filename

    # Handle duplicates
    counter = 1
    while draft_path.exists():
        draft_path = drafts_folder / f"{today.isoformat()}-{slug}-{counter}.md"
        counter += 1

    fm_lines = [
        '---',
        f'type: draft',
        f'date: {today.isoformat()}',
        f'source: narrations',
        f'status: draft',
        '---'
    ]
    frontmatter = '\n'.join(fm_lines)

    draft_path.write_text(f"{frontmatter}\n\n{content}\n", encoding='utf-8')

    result = {
        'status': 'saved',
        'path': str(draft_path.relative_to(vault_path)),
        'title': title,
        'date': today.isoformat()
    }
    print(json.dumps(result, indent=2))
    return str(draft_path)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "create":
        if len(sys.argv) < 4:
            print("ERROR: title and content required")
            sys.exit(1)
        title = sys.argv[2]
        content = sys.argv[3]
        tags = sys.argv[4].split(',') if len(sys.argv) > 4 and sys.argv[4] else None
        folder = sys.argv[5] if len(sys.argv) > 5 else "Inbox"
        create_note(title, content, tags=tags, folder=folder)

    elif command == "append-daily":
        if len(sys.argv) < 3:
            print("ERROR: content required")
            sys.exit(1)
        content = sys.argv[2]
        tags = sys.argv[3].split(',') if len(sys.argv) > 3 and sys.argv[3] else None
        # Optional date override as 4th arg YYYY-MM-DD
        target_date = None
        if len(sys.argv) > 4 and sys.argv[4]:
            try:
                target_date = date.fromisoformat(sys.argv[4])
            except ValueError:
                print(f"ERROR: invalid date format: {sys.argv[4]}", file=sys.stderr)
                sys.exit(1)
        append_to_daily(content, tags=tags, target_date=target_date)

    elif command == "search":
        if len(sys.argv) < 3:
            print("ERROR: query required")
            sys.exit(1)
        query = sys.argv[2]
        folder = sys.argv[3] if len(sys.argv) > 3 else None
        tags = sys.argv[4].split(',') if len(sys.argv) > 4 and sys.argv[4] else None
        search_notes(query, folder=folder, tags=tags)

    elif command == "read":
        if len(sys.argv) < 3:
            print("ERROR: filename required")
            sys.exit(1)
        read_note(sys.argv[2])

    elif command == "list":
        folder = sys.argv[2] if len(sys.argv) > 2 else None
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        list_notes(folder=folder, limit=limit)

    elif command == "save-narration":
        if len(sys.argv) < 3:
            print("ERROR: content required")
            sys.exit(1)
        content = sys.argv[2]
        day_type = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
        # Optional date override as 4th arg YYYY-MM-DD
        target_date = None
        if len(sys.argv) > 4 and sys.argv[4]:
            try:
                target_date = date.fromisoformat(sys.argv[4])
            except ValueError:
                print(f"ERROR: invalid date format: {sys.argv[4]}", file=sys.stderr)
                sys.exit(1)
        save_narration(content, day_type=day_type, target_date=target_date)

    elif command == "list-narrations":
        week = None
        last_n = None
        keyword = None
        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--week" and i + 1 < len(sys.argv):
                week = sys.argv[i + 1]
                i += 2
            elif arg == "--last" and i + 1 < len(sys.argv):
                last_n = int(sys.argv[i + 1])
                i += 2
            elif arg == "--keyword" and i + 1 < len(sys.argv):
                keyword = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        list_narrations(week=week, last_n=last_n, keyword=keyword)

    elif command == "save-draft":
        if len(sys.argv) < 4:
            print("ERROR: title and content required")
            sys.exit(1)
        save_draft(sys.argv[2], sys.argv[3])

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
