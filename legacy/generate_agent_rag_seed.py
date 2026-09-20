import argparse
import json
import re
from datetime import datetime

import pandas as pd

import generative_city_sim as sim
from memory_store import load_agent_memory, save_agent_memory, vector_db_add_entry


def _parse_agent_ids(args, df):
    ids = set()
    if args.all:
        ids.update(int(x) for x in df["id"].dropna().tolist())
    if args.agent_id:
        ids.update(int(x) for x in args.agent_id)
    if args.agent_ids:
        for token in str(args.agent_ids).split(","):
            text = token.strip()
            if text:
                ids.add(int(text))
    return sorted(ids)


def _extract_keywords(agent, max_items=8):
    seed = " ".join(
        str(agent.get(k, ""))
        for k in ("job", "personality", "daily_life", "values", "living", "residence")
    )
    tokens = re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}", seed)
    stop = {"生活", "工作", "日常", "价值观", "性格", "城市", "社会", "事务", "today", "with", "from"}
    out = []
    seen = set()
    for token in tokens:
        t = token.lower().strip()
        if not t or t in stop or len(t) < 2:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(token)
        if len(out) >= max_items:
            break
    return out


def _has_external_info(memory):
    for item in memory:
        if str(item).strip().startswith("[额外信息"):
            return True
    return False


def _heuristic_profile_items(agent, count=3, max_chars=280):
    state = agent.get("state", {})
    living = str(agent.get("living") or agent.get("residence") or "").strip()
    job = str(agent.get("job", "")).strip()
    personality = str(agent.get("personality", "")).strip()
    daily_life = str(agent.get("daily_life", "")).strip()
    values = str(agent.get("values", "")).strip()
    stress = float(state.get("stress", 0.5))
    econ_security = float(state.get("econ_security", 0.5))

    candidates = []
    if living:
        candidates.append(f"长期在{living}活动，对本地通勤、租住成本和生活服务可达性有稳定经验。")
    if job:
        candidates.append(f"持续关注“{job}”相关的岗位变化、技能要求与收入波动，并据此调整工作策略。")
    if personality:
        candidates.append(f"在熟人眼中，通常表现为：{personality}")
    if daily_life:
        candidates.append(f"稳定的生活习惯是：{daily_life}")
    if values:
        candidates.append(f"长期决策偏好：{values}")
    if stress >= 0.6 or econ_security <= 0.45:
        candidates.append("对生活成本、收入稳定性和风险事件更敏感，做决策时会优先考虑财务安全。")
    else:
        candidates.append("倾向于在工作效率、生活质量和社交投入之间做平衡，不追求极端策略。")

    out = []
    seen = set()
    for text in candidates:
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = cleaned[:max_chars]
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
        if len(out) >= max(1, int(count)):
            break
    return out


def _build_queries(agent, max_items=4):
    keywords = _extract_keywords(agent, max_items=8)
    job = str(agent.get("job", "")).strip()
    defaults = ["本地就业", "生活成本", "公共政策", "行业动态"]
    seeds = keywords if keywords else defaults
    queries = []
    for kw in seeds:
        queries.append(f"{kw} 最新消息")
        if job:
            queries.append(f"{job} {kw} 资讯")
        if len(queries) >= max_items:
            break
    if not queries:
        queries = defaults[:max_items]
    return queries[:max_items]


def _web_item_to_memory(agent, title, content, url, max_chars=280):
    job = str(agent.get("job", "")).strip() or "其职业"
    snippet = re.sub(r"\s+", " ", content).strip()
    snippet = snippet[: min(120, len(snippet))]
    title_text = title.strip() if title else "该类资讯"
    text = f"会长期关注“{title_text}”这类信息，因为它可能影响{job}相关机会、生活成本预期与风险判断。"
    if snippet:
        text = f"{text} 线索：{snippet}"
    return text[:max_chars], url


def _collect_web_items(agent, web_items=1, max_chars=280):
    results = []
    seen_urls = set()
    search_cfg = dict(sim.INFO_SEEK_CONFIG)
    search_cfg["max_results"] = max(3, int(search_cfg.get("max_results", 4)))
    for query in _build_queries(agent, max_items=max(3, web_items * 3)):
        engine, rows = sim.web_search(query, config=search_cfg)
        if not rows:
            continue
        for item in rows:
            url = str(item.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = str(item.get("title", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            excerpt = sim.fetch_news_excerpt(
                url,
                timeout=int(search_cfg.get("content_timeout", search_cfg.get("timeout", 8))),
                max_chars=int(search_cfg.get("content_max_chars", 1200)),
                user_agent=str(search_cfg.get("user_agent", "GAWorld/1.0")),
            )
            content = excerpt or snippet
            if not content:
                continue
            mem_text, src_url = _web_item_to_memory(agent, title, content, url, max_chars=max_chars)
            results.append(
                {
                    "text": mem_text,
                    "timestamp": datetime.now().strftime("%Y-%m-%d"),
                    "source": f"seed_web:{engine or 'web'}:{sim._domain_from_url(src_url) or 'unknown'}",
                }
            )
            if len(results) >= web_items:
                return results
    return results


def _insert_external_info(agent, text, timestamp=None, source="seed_profile"):
    payload = sim._compose_external_info_text(text, timestamp=timestamp, source=source)
    if not payload:
        return ""
    memory = agent.setdefault("memory", [])
    if payload in memory:
        return ""
    memory.append(payload)
    vector_db_add_entry(agent["id"], "external_info", payload, sim_day=None, sim_time=timestamp or "external")
    return payload


def _generate_for_agent(agent, profile_items, web_items, use_web, force):
    inserted = []
    existing = list(agent.get("memory", []))
    if (not force) and _has_external_info(existing):
        return inserted, "skipped_existing"

    for text in _heuristic_profile_items(agent, count=profile_items):
        payload = _insert_external_info(
            agent,
            text=text,
            timestamp=None,
            source="seed_profile",
        )
        if payload:
            inserted.append(payload)

    if use_web and web_items > 0:
        web_rows = _collect_web_items(agent, web_items=web_items)
        for row in web_rows:
            payload = _insert_external_info(
                agent,
                text=row["text"],
                timestamp=row.get("timestamp"),
                source=row.get("source", "seed_web"),
            )
            if payload:
                inserted.append(payload)
    save_agent_memory(agent)
    return inserted, "ok"


def generate_for_runtime_agent(
    agent,
    profile_items=3,
    web_items=1,
    use_web=True,
    force=False,
):
    """
    Reusable entry for runtime bootstrap from other modules.
    Returns (inserted_payloads, status).
    """
    return _generate_for_agent(
        agent=agent,
        profile_items=max(1, int(profile_items)),
        web_items=max(0, int(web_items)),
        use_web=bool(use_web),
        force=bool(force),
    )


def main():
    parser = argparse.ArgumentParser(description="Generate profile-based RAG seeds for one or multiple agents.")
    parser.add_argument("--agent-id", type=int, action="append", help="Single agent id, can repeat.")
    parser.add_argument("--agent-ids", default="", help="Comma-separated agent ids, e.g. 1,2,3")
    parser.add_argument("--all", action="store_true", help="Generate for all agents in csv.")
    parser.add_argument("--profile-items", type=int, default=3, help="How many profile-based items per agent.")
    parser.add_argument("--web-items", type=int, default=1, help="How many web-enhanced items per agent.")
    parser.add_argument("--no-web", action="store_true", help="Disable web search based seeding.")
    parser.add_argument("--force", action="store_true", help="Generate even if external_info already exists.")
    parser.add_argument("--csv-path", default=sim.CSV_PATH, help="Agent csv path.")
    parser.add_argument("--json-report", default="", help="Optional output report path.")
    args = parser.parse_args()

    df = pd.read_csv(args.csv_path)
    target_ids = _parse_agent_ids(args, df)
    if not target_ids:
        raise SystemExit("No agent selected. Use --agent-id/--agent-ids/--all.")

    city_map = sim.load_city_map(sim.MAP_PATH)
    summary = []
    total_inserted = 0
    for agent_id in target_ids:
        if int(agent_id) not in set(int(x) for x in df["id"].dropna().tolist()):
            summary.append({"agent_id": int(agent_id), "status": "not_found", "inserted": 0})
            continue
        agent = sim.build_agent(int(agent_id), df, city_map=city_map)
        agent["memory"] = load_agent_memory(agent["id"])
        inserted, status = _generate_for_agent(
            agent=agent,
            profile_items=max(1, int(args.profile_items)),
            web_items=max(0, int(args.web_items)),
            use_web=not args.no_web,
            force=bool(args.force),
        )
        total_inserted += len(inserted)
        summary.append(
            {
                "agent_id": int(agent_id),
                "name": agent.get("name", ""),
                "status": status,
                "inserted": len(inserted),
                "memory_total": len(agent.get("memory", [])),
            }
        )
        print(
            f"agent={agent_id} name={agent.get('name', '')} status={status} "
            f"inserted={len(inserted)} memory_total={len(agent.get('memory', []))}"
        )

    print(f"done: agents={len(target_ids)} inserted_total={total_inserted}")
    if args.json_report:
        report = {
            "agents": summary,
            "inserted_total": total_inserted,
            "profile_items": int(args.profile_items),
            "web_items": int(args.web_items),
            "use_web": not args.no_web,
            "force": bool(args.force),
        }
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"report={args.json_report}")


if __name__ == "__main__":
    main()
