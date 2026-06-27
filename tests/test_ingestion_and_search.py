from __future__ import annotations

import json
import shutil
import sys
import tempfile
import sqlite3
from pathlib import Path
from unittest import TestCase, main

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.retrieval.search as search_module
from app.indexing.crawler import markdown_from_result
from app.db import Database
from app.retrieval.embeddings import embedding_signature, tokenize
from app.indexing.documents import clean_web_markdown, document_from_file, html_to_markdown, normalize_content
from app.indexing.discovery import iter_files
from app.indexing.chunking import CHUNK_TARGET_CHARS, build_document, split_markdown_sections, split_section_content
import app.sources.service as source_service
from app.sources.service import ignore_snapshot_entries
from app.domain.models import JobRecord, JobStatus, SearchMode, SourceKind, SourceRecord, SourceStatus
from app.retrieval.search import assemble_context, diversify_by_document, extract_code, rank_lookup, shape_result


def make_search_row(
    *,
    row_id: int = 1,
    document_id: int = 1,
    title: str,
    uri: str,
    section_path: str = "[]",
    content: str = "",
) -> sqlite3.Row:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE rows (
          id INTEGER,
          document_id INTEGER,
          title TEXT,
          uri TEXT,
          section_path TEXT,
          content TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO rows VALUES (?, ?, ?, ?, ?, ?)",
        (row_id, document_id, title, uri, section_path, content),
    )
    return connection.execute("SELECT * FROM rows").fetchone()


class IngestionNormalizationTests(TestCase):
    def test_markdown_front_matter_is_not_indexed(self) -> None:
        content = normalize_content(
            """---
title: Responsive Design
description: Learn responsive styles
---

# Responsive Design

```jsx
<Text fontWeight={{ base: "medium", lg: "bold" }}>Text</Text>
```
""",
            ".mdx",
        )

        self.assertNotIn("title: Responsive Design", content)
        self.assertIn("# Responsive Design", content)

    def test_fastapi_include_directive_expands_existing_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc_dir = root / "docs" / "tutorial"
            src_dir = root / "docs_src" / "response_model"
            doc_dir.mkdir(parents=True)
            src_dir.mkdir(parents=True)
            source = src_dir / "tutorial004_py310.py"
            source.write_text(
                "\n".join(
                    [
                        "from fastapi import FastAPI",
                        "app = FastAPI()",
                        "@app.get('/items/{item_id}', response_model_exclude_unset=True)",
                        "def read_item(item_id: str):",
                        "    return {'name': 'Foo'}",
                    ]
                ),
                encoding="utf-8",
            )
            doc = doc_dir / "response-model.md"
            doc.write_text(
                "# Response Model\n\n{* ../../docs_src/response_model/tutorial004_py310.py hl[2:4] *}\n",
                encoding="utf-8",
            )

            parsed = document_from_file(doc, root / "docs", embed=False)

        self.assertIsNotNone(parsed)
        content = parsed["content"]
        self.assertIn("```py", content)
        self.assertIn("response_model_exclude_unset=True", content)
        self.assertNotIn("{*", content)

    def test_mdx_example_tag_expands_when_backing_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc_dir = root / "content" / "docs"
            example_dir = root / "examples"
            doc_dir.mkdir(parents=True)
            example_dir.mkdir()
            (example_dir / "color-mode-basic.tsx").write_text(
                'import { ColorModeButton } from "@/components/ui/color-mode"\n\nexport function Demo() {\n  return <ColorModeButton />\n}\n',
                encoding="utf-8",
            )
            doc = doc_dir / "color-mode.mdx"
            doc.write_text("# Color Mode\n\n<ExampleTabs name=\"color-mode-basic\" />\n", encoding="utf-8")

            parsed = document_from_file(doc, root, embed=False)

        self.assertIsNotNone(parsed)
        content = parsed["content"]
        self.assertIn("Example: color-mode-basic", content)
        self.assertIn("```tsx", content)
        self.assertIn("<ColorModeButton />", content)

    def test_web_markdown_common_chrome_is_removed(self) -> None:
        cleaned = clean_web_markdown(
            """[New in Neon: Read the changelog. ![](https://example.com/a.png)](https://neon.com/docs/changelog)
Search...⌘K
Ask AI

# Database branching workflow primer
With Neon, you can work with your data like code.

### On this page
  * [Usage](https://neon.com/docs/example#usage)
  * [Examples](https://neon.com/docs/example#examples)

Was this page helpful?
YesNo
Thank you for your feedback!
"""
        )

        self.assertIn("# Database branching workflow primer", cleaned)
        self.assertIn("With Neon, you can work with your data like code.", cleaned)
        self.assertNotIn("Search...", cleaned)
        self.assertNotIn("Ask AI", cleaned)
        self.assertNotIn("On this page", cleaned)
        self.assertNotIn("Was this page helpful", cleaned)

    def test_local_html_normalization_preserves_markdown_structure(self) -> None:
        markdown = html_to_markdown(
            """<html><body>
<nav>Sidebar</nav>
<main>
  <h1>Install</h1>
  <p>Use the <a href="/cli">CLI</a>.</p>
  <pre><code>npm install ingestor</code></pre>
  <ul><li>Run setup</li></ul>
</main>
</body></html>"""
        )

        self.assertIn("# Install", markdown)
        self.assertIn("[CLI](/cli)", markdown)
        self.assertIn("```", markdown)
        self.assertIn("npm install ingestor", markdown)
        self.assertIn("- Run setup", markdown)
        self.assertNotIn("Sidebar", markdown)

    def test_local_discovery_skips_build_and_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# Guide", encoding="utf-8")
            (root / "target").mkdir()
            (root / "target" / "fingerprint.json").write_text('{"artifact": true}', encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv" / "package.json").write_text('{"private": true}', encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("[core]", encoding="utf-8")

            discovered = [path.relative_to(root).as_posix() for path in iter_files(root)]

        self.assertEqual(discovered, ["docs/guide.md"])

    def test_snapshot_ignore_skips_heavy_artifact_directories(self) -> None:
        ignored = ignore_snapshot_entries(
            "docs",
            ["docs", "target", ".git", ".venv", ".vscode", "node_modules", "README.md"],
        )

        self.assertEqual(ignored, {"target", ".git", ".venv", ".vscode", "node_modules"})

    def test_chunks_include_structural_metadata(self) -> None:
        document = build_document(
            "docs/install.md",
            "Install",
            """# Install

Use this table to choose a command.

| Runtime | Command |
| --- | --- |
| npm | npm install ingestor |
""",
            embed=False,
        )

        chunk = document["chunks"][0]

        self.assertEqual(chunk["content_type"], "markdown")
        self.assertEqual(chunk["parent_chunk_id"], None)
        self.assertEqual(chunk["metadata"]["document_uri"], "docs/install.md")
        self.assertEqual(chunk["metadata"]["document_title"], "Install")
        self.assertEqual(chunk["metadata"]["section_path"], ["Install"])
        self.assertEqual(chunk["metadata"]["chunk_kind"], "table")
        self.assertIsInstance(chunk["metadata"]["parent_key"], str)
        self.assertIn("Use this table", chunk["metadata"]["parent_context"])

    def test_markdown_section_splitter_ignores_headings_inside_code_fences(self) -> None:
        sections = split_markdown_sections(
            """# Install

```md
## Not a real section
```

## Configure
Use the settings page.
"""
        )

        self.assertEqual([path for path, _content in sections], [["Install"], ["Install", "Configure"]])

    def test_section_content_splits_large_text_but_keeps_code_block_intact(self) -> None:
        repeated_text = " ".join(f"sentence {index} explains configuration." for index in range(140))
        code = "```ts\nconst config = { enabled: true, retries: 3 };\n```"

        pieces = split_section_content(f"# Configure\n\n{repeated_text}\n\n{code}")

        self.assertGreater(len(pieces), 1)
        self.assertTrue(any(code in piece for piece in pieces))
        self.assertTrue(all(len(piece) <= CHUNK_TARGET_CHARS + 300 or code in piece for piece in pieces))

    def test_greedy_merge_keeps_distinct_large_sections_separate(self) -> None:
        first = " ".join(["alpha explains setup."] * 80)
        second = " ".join(["beta explains runtime."] * 80)

        document = build_document(
            "docs/runtime.md",
            "Runtime",
            f"# Setup\n\n{first}\n\n# Runtime\n\n{second}",
            embed=False,
        )

        titles = [chunk["title"] for chunk in document["chunks"]]

        self.assertIn("Setup", titles)
        self.assertIn("Runtime", titles)


class CrawlMarkdownSelectionTests(TestCase):
    def test_markdown_from_result_prefers_fit_markdown(self) -> None:
        class Markdown:
            fit_markdown = "# Focused content\n\nUseful body."
            markdown_with_citations = "# Raw content with citations\n\nSidebar noise."
            raw_markdown = "# Raw content\n\nSidebar noise."

        class Result:
            markdown = Markdown()
            cleaned_html = "<main>Fallback</main>"
            html = "<html>Fallback</html>"

        self.assertEqual(markdown_from_result(Result()), "# Focused content\n\nUseful body.")

    def test_markdown_from_result_falls_back_when_fit_markdown_is_empty(self) -> None:
        class Markdown:
            fit_markdown = ""
            markdown_with_citations = "# Raw content with citations\n\nUseful body."
            raw_markdown = "# Raw content\n\nUseful body."

        class Result:
            markdown = Markdown()
            cleaned_html = "<main>Fallback</main>"
            html = "<html>Fallback</html>"

        self.assertEqual(markdown_from_result(Result()), "# Raw content with citations\n\nUseful body.")

    def test_markdown_from_result_extracts_html_when_fit_markdown_is_noisy(self) -> None:
        class Markdown:
            fit_markdown = """Search...⌘K
Ask AI

### On this page
- [Install](#install)

Was this page helpful?
"""
            markdown_with_citations = "# Raw content\n\nSidebar noise."
            raw_markdown = "# Raw content\n\nSidebar noise."

        class Result:
            url = "https://example.com/docs/install"
            markdown = Markdown()
            cleaned_html = "<html><body><nav>Sidebar</nav><article><h1>Install</h1><p>Use the CLI.</p></article></body></html>"
            html = ""

        selected = markdown_from_result(Result())

        self.assertIn("Install", selected)
        self.assertIn("Use the CLI", selected)
        self.assertNotIn("Search", selected)


class SearchShapingTests(TestCase):
    def test_jsx_blocks_are_treated_as_code(self) -> None:
        content = """Use object syntax for responsive props.

```jsx
<Text fontWeight={{ base: "medium", lg: "bold" }}>Text</Text>
```
"""

        code = extract_code(content, {"responsive", "breakpoints"})

        self.assertIsNotNone(code)
        self.assertIn("<Text", code)

    def test_rank_lookup_sorts_by_score_not_dict_order(self) -> None:
        ranks = rank_lookup({10: 0.2, 20: 0.9, 30: 0.5})

        self.assertEqual(ranks, {20: 1, 30: 2, 10: 3})

    def test_diversification_defers_duplicate_documents(self) -> None:
        first_chunk = make_search_row(row_id=1, document_id=1, title="Install", uri="docs/install.mdx")
        second_chunk = make_search_row(row_id=2, document_id=1, title="Install", uri="docs/install.mdx")
        composition = make_search_row(row_id=3, document_id=3, title="Composition", uri="docs/composition.mdx")

        selected = diversify_by_document(
            [
                (1.0, 0.0, 0.0, 1, first_chunk),
                (0.99, 0.0, 0.0, 2, second_chunk),
                (0.9, 0.0, 0.0, 3, composition),
            ],
            2,
        )

        self.assertEqual([row["id"] for _, _, _, _, row in selected], [1, 3])

    def test_shape_result_returns_compact_clean_excerpt(self) -> None:
        row = make_search_row(
            title="Connection pooling",
            uri="https://neon.com/docs/connect/connection-pooling",
            section_path='["Connection pooling", "How to use connection pooling"]',
            content="Connection pooling",
        )
        shaped = shape_result(
            row,
            """Search...⌘K
Ask AI

## How to use connection pooling
To enable connection pooling, use a pooled connection string. Add `-pooler` to your endpoint ID.

```
const connectionString = "postgresql://user:pass@ep-example-pooler.us-east-2.aws.neon.tech/db?sslmode=require";
```

Was this page helpful?
YesNo
Thank you for your feedback!
            """,
            {"connection", "pooling", "pooled"},
        )

        self.assertIn("pooled connection string", shaped["content"])
        self.assertNotIn("Search", shaped["content"])
        self.assertNotIn("Was this page helpful", shaped["content"])
        self.assertIsNotNone(shaped["code"])


class VectorIndexTests(TestCase):
    def test_local_source_request_rejects_legacy_path_field(self) -> None:
        with self.assertRaises(ValidationError):
            source_service.LocalSourceRequest(path=Path("docs"), name="docs")

    def test_duplicate_local_source_path_is_rejected_before_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Guide", encoding="utf-8")
            snapshot_root = root / "local"
            test_db = Database(root / "ingestor.sqlite")
            original_db = source_service.db
            original_get_settings = source_service.get_settings

            class Settings:
                local_source_dir = snapshot_root

            try:
                source_service.db = test_db
                source_service.get_settings = lambda: Settings()
                source_service.register_local_source(source_service.LocalSourceRequest(paths=[docs], name="docs"))

                with self.assertRaisesRegex(ValueError, 'already registered as "docs"'):
                    source_service.register_local_source(source_service.LocalSourceRequest(paths=[docs], name="docs-copy"))

                snapshots = list(snapshot_root.iterdir())
            finally:
                source_service.db = original_db
                source_service.get_settings = original_get_settings
                test_db.engine.dispose()

        self.assertEqual(len(snapshots), 1)

    def test_reindex_recreates_missing_local_snapshot_before_clearing_documents(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Guide\n\nUse Ingestor for local docs.", encoding="utf-8")
            snapshot_root = root / "local"
            test_db = Database(root / "ingestor.sqlite")
            original_db = source_service.db
            original_get_settings = source_service.get_settings

            class Settings:
                local_source_dir = snapshot_root

            try:
                source_service.db = test_db
                source_service.get_settings = lambda: Settings()
                source = source_service.register_local_source(source_service.LocalSourceRequest(paths=[docs], name="docs"))
                indexed = source_service.index_source(source.id)
                old_snapshot_dir = Path(str(indexed.metadata["snapshot_dir"]))
                shutil.rmtree(old_snapshot_dir)

                reindexed = source_service.index_source(source.id)

                self.assertEqual(reindexed.status, SourceStatus.INDEXED)
                self.assertEqual(reindexed.document_count, 1)
                self.assertGreater(reindexed.chunk_count, 0)
                self.assertTrue(Path(str(reindexed.metadata["snapshot_dir"])).exists())
            finally:
                source_service.db = original_db
                source_service.get_settings = original_get_settings
                test_db.engine.dispose()

    def test_reindex_refreshes_snapshot_from_changed_original_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            guide = docs / "guide.md"
            guide.write_text("# Guide\n\nOriginal snapshot content.", encoding="utf-8")
            snapshot_root = root / "local"
            db_path = root / "ingestor.sqlite"
            test_db = Database(db_path)
            original_db = source_service.db
            original_get_settings = source_service.get_settings

            class Settings:
                local_source_dir = snapshot_root

            try:
                source_service.db = test_db
                source_service.get_settings = lambda: Settings()
                source = source_service.register_local_source(source_service.LocalSourceRequest(paths=[docs], name="docs"))
                indexed = source_service.index_source(source.id)
                old_snapshot_dir = Path(str(indexed.metadata["snapshot_dir"]))

                guide.write_text("# Guide\n\nUpdated source folder content.", encoding="utf-8")
                reindexed = source_service.index_source(source.id)

                with sqlite3.connect(db_path) as connection:
                    chunk_text = "\n".join(
                        row[0] for row in connection.execute("SELECT content FROM chunks WHERE source_id = ?", (source.id,))
                    )

                self.assertEqual(reindexed.status, SourceStatus.INDEXED)
                self.assertIn("Updated source folder content", chunk_text)
                self.assertNotIn("Original snapshot content", chunk_text)
                self.assertFalse(old_snapshot_dir.exists())
                self.assertTrue(Path(str(reindexed.metadata["snapshot_dir"])).exists())
            finally:
                source_service.db = original_db
                source_service.get_settings = original_get_settings
                test_db.engine.dispose()

    def test_running_job_can_be_found_for_source(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
            try:
                source = SourceRecord(
                    id="running-source",
                    kind=SourceKind.LOCAL,
                    name="running-source",
                    version="test",
                    location="memory",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)

                running_job = test_db.create_job(source.id)

                self.assertEqual(test_db.find_running_job_for_source(source.id), running_job)
            finally:
                test_db.engine.dispose()

    def test_job_progress_fields_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
            try:
                source = SourceRecord(
                    id="progress-source",
                    kind=SourceKind.LOCAL,
                    name="progress-source",
                    version="test",
                    location="memory",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)
                job = test_db.create_job(source.id)

                test_db.update_job(job, progress_current=3, progress_total=10, progress_label="guide.md")
                stored_job = test_db.get_job(job.id)
            finally:
                test_db.engine.dispose()

        self.assertIsNotNone(stored_job)
        self.assertEqual(stored_job.progress_current, 3)
        self.assertEqual(stored_job.progress_total, 10)
        self.assertEqual(stored_job.progress_label, "guide.md")

    def test_cancelled_job_blocks_duplicate_until_worker_stops(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
            original_db = source_service.db
            try:
                source = SourceRecord(
                    id="cancel-source",
                    kind=SourceKind.LOCAL,
                    name="cancel-source",
                    version="test",
                    location="memory",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)
                job = test_db.create_job(source.id)
                source_service.db = test_db
                with source_service.active_jobs_lock:
                    source_service.active_job_ids.add(job.id)

                cancelled = source_service.cancel_index_job(job.id)

                self.assertIsNotNone(cancelled)
                self.assertEqual(cancelled.status, JobStatus.CANCELLING)
                self.assertEqual(test_db.find_running_job_for_source(source.id).id, job.id)
                with self.assertRaises(source_service.IndexCancelled):
                    source_service.ensure_job_not_cancelled(job)
            finally:
                with source_service.active_jobs_lock:
                    source_service.active_job_ids.discard(job.id)
                source_service.db = original_db
                test_db.engine.dispose()

    def test_cancel_stale_running_job_finalizes_immediately(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
            original_db = source_service.db
            try:
                source = SourceRecord(
                    id="stale-cancel-source",
                    kind=SourceKind.LOCAL,
                    name="stale-cancel-source",
                    version="test",
                    location="memory",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)
                job = test_db.create_job(source.id)
                source_service.db = test_db

                cancelled = source_service.cancel_index_job(job.id)

                self.assertIsNotNone(cancelled)
                self.assertEqual(cancelled.status, JobStatus.CANCELLED)
                self.assertIsNone(test_db.find_running_job_for_source(source.id))
                stored_source = test_db.get_source(source.id)
                self.assertEqual(stored_source.status, SourceStatus.REGISTERED)
                self.assertEqual(stored_source.error, "Indexing cancelled.")
            finally:
                source_service.db = original_db
                test_db.engine.dispose()

    def test_background_job_failure_is_logged_to_process_logger(self) -> None:
        job = JobRecord(id="job-1", source_id="source-1")
        original_index_source = source_service.index_source

        def fail_index_source(source_id: str, current_job: JobRecord) -> None:
            raise RuntimeError(f"boom for {source_id} and {current_job.id}")

        try:
            source_service.index_source = fail_index_source
            with self.assertLogs("app.sources.service", level="ERROR") as logs:
                source_service._run_job("source-1", job)
        finally:
            source_service.index_source = original_index_source

        output = "\n".join(logs.output)
        self.assertIn("Index job job-1 failed for source source-1", output)
        self.assertIn("RuntimeError: boom for source-1 and job-1", output)

    def test_sqlite_vec_index_is_populated_during_ingestion(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
            try:
                source = SourceRecord(
                    id="vec-source",
                    kind=SourceKind.LOCAL,
                    name="vec-source",
                    version="test",
                    location="memory",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)
                test_db.replace_source_documents(
                    source,
                    [
                        {
                            "uri": "vectors.md",
                            "title": "Vectors",
                            "content": "# Vectors",
                            "content_hash": "vectors",
                            "chunks": [
                                vector_chunk(0, "Alpha", "alpha", [1.0, 0.0, 0.0]),
                                vector_chunk(1, "Beta", "beta", [0.0, 1.0, 0.0]),
                            ],
                        }
                    ],
                )

                with test_db.connect() as connection:
                    vec_count = connection.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
                    dimensions = connection.execute(
                        "SELECT value FROM vector_index_meta WHERE key = 'dimensions'"
                    ).fetchone()[0]
                    chunk_metadata = connection.execute(
                        """
                        SELECT content_type, parent_chunk_id, metadata, embedding_provider,
                               embedding_model, embedding_dimensions
                        FROM chunks
                        WHERE title = 'Alpha'
                        """
                    ).fetchone()

                original_db = search_module.db
                search_module.db = test_db
                try:
                    results = search_module.sqlite_vec_search([1.0, 0.0, 0.0], ["vec-source"], 2)
                finally:
                    search_module.db = original_db
            finally:
                test_db.engine.dispose()

        self.assertEqual(vec_count, 2)
        self.assertEqual(dimensions, "3")
        self.assertEqual(list(results), [1, 2])
        self.assertGreater(results[1], results[2])
        self.assertEqual(chunk_metadata["content_type"], "markdown")
        self.assertIsNone(chunk_metadata["parent_chunk_id"])
        self.assertEqual(chunk_metadata["embedding_provider"], embedding_signature()["provider"])
        self.assertEqual(chunk_metadata["embedding_model"], embedding_signature()["model"])
        self.assertEqual(chunk_metadata["embedding_dimensions"], 3)
        stored_metadata = json.loads(chunk_metadata["metadata"])
        self.assertEqual(stored_metadata["source_id"], "vec-source")
        self.assertEqual(stored_metadata["document_uri"], "vectors.md")

    def test_sqlite_vec_index_is_backfilled_for_existing_chunks(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            db_path = Path(directory) / "ingestor.sqlite"
            test_db = Database(db_path)
            try:
                source = SourceRecord(
                    id="vec-source",
                    kind=SourceKind.LOCAL,
                    name="vec-source",
                    version="test",
                    location="memory",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)
                test_db.replace_source_documents(
                    source,
                    [
                        {
                            "uri": "vectors.md",
                            "title": "Vectors",
                            "content": "# Vectors",
                            "content_hash": "vectors",
                            "chunks": [vector_chunk(0, "Alpha", "alpha", [1.0, 0.0, 0.0])],
                        }
                    ],
                )
                with test_db.connect() as connection:
                    connection.execute("DROP TABLE chunks_vec")
                    connection.execute("DELETE FROM vector_index_meta")
                    connection.commit()
            finally:
                test_db.engine.dispose()

            rebuilt_db = Database(db_path)
            try:
                with rebuilt_db.connect() as connection:
                    vec_count = connection.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
            finally:
                rebuilt_db.engine.dispose()

        self.assertEqual(vec_count, 1)


class RetrievalContextTests(TestCase):
    def test_assemble_context_prefers_parent_section_context(self) -> None:
        first_part = " ".join(["Parent setup background explains the larger section."] * 70)
        second_part = " ".join(["Needle transaction detail uses websocket sessions."] * 70)
        document = build_document(
            "docs/serverless.md",
            "Serverless",
            f"# Serverless driver\n\n{first_part}\n\n{second_part}",
            embed=False,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
            try:
                source = SourceRecord(
                    id="ctx-source",
                    kind=SourceKind.LOCAL,
                    name="ctx-source",
                    version="test",
                    location="memory",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)
                test_db.replace_source_documents(source, [document])

                with test_db.connect() as connection:
                    row = connection.execute(
                        """
                        SELECT chunks.*, sources.name AS source_name
                        FROM chunks
                        JOIN sources ON sources.id = chunks.source_id
                        WHERE chunks.content LIKE ?
                        ORDER BY chunks.ordinal DESC
                        LIMIT 1
                        """,
                        ("%Needle transaction detail%",),
                    ).fetchone()

                original_db = search_module.db
                search_module.db = test_db
                try:
                    context = assemble_context(row)
                finally:
                    search_module.db = original_db
            finally:
                test_db.engine.dispose()

        self.assertIn("Parent setup background", context)
        self.assertIn("Needle transaction detail", context)


class NeonRetrievalSmokeTests(TestCase):
    def test_neon_style_queries_retrieve_expected_docs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
            try:
                source = SourceRecord(
                    id="neon",
                    kind=SourceKind.WEB,
                    name="neon",
                    version="test",
                    location="https://neon.com/docs/introduction",
                    metadata={"embedding": embedding_signature()},
                )
                test_db.upsert_source(source)
                test_db.replace_source_documents(
                    source,
                    [
                        neon_document(
                            "https://neon.com/docs/serverless/serverless-driver",
                            "Neon serverless driver",
                            "Use the driver over WebSockets. Pool and Client provide session and transaction support. "
                            "Choose WebSocket for interactive transactions. HTTP uses fetch for one-shot queries. "
                            "In Node.js, set neonConfig.webSocketConstructor = ws to supply a websocket constructor.",
                        ),
                        neon_document(
                            "https://neon.com/docs/guides/prisma",
                            "Direct connection for Prisma CLI",
                            "Why two connection strings? Pooled connection DATABASE_URL is for application runtime. "
                            "Direct connection DIRECT_URL is for Prisma migrate and db push schema operations.",
                        ),
                        neon_document(
                            "https://neon.com/docs/guides/branching-neon-api",
                            "Branching with the Neon API",
                            "Create schema-only branches with init_source schema-only. Restore a branch using the branch restore endpoint.",
                        ),
                        neon_document(
                            "https://neon.com/docs/cli/branches",
                            "Neon CLI command: branches",
                            "neonctl branches reset development --parent resets a child branch. "
                            "neonctl branches restore restores a branch to a specified point in time.",
                        ),
                        neon_document(
                            "https://neon.com/docs/guides/nestjs",
                            "Connect a NestJS application to Neon",
                            "Define a controller endpoint and query a table from a NestJS service.",
                        ),
                    ],
                )

                original_db = search_module.db
                search_module.db = test_db
                try:
                    expectations = [
                        (
                            "Neon serverless driver transactions WebSocket fetch websocket constructor",
                            "serverless/serverless-driver",
                        ),
                        (
                            "Neon connection pooling Prisma pooled connection string directUrl migrations",
                            "guides/prisma",
                        ),
                        (
                            "Neon branching create branch schema data reset restore point",
                            "cli/branches",
                        ),
                    ]
                    for query, expected_uri_part in expectations:
                        results = search_module.search_chunks(
                            query=query,
                            source_name="neon",
                            limit=5,
                            mode=SearchMode.KEYWORD,
                        )
                        self.assertTrue(
                            any(expected_uri_part in result.uri for result in results),
                            f"{expected_uri_part} not found for query {query!r}: {[result.uri for result in results]}",
                        )
                finally:
                    search_module.db = original_db
            finally:
                test_db.engine.dispose()


def neon_document(uri: str, title: str, content: str) -> dict:
    chunk = {
        "ordinal": 0,
        "title": title,
        "uri": uri,
        "content": f"# {title}\n\n{content}",
        "section_path": [title],
        "token_count": len(tokenize(content)),
        "embedding": [],
    }
    return {
        "uri": uri,
        "title": title,
        "content": chunk["content"],
        "content_hash": uri,
        "chunks": [chunk],
    }


def vector_chunk(ordinal: int, title: str, content: str, embedding: list[float]) -> dict:
    return {
        "ordinal": ordinal,
        "title": title,
        "uri": f"{title.lower()}.md",
        "content": content,
        "section_path": [title],
        "token_count": len(tokenize(content)),
        "embedding": embedding,
    }


if __name__ == "__main__":
    main()

