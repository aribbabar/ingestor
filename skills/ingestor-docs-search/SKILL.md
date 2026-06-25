---
name: ingestor-docs-search
description: >-
  Search and query the local Ingestor documentation index. Use when an agent
  needs to look up indexed documentation, inspect available sources, or retrieve
  context from local/remote docs captured by Ingestor.
compatibility: Requires the Ingestor desktop app or local backend running on 127.0.0.1.
metadata:
  author: ingestor
---

# Ingestor Docs Search

Search the local Ingestor index for documentation context. These commands call
the local Ingestor API and do not modify indexed sources.

## When to use

- You need documentation context for an indexed library or project.
- You want to check what sources are available before searching.
- You need agent-readable snippets with source URIs and relevance scores.

Always run `list` first if you are unsure whether a source has been indexed.
If the source is missing, use the **ingestor-docs-manage** skill to index it.

## Commands

Use the `ingestor` CLI command. If it is not installed but the Python package
is available, run the same commands with `uvx ingestor ...`. If these calls
fail, open the Ingestor desktop app, run `ingestor daemon`, or use
`ingestor --start-daemon ...` so the local daemon is available.

### list

List indexed sources.

```sh
ingestor list --output json
```

### search

Search indexed documentation by source name or id.

```sh
ingestor search "<source-name-or-id>" "<query>" --limit 5 --mode hybrid --output json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit <n>` | `8` | Maximum number of results |
| `--mode hybrid\|keyword\|vector` | `hybrid` | Retrieval mode |
| `--output json\|text` | `text` | Output format |

Example:

```sh
ingestor search prisma "Prisma Migrate declarative data modeling" --limit 5 --output json
```

Each result includes the source name, title, URI, content snippet, combined
score, keyword score, and vector score.

## Interpreting Output

- Prefer results with high combined `score` and content that directly answers
  the question.
- If `keyword_score` is high but `vector_score` is zero, the result is still
  useful for exact terminology matches.
- If searching with an Ollama embedding model, re-index sources after changing
  the model so stored chunk vectors and query vectors use the same dimensions.

## Typical Workflow

```sh
ingestor list --output json
ingestor search prisma "Prisma schema data model" --limit 5 --output json
```
