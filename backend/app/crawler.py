from __future__ import annotations

import fnmatch
import re
from urllib.parse import urlparse

from collections.abc import AsyncIterator

from app.content import extract_main_markdown, has_obvious_web_chrome, html_to_markdown
from app.ingestion import document_from_web_page


async def crawl_web_documents(
    url: str,
    *,
    max_depth: int,
    max_pages: int,
    scope: str,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[dict]:
    return [
        document
        async for document in iter_web_documents(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            scope=scope,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
    ]


async def iter_web_documents(
    url: str,
    *,
    max_depth: int,
    max_pages: int,
    scope: str,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> AsyncIterator[dict]:
    try:
        async for document in crawl_with_crawl4ai(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
            scope=scope,
            include_patterns=include_patterns or [],
            exclude_patterns=exclude_patterns or [],
        ):
            yield document
    except ImportError as exc:
        raise RuntimeError(
            "Crawl4AI is not installed. Run `pip install -r requirements.txt` in backend."
        ) from exc


async def crawl_with_crawl4ai(
    url: str,
    *,
    max_depth: int,
    max_pages: int,
    scope: str,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> AsyncIterator[dict]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from crawl4ai.content_filter_strategy import PruningContentFilter
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
    from crawl4ai.deep_crawling.filters import ContentTypeFilter, DomainFilter, FilterChain, URLPatternFilter
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    filters = []
    host = urlparse(url).hostname
    if scope == "subpages":
        filters.append(URLPatternFilter(patterns=[f"{url.rstrip('/')}*"]))
    elif host:
        allowed_domain = root_domain(host) if scope == "domain" else host
        filters.append(DomainFilter(allowed_domains=[allowed_domain]))
    crawl_include_patterns = crawl_url_patterns(include_patterns)
    if crawl_include_patterns:
        filters.append(URLPatternFilter(patterns=crawl_include_patterns))
    crawl_exclude_patterns = crawl_url_patterns(exclude_patterns)
    if crawl_exclude_patterns:
        filters.append(URLPatternFilter(patterns=crawl_exclude_patterns, reverse=True))
    filters.append(ContentTypeFilter(allowed_types=["text/html"]))

    strategy = BFSDeepCrawlStrategy(
        max_depth=max_depth,
        max_pages=max_pages,
        include_external=False,
        filter_chain=FilterChain(filters) if filters else None,
    )
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        deep_crawl_strategy=strategy if max_depth > 0 else None,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(
                threshold=0.45,
                threshold_type="dynamic",
                min_word_threshold=5,
            ),
            options={"citations": True},
        ),
        stream=True,
        word_count_threshold=5,
        excluded_tags=["nav", "footer", "header"],
        exclude_external_links=True,
        exclude_social_media_links=True,
    )
    browser_config = BrowserConfig(headless=True, text_mode=True, verbose=False)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        stream = await crawler.arun(url=url, config=run_config)
        async for result in stream:
            result_url = getattr(result, "url", "")
            if not should_index_url(result_url, include_patterns, exclude_patterns):
                continue
            markdown = markdown_from_result(result)
            document = document_from_web_page(result_url, markdown, title=result.metadata.get("title") if result.metadata else None)
            if document:
                yield document


def should_index_url(url: str, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    if include_patterns and not any(pattern_matches_url(pattern, url) for pattern in include_patterns):
        return False
    if any(pattern_matches_url(pattern, url) for pattern in exclude_patterns):
        return False
    return True


def pattern_matches_url(pattern: str, url: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False

    candidates = url_candidates(url)
    if is_path_fragment_pattern(pattern):
        return any(pattern in candidate for candidate in candidates)
    if is_regex_pattern(pattern):
        expression = pattern[1 : pattern.rfind("/")]
        try:
            return any(re.search(expression, candidate) for candidate in candidates)
        except re.error:
            return False

    return any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates)


def crawl_url_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern:
            continue
        if is_path_fragment_pattern(pattern):
            expression = re.escape(pattern)
        elif is_regex_pattern(pattern):
            expression = pattern[1 : pattern.rfind("/")]
        else:
            expression = fnmatch.translate(pattern)
        try:
            compiled.append(re.compile(expression))
        except re.error:
            continue
    return compiled


def is_regex_pattern(pattern: str) -> bool:
    return len(pattern) >= 2 and pattern.startswith("/") and pattern.rfind("/") > 0


def is_path_fragment_pattern(pattern: str) -> bool:
    return bool(re.fullmatch(r"/[A-Za-z0-9._~!$&'()+,;=:@%-]+/", pattern))


def url_candidates(url: str) -> list[str]:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return [
        url,
        path,
        path.lstrip("/"),
        f"{path.lstrip('/')}?{parsed.query}" if parsed.query else path.lstrip("/"),
    ]


def markdown_from_result(result: object) -> str:
    markdown = getattr(result, "markdown", "")
    if isinstance(markdown, str):
        return markdown
    fit = getattr(markdown, "fit_markdown", None)
    cited = getattr(markdown, "markdown_with_citations", None)
    raw = getattr(markdown, "raw_markdown", None)
    if fit:
        if not has_obvious_web_chrome(fit):
            return fit
        extracted = markdown_from_result_html(result)
        if extracted:
            return extracted
        return fit

    crawl_markdown = cited or raw or ""
    if crawl_markdown and not has_obvious_web_chrome(crawl_markdown):
        return crawl_markdown

    extracted = markdown_from_result_html(result)
    if extracted:
        return extracted
    return crawl_markdown


def markdown_from_result_html(result: object) -> str:
    result_url = str(getattr(result, "url", "") or "")
    html = str(getattr(result, "cleaned_html", "") or getattr(result, "html", "") or "")
    if html:
        extracted = extract_main_markdown(html, url=result_url)
        if extracted:
            return extracted
        fallback_markdown = html_to_markdown(html)
        if fallback_markdown:
            return fallback_markdown
    return ""


def root_domain(host: str) -> str:
    parts = host.split(".")
    return host if len(parts) <= 2 else ".".join(parts[-2:])
