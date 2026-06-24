from __future__ import annotations

import sys
import tempfile
import sqlite3
from pathlib import Path
from unittest import TestCase, main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.search as search_module
from app.database import Database
from app.embedding import embedding_signature, tokenize
from app.ingestion import clean_web_markdown, document_from_file, normalize_content
from app.models import SearchMode, SourceKind, SourceRecord
from app.search import diversify_by_document, extract_code, meaningful_terms, shape_result, source_quality_multiplier


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

    def test_web_markdown_chrome_is_removed(self) -> None:
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
Neon Docs
A Databricks Company
© Neon 2026. All rights reserved.
"""
        )

        self.assertIn("# Database branching workflow primer", cleaned)
        self.assertIn("With Neon, you can work with your data like code.", cleaned)
        self.assertNotIn("Search...", cleaned)
        self.assertNotIn("Ask AI", cleaned)
        self.assertNotIn("On this page", cleaned)
        self.assertNotIn("Was this page helpful", cleaned)
        self.assertNotIn("Databricks", cleaned)


class SearchShapingTests(TestCase):
    def test_jsx_blocks_are_treated_as_code(self) -> None:
        content = """Use object syntax for responsive props.

```jsx
<Text fontWeight={{ base: "medium", lg: "bold" }}>Text</Text>
```
"""

        code = extract_code(content, {"responsive", "breakpoints"}, ["responsive"])

        self.assertIsNotNone(code)
        self.assertIn("<Text", code)

    def test_iconify_tailwind_setup_beats_troubleshooting_intent(self) -> None:
        terms = meaningful_terms("How do I use Iconify icons in CSS or Tailwind with icon selectors?")
        setup = make_search_row(
            title="Basic usage",
            uri="docs/usage/css/tailwind/index.md",
            content='const { addIconSelectors } = require("@iconify/tailwind");',
        )
        issue = make_search_row(
            title="Selectors do not work",
            uri="docs/usage/css/tailwind/issues/index.md",
            content="Troubleshooting selectors that do not work.",
        )

        self.assertGreater(source_quality_multiplier(setup, terms), source_quality_multiplier(issue, terms))

    def test_remotion_offthreadvideo_beats_generic_static_files(self) -> None:
        terms = meaningful_terms("How do I use OffthreadVideo or static audio video files in Remotion?")
        exact = make_search_row(
            title="OffthreadVideo",
            uri="docs/offthreadvideo.mdx",
            content="import {OffthreadVideo, staticFile} from 'remotion';",
        )
        generic = make_search_row(
            title="getStaticFiles()",
            uri="docs/get-static-files.mdx",
            content="import {getStaticFiles, StaticFile} from 'remotion';",
        )

        self.assertGreater(source_quality_multiplier(exact, terms), source_quality_multiplier(generic, terms))

    def test_cloud_render_is_penalized_for_local_remotion_render_queries(self) -> None:
        terms = meaningful_terms("How do I create a Remotion composition and render a video?")
        local = make_search_row(
            title="Render",
            uri="docs/cli/render.mdx",
            content="npx remotion render src/index.ts MyComp out.mp4",
        )
        cloud = make_search_row(
            title="Render",
            uri="docs/cloudrun/render.mdx",
            content="npx remotion cloudrun render site serve-url MyComp out.mp4",
        )

        self.assertGreater(source_quality_multiplier(local, terms), source_quality_multiplier(cloud, terms))

    def test_diversification_defers_duplicate_topic_titles(self) -> None:
        first_render = make_search_row(row_id=1, document_id=1, title="Render", uri="docs/cloudrun/render.mdx")
        second_render = make_search_row(row_id=2, document_id=2, title="Render", uri="docs/lambda/render.mdx")
        composition = make_search_row(row_id=3, document_id=3, title="Composition", uri="docs/composition.mdx")

        selected = diversify_by_document(
            [
                (1.0, 0.0, 0.0, first_render),
                (0.99, 0.0, 0.0, second_render),
                (0.9, 0.0, 0.0, composition),
            ],
            2,
        )

        self.assertEqual([row["uri"] for _, _, _, row in selected], ["docs/cloudrun/render.mdx", "docs/composition.mdx"])

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
            {"connection", "pooling", "pooled"},
        )

        self.assertIn("pooled connection string", shaped["content"])
        self.assertNotIn("Search", shaped["content"])
        self.assertNotIn("Was this page helpful", shaped["content"])
        self.assertIsNotNone(shaped["code"])


class NeonRetrievalSmokeTests(TestCase):
    def test_neon_style_queries_retrieve_expected_docs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            test_db = Database(Path(directory) / "ingestor.sqlite")
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


if __name__ == "__main__":
    main()
