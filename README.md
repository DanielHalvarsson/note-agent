# Note Agent

A specialist agent in Daniel's Hayekian personal assistant system. Handles note capture, search, and a **wiki knowledge compiler** that turns raw source material into a structured, LLM-maintained knowledge base inside Obsidian.

## What it does

**Note-taking** — capture thoughts via Telegram, auto-organize into Obsidian vault (people, projects, daily notes, inbox).

**Wiki compilation** — raw sources (clippings, papers, fragments) land in `raw/`, get compiled by Claude into structured wiki articles with a tiered index system that keeps context windows small as the corpus grows.

## Architecture

```
note-agent/
├── query.py          # Router entry point — note queries + wiki queries + handshakes
├── compile.py        # Wiki compiler engine (LLM-powered)
├── registry.py       # Tier 1: _registry.yaml — always-loaded master manifest
├── indexer.py        # Tier 2: per-section _index.md — loaded on demand
├── intake.py         # Raw source entry point — classify, register, scan
├── monitor.py        # Daily health checks — pending sources, stale sections
├── scripts/
│   └── note.py       # Obsidian vault operations CLI
└── config.yaml       # Vault path, Claude CLI config, wiki settings
```

## Vault structure

```
obsidian-vault/
├── Daily/            # Daily notes (YYYY-MM-DD.md)
├── Inbox/            # Quick captures
├── People/           # People notes
├── Projects/         # Project notes
├── wiki/             # Compiled knowledge base (LLM-maintained)
│   ├── _registry.yaml        # Tier 1: master manifest (~5KB, always in context)
│   ├── research/
│   │   ├── _index.md         # Tier 2: section index (loaded on demand)
│   │   └── *.md              # Tier 3: full articles
│   ├── ideas/
│   ├── references/
│   └── personal/
└── raw/              # Intake directory
    ├── clippings/    # Web clippings
    ├── fragments/    # Fragment Library / quick grabs
    ├── papers/       # Research papers (from research agent)
    └── notes/        # Note captures
```

## Tiered indexing

The wiki never loads the full corpus into context:

| Tier | File | Size | When loaded |
|------|------|------|-------------|
| 1 | `_registry.yaml` | ~5KB | Every compilation |
| 2 | `wiki/{section}/_index.md` | ~10KB | When working in a section |
| 3 | `wiki/{section}/{slug}.md` | varies | Only the target article |

This keeps compilation fast and token-cheap even at hundreds of articles.

## Compilation loop

For each new raw source:

1. Load registry (Tier 1)
2. **LLM Call #1 — classify & route** (haiku): which section? new article or update existing?
3. Load section index (Tier 2)
4. **LLM Call #2 — write or update** (sonnet): create knowledge article or merge new source into existing one
5. Write article, update section index, update registry, mark source compiled

## Setup

```bash
cd ~/server-projects/note-agent
uv venv
uv pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml: set vault_path
```

Create vault directories:

```bash
mkdir -p ~/obsidian-vault/{Daily,Inbox,People,Projects}
mkdir -p ~/obsidian-vault/wiki/{research,ideas,references,personal}
mkdir -p ~/obsidian-vault/raw/{clippings,fragments,papers,notes}
```

## Usage

### Note capture (via Telegram or CLI)

```bash
uv run python query.py "Note: had great idea about X"
uv run python query.py "Add to today: met with Sarah"
uv run python query.py "What did I note about Canadian?"
```

### Wiki queries

```bash
uv run python query.py "Wiki status"
uv run python query.py "What does the wiki know about firm dynamics?"
```

### Compile sources

```bash
# Register and compile a single file
uv run python intake.py /path/to/source.md
uv run python compile.py raw/clippings/source.md

# Scan raw/ for new files, then compile all pending
uv run python intake.py --scan
uv run python intake.py --process

# Or directly
uv run python compile.py --all
```

### Inspect the registry and indexes

```bash
uv run python registry.py --context   # Tier 1 context (what Claude sees)
uv run python registry.py --pending   # Pending sources
uv run python indexer.py --section research  # Section index
```

## Handshakes (agent-to-agent)

```bash
# Research agent drops a paper for compilation
uv run python query.py --handshake '{"action": "compile_source", "source_path": "raw/papers/paper.md", "source_type": "paper"}'

# Any agent queries the wiki
uv run python query.py --handshake '{"action": "query_wiki", "topic": "AI labor demand"}'

# Research agent returns citations
uv run python query.py --handshake '{"action": "citation_results", "papers": [...], "note_path": "Inbox/note.md"}'
```

## Router config

```yaml
agents:
  note:
    path: "/home/server_lama/server-projects/note-agent"
    query_command: "uv run python query.py"
    model: "haiku"
```

Router keywords: "note", "capture", "remember", "add to today", "wiki", "what does the wiki know", "compile"

## Monitor

`monitor.py` runs daily via cron and alerts via Telegram if:
- Sources have been pending compilation for >48 hours
- A section with pending sources hasn't been updated in 2+ weeks
- Sunday: wiki review prompt if articles exist

## Design principles

- **Tiered indexing, not RAG** — well-structured index files + dense summaries let Claude navigate the corpus without vector search. Sufficient up to ~400K words (Karpathy's observation).
- **LLM maintains the wiki, human queries it** — articles are written and updated by the compiler. You supply raw material and ask questions.
- **Plumbing is pure Python** — `registry.py`, `indexer.py`, `intake.py` have no LLM calls. Fast, testable, reliable.
- **Obsidian as frontend** — wiki lives in plain `.md` files. Browse, search, and graph-view natively without any special tooling.
- **Conservative merging** — the update prompt instructs Claude to add, not replace. Source provenance is tracked in article frontmatter and a Source Notes section.
