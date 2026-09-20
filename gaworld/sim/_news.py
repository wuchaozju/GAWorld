"""External information acquisition extracted from ``generative_city_sim.py``.

Scope — the contiguous block of news, search, and info-seeking helpers
originally at L244–L1031 of the legacy file. Three layers:

1. **Source plumbing** — fetch a social/news page, load configured
   sources, refresh a local news cache.
2. **Interest scoring** — keyword extraction from an agent's profile,
   relevance scoring of a URL/title/excerpt against those interests,
   preferred-site selection.
3. **Acquisition pipelines** — three entry points that write a memory
   record + log line per agent: ``info_seek_and_store`` (smart
   target chooser), ``search_web_and_store`` (explicit query +
   multi-engine fallback), ``read_news_and_store`` (read a single URL
   the caller already has).

LLM access uses module-attribute dispatch (``_llm_providers.call_llm``)
rather than a ``from`` import so the test mock installer's
``llm_providers.call_llm = mock`` reassignment is picked up.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

from gaworld.io.web_scrape import (
    extract_meta_description as _extract_meta_content,
    extract_news_main_content as _extract_news_main_content,
    extract_title as _extract_title,
    fetch_news_excerpt,
    normalize_text as _normalize_text,
    strip_html as _strip_html,
)
from gaworld.io.x_mcp import x_mcp_search
from gaworld.llm import providers as _llm_providers
from gaworld.memory.store import save_agent_memory, vector_db_add_entry
from gaworld.personality import personality_line


# ---------------------------------------------------------------------------
# 1. Source plumbing
# ---------------------------------------------------------------------------

def fetch_social_page_profile_source(
    url: str,
    timeout: int = 12,
    max_chars: int = 12000,
    user_agent: str = "GAWorld/1.0",
) -> dict[str, Any]:
    if not url:
        raise ValueError("缺少 URL")
    headers = {"User-Agent": user_agent}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    if not resp.encoding:
        resp.encoding = resp.apparent_encoding
    raw_text = resp.text or ""
    title = _extract_title(raw_text)
    meta_desc = _extract_meta_content(
        raw_text,
        "description",
        "og:description",
        "twitter:description",
    )
    content = _extract_news_main_content(raw_text)
    if len(content) < 200:
        content = _strip_html(raw_text)
    combined = "\n".join(
        part for part in [
            f"页面标题：{title}" if title else "",
            f"页面摘要：{meta_desc}" if meta_desc else "",
            content,
        ]
        if part
    ).strip()
    if max_chars and len(combined) > max_chars:
        combined = combined[:max_chars]
    return {
        "url": url,
        "title": title,
        "summary": meta_desc,
        "content": combined,
    }


def load_news_sources(path: str | None) -> list[str]:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    # Preserved verbatim from the legacy source — these are double-backslashed
    # in the original (not a typo on our end), matching e.g. literal `\(...\)`
    # patterns that some upstream profile markdown apparently emits. The second
    # findall catches everything else so the over-escape rarely matters in
    # practice. Do NOT "fix" this during the extraction.
    urls = re.findall(r"\\((https?://[^)\\s]+)\\)", text)
    urls.extend(re.findall(r"https?://[^\\s)]+", text))
    cleaned: list[str] = []
    seen: set[str] = set()
    for url in urls:
        url = url.strip().rstrip(").,;")
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append(url)
    return cleaned


def load_news_cache(path: str | None) -> list[dict[str, str]]:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        text = str(item.get("text", "")).strip()
        if not url or not text:
            continue
        cleaned.append({
            "url": url,
            "text": text,
            "title": str(item.get("title", "")).strip(),
            "fetched_at": str(item.get("fetched_at", "")).strip(),
        })
    return cleaned


def update_news_cache(
    path: str,
    sources: list[str],
    config: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    config = config or {}
    existing = load_news_cache(path)
    if not sources:
        return existing
    timeout = int(config.get("timeout", 8))
    max_chars = int(config.get("max_chars", 2000))
    user_agent = str(config.get("user_agent", "GAWorld/1.0"))
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in sources:
        url = str(url).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        excerpt, title = fetch_news_excerpt(
            url,
            timeout=timeout,
            max_chars=max_chars,
            user_agent=user_agent,
            return_title=True,
        )
        if not excerpt:
            continue
        items.append({
            "url": url,
            "title": title,
            "text": excerpt,
            "fetched_at": time.strftime("%Y-%m-%d"),
        })
    if not items:
        return existing
    cache_dir = os.path.dirname(path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except OSError:
        return existing
    return items


# ---------------------------------------------------------------------------
# 2. Interest scoring & target selection
# ---------------------------------------------------------------------------

def _extract_interest_keywords(agent: dict[str, Any], max_items: int = 24) -> list[str]:
    profile_fields = [
        "job",
        "personality",
        "daily_life",
        "values",
        "work_style",
        "living",
        "residence",
    ]
    seed_text = " ".join(str(agent.get(k, "")) for k in profile_fields)
    tokens = re.findall(r"[A-Za-z]{3,}|[一-鿿]{2,8}", seed_text)
    stopwords = {
        "自己", "一些", "这种", "这个", "那个", "他们", "我们", "你们",
        "以及", "对于", "非常", "比较", "可以", "因为", "所以", "但是",
        "工作", "生活", "习惯", "日常", "态度", "价值观", "情绪", "性格",
        "城市", "社会", "公共", "事务", "时候", "进行", "觉得", "喜欢",
        "about", "into", "with", "from", "that", "this", "have", "their",
    }
    counts: dict[str, int] = defaultdict(int)
    for raw in tokens:
        token = raw.lower().strip()
        if len(token) < 2 or token in stopwords:
            continue
        counts[token] += 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))
    return [k for k, _ in ranked[:max_items]]


def _score_news_relevance(
    url: str, title: str, excerpt: str, interests: list[str]
) -> tuple[float, list[str]]:
    if not interests:
        return 0.0, []
    domain = urlparse(url).netloc.lower() if url else ""
    haystack = " ".join(
        [
            str(url or "").lower(),
            str(domain or "").lower(),
            str(title or "").lower(),
            str(excerpt or "").lower(),
        ]
    )
    if not haystack.strip():
        return 0.0, []
    matched: list[str] = []
    score = 0.0
    for kw in interests:
        if kw and kw in haystack:
            matched.append(kw)
            score += 1.0 + min(len(kw), 10) * 0.05
    return score, matched[:8]


def choose_news_for_agent(
    agent: dict[str, Any],
    news_cache: list[dict[str, Any]],
    news_sources: list[str],
    use_cache_first: bool = True,
    seen_urls: set[str] | None = None,
) -> tuple[str, str, str, float, list[str]]:
    seen_urls = seen_urls or set()
    interests = _extract_interest_keywords(agent)

    def _pick_best_from_cache(items):
        ranked = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            title = str(item.get("title", "")).strip()
            text = str(item.get("text", "")).strip()
            score, matched = _score_news_relevance(url, title, text, interests)
            ranked.append((score + random.random() * 0.05, matched, item))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[0], reverse=True)
        top_n = ranked[: min(3, len(ranked))]
        chosen = random.choice(top_n)
        return chosen[2], chosen[0], chosen[1]

    if use_cache_first and news_cache:
        picked = _pick_best_from_cache(news_cache)
        if picked:
            item, score, matched = picked
            return (
                item.get("url", ""),
                item.get("text", ""),
                item.get("title", ""),
                score,
                matched,
            )

    candidate_sources = [u for u in news_sources if u and u not in seen_urls]
    if candidate_sources:
        source_ranked = []
        for source_url in candidate_sources:
            score, matched = _score_news_relevance(source_url, "", "", interests)
            source_ranked.append((score + random.random() * 0.05, matched, source_url))
        source_ranked.sort(key=lambda x: x[0], reverse=True)
        best_score, best_matched, best_url = source_ranked[0]
        return best_url, "", "", best_score, best_matched

    if news_cache:
        picked = _pick_best_from_cache(news_cache)
        if picked:
            item, score, matched = picked
            return (
                item.get("url", ""),
                item.get("text", ""),
                item.get("title", ""),
                score,
                matched,
            )
    return "", "", "", 0.0, []


def _domain_from_url(url: str) -> str:
    domain = urlparse(str(url or "")).netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


# Domains behind a login wall: page fetches return junk, but search
# results from these already carry the full post text in "snippet".
_SNIPPET_ONLY_DOMAINS = {"x.com", "twitter.com"}


def _build_agent_preferred_sites(
    agent: dict[str, Any],
    news_sources: list[str] | None = None,
    news_cache: list[dict[str, Any]] | None = None,
    max_sites: int = 6,
) -> list[str]:
    news_sources = news_sources or []
    news_cache = news_cache or []
    interests = _extract_interest_keywords(agent, max_items=18)
    fallback_domains = [
        "baidu.com",
        "bing.com",
        "google.com",
        "thepaper.cn",
        "news.qq.com",
        "weibo.com",
        "zhihu.com",
    ]
    domain_scores: dict[str, float] = defaultdict(float)
    for url in news_sources:
        domain = _domain_from_url(url)
        if domain:
            domain_scores[domain] += 0.6
            score, _ = _score_news_relevance(url, "", "", interests)
            domain_scores[domain] += score
    for item in news_cache:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        domain = _domain_from_url(url)
        if not domain:
            continue
        score, _ = _score_news_relevance(url, title, text, interests)
        domain_scores[domain] += 0.5 + score
    for domain in fallback_domains:
        domain_scores[domain] += 0.2
    ranked = sorted(domain_scores.items(), key=lambda x: (-x[1], x[0]))
    return [domain for domain, _ in ranked[:max(1, int(max_sites))]]


def _choose_info_target(
    agent: dict[str, Any],
    news_cache: list[dict[str, Any]],
    news_sources: list[str],
    preferred_sites: list[str],
    seen_urls: set[str] | None = None,
    used_queries: set[str] | None = None,
    config: dict[str, Any] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any] | None:
    config = config or {}
    seen_urls = seen_urls or set()
    used_queries = used_queries or set()
    direct_visit_ratio = float(config.get("prefer_source_visit_ratio", 0.55))
    interests = _extract_interest_keywords(agent)

    if keywords:
        query = " ".join(str(k).strip() for k in keywords if str(k).strip())
        if query:
            return _web_search_target(
                agent=agent,
                query=query,
                interests=interests,
                preferred_sites=preferred_sites,
                seen_urls=seen_urls,
                config=config,
            )

    preferred_cache = []
    for item in news_cache or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        domain = _domain_from_url(url)
        if preferred_sites and domain not in preferred_sites:
            continue
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        score, matched = _score_news_relevance(url, title, text, interests)
        preferred_cache.append((score + random.random() * 0.03, matched, url, title, text))
    preferred_cache.sort(key=lambda x: x[0], reverse=True)

    preferred_sources = []
    for url in news_sources or []:
        url = str(url).strip()
        if not url or url in seen_urls:
            continue
        domain = _domain_from_url(url)
        if preferred_sites and domain not in preferred_sites:
            continue
        score, matched = _score_news_relevance(url, "", "", interests)
        preferred_sources.append((score + random.random() * 0.03, matched, url))
    preferred_sources.sort(key=lambda x: x[0], reverse=True)

    if random.random() < direct_visit_ratio and preferred_cache:
        score, matched, url, title, text = preferred_cache[0]
        return {
            "mode": "direct_source",
            "query": "",
            "engine": "",
            "url": url,
            "title": title,
            "content": text,
            "score": score,
            "matched": matched,
        }
    if random.random() < direct_visit_ratio and preferred_sources:
        score, matched, url = preferred_sources[0]
        text = fetch_news_excerpt(
            url,
            timeout=int(config.get("content_timeout", config.get("timeout", 8))),
            max_chars=int(config.get("content_max_chars", 2000)),
            user_agent=str(config.get("user_agent", "GAWorld/1.0")),
        )
        if text:
            return {
                "mode": "direct_source",
                "query": "",
                "engine": "",
                "url": url,
                "title": "",
                "content": text,
                "score": score,
                "matched": matched,
            }

    query = _build_search_query(agent, used_queries=used_queries)
    if preferred_sites and random.random() < 0.85:
        query = f"{query} site:{random.choice(preferred_sites)}"
    return _web_search_target(
        agent=agent,
        query=query,
        interests=interests,
        preferred_sites=preferred_sites,
        seen_urls=seen_urls,
        config=config,
    )


def _web_search_target(
    *,
    agent: dict[str, Any],
    query: str,
    interests: list[str],
    preferred_sites: list[str],
    seen_urls: set[str] | None,
    config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    config = config or {}
    seen_urls = seen_urls or set()
    engine, results = web_search(query, config=config)
    if not results:
        return None
    ranked = []
    timeout = int(config.get("content_timeout", config.get("timeout", 8)))
    max_chars = int(config.get("content_max_chars", 2000))
    user_agent = str(config.get("user_agent", "GAWorld/1.0"))
    for item in results:
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        if _domain_from_url(url) in _SNIPPET_ONLY_DOMAINS:
            excerpt = ""
        else:
            excerpt = fetch_news_excerpt(url, timeout=timeout, max_chars=max_chars, user_agent=user_agent)
        content = excerpt or snippet
        if not content:
            continue
        score, matched = _score_news_relevance(url, title, content, interests)
        if preferred_sites and _domain_from_url(url) in preferred_sites:
            score += 0.9
        ranked.append((score + random.random() * 0.03, matched, url, title, content))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0], reverse=True)
    score, matched, url, title, content = ranked[0]
    return {
        "mode": "web_search",
        "query": query,
        "engine": engine,
        "url": url,
        "title": title,
        "content": content,
        "score": score,
        "matched": matched,
    }


# ---------------------------------------------------------------------------
# 3. Acquisition pipelines (each writes one memory record + log line)
# ---------------------------------------------------------------------------

def info_seek_and_store(
    agent: dict[str, Any],
    day: int | None = None,
    time_str: str | None = None,
    news_cache: list[dict[str, Any]] | None = None,
    news_sources: list[str] | None = None,
    preferred_sites: list[str] | None = None,
    seen_urls: set[str] | None = None,
    used_queries: set[str] | None = None,
    keywords: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[str | None, str | None, str, str]:
    config = config or {}
    target = _choose_info_target(
        agent=agent,
        news_cache=news_cache or [],
        news_sources=news_sources or [],
        preferred_sites=preferred_sites or [],
        seen_urls=seen_urls or set(),
        used_queries=used_queries or set(),
        config=config,
        keywords=keywords,
    )
    if not target:
        return None, None, "", ""

    title = target.get("title", "")
    url = target.get("url", "")
    content = str(target.get("content", "")).strip()
    if not url or not content:
        return None, None, "", ""
    mode = target.get("mode", "direct_source")
    query = target.get("query", "")
    engine = target.get("engine", "")

    # Note: legacy source joins with literal "\n" (backslash-n), not a real
    # newline. Almost certainly a bug-in-source, but per Surgical Changes we
    # preserve it verbatim — fixing it would silently shift LLM prompt format.
    profile_text = "\\n".join([
        f"姓名：{agent.get('name', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "news"),
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    prompt = f"""
你是{agent['name']}。
角色资料：
{profile_text}

你本次的信息获取方式：{mode}
检索词：{query or "N/A"}
来源：{title or "N/A"} ({url})
内容摘要：
{content}

请用1-2句写出你为何会关注这条信息，以及你的看法。
"""
    thought = _llm_providers.call_llm(prompt, task="info_seek_reaction", agent_id=agent["id"]).strip()
    if not thought:
        thought = "这条信息符合我近期关注，我会继续观察。"

    memory_excerpt_chars = int(config.get("memory_excerpt_chars", 700))
    memory_excerpt = content
    if memory_excerpt_chars > 0 and len(memory_excerpt) > memory_excerpt_chars:
        memory_excerpt = memory_excerpt[:memory_excerpt_chars].rsplit(" ", 1)[0].strip() if " " in memory_excerpt else memory_excerpt[:memory_excerpt_chars]
        memory_excerpt = f"{memory_excerpt}..."

    stamp = f"Day {day} {time_str}" if day and time_str else "InfoSeek"
    preferred_text = ", ".join(preferred_sites or []) if preferred_sites else "N/A"
    memory_entry = (
        f"[{stamp}] 信息获取：{mode}\n"
        f"偏好站点：{preferred_text}\n"
        f"检索词：{query or 'N/A'}\n"
        f"来源：{title or 'N/A'} ({url})\n"
        f"内容：{memory_excerpt}\n"
        f"想法：{thought}"
    )
    agent["memory"].append(memory_entry)
    save_agent_memory(agent)
    vector_db_add_entry(agent["id"], "info_seek", memory_entry, sim_day=day, sim_time=time_str or "info_seek")

    log = f"""
[InfoSeek {agent['name']} @ {time_str}]
Mode: {mode}
Query: {query or "N/A"}
Engine: {engine or "N/A"}
PreferredSites: {preferred_text}
Result: {title or "N/A"}
URL: {url}
MatchedInterests: {", ".join(target.get("matched", [])) if target.get("matched") else "N/A"}
RelevanceScore: {float(target.get("score", 0.0)):.2f}
"""
    return memory_entry, log, url, query


def _estimate_curiosity(agent: dict[str, Any]) -> float:
    state = agent.get("state", {})
    platform_dependence = float(state.get("platform_dependence", 0.5))
    risk_preference = float(state.get("risk_preference", 0.5))
    text = " ".join(
        str(agent.get(k, ""))
        for k in ("personality", "daily_life", "values", "job")
    )
    boosts = {
        "好奇": 0.25,
        "探索": 0.20,
        "新鲜": 0.12,
        "学习": 0.10,
        "研究": 0.10,
        "科技": 0.08,
        "关注": 0.06,
        "trend": 0.06,
        "research": 0.10,
    }
    dampens = {
        "保守": 0.12,
        "封闭": 0.15,
        "排斥": 0.10,
        "抗拒": 0.10,
    }
    score = 0.20 + 0.45 * platform_dependence + 0.20 * risk_preference
    for key, value in boosts.items():
        if key in text.lower() or key in text:
            score += value
    for key, value in dampens.items():
        if key in text:
            score -= value
    return max(0.05, min(0.98, score))


def _build_search_query(
    agent: dict[str, Any], used_queries: set[str] | None = None
) -> str:
    used_queries = used_queries or set()
    interests = _extract_interest_keywords(agent, max_items=16)
    if not interests:
        interests = ["本地新闻", "行业动态", "公共政策"]
    name = agent.get("name", "该居民")
    job = str(agent.get("job", "")).strip()
    seeds = []
    for kw in interests[:8]:
        seeds.extend(
            [
                f"{kw} 最新消息",
                f"{kw} 今日新闻",
                f"{kw} 趋势",
            ]
        )
        if job:
            seeds.append(f"{job} {kw} 资讯")
    random.shuffle(seeds)
    for q in seeds:
        if q not in used_queries:
            return q
    return f"{name} 关注话题 今日新闻"


def _extract_google_results(html_text: str, max_results: int = 5) -> list[dict[str, str]]:
    results = []
    blocks = re.findall(r'(?is)<a[^>]+href="(/url\?q=[^"]+)"[^>]*>(.*?)</a>', html_text)
    for href, anchor in blocks:
        qs = parse_qs(urlparse(href).query)
        raw_url = (qs.get("q") or [""])[0]
        raw_url = unquote(raw_url).strip()
        if not raw_url.startswith("http"):
            continue
        title = _normalize_text(_strip_html(anchor))
        if len(title) < 6:
            continue
        results.append({"url": raw_url, "title": title, "snippet": ""})
        if len(results) >= max_results:
            break
    return results


def _extract_baidu_results(html_text: str, max_results: int = 5) -> list[dict[str, str]]:
    results = []
    blocks = re.findall(r'(?is)<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>', html_text)
    for href, anchor in blocks:
        url = unquote(href).strip()
        if not url.startswith("http"):
            continue
        title = _normalize_text(_strip_html(anchor))
        if len(title) < 4:
            continue
        results.append({"url": url, "title": title, "snippet": ""})
        if len(results) >= max_results:
            break
    return results


def _extract_bing_results(html_text: str, max_results: int = 5) -> list[dict[str, str]]:
    results = []
    blocks = re.findall(r'(?is)<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>.*?</li>', html_text)
    for block in blocks:
        link = re.search(r'(?is)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>\s*</h2>', block)
        if not link:
            continue
        url = unquote(link.group(1)).strip()
        if not url.startswith("http"):
            continue
        title = _normalize_text(_strip_html(link.group(2)))
        snippet_match = re.search(r'(?is)<p[^>]*>(.*?)</p>', block)
        snippet = _normalize_text(_strip_html(snippet_match.group(1))) if snippet_match else ""
        if len(title) < 4:
            continue
        results.append({"url": url, "title": title, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _extract_generic_results(html_text: str, max_results: int = 5) -> list[dict[str, str]]:
    results = []
    links = re.findall(r'(?is)<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html_text)
    for href, anchor in links:
        title = _normalize_text(_strip_html(anchor))
        if len(title) < 10:
            continue
        results.append({"url": unquote(href).strip(), "title": title, "snippet": ""})
        if len(results) >= max_results:
            break
    return results


def web_search(
    query: str, config: dict[str, Any] | None = None
) -> tuple[str, list[dict[str, str]]]:
    config = config or {}
    engines = config.get("engines", ["google", "baidu", "bing"])
    timeout = int(config.get("timeout", 8))
    max_results = int(config.get("max_results", 4))
    user_agent = str(config.get("user_agent", "GAWorld/1.0"))
    search_urls = {
        "google": f"https://www.google.com/search?q={quote_plus(query)}&hl=zh-CN",
        "baidu": f"https://www.baidu.com/s?wd={quote_plus(query)}",
        "bing": f"https://www.bing.com/search?q={quote_plus(query)}",
    }
    extractors = {
        "google": _extract_google_results,
        "baidu": _extract_baidu_results,
        "bing": _extract_bing_results,
    }
    headers = {"User-Agent": user_agent}
    for engine in engines:
        engine_name = str(engine).lower()
        if engine_name in ("x", "x_mcp", "twitter"):
            x_results = x_mcp_search(query, config=config)
            if x_results:
                return "x", x_results
            continue
        search_url = search_urls.get(engine_name)
        if not search_url:
            continue
        try:
            resp = requests.get(search_url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            html_text = resp.text or ""
        except requests.RequestException:
            continue
        extractor = extractors.get(str(engine).lower(), _extract_generic_results)
        results = extractor(html_text, max_results=max_results)
        if not results:
            results = _extract_generic_results(html_text, max_results=max_results)
        if results:
            return engine, results
    return "", []


def search_web_and_store(
    agent: dict[str, Any],
    query: str,
    day: int | None = None,
    time_str: str | None = None,
    config: dict[str, Any] | None = None,
    seen_urls: set[str] | None = None,
) -> tuple[str | None, str | None, str]:
    config = config or {}
    seen_urls = seen_urls or set()
    engine, results = web_search(query, config=config)
    if not results:
        return None, None, ""
    interests = _extract_interest_keywords(agent)
    timeout = int(config.get("content_timeout", config.get("timeout", 8)))
    max_chars = int(config.get("content_max_chars", 2000))
    user_agent = str(config.get("user_agent", "GAWorld/1.0"))

    ranked = []
    for item in results:
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        if _domain_from_url(url) in _SNIPPET_ONLY_DOMAINS:
            excerpt = ""
        else:
            excerpt = fetch_news_excerpt(
                url,
                timeout=timeout,
                max_chars=max_chars,
                user_agent=user_agent,
            )
        candidate_text = excerpt or snippet
        if not candidate_text:
            continue
        score, matched = _score_news_relevance(url, title, candidate_text, interests)
        ranked.append((score + random.random() * 0.03, matched, url, title, candidate_text))

    if not ranked:
        return None, None, ""

    ranked.sort(key=lambda x: x[0], reverse=True)
    score, matched, url, title, content = ranked[0]
    # Note: legacy source joins with literal "\n" (backslash-n), not a real
    # newline. Almost certainly a bug-in-source, but per Surgical Changes we
    # preserve it verbatim — fixing it would silently shift LLM prompt format.
    profile_text = "\\n".join([
        f"姓名：{agent.get('name', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "news"),
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    prompt = f"""
你是{agent['name']}。
角色资料：
{profile_text}

你主动搜索了：{query}
搜索结果标题：{title}
内容摘要：
{content}

请用1-2句写出你为何关注这个信息，以及你的看法。
"""
    thought = _llm_providers.call_llm(prompt, task="web_search_reaction", agent_id=agent["id"]).strip()
    if not thought:
        thought = "这条信息与我关注的话题相关，我会继续跟进。"

    memory_excerpt_chars = int(config.get("memory_excerpt_chars", 700))
    memory_excerpt = content.strip()
    if memory_excerpt_chars > 0 and len(memory_excerpt) > memory_excerpt_chars:
        memory_excerpt = memory_excerpt[:memory_excerpt_chars].rsplit(" ", 1)[0].strip() if " " in memory_excerpt else memory_excerpt[:memory_excerpt_chars]
        memory_excerpt = f"{memory_excerpt}..."

    stamp = f"Day {day} {time_str}" if day and time_str else "WebSearch"
    memory_entry = (
        f"[{stamp}] 主动搜索：{query}\n"
        f"搜索引擎：{engine or 'unknown'}\n"
        f"结果：{title} ({url})\n"
        f"内容：{memory_excerpt}\n"
        f"想法：{thought}"
    )
    agent["memory"].append(memory_entry)
    save_agent_memory(agent)
    vector_db_add_entry(agent["id"], "web_search", memory_entry, sim_day=day, sim_time=time_str or "search")

    log = f"""
[WebSearch {agent['name']} @ {time_str}]
Query: {query}
Engine: {engine or "N/A"}
Result: {title}
URL: {url}
MatchedInterests: {", ".join(matched) if matched else "N/A"}
RelevanceScore: {score:.2f}
"""
    return memory_entry, log, url


def read_news_and_store(
    agent: dict[str, Any],
    source_url: str,
    day: int | None = None,
    time_str: str | None = None,
    config: dict[str, Any] | None = None,
    excerpt: str | None = None,
    title: str | None = None,
) -> tuple[str | None, str | None]:
    config = config or {}
    if not excerpt:
        excerpt = fetch_news_excerpt(
            source_url,
            timeout=int(config.get("timeout", 8)),
            max_chars=int(config.get("max_chars", 2000)),
            user_agent=str(config.get("user_agent", "GAWorld/1.0")),
        )
    if not excerpt:
        return None, None
    # Legacy literal "\n" preserved verbatim — see comment in info_seek_and_store.
    profile_text = "\\n".join([
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "news"),
        f"日常生活与习惯：{agent.get('daily_life', '')}",
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    prompt = f"""
你是{agent['name']}。
角色资料：
{profile_text}

你刚阅读了一条新闻/社交媒体内容（节选）：
{excerpt}

请用1-2句写出你的反应，尽量体现角色身份与态度。
"""
    response = _llm_providers.call_llm(prompt, task="news_reaction", agent_id=agent["id"]).strip()
    if not response:
        return None, None
    stamp = f"Day {day} {time_str}" if day and time_str else "NewsRead"
    title_text = f" 标题：{title}" if title else ""
    memory_excerpt_chars = int(config.get("memory_excerpt_chars", 600))
    memory_excerpt = excerpt.strip()
    if memory_excerpt_chars > 0 and len(memory_excerpt) > memory_excerpt_chars:
        memory_excerpt = memory_excerpt[:memory_excerpt_chars].rsplit(" ", 1)[0].strip() if " " in memory_excerpt else memory_excerpt[:memory_excerpt_chars]
        memory_excerpt = f"{memory_excerpt}..."
    memory_entry = (
        f"[{stamp}] 来源：{source_url}{title_text}\n"
        f"内容：{memory_excerpt}\n"
        f"想法：{response}"
    )
    agent["memory"].append(memory_entry)
    save_agent_memory(agent)
    vector_db_add_entry(agent["id"], "news", memory_entry, sim_day=day, sim_time=time_str or "news")
    log = f"""
[NewsRead {agent['name']} @ {time_str}]
Source: {source_url}
Title: {title or "N/A"}
Response: {response}
"""
    return memory_entry, log


__all__ = [
    "fetch_social_page_profile_source",
    "load_news_sources",
    "load_news_cache",
    "update_news_cache",
    "_extract_interest_keywords",
    "_score_news_relevance",
    "choose_news_for_agent",
    "_domain_from_url",
    "_build_agent_preferred_sites",
    "_choose_info_target",
    "info_seek_and_store",
    "_estimate_curiosity",
    "_build_search_query",
    "_extract_google_results",
    "_extract_baidu_results",
    "_extract_bing_results",
    "_extract_generic_results",
    "web_search",
    "search_web_and_store",
    "read_news_and_store",
]
