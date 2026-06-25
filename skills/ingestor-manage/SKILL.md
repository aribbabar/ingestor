---
name: ingestor-manage
description: >-
  Manage the local Ingestor documentation index. Use to index local folders or
  files, crawl web documentation, refresh sources, and prepare docs for
  Ingestor search.
compatibility: Requires the Ingestor desktop app or local backend running on 127.0.0.1.
metadata:
  author: ingestor
---

# Ingestor Docs Manage

Index documentation into Ingestor so agents can retrieve it later with the
**ingestor-search** skill.

## When to use

- A documentation source is not indexed yet.
- Local docs changed and need to be re-indexed.
- You need to crawl a remote documentation site.

## Commands

Use the `ingestor` CLI command. If it is not installed but the Python package
is available, run the same commands with `uvx --from ingestor-docs ingestor ...`.
If these calls fail, open the Ingestor desktop app, run `ingestor daemon`, or use
`ingestor --start-daemon ...` so the local daemon is available.

### index-local

Index one or more local files or folders.

```sh
ingestor index-local "<path>" "<optional-second-path>" --name "<source-name>"
```

Example:

```sh
ingestor index-local "/path/to/docs" --name prisma
```

### index-web

Crawl and index remote documentation.

```sh
ingestor index-web "<url>" --name "<source-name>" --max-depth 2 --max-pages 100 --scope hostname
```

| Flag | Default | Description |
|------|---------|-------------|
| `--name <name>` | inferred | Source name shown in search |
| `--max-depth <n>` | `2` | Crawl depth |
| `--max-pages <n>` | `100` | Page limit |
| `--scope subpages\|hostname\|domain` | `hostname` | Crawl boundary |

## Notes

- Local indexing reads supported docs files directly; no `file://` URL is
  required.
- Re-indexing the same source name creates a new source entry in the current
  CLI flow. Delete stale sources from the UI or API when needed.
- When the preferred embedding model changes, re-index sources so vector search
  uses embeddings from the selected model.

## Typical Workflow

```sh
ingestor index-local "/path/to/docs" --name prisma
```
