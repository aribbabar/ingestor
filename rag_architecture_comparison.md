# RAG Pipeline Comparison for Ingestor

This document compares the architecture and RAG pipeline of each project in `E:\\Projects\\experiments\\rag`, with an eye toward improving Ingestor's embedding generation, retrieval, and document processing.

## 1. Ingestor (your project)

### Architecture summary

Ingestor is a local-first documentation ingestion and retrieval tool with three thin surfaces around a single Python backend:

```text
Desktop app (Tauri + React) -> local daemon API -> Python core
CLI                         -> local daemon API -> Python core
Agent skills                -> ingestor CLI      -> local daemon API -> Python core
```

The backend is a FastAPI daemon (`app.daemon.app`) that exposes routes under `/api` (`app.api.routes`). Data is stored locally in an SQLite database, a `sqlite-vec` vector index, a SQLite FTS5 full-text index, and local snapshot copies of indexed files.

Key modules:
- `app.indexing` — discovery, web crawling, document cleaning/chunking, embedding pipeline.
- `app.retrieval` — embedding providers, vector index, FTS keyword search, hybrid ranking, search settings.
- `app.sources` — source registration and async indexing jobs.
- `app.db` — SQLite persistence with SQLModel.
- `app.cli` — Typer-based CLI that calls the daemon API.

### End-to-end RAG flow

1. **User adds a source**
   - *Local folder/file*: `POST /api/sources/local-folder` -> `app.sources.service.register_local_source()` copies selected paths into `data/local` and stores a `SourceRecord`.
   - *Web docs*: `POST /api/sources/web` -> `register_web_source()` stores crawl settings (`max_depth`, `max_pages`, `scope`, include/exclude patterns).

2. **Indexing job starts**
   - `POST /api/sources/{id}/index` -> `start_index_job()` spawns a background thread.
   - `index_local_source_incrementally()` or `index_web_source_incrementally()` processes files/pages one at a time, yielding document dictionaries (`uri`, `title`, `content`, `content_hash`, `chunks`).

3. **Document processing / cleaning**
   - Local files: `app.indexing.discovery.document_from_file()` reads supported suffixes, strips front matter for markdown, expands FastAPI `{* ... *}` includes and MDX example tags, and converts HTML to markdown.
   - Web pages: `crawl4ai` scrapes pages; `app.indexing.content.extract_main_markdown()` uses `trafilatura`, with a `BeautifulSoup` + `markdownify` fallback, then `clean_web_markdown()` removes boilerplate ("search", "ask AI", TOC headings).

4. **Chunking**
   - `app.indexing.chunking.build_chunks()` splits on markdown headings (`#`, `##`, `###`) to produce a section path, then splits long sections at paragraph/sentence boundaries (`CHUNK_TARGET_CHARS=3600`, `CHUNK_OVERLAP_CHARS=400`).
   - Embedding text for each chunk is `f"{chunk_title}\n{piece}"`.

5. **Embedding generation**
   - `app.indexing.embedding_pipeline.embed_chunks()` sends batches to `app.retrieval.embeddings.embed_texts()`.
   - Providers:
     - **Local hashing fallback** (`local-hashing-256`): deterministic 256-dim bag-of-tokens vector built with `hashlib.blake2b`.
     - **Ollama**: calls `/api/embed` with batched `input` arrays and normalizes vectors.
   - Config stored in `app_settings` (provider, model, batching strategy, batch size). Batching strategies: `batch` (default 32) or `single`.
   - Dimension is hard-coded at `VECTOR_DIMENSIONS = 256`. Ollama vectors are normalized but their native dimension may differ, which is a compatibility risk.

6. **Storage**
   - Documents and chunks go into SQLite (`DocumentTable`, `ChunkTable`).
   - Each chunk is also inserted into FTS5 `chunks_fts` and into the `sqlite-vec` virtual table `chunks_vec` (partitioned by `source_id`).
   - The vector table is recreated if dimension changes; a meta table tracks the current vector dimension.

7. **Query / retrieval**
   - `POST /api/sources/search` -> `search_chunks()`.
   - Modes: `keyword` (FTS5), `vector` (sqlite-vec), `hybrid` (RRF with `RRF_K=60`, equal weights).
   - For each mode, candidates are fetched with `limit*6`, then ranked.
   - Results are diversified by document (max one chunk per document until all documents are represented).
   - A context window of ±1 chunk around each result is assembled.
   - Results are "shaped": snippet trimmed to ~1200 chars, code blocks extracted, section paths parsed.

8. **Answer generation**
   - Ingestor does **not** call an LLM itself. It returns search results to the UI/CLI/agent. The `ingestor-search` skill calls `ingestor search ... --output json` and feeds snippets into the agent's own LLM context.

### Improvement notes for Ingestor

- **Embedding dimension mismatch**: `VECTOR_DIMENSIONS = 256` is hard-coded. If a user picks an Ollama model whose output dimension is not 256, the sqlite-vec table must be rebuilt, and old sources are marked "reindex required". Consider making the vector dimension dynamic per model or normalizing/truncating to a fixed size consistently.
- **Embedding provider diversity**: Only Ollama and a local hash fallback are supported. Other projects support many providers (OpenAI, Azure, Gemini, local ONNX, etc.).
- **Chunking target**: 3600 chars is large for dense embedding models. Many tools use 512–1500 tokens/chars; large chunks can dilute relevance and exceed small embedding models.
- **No re-ranker**: Hybrid ranking uses simple RRF without a learned or cross-encoder re-ranker.
- **Query understanding**: The FTS query is built by OR-ing tokenized query terms; there is no query expansion, synonym handling, or stop-word-aware phrase search.
- **No structured metadata filtering**: Sources have basic metadata, but chunks have no custom metadata/tags.

---

## 2. LocalKit Docs

### Architecture summary

LocalKit Docs is very close in scope to Ingestor: a local-first documentation index for coding agents, with a Python backend, optional React/Vite frontend, SQLite metadata store, Chroma vector store, and agent skills.

Key modules:
- `backend/src/ingest` — file copying, web crawling, markdown cleaning, chunking.
- `backend/src/storage` — SQLite/SQLModel, Chroma vector store, Ollama embeddings.
- `backend/src/core` — source service, indexer, search service.
- `backend/src/api` / `backend/src/cli` — FastAPI and Typer surfaces.

### RAG flow relevant to Ingestor

1. **Ingestion**
   - Local docs are copied into `~/.localkit-docs/sources/local`.
   - Web docs are crawled with `crawl4ai` and saved to `~/.localkit-docs/sources/remote` as markdown files with front-matter metadata (`source_url`, `title`, `status_code`, `depth`, `saved_at`).

2. **Cleaning**
   - `clean_document_text()` strips leading metadata comments, removes boilerplate lines ("ask ai", "copy page", footer links, compliance prefixes), normalizes markdown links/images, and collapses blank lines.

3. **Chunking**
   - `chunk_text()` defaults to `chunk_size=1400`, `overlap=200`.
   - `_chunk_markdown_sections()` splits by H1–H6, building a heading path. Long sections are split at paragraph/sentence boundaries.
   - If no markdown structure is found, it falls back to plain sliding-window chunking.

4. **Embedding**
   - `OllamaEmbeddingProvider` only, default `nomic-embed-text`. Uses `/api/embed` with batched `input` and normalizes newlines.
   - Vectors are stored in ChromaDB with metadata filters (`source_id`, `embedding_model`).

5. **Retrieval**
   - Hybrid search: vector search with large over-fetch (`vector_multiplier=10`, max 500), plus SQLite FTS5 full-text search (`porter unicode61` tokenizer).
   - `_rank_hybrid()` uses RRF (`k=60`, normalized by channel count).
   - `_diversify()` spreads results across documents and expands context from neighboring chunks (`context_window=1`, `max_context_chars=4800`), with de-duplication and overlap trimming.

### What Ingestor can learn

- **Better chunk size default**: 1400 chars is closer to common embedding model sweet spots than Ingestor's 3600.
- **Metadata-aware cleaning**: front-matter metadata (`source_url`, `title`) is preserved and used later; Ingestor strips some of this.
- **Diversification + context expansion**: LocalKit's `_diversify()` and `_join_chunk_text()` are more sophisticated than Ingestor's simple document-diversity + ordinal window.
- **Embedding model identity stored per chunk**: Chroma metadata records `embedding_model`, making it easy to invalidate stale vectors. Ingestor stores the signature on the source only.

---

## 3. Docs MCP Server (Grounded Docs)

### Architecture summary

A TypeScript/Node documentation indexing server exposing CLI, MCP (stdio/HTTP), and a small web UI. It indexes library docs from the web, npm/PyPI, GitHub, local files, and zip archives, with version-specific search.

Key modules:
- `src/scraper` — fetchers, middleware, content-type-specific pipelines.
- `src/splitter` — semantic markdown, code, list, table, JSON, tree-sitter splitters; a greedy concatenation pass.
- `src/store` — SQLite doc store, FTS5, optional vector embeddings via LangChain.js providers.
- `src/pipeline` — async job processing with cancellation and refresh.

### RAG flow relevant to Ingestor

1. **Ingestion / scraping**
   - `ScraperService.scrape()` runs a content-type-specific pipeline. URL discovery, extraction, and conversion are pluggable.
   - Supports `llms.txt` probing and Markdown content negotiation for cleaner web docs.

2. **Splitting / chunking**
   - `SemanticMarkdownSplitter` parses HTML/markdown into a DOM, then sections (H1–H3), then content-type-aware pieces:
     - text → `TextContentSplitter`
     - code → `CodeContentSplitter`
     - tables → `TableContentSplitter`
     - lists → `ListContentSplitter`
   - `GreedySplitter` concatenates small chunks while respecting H1/H2 boundaries and hard max chunk size.
   - This produces semantically coherent chunks that preserve structure.

3. **Embedding**
   - LangChain.js providers: OpenAI, Azure, Vertex/Gemini, AWS Bedrock, SageMaker.
   - `FixedDimensionEmbeddings` wrapper normalizes dimensions by truncation (MRL-safe, e.g. Gemini) or zero-padding.
   - Stored in SQLite via vector extension or FTS5 fallback.

4. **Retrieval / assembly**
   - `DocumentRetrieverService.search()` does hybrid search (vector + FTS5).
   - Results are clustered by URL and chunk distance.
   - `ContentAssemblyStrategyFactory` picks a content-type-aware strategy to select and assemble context snippets.
   - Search result reassembly keeps related chunks together and trims overlap.

### What Ingestor can learn

- **Semantic + content-type chunking**: splitting text, code, tables, and lists differently yields much better retrieval for docs.
- **Greedy re-assembly**: the greedy splitter solves the "tiny orphan chunk" problem.
- **Multi-provider embeddings**: supporting OpenAI, Azure, Gemini, etc. dramatically improves result quality versus a hashing fallback.
- **Fixed-dimension wrapper**: avoids the dimension-mismatch headaches Ingestor has with Ollama.
- **Content-type-aware retrieval assembly**: returning assembled context instead of raw chunk snippets is closer to what an LLM needs.

---

## 4. Context7

### Architecture summary

Context7 is a hosted service with an open-source MCP server / CLI wrapper. The actual crawling, parsing, embedding, and storage backend is private, so only the client-side architecture is visible here.

What we can see:
- `ctx7` CLI / MCP server in TypeScript.
- Uses the Context7 API to fetch version-specific documentation for libraries.
- Provides tools: `resolve-library-id`, `query-docs`.

### RAG flow relevant to Ingestor

1. User asks a coding question with `use context7`.
2. The agent calls `resolve-library-id` to map a package/library name to a Context7-compatible ID.
3. It calls `query-docs` with the library ID and the question.
4. Context7's backend presumably performs retrieval over pre-indexed, version-specific docs and returns snippets.
5. The agent appends those snippets to the LLM prompt.

### What Ingestor can learn

- **Version-specific indexing**: associating sources with a version and allowing version-aware search is valuable for library docs.
- **Library identity resolution**: normalizing package names to canonical IDs makes agent usage much smoother.
- **Hosted/community index trade-off**: Context7 covers popular libraries out of the box; Ingestor is local/private. A hybrid option (local index + optional shared index) could extend coverage.

---

## 5. AnythingLLM

### Architecture summary

AnythingLLM is a full-stack chat-with-documents app: Node.js/Express backend, React frontend, Prisma/SQLite metadata, pluggable vector DBs and embedding providers, plus AI agents and multi-user workspaces.

Key RAG modules:
- `server/utils/EmbeddingEngines` — providers: native ONNX (`Xenova/all-MiniLM-L6-v2`), Ollama, OpenAI, Azure, Gemini, Cohere, Voyage, etc.
- `server/utils/vectorDbProviders` — Chroma, Pinecone, Qdrant, Weaviate, Astra, pgvector, Lance, Milvus/Zilliz.
- `server/utils/TextSplitter` — wraps LangChain's `RecursiveCharacterTextSplitter`; prepends chunk prefixes and document metadata headers.
- `server/utils/DocumentManager` — handles pinned documents and token budgets.
- `collector/` — separate content ingestion process that converts files to markdown-like text.

### RAG flow relevant to Ingestor

1. **Upload / collector**
   - Documents are uploaded to a workspace. The `collector` process normalizes PDFs, Office files, web pages, etc. to text.
   - `EmbeddingWorkerManager` queues embedding jobs.

2. **Chunking**
   - `TextSplitter` uses `RecursiveCharacterTextSplitter` with configurable `chunkSize`/`chunkOverlap`.
   - It can prepend an embedder-specific chunk prefix (e.g. `search_query:` / `search_document:`) and document metadata headers (`sourceDocument`, `published`, `source`).

3. **Embedding**
   - Native embedder downloads ONNX models from HuggingFace and runs them locally, writing embeddings to a temp file to keep memory low.
   - Ollama embedder batches with `num_ctx` set to the max chunk length.
   - Many cloud providers are supported.

4. **Storage**
   - Vectors go to one of many vector DBs. Metadata includes workspace ID, document ID, etc.

5. **Retrieval**
   - Query is embedded with the same provider/model.
   - Vector DB similarity search, optionally with metadata filters.
   - Retrieved chunks are injected into the chat prompt along with system prompt and chat history.

### What Ingestor can learn

- **Provider/model diversity**: supporting many embedders and vector stores makes the app useful in more environments.
- **Chunk prefixes / metadata headers**: prepending task-specific prefixes and source metadata to chunks improves embedding quality and citation.
- **Token-aware context management**: DocumentManager respects `maxTokens` when injecting pinned docs.
- **Workspace-scoped collections**: isolating vector collections per workspace/source prevents cross-contamination.

---

## 6. Open WebUI

### Architecture summary

Open WebUI is a self-hosted AI platform (Python/FastAPI backend, Svelte frontend) built around Ollama and OpenAI-compatible APIs. It has extensive RAG, web search, and knowledge-base features.

Key RAG modules:
- `backend/open_webui/retrieval/loaders/main.py` — document loader supporting PDF, Office, HTML, CSV, EPUB, YouTube, etc. via LangChain loaders and custom OCR loaders.
- `backend/open_webui/retrieval/utils.py` — embedding generation, RAG pipeline, hybrid retrieval (BM25 + vector), reranking.
- `backend/open_webui/retrieval/vector` — vector DB factory supporting Chroma, Milvus, Qdrant, Pinecone, pgvector, Weaviate, Elasticsearch, etc.
- `backend/open_webui/retrieval/web` — many web search providers (Brave, Bing, Tavily, SearXNG, etc.).

### RAG flow relevant to Ingestor

1. **Ingestion**
   - Files are uploaded to a knowledge collection. `Loader` picks a loader by extension/content type.
   - Optional OCR/document-intelligence engines (Marker, Mistral, PaddleOCR, MinerU, Azure Document Intelligence).

2. **Chunking**
   - Uses LangChain text splitters with configurable `chunk_size`, `chunk_overlap`, separators, and embedding-prefix injection (`RAG_EMBEDDING_CONTENT_PREFIX`, `RAG_EMBEDDING_QUERY_PREFIX`).

3. **Embedding**
   - Supports Ollama, OpenAI, Azure OpenAI. Batch embeddings with parallel batches.
   - Prefixes can be applied per field.

4. **Retrieval**
   - Hybrid search via `EnsembleRetriever` (BM25 + vector) with configurable weights.
   - Optional reranking via cross-encoder or external reranker.
   - Context compression with `ContextualCompressionRetriever`.
   - Filters by user access grants and collection scope.

5. **Answer generation**
   - Retrieved context is injected into the chat prompt and sent to the configured LLM.

### What Ingestor can learn

- **Rich document loaders**: supporting many file types (PDF, Office, EPUB, email, etc.) with fallback loaders expands use cases.
- **Hybrid ensemble with BM25 + vector**: BM25 is cheaper than FTS5 for some deployments and easy to tune.
- **Reranking + contextual compression**: rerankers significantly improve relevance; contextual compression trims noise before sending to the LLM.
- **Embedding prefixes**: separate prefixes for query vs. document chunks are a cheap win for asymmetric retrieval.

---

## 7. RAGFlow

### Architecture summary

RAGFlow is a document-analytics-focused RAG platform. Python backend (Quart/FastAPI), React frontend, MySQL metadata, Elasticsearch/Infinity doc store, Redis queue, and dedicated task executors. It emphasizes deep document understanding (layout parsing, OCR, table extraction) before retrieval.

Key RAG modules:
- `rag/app/` — document-type-specific parsers (naive, resume, laws, paper, book, table, QA, email, presentation, picture, manual).
- `rag/nlp/` — tokenizer, keyword/term weighting, query handling, search logic.
- `api/db/services/document_service.py` — document lifecycle and chunk management.
- `api/apps/restful_apis/document_api.py` / `search_api.py` — upload and search APIs.

### RAG flow relevant to Ingestor

1. **Upload**
   - Documents uploaded to a knowledge base (dataset). Parser (`chunk_method`) and parser config are selected per document.

2. **Parsing / chunking**
   - `naive.py` is the general parser. It runs layout recognizers (DeepDOC, PlainText, MinerU, PaddleOCR, Docling, OpenDataLoader, TCADP) to extract sections, tables, and images.
   - Different file types have dedicated parsers. Tables are tokenized specially; images can be described with a vision LLM.
   - `rag_tokenizer` tokenizes for term weighting and keyword search.

3. **Embedding / indexing**
   - Text chunks are embedded by the task executor.
   - `doc_store` (Elasticsearch/Infinity) stores chunks with dense vectors, sparse term fields (`content_ltks`, `title_tks`), and metadata.

4. **Retrieval**
   - `rag/nlp/search.py` `Dealer.search()`:
     - Fulltext query via `query.FulltextQueryer()`.
     - Dense vector query with cosine similarity.
     - Fusion of keyword and vector signals.
     - Reranking, tag/metadata filters, TOC-aware retrieval, parent/child chunk assembly (`retrieval_by_children`).
   - `search_api.py` exposes streaming completions over retrieved chunks.

### What Ingestor can learn

- **Document-type-aware parsing**: treating PDFs, tables, presentations, and images differently yields much higher-quality chunks than one-size-fits-all markdown extraction.
- **Layout-aware extraction**: tools like DeepDOC, Marker, Docling preserve reading order and table structure.
- **Hybrid keyword + vector in one doc store**: Elasticsearch/Infinity supports both dense and sparse fields, enabling unified ranking.
- **TOC and parent-child retrieval**: using document outline to expand or rerank results gives more coherent answers.

---

## 8. Dify

### Architecture summary

Dify is a full LLM application development platform (Python/Flask backend, React frontend, PostgreSQL metadata, Redis, Celery, Weaviate/Qdrant/PGVector/etc. vector stores). Its RAG pipeline is highly modular and supports knowledge bases, datasets, and workflow-based retrieval.

Key RAG modules:
- `api/core/rag/extractor` — extractors for PDF, Word, Excel, HTML, CSV, EPUB, email, Notion, web (Firecrawl, Watercrawl, Jina Reader).
- `api/core/rag/splitter` — `FixedRecursiveCharacterTextSplitter`, `EnhanceRecursiveCharacterTextSplitter`.
- `api/core/rag/index_processor` — `ParagraphIndexProcessor` orchestrates extract → clean → split → embed → index.
- `api/core/rag/retrieval` — `DatasetRetrieval` with keyword (jieba keyword table), vector, full-text, rerank, metadata filtering, multi-dataset routing.
- `api/services/dataset_service.py`, `api/services/external_knowledge_service.py` — knowledge base management.

### RAG flow relevant to Ingestor

1. **Upload / data source**
   - Documents or web pages are uploaded to a Dataset (knowledge base). `ExtractProcessor` picks an extractor by source type and file extension.

2. **Cleaning**
   - `CleanProcessor` removes noise and applies process rules.

3. **Splitting**
   - Automatic or custom rules drive `FixedRecursiveCharacterTextSplitter`.
   - Supports hierarchical/parent-child chunking and summary index generation.

4. **Embedding / indexing**
   - Chunks are embedded via the configured model provider.
   - Keyword table (jieba) and vector index are built; metadata and child chunks are stored.

5. **Retrieval**
   - `DatasetRetrieval.retrieve()` supports multiple retrieval methods: full-text, vector, keyword.
   - Multi-dataset retrieval with function-call or ReAct routing.
   - Optional reranking model and score thresholds.
   - Metadata filtering conditions.
   - Images attached to segments can be returned.

6. **Answer generation**
   - Retrieved context is formatted and passed to the LLM via Dify's prompt/completion pipeline.

### What Ingestor can learn

- **Extractor pipeline**: supporting many data sources and file types with dedicated extractors is a big usability win.
- **Process rules / chunk templates**: letting users choose automatic vs. custom chunking rules (separator, size, overlap) is essential for heterogeneous docs.
- **Keyword table**: jieba-based keyword tables give cheap, effective lexical retrieval.
- **Multi-dataset / multi-source routing**: for agents, routing a query to the right source(s) matters; Ingestor currently searches one source or all sources.
- **Metadata filtering**: attaching and filtering by metadata greatly improves precision.

---

## 9. LangChain

### Architecture summary

LangChain is a framework, not an end-user application. It provides composable building blocks for RAG: document loaders, text splitters, embedding models, vector stores, retrievers, and LLM chains.

Relevant pieces:
- `langchain_community.document_loaders` and `langchain_text_splitters`.
- `libs/text-splitters/langchain_text_splitters/markdown.py` — `MarkdownHeaderTextSplitter`, `MarkdownTextSplitter`.
- `langchain_core` embeddings/retriever interfaces.

### RAG flow relevant to Ingestor

A typical LangChain RAG app:
1. Load docs with a loader.
2. Split with `RecursiveCharacterTextSplitter`, `MarkdownHeaderTextSplitter`, etc.
3. Embed with an `Embeddings` implementation.
4. Store in a `VectorStore`.
5. Retrieve with `similarity_search` or `as_retriever`.
6. Feed results into an LLM chain.

### What Ingestor can learn

- **Reusable splitter library**: `MarkdownHeaderTextSplitter` with configurable header levels and metadata propagation is more flexible than Ingestor's custom regex splitter.
- **Separator-based recursive splitting**: splitting by a list of separators (`\n\n`, `\n`, `. `, ` `, ```) preserves semantics better than fixed character windows.
- **Framework ecosystem**: using standard interfaces makes it easy to swap loaders, embedders, and vector stores.

---

## 10. LlamaIndex

### Architecture summary

LlamaIndex is another RAG/agentic framework. It centers on "nodes" (chunks with metadata and relationships) and indices over those nodes.

Relevant pieces:
- `llama_index.core.node_parser.text.sentence.SentenceSplitter` — token-aware sentence/paragraph chunking with overlap.
- `llama_index.core.node_parser.text.utils` — split helpers.
- `VectorStoreIndex`, `SimpleDirectoryReader`, query engines.

### RAG flow relevant to Ingestor

A typical LlamaIndex RAG app:
1. `SimpleDirectoryReader` loads files.
2. A node parser (e.g. `SentenceSplitter`) produces nodes with metadata and prev/next relationships.
3. `VectorStoreIndex.from_documents()` embeds and stores nodes.
4. A query engine retrieves nodes and synthesizes answers.

### What Ingestor can learn

- **Token-aware chunking**: `SentenceSplitter` measures token size rather than character count, which aligns better with embedding and LLM context limits.
- **Node metadata and relationships**: storing prev/next node links enables better context expansion and citation.
- **Index abstraction**: separating parsing, indexing, and retrieval makes it easier to plug in rerankers, metadata filters, and response synthesizers later.

---

## Summary of improvement opportunities for Ingestor

| Area | What Ingestor does now | What other projects do | Suggested improvement |
|------|------------------------|------------------------|----------------------|
| **Embedding providers** | Ollama + local hashing fallback | OpenAI, Azure, Gemini, local ONNX, Cohere, Voyage, Bedrock, etc. | Add a provider abstraction so users can pick Ollama, OpenAI, Azure, etc. without hard-coded dimensions. |
| **Embedding dimensions** | Hard-coded 256; rebuilds index on mismatch | Dynamic per model; truncation/padding wrappers | Store model dimension in settings; normalize vectors to a target dimension (truncate/pad) or recreate index only when needed. |
| **Chunk size** | 3600 chars target | 512–1500 tokens typical; content-type-aware | Move to token-based targets or smaller char targets; consider content-type-specific splitters. |
| **Chunking strategy** | Markdown heading split + fixed window | Semantic splitters, greedy re-assembly, code/table/list splitters | Use a pluggable splitter pipeline (markdown, code, tables) and a greedy merge pass. |
| **Hybrid retrieval** | FTS5 + sqlite-vec + RRF | BM25 + vector ensemble, rerankers, contextual compression | Add optional reranker and query/document embedding prefixes. |
| **Diversification / context** | Document diversity + ±1 ordinal window | URL/distance clustering, parent-child assembly, overlap trimming | Improve context assembly: cluster by section, trim overlap, expand around headings. |
| **Document sources/types** | Local markdown/text/web | PDFs, Office, EPUB, email, Notion, YouTube, many web extractors | Add more loaders over time, starting with PDF and HTML. |
| **Metadata** | Basic source metadata | Per-chunk metadata, tags, custom fields | Add chunk-level metadata (source URL, section path, doc type) and allow simple metadata filters. |
| **Versioning** | Source version field, not used for retrieval | Version-specific search, semver resolution | Let users tag source versions and optionally scope search to a version. |
| **Agent skills** | Search + manage via CLI | MCP-native tools, library ID resolution | Consider an MCP server surface in addition to CLI skills for richer agent integration. |
| **Observability / eval** | Job logs | Benchmark suites, LLM-judged retrieval metrics | Add retrieval eval harness to compare chunking/embedding/retrieval changes. |

## Recommended next steps

1. **Stabilize embedding dimensions**: remove the 256-dim assumption; support model-native dimensions with a migration path.
2. **Expand embedding providers**: at minimum add OpenAI/Azure/Gemini via a config-driven factory.
3. **Improve chunking**: adopt a token-aware, content-type-aware splitter (markdown headings + recursive separators + greedy merge), and reduce default chunk target size.
4. **Add reranking**: integrate a small cross-encoder reranker (local or external) in hybrid mode.
5. **Better context assembly**: cluster neighboring chunks, trim overlap, and include section paths/citations in returned results.
6. **Add PDF/HTML loaders**: these are the most common non-markdown doc formats.
7. **Build a retrieval benchmark**: create a small labeled dataset of queries and expected chunks so future changes can be measured.