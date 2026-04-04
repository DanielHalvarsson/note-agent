# Note Agent → Wiki Compiler Upgrade

## Context

This is an upgrade plan for the note-agent repo at `/home/server_lama/server-projects/note-agent`. The note agent is part of a Hayekian multi-agent personal assistant system coordinated by a Telegram router. The agent currently handles note capture and search against an Obsidian vault.

We are expanding its domain to include a **knowledge wiki compiler** — inspired by Karpathy's LLM Knowledge Base pattern. Raw sources (clippings, fragments, papers, notes) land in an intake directory. An LLM incrementally compiles them into a structured wiki of .md articles, organized by category, with a tiered index system that keeps context windows small even as the corpus grows large.

**Key design principles:**

1. **Scalability via tiered indexing** — never load the full wiki into context. Use a registry (always loaded, ~5KB), section indexes (loaded on demand), and full articles (loaded only when editing).
2. **Modularity** — the compiler engine is decoupled from rendering. Obsidian reads the wiki natively. The website, Telegram, or any other consumer just reads .md files.
3. **The note agent owns the domain** — this is an expansion of its territory, not a new agent. Existing note capture/search functionality is preserved.
4. **Plumbing first, intelligence later** — get the file operations, registry, and indexing working and testable before adding LLM compilation logic.

## Prerequisites

Before starting, read:
- The existing `CLAUDE.md` in this repo (note-taking instructions)
- `config.yaml` for vault paths and Claude CLI config
- `scripts/note.py` for existing vault operations (DO NOT modify this file)
- The router's agent config to understand how query.py is called

## Phase 1: Trim the Bloat

**Goal:** Remove dead code and superseded features. The repo should be simpler when this phase ends.

### 1.1 Delete files

```bash
rm upgrade-v2.md
rm -rf templates/
```

### 1.2 Simplify query.py

The current `query.py` is 480 lines. It needs to become ~200 lines. Here's what to cut:

**DELETE these functions entirely:**
- `detect_citation_request()` — regex intent detection that duplicates the router's job
- `detect_narration_request()` — same problem
- `extract_claims_with_claude()` — dead code path, spawns unnecessary Claude subprocess

**DELETE from `handle_handshake()`:**
- The `save_narration` handler (entire block)
- The `weekly_synthesis` handler (entire block — this is ~120 lines of synthesis logic)
- Keep ONLY the `citation_results` handler for now (research agent integration still valid)

**SIMPLIFY `main()`:**
- Remove the `detect_citation_request` and `detect_narration_request` branches
- The main function should be: parse args → if handshake, handle it → else, call `query_with_claude(request)` → format and print response
- That's it. No detection logic, no branching by request type.

**SIMPLIFY `query_with_claude()`:**
- Keep the core pattern: build prompt, call Claude CLI, return response
- Remove narration-specific prompt instructions (the "save-narration", "list-narrations", "draft a post" patterns)
- The prompt should focus on: note capture, search, daily notes, and wiki queries (added in Phase 3)

**After trimming, `query.py` should have these functions only:**
1. `load_config()` — unchanged
2. `query_with_claude(user_request)` — simplified prompt
3. `handle_handshake(context_json)` — only citation_results handler, plus new wiki handlers added in Phase 3
4. `main()` — clean arg parsing, no detection logic

### 1.3 Clean up state/

The `state/` directory has a `monitor_alerts.json` used by `monitor.py`. Keep the directory but remove any narration-specific state files if present. The monitor will be updated in Phase 4.

### 1.4 Verify nothing is broken

After trimming, test that the core note operations still work:

```bash
uv run python query.py "Note: test note after cleanup"
uv run python query.py "What did I note today?"
uv run python query.py "Search for test"
```

The router integration must still work: JSON output with `response`, `parse_mode`, `status` fields.

**Commit after Phase 1 with message: "trim: remove narration pipeline and dead code"**

---

## Phase 2: Build the Plumbing (No LLM Calls)

**Goal:** Create the registry, indexer, intake classifier, and directory structure. All testable with plain Python — no Claude CLI calls in this phase.

### 2.1 Create directory structure

Add to the Obsidian vault (path from `config.yaml`):

```
{vault_path}/
├── wiki/                     # Compiled wiki (managed by compiler)
│   ├── _registry.yaml        # Tier 1: master manifest
│   ├── research/             # Section directories (created dynamically)
│   │   └── _index.md         # Tier 2: section index
│   ├── ideas/
│   │   └── _index.md
│   ├── references/
│   │   └── _index.md
│   └── personal/
│       └── _index.md
└── raw/                      # Intake directory
    ├── fragments/            # From Fragment Library chrome extension
    ├── clippings/            # From PrintWise / web clipper
    ├── papers/               # From research agent handshake
    └── notes/                # From Telegram note captures
```

Create these directories in the setup. The `wiki/` and `raw/` directories are INSIDE the Obsidian vault so Obsidian sees them natively.

Also create a convenience symlink or config entry so the note-agent code can reference them without hardcoding vault paths everywhere.

### 2.2 Create `registry.py`

This module manages `_registry.yaml` — the Tier 1 manifest that's always loaded into context.

**File: `registry.py`**

```python
#!/usr/bin/env python3
"""
Registry — Tier 1 index for the wiki.
Always fits in context. One-line entry per article and per raw source.
"""
```

**Registry format (`_registry.yaml`):**

```yaml
# Wiki Registry — auto-maintained by compiler
# Last updated: 2026-04-04T14:30:00

sections:
  research:
    description: "Academic research topics, empirical findings, methodological notes"
    article_count: 0
    last_updated: null
  ideas:
    description: "Working hypotheses, research directions, conceptual explorations"
    article_count: 0
    last_updated: null
  references:
    description: "Summaries of papers, articles, books, and external sources"
    article_count: 0
    last_updated: null
  personal:
    description: "Preferences, workflows, creative projects, personal knowledge"
    article_count: 0
    last_updated: null

articles: {}
  # Format:
  # article-slug:
  #   title: "Article Title"
  #   section: research
  #   summary: "One-sentence summary"
  #   last_updated: 2026-04-04T14:30:00
  #   source_count: 3
  #   tags: [firm-dynamics, productivity]

pending_sources: []
  # Format:
  # - path: raw/clippings/2026-04-04-karpathy-wiki.md
  #   type: clipping
  #   received: 2026-04-04T14:30:00
  #   status: pending  # pending | compiled | failed
```

**Functions to implement:**

```python
def load_registry(vault_path: Path) -> dict:
    """Load _registry.yaml. Create with defaults if missing."""

def save_registry(vault_path: Path, registry: dict) -> None:
    """Write _registry.yaml atomically (write to tmp, then rename)."""

def add_pending_source(vault_path: Path, source_path: str, source_type: str) -> None:
    """Register a new raw source as pending compilation."""

def mark_source_compiled(vault_path: Path, source_path: str) -> None:
    """Update a pending source status to 'compiled'."""

def get_pending_sources(vault_path: Path) -> list:
    """Return all sources with status 'pending'."""

def register_article(vault_path: Path, slug: str, title: str, section: str, summary: str, tags: list) -> None:
    """Add or update an article entry in the registry."""

def get_article(vault_path: Path, slug: str) -> dict | None:
    """Look up an article by slug."""

def list_articles(vault_path: Path, section: str = None, tag: str = None) -> list:
    """List articles, optionally filtered by section or tag."""

def get_registry_context(vault_path: Path) -> str:
    """Return the registry as a formatted string suitable for LLM context.
    This is what gets loaded into every compiler invocation."""
```

**Critical implementation notes:**
- Use `PyYAML` for YAML operations (already in requirements.txt or add it)
- Atomic writes: write to `_registry.yaml.tmp`, then `os.rename()` to avoid corruption
- `get_registry_context()` should produce a compact text representation, not dump the full YAML. Something like:

```
Wiki Registry (4 sections, 12 articles)

Sections: research (5 articles), ideas (3), references (3), personal (1)

Articles:
- firm-dynamics [research] "Firm dynamics and productivity in Sweden" (updated 2026-04-01, 3 sources) #firm-dynamics #productivity
- ai-labor [research] "AI adoption and labor demand" (updated 2026-04-03, 5 sources) #ai #labor #job-ads
...

Pending sources (2):
- raw/clippings/2026-04-04-karpathy-wiki.md (clipping, received 2026-04-04)
- raw/papers/2026-04-03-acemoglu-ai.md (paper, received 2026-04-03)
```

### 2.3 Create `indexer.py`

This module manages section-level `_index.md` files — the Tier 2 indexes loaded on demand.

**File: `indexer.py`**

```python
#!/usr/bin/env python3
"""
Indexer — Tier 2 section indexes for the wiki.
Each section has an _index.md with article summaries and cross-references.
Loaded on demand when the compiler works within a section.
"""
```

**Section index format (`wiki/research/_index.md`):**

```markdown
---
section: research
description: Academic research topics, empirical findings, methodological notes
article_count: 5
last_updated: 2026-04-04T14:30:00
---

# Research

## Articles

### firm-dynamics
**Firm dynamics and productivity in Sweden**
Entry, exit, and growth patterns in Swedish firms using XBRL annual report data and SCB microdata. Covers Haltiwanger-style decompositions and the role of firm age.
Tags: firm-dynamics, productivity, xbrl, scb
Sources: 3 | Updated: 2026-04-01
Related: [ai-labor], [structural-transformation]

### ai-labor
**AI adoption and labor demand**
Evidence from Swedish job ads (Platsbanken) and firm annual reports on how AI skill requirements correlate with firm characteristics and employment changes.
Tags: ai, labor, job-ads, platsbanken
Sources: 5 | Updated: 2026-04-03
Related: [firm-dynamics]

## Cross-references
- "productivity" also appears in: ideas/research-productivity-llm
- "Swedish firms" also appears in: references/swedish-microdata-overview
```

**Functions to implement:**

```python
def load_section_index(vault_path: Path, section: str) -> dict:
    """Load and parse a section's _index.md. Create if missing."""

def save_section_index(vault_path: Path, section: str, index_data: dict) -> None:
    """Write section _index.md."""

def get_article_summary(vault_path: Path, section: str, slug: str) -> str | None:
    """Get the summary block for a specific article from its section index."""

def update_article_in_index(vault_path: Path, section: str, slug: str, title: str, summary: str, tags: list, related: list, source_count: int) -> None:
    """Add or update an article entry in the section index."""

def get_section_context(vault_path: Path, section: str) -> str:
    """Return the section index as a string for LLM context."""

def find_related_articles(vault_path: Path, tags: list) -> list:
    """Search across all section indexes for articles with overlapping tags.
    Returns list of (section, slug, title, overlap_tags)."""
```

**Critical implementation notes:**
- Parse the markdown frontmatter (YAML between `---` delimiters) separately from the body
- The body is structured markdown — use simple string parsing, not a full markdown AST
- `find_related_articles()` reads ALL section indexes but only their tag fields — still fast because indexes are small
- Keep the markdown human-readable. Someone opening this in Obsidian should be able to browse it directly.

### 2.4 Create `intake.py`

This is the entry point for new raw sources. It handles classification and registration — but NOT compilation (that's Phase 3).

**File: `intake.py`**

```python
#!/usr/bin/env python3
"""
Intake — entry point for new raw sources.
Classifies incoming files and registers them for compilation.

Usage:
    # Register a single file
    python intake.py /path/to/source.md

    # Register a file with explicit type
    python intake.py /path/to/source.md --type clipping

    # Scan raw/ directories for unregistered files
    python intake.py --scan

    # Process all pending sources (triggers compilation)
    python intake.py --process
"""
```

**Functions to implement:**

```python
def classify_source(file_path: Path) -> dict:
    """Classify a raw source file by reading its content and metadata.
    
    Returns:
        {
            "type": "clipping" | "fragment" | "paper" | "note",
            "title": "extracted or generated title",
            "detected_topics": ["ai", "firm-dynamics"],  # from content keywords
            "suggested_section": "research",  # best guess from content
        }
    
    Classification logic (NO LLM — pure heuristics):
    - Files in raw/fragments/ → type: fragment
    - Files in raw/clippings/ → type: clipping
    - Files in raw/papers/ → type: paper
    - Files in raw/notes/ → type: note
    - Title: from frontmatter 'title' field, or first # heading, or filename
    - Topics: extract from frontmatter 'tags' field if present
    - Section: keyword matching against section descriptions in registry
    """

def register_source(file_path: Path, source_type: str = None) -> dict:
    """Classify a file and register it as pending in the registry.
    
    Returns the classification result plus registration status.
    """

def scan_raw_directories(vault_path: Path) -> list:
    """Walk raw/ subdirectories, find files not yet in registry, register them.
    
    Returns list of newly registered sources.
    """

def get_pending_for_processing(vault_path: Path) -> list:
    """Return pending sources grouped by suggested section.
    
    Returns:
        [
            {
                "source": {path, type, received, ...},
                "classification": {title, detected_topics, suggested_section},
                "content_preview": "first 500 chars of the file"
            }
        ]
    """
```

**Critical implementation notes:**
- `classify_source()` does NOT call the LLM. It uses directory location, frontmatter, and keyword matching. This keeps intake fast and testable.
- The LLM-powered "where does this fit in the wiki?" decision happens in Phase 3 (compile.py).
- `--scan` is designed to be run by cron or the monitor — it finds orphaned files in raw/ that arrived via filesystem (e.g., synced from Fragment Library) without going through the agent.
- `--process` is the trigger for compilation — in Phase 2 it just lists what's pending. In Phase 3 it calls the compiler.

### 2.5 Create initial `_registry.yaml`

Write the initial registry file with the four default sections and empty articles/pending lists:

```bash
# The setup should create this automatically via registry.py
python -c "from registry import load_registry; load_registry(Path('...'))"
```

### 2.6 Raw source frontmatter convention

All files arriving in `raw/` should have minimal frontmatter. Document this convention in CLAUDE.md. The compiler expects:

```yaml
---
title: "Article or source title"
source_url: "https://..." # optional, for web clippings
source_type: clipping | fragment | paper | note
captured: 2026-04-04T14:30:00
tags: [optional, list]  # optional
---

Content body here...
```

If frontmatter is missing, `classify_source()` infers what it can from the file path and content. Don't reject files without frontmatter — just handle them gracefully.

### 2.7 Update requirements.txt

Add any new dependencies. Should be minimal:
- `pyyaml` (likely already there)
- `watchdog` (optional — for filesystem watching in intake.py, can defer)

### 2.8 Test Phase 2

All of these should work WITHOUT any LLM calls:

```bash
# Registry operations
python -c "
from pathlib import Path
from registry import load_registry, add_pending_source, get_registry_context
vault = Path('/home/server_lama/obsidian-vault')  # or from config
reg = load_registry(vault)
print('Registry loaded:', len(reg.get('sections', {})), 'sections')
add_pending_source(vault, 'raw/clippings/test.md', 'clipping')
print(get_registry_context(vault))
"

# Indexer operations
python -c "
from pathlib import Path
from indexer import load_section_index, update_article_in_index, get_section_context
vault = Path('/home/server_lama/obsidian-vault')
update_article_in_index(vault, 'research', 'test-article', 'Test Article', 'A test summary.', ['test'], [], 0)
print(get_section_context(vault, 'research'))
"

# Intake operations
python -c "
from pathlib import Path
from intake import scan_raw_directories
vault = Path('/home/server_lama/obsidian-vault')
# Drop a test file first:
# echo '---\ntitle: Test Clipping\n---\nSome content' > {vault}/raw/clippings/test.md
results = scan_raw_directories(vault)
print(f'Found {len(results)} unregistered files')
"
```

**Commit after Phase 2 with message: "feat: wiki plumbing — registry, indexer, intake"**

---

## Phase 3: The Compiler Engine (LLM-Powered)

**Goal:** Build `compile.py` — the module that reads raw sources and produces/updates wiki articles. This is where the LLM does the knowledge work.

### 3.1 Create `compile.py`

**File: `compile.py`**

```python
#!/usr/bin/env python3
"""
Compiler — the wiki compilation engine.
Takes raw sources and produces/updates wiki articles.

Called by intake.py --process or directly:
    python compile.py raw/clippings/2026-04-04-karpathy-wiki.md
    python compile.py --all  # process all pending sources
"""
```

**The compilation loop for a single source:**

```
1. Load registry (Tier 1 — always)
2. Read the raw source content
3. LLM CALL #1: Classify & Route
   Input: registry context + source content preview (first 1000 chars)
   Output: { section, existing_article_slug | "new", suggested_slug, suggested_title }
   Decision: does this update an existing article or create a new one?
4. Load section index (Tier 2 — for the target section)
5. If updating existing article:
   a. Load the full article (Tier 3)
   b. LLM CALL #2: Update Article
      Input: section index context + existing article + full source content
      Output: updated article markdown
   c. Write updated article
6. If creating new article:
   a. LLM CALL #2: Create Article
      Input: section index context + full source content
      Output: new article markdown + summary for index
   b. Write new article to wiki/{section}/{slug}.md
7. Update section index (add/update article summary)
8. Update registry (article entry + mark source as compiled)
9. Find and log cross-references to other sections
```

**Functions to implement:**

```python
def compile_source(vault_path: Path, source_path: str, config: dict) -> dict:
    """Compile a single raw source into the wiki.
    
    This is the main entry point. Orchestrates the full compilation loop.
    
    Returns:
        {
            "status": "compiled" | "failed",
            "action": "created" | "updated",
            "article": {"slug": "...", "section": "...", "title": "..."},
            "error": "..." (if failed)
        }
    """

def classify_and_route(registry_context: str, source_content: str, config: dict) -> dict:
    """LLM Call #1: Decide where this source belongs.
    
    Returns:
        {
            "section": "research",
            "action": "update" | "create",
            "target_slug": "existing-article-slug" or null,
            "suggested_slug": "new-article-slug",
            "suggested_title": "New Article Title",
            "reasoning": "Brief explanation of classification"
        }
    """

def update_article(section_context: str, existing_article: str, source_content: str, config: dict) -> dict:
    """LLM Call #2a: Update an existing article with new source material.
    
    Returns:
        {
            "article_content": "full updated markdown",
            "summary": "updated one-paragraph summary for index",
            "tags": ["updated", "tag", "list"],
            "related": ["other-article-slugs"]
        }
    """

def create_article(section_context: str, source_content: str, suggested_title: str, config: dict) -> dict:
    """LLM Call #2b: Create a new article from source material.
    
    Returns:
        {
            "article_content": "full article markdown",
            "summary": "one-paragraph summary for index",
            "tags": ["tag", "list"],
            "related": ["other-article-slugs"]
        }
    """

def compile_all_pending(vault_path: Path, config: dict) -> list:
    """Process all pending sources. Returns list of compilation results."""

def call_claude(prompt: str, config: dict, model: str = None) -> str:
    """Wrapper around Claude CLI call. 
    
    Uses config for claude_cli.bin path.
    Default model: 'sonnet' for compilation (not haiku — needs reasoning).
    Handles timeouts and errors gracefully.
    """
```

### 3.2 Article format

Wiki articles follow this format:

```markdown
---
title: "AI Adoption and Labor Demand"
section: research
slug: ai-labor
created: 2026-04-03T10:00:00
last_updated: 2026-04-04T14:30:00
sources:
  - raw/papers/2026-04-01-acemoglu-ai.md
  - raw/clippings/2026-04-03-brynjolfsson-interview.md
  - raw/fragments/2026-04-04-oecd-report-excerpt.md
tags: [ai, labor, job-ads, platsbanken, firm-dynamics]
related: [firm-dynamics, structural-transformation]
---

# AI Adoption and Labor Demand

## Key Findings
[Synthesized from sources — not just copied]

## Evidence from Swedish Data
[Specific to Daniel's research context]

## Open Questions
[What's unresolved, what to investigate next]

## Source Notes
- Acemoglu (2024): [brief note on what this source contributed]
- Brynjolfsson interview: [brief note]
- OECD excerpt: [brief note]
```

**Critical: the LLM writes and maintains this content. Daniel rarely edits articles directly.** The Source Notes section maintains provenance — you can always trace back to what raw source contributed what.

### 3.3 LLM prompts

The prompts for `classify_and_route()` and `create_article()`/`update_article()` are critical. Here are the templates:

**Classify & Route prompt:**

```
You are a knowledge wiki compiler. Given the current wiki registry and a new source, decide where it belongs.

WIKI REGISTRY:
{registry_context}

NEW SOURCE (preview):
{source_content[:1500]}

Respond with ONLY a JSON object:
{{
    "section": "one of: research, ideas, references, personal",
    "action": "create or update",
    "target_slug": "slug of existing article to update, or null",
    "suggested_slug": "kebab-case-slug for new article",
    "suggested_title": "Title for new article",
    "reasoning": "One sentence explaining your decision"
}}

Rules:
- If the source clearly relates to an existing article, update it
- If it's a new topic not covered by any existing article, create
- Prefer updating over creating — don't fragment knowledge into tiny articles
- Section choice should match the content: research for empirical/academic, ideas for hypotheses/directions, references for external source summaries, personal for workflows/preferences
```

**Create Article prompt:**

```
You are a knowledge wiki compiler. Create a new wiki article from this source material.

SECTION CONTEXT (existing articles in this section):
{section_context}

SOURCE MATERIAL:
{source_content}

Write a wiki article in markdown. Requirements:
- Start with YAML frontmatter (title, section, slug, created, tags, related)
- Write in clear, information-dense prose — not a summary of the source, but a KNOWLEDGE ARTICLE that synthesizes the information
- Include sections for: key findings/concepts, evidence/details, open questions
- End with a Source Notes section attributing what came from this source
- Cross-reference related articles from the section context where relevant
- Tags should be lowercase, kebab-case, 3-8 tags

Also return a JSON block at the very end, after a --- separator:
{{
    "summary": "One-paragraph summary for the section index",
    "tags": ["tag", "list"],
    "related": ["slugs-of-related-articles"]
}}
```

**Update Article prompt:**

```
You are a knowledge wiki compiler. Update an existing wiki article with new source material.

SECTION CONTEXT:
{section_context}

EXISTING ARTICLE:
{existing_article}

NEW SOURCE MATERIAL:
{source_content}

Update the article to integrate the new source. Requirements:
- Preserve existing content — add to it, don't replace it
- Update sections where the new source adds information
- Add the new source to the Source Notes section
- Update frontmatter: last_updated, sources list, tags if needed
- If the new source contradicts existing content, note both perspectives
- Keep the article focused — if the source is tangential, add only the relevant parts

Return the full updated article markdown, followed by a --- separator and JSON:
{{
    "summary": "Updated one-paragraph summary for the section index",
    "tags": ["updated", "tag", "list"],
    "related": ["slugs-of-related-articles"]
}}
```

### 3.4 Model selection

```yaml
# Add to config.yaml
compiler:
  classify_model: "haiku"    # Fast, cheap — classification is simple
  compile_model: "sonnet"    # Needs reasoning for article writing
  timeout: 120               # Compilation can take a while
```

### 3.5 Wire intake.py --process to compiler

Update `intake.py` so that `--process` calls `compile.py`:

```python
# In intake.py, add:
def process_pending(vault_path: Path, config: dict) -> list:
    """Process all pending sources through the compiler."""
    from compile import compile_all_pending
    return compile_all_pending(vault_path, config)
```

### 3.6 Test Phase 3

Create a test raw file and compile it:

```bash
# Create a test clipping
cat > /home/server_lama/obsidian-vault/raw/clippings/test-karpathy-wiki.md << 'EOF'
---
title: "Karpathy on LLM Knowledge Bases"
source_url: "https://x.com/karpathy/status/..."
source_type: clipping
captured: 2026-04-04T10:00:00
tags: [llm, knowledge-management, wiki, obsidian]
---

Karpathy describes using LLMs to build personal knowledge bases. Raw data from sources is collected into a raw/ directory, then compiled by an LLM into a .md wiki. The wiki includes summaries, backlinks, categorized concepts, and linked articles. He uses Obsidian as the frontend. At ~100 articles and ~400K words, the LLM handles Q&A against the wiki without fancy RAG — just smart indexing and brief summaries in index files.

Key insight: the LLM maintains the wiki, you rarely edit it directly. Your queries and explorations get filed back into the wiki, so the knowledge compounds.
EOF

# Register it
python intake.py /home/server_lama/obsidian-vault/raw/clippings/test-karpathy-wiki.md

# Compile it
python compile.py /home/server_lama/obsidian-vault/raw/clippings/test-karpathy-wiki.md

# Check results
cat /home/server_lama/obsidian-vault/wiki/_registry.yaml
cat /home/server_lama/obsidian-vault/wiki/references/_index.md  # or wherever it was classified
ls /home/server_lama/obsidian-vault/wiki/references/
```

**Commit after Phase 3 with message: "feat: wiki compiler engine with tiered indexing"**

---

## Phase 4: Integration

**Goal:** Wire the compiler into the existing agent infrastructure — router handshakes, query interface, and monitoring.

### 4.1 Update `query.py` with wiki query capability

Add wiki-related patterns to the Claude prompt in `query_with_claude()`:

```
# Add to the prompt instructions:
Wiki queries:
- "What does the wiki say about X?" → Read registry, find relevant articles, load and answer
- "Compile new sources" → Run intake.py --scan && intake.py --process
- "Wiki status" → Show registry stats: article count, pending sources, sections
- "What's in the wiki about [topic]?" → Search registry and indexes for matching articles

For wiki queries, use these tools:
- uv run python registry.py --context  (prints registry context for you to read)
- uv run python indexer.py --section research  (prints a section index)
- uv run python intake.py --scan  (find unregistered raw files)
- uv run python intake.py --process  (compile all pending sources)
- cat wiki/{section}/{slug}.md  (read a specific article)
```

Add CLI entry points to `registry.py` and `indexer.py` so Claude CLI can invoke them:

```python
# At bottom of registry.py:
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", action="store_true", help="Print registry context")
    parser.add_argument("--list", action="store_true", help="List all articles")
    parser.add_argument("--pending", action="store_true", help="List pending sources")
    args = parser.parse_args()
    # ... implement
```

### 4.2 Add handshake handlers

Add to `handle_handshake()` in `query.py`:

```python
if action == "compile_source":
    # Another agent (e.g., research agent) drops a source for compilation
    source_path = context.get("source_path")
    source_type = context.get("source_type", "paper")
    # Register and optionally compile immediately
    from intake import register_source
    result = register_source(Path(source_path), source_type)
    return json.dumps({
        "response": f"Source registered: {result.get('title', source_path)}",
        "status": "complete",
        "actions": [{"type": "source_registered", "path": source_path}]
    })

if action == "query_wiki":
    # Another agent asks what the wiki knows about a topic
    topic = context.get("topic", "")
    from registry import load_registry, get_registry_context
    from indexer import find_related_articles
    config = load_config()
    vault_path = Path(config["obsidian"]["vault_path"])
    
    # Search registry for matching articles
    articles = find_related_articles(vault_path, topic.lower().split())
    
    if articles:
        summaries = []
        for section, slug, title, tags in articles[:5]:
            from indexer import get_article_summary
            summary = get_article_summary(vault_path, section, slug)
            summaries.append(f"[{section}/{slug}] {title}: {summary}")
        
        return json.dumps({
            "response": "\n".join(summaries),
            "status": "complete",
            "articles_found": len(articles)
        })
    else:
        return json.dumps({
            "response": f"No wiki articles found matching '{topic}'",
            "status": "complete",
            "articles_found": 0
        })
```

### 4.3 Update `monitor.py`

Replace or extend the narration gap checks with wiki health checks:

1. **Pending source alert** — if sources have been pending > 48 hours, nudge: "You have X uncompiled sources in the wiki intake. Run compilation?"
2. **Stale section alert** — if a section hasn't been updated in 2+ weeks but has pending sources, flag it
3. **Keep the weekly synthesis prompt** — but reframe it as "wiki review" rather than narration synthesis

### 4.4 Update `CLAUDE.md`

Rewrite CLAUDE.md to reflect the new architecture. This is what Claude Code reads when working in the repo.

Key sections:
- **Agent identity**: Note agent — handles note capture, search, and wiki compilation
- **Architecture**: Tiered indexing (registry → section index → articles), raw/ intake pipeline
- **File structure**: Where everything lives
- **Wiki operations**: How compilation works, what the LLM does vs. what's pure Python
- **Query patterns**: What kinds of requests this agent handles
- **Handshake protocol**: compile_source, query_wiki, citation_results
- **Config**: vault_path, claude_cli settings, compiler model selection

### 4.5 Update `README.md`

Rewrite to reflect the wiki compiler upgrade. Keep it concise — the README is for humans browsing GitHub, CLAUDE.md is for the code agent.

### 4.6 Test Phase 4

```bash
# Router integration
uv run python query.py "Wiki status"
uv run python query.py "What does the wiki know about firm dynamics?"
uv run python query.py "Compile new sources"

# Handshake from research agent
uv run python query.py --handshake '{"action": "compile_source", "source_path": "raw/papers/test.md", "source_type": "paper"}'

# Handshake query
uv run python query.py --handshake '{"action": "query_wiki", "topic": "AI labor demand"}'

# Monitor
python monitor.py
```

**Commit after Phase 4 with message: "feat: wiki integration — queries, handshakes, monitoring"**

---

## Phase Summary

| Phase | What | LLM calls | Testable without LLM |
|-------|------|-----------|---------------------|
| 1 | Trim bloat | None | Yes — just deletion |
| 2 | Registry, indexer, intake | None | Yes — pure Python |
| 3 | Compiler engine | Yes (classify + compile) | No — needs Claude CLI |
| 4 | Integration | Via query.py | Partially |

## Config additions

Add to `config.yaml`:

```yaml
# Existing
obsidian:
  vault_path: "/home/server_lama/obsidian-vault"

claude_cli:
  bin: "/home/server_lama/.local/bin/claude"
  model: "haiku"

# New
wiki:
  sections:
    - research
    - ideas
    - references
    - personal
  compile_model: "sonnet"      # Model for article creation/updates
  classify_model: "haiku"      # Model for source classification
  compile_timeout: 120         # Seconds
  max_article_sources: 20      # Warn if article has too many sources
```

## What NOT to do

- Do NOT modify `scripts/note.py` — it works, leave it alone
- Do NOT add vector embeddings, FAISS, or any RAG infrastructure — the tiered index IS the retrieval mechanism
- Do NOT add Obsidian CLI or any Obsidian-specific tooling — we work with plain files
- Do NOT build rendering/publishing (website, Telegram formatting) — that's a future phase
- Do NOT over-engineer the classification in intake.py — simple heuristics now, LLM classification happens in compile.py
- Do NOT add watchdog/filesystem watching in Phase 2 — cron-based scanning via `intake.py --scan` is sufficient for now
- Do NOT modify the router or other agents from this repo