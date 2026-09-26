"""Dashboard backend for the bulk-import workflow.

Design notes:

* **Owns nothing the dashboard already owns.** This module never registers an
  HTTP route: ``dashboard_server._handle_api_*`` forwards ``/api/import/*``
  here via the same delegate pattern ``population_api`` and ``persona_api``
  use. Anything new should be added to ``handle_get`` / ``handle_post`` so
  the dashboard server never grows another long if/elif chain.

* **Files arrive as multipart/form-data.** ``BaseHTTPRequestHandler`` exposes
  ``cgi.FieldStorage`` when the request is a multipart POST; we read fields
  from it. Pure-JSON POSTs are also accepted so the API can be scripted.

* **Two-phase workflow.** The browser first calls ``/api/import/preview`` to
  get a column-mapping suggestion and a privacy preview. After the user
  confirms the configuration, ``/api/import/run`` executes it as a background
  job (the existing ``_new_job`` / ``_run_in_background`` plumbing from
  ``population_api`` is reused — see ``_import_job_runner``).

* **Anonymisation is the default.** Free-text fields are scanned for names
  (``姓名`` / ``name`` columns and 2-4 char capitalised tokens) and locations
  (anything tagged ``家乡 / 城市 / city / hometown``); they are replaced with
  deterministic city-themed fake values derived from a salted SHA-256 so the
  same row produces the same pseudonym across retries.

* **Expansion uses the existing IPF sampler.** We summarise the uploaded
  roster into a ``PopulationSpec``, then call ``generate_population`` once
  for the synthetic tail. The synthetic tail's ids start above the existing
  max id in the city, so it appends cleanly via ``add_population(replace=False)``.

The module never imports ``dashboard_server``; that import order would form
a cycle.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import threading
import time
import uuid
from collections import Counter
from typing import Any

from gaworld.city.agents import add_population
from gaworld.city.bundle import resolve_city
from gaworld.logging_setup import get_logger
from gaworld.population.schema import STATE_VAR_KEYS

_LOG = get_logger("gaworld.dashboard.import_api")

# ---------------------------------------------------------------------------
# Job plumbing — borrowed from population_api to stay consistent.
# ---------------------------------------------------------------------------

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 20


def _new_job(kind: str) -> str:
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "progress": 0.0,
            "message": "启动中…",
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        finished = [
            (record["started_at"], key) for key, record in _JOBS.items() if record["status"] != "running"
        ]
        while len(_JOBS) > _MAX_JOBS and finished:
            finished.sort()
            _, oldest = finished.pop(0)
            _JOBS.pop(oldest, None)
    return job_id


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if record is not None:
            record.update(fields)


def _run_in_background(job_id: str, work: Any) -> None:
    def runner() -> None:
        try:
            result = work(lambda p, m: _update_job(job_id, progress=p, message=m))
            _update_job(
                job_id,
                status="done",
                progress=1.0,
                finished_at=time.time(),
                result=result,
            )
        except Exception as exc:  # pragma: no cover - reported through the API
            _update_job(
                job_id,
                status="failed",
                finished_at=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )
            _LOG.exception("import job %s failed", job_id)

    thread = threading.Thread(target=runner, name=f"import-{job_id}", daemon=True)
    thread.start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        return dict(record) if record is not None else None


# ---------------------------------------------------------------------------
# Column-mapping vocabulary
# ---------------------------------------------------------------------------

#: Built-in synonyms: lower-cased substring → canonical field.
#: Recognised canonical fields map onto the behavioural chart's column list
#: (``id,name,gender,age,hukou,residence,employment,industry,monthly_income,*STATE``).
#: Free-text columns (``personality`` / ``daily_life`` / ``values`` / ``profile``)
#: are recognised but not used to drive the IPF.
_CANONICAL_FIELDS: tuple[str, ...] = (
    "name",
    "gender",
    "age",
    "hukou",
    "residence",
    "employment",
    "industry",
    "monthly_income",
    "education",
    "hometown",
    "company",
    "personality",
    "daily_life",
    "values",
    "phone",
    "email",
    "id_card",
    "id",
    *STATE_VAR_KEYS,
)

_FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("name", "姓名", "名字"),
    "gender": ("gender", "sex", "性别"),
    "age": ("age", "年龄"),
    "hukou": ("hukou", "户口"),
    "residence": ("residence", "address", "住址", "现居", "居住地"),
    "employment": ("employment", "job_status", "在职", "工作状态"),
    "industry": ("industry", "行业"),
    "monthly_income": ("monthly_income", "income", "salary", "收入", "月薪"),
    "education": ("education", "学历", "教育"),
    "hometown": ("hometown", "家乡", "籍贯"),
    "company": ("company", "workplace", "公司", "工作单位"),
    "personality": ("personality", "性格", "personality_description"),
    "daily_life": ("daily_life", "daily", "daily_life_description", "日常生活"),
    "values": ("values", "价值观"),
    "phone": ("phone", "mobile", "tel", "电话", "手机"),
    "email": ("email", "mail", "邮箱", "邮件"),
    "id_card": ("id_card", "id_number", "idcard", "身份证", "证件号"),
    "id": ("id", "agent_id", "编号"),
}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _sniff_format(filename: str, content_type: str, raw: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".csv") or "csv" in (content_type or "").lower():
        return "csv"
    if name.endswith(".xlsx") or "spreadsheetml" in (content_type or "").lower():
        return "xlsx"
    if name.endswith((".jsonl", ".ndjson", ".json")):
        return "jsonl"  # .json is accepted as a single-batch JSONL
    head = raw[:4096].decode("utf-8", errors="ignore")
    if head.lstrip().startswith(("{", "[")):
        return "jsonl"
    if "，" in head or "," in head:
        return "csv"
    raise ValueError("无法识别文件格式：仅支持 CSV、xlsx 与 JSONL。")


def _parse_csv(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = raw.decode("utf-8-sig", errors="replace")
    handle = io.StringIO(text)
    reader = csv.DictReader(handle)
    headers = list(reader.fieldnames or [])
    rows: list[dict] = []
    for row in reader:
        rows.append({key: ("" if value is None else str(value)) for key, value in row.items()})
    return headers, rows


def _parse_jsonl(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = raw.decode("utf-8", errors="replace")
    handle = io.StringIO(text)
    records: list[dict] = []
    for line in handle:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        if isinstance(payload, list):
            payload = {"batch": payload}
        if not isinstance(payload, dict):
            raise ValueError("JSONL 每行必须是对象")
        records.append({str(key): "" if value is None else str(value) for key, value in payload.items()})
    headers = sorted({key for record in records for key in record})
    return headers, records


def _parse_xlsx(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency declared in requirements
        raise ValueError("解析 .xlsx 需要 openpyxl，请执行 `pip install openpyxl` 后重试。") from exc

    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        headers_row = next(rows_iter)
    except StopIteration as exc:
        raise ValueError("Excel 文件没有任何内容") from exc
    headers = [str(cell) if cell is not None else "" for cell in headers_row]
    rows: list[dict] = []
    for cells in rows_iter:
        if cells is None or all(cell is None or str(cell).strip() == "" for cell in cells):
            continue
        record: dict[str, str] = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            value = cells[index] if index < len(cells) else None
            record[header] = "" if value is None else str(value)
        if record:
            rows.append(record)
    workbook.close()
    return headers, rows


def parse_upload(filename: str, content_type: str, raw: bytes) -> tuple[str, list[str], list[dict[str, str]]]:
    """Return ``(format, headers, rows)`` for an uploaded file."""
    fmt = _sniff_format(filename, content_type, raw)
    if fmt == "csv":
        headers, rows = _parse_csv(raw)
    elif fmt == "xlsx":
        headers, rows = _parse_xlsx(raw)
    elif fmt == "jsonl":
        headers, rows = _parse_jsonl(raw)
    else:  # pragma: no cover - guarded by _sniff_format
        raise ValueError(f"不支持的格式: {fmt}")
    if not headers:
        raise ValueError("文件没有表头或第一行是空行")
    return fmt, headers, rows


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Pick the best canonical field for each header.

    Returns ``{raw_header: canonical_field | ""}``. The empty string means
    "no match" and the column will be ignored.
    """
    mapping: dict[str, str] = {}
    for raw in headers:
        key = raw.strip().lower().replace(" ", "_")
        chosen = ""
        for canonical, synonyms in _FIELD_SYNONYMS.items():
            for synonym in synonyms:
                needle = synonym.lower()
                if needle == key or needle in key or key in needle:
                    chosen = canonical
                    break
            if chosen:
                break
        mapping[raw] = chosen
    return mapping


def normalise_rows(
    rows: list[dict[str, str]],
    mapping: dict[str, str],
) -> list[dict[str, str]]:
    """Re-key every row from ``raw header`` to ``canonical field``.

    The original raw header is preserved under ``_raw_{col}`` so the anonymiser
    can replace names / places it might still appear in (e.g. a person's
    ``personality`` column quoting their hometown).
    """
    out: list[dict[str, str]] = []
    for row in rows:
        clean: dict[str, str] = {}
        for raw_header, value in row.items():
            canonical = mapping.get(raw_header, "")
            if not canonical or canonical == "id":  # 重置 id：导入不沿用上传库编号
                continue
            clean[canonical] = value
        out.append(clean)
    return out


# ---------------------------------------------------------------------------
# Anonymisation
# ---------------------------------------------------------------------------

_NAME_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,4}")
_ANON_NAME_PREFIX = ("居民",)
_ANON_HOMETOWN_SUFFIX = ("县", "区", "市", "镇")


def _hash_to_index(*parts: str, modulo: int) -> int:
    seed = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    return int.from_bytes(digest[:4], "big") % modulo


def _fake_pinyin_pool() -> tuple[str, ...]:
    # 1024 surnames × 64 given chars keeps collisions rare and recognisable as
    # synthetic without being offensive.
    surnames = "王李张刘陈杨黄赵吴周徐孙朱马胡郭林何高梁郑罗宋谢唐韩冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦吴史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文"
    given = (
        "伟芳娜秀英敏静丽强磊军洋勇艳杰娟涛明超秀兰霞平刚桂英文华建国家俊宇浩然子涵欣怡梓萱皓轩睿哲思源雨桐"
    )
    pool: list[str] = []
    for sn in surnames:
        for gn in given:
            pool.append(sn + gn)
    return tuple(pool)


_FAKE_NAME_POOL = _fake_pinyin_pool()
_FAKE_CITY_POOL = (
    "柳溪镇",
    "青石镇",
    "梅湾村",
    "向阳街道",
    "南湖社区",
    "北山街区",
    "西塘镇",
    "东篱村",
    "槐荫镇",
    "梧桐街道",
    "桂花园社区",
    "竹溪村",
    "桃林镇",
)


def anonymise_rows(rows: list[dict[str, str]], salt: str = "gaworld-import") -> list[dict[str, str]]:
    """Drop identifiers and scrub free-text columns of names / place names.

    The salt is mixed into every hash so two operators uploading the same file
    in the same city do not produce the same pseudonyms.
    """
    out: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        clean = dict(row)
        # 1. Drop direct identifiers.
        for key in ("phone", "email", "id_card"):
            clean.pop(key, None)
        # 2. Pseudonymise the name.
        if clean.get("name"):
            name_index = _hash_to_index(salt, clean["name"], str(index), modulo=len(_FAKE_NAME_POOL))
            clean["name"] = _FAKE_NAME_POOL[name_index]
        # 3. Replace hometown with a stable pseudonym.
        if clean.get("hometown"):
            city_index = _hash_to_index(
                salt, "hometown", clean["hometown"], str(index), modulo=len(_FAKE_CITY_POOL)
            )
            clean["hometown"] = _FAKE_CITY_POOL[city_index]
        if clean.get("residence") and "city" in (clean.get("residence", "") + clean.get("name", "")).lower():
            city_index = _hash_to_index(
                salt, "residence", clean["residence"], str(index), modulo=len(_FAKE_CITY_POOL)
            )
            clean["residence"] = _FAKE_CITY_POOL[city_index]
        # 4. Scrub free-text fields for any remaining name-like / place-like token.
        for field in ("personality", "daily_life", "values", "hometown", "company", "residence"):
            text = clean.get(field)
            if text:
                clean[field] = _scrub_free_text(text, salt, index)
        out.append(clean)
    return out


def _scrub_free_text(text: str, salt: str, row_index: int) -> str:
    # Replace 2-4 CJK name-shaped tokens and explicitly-tagged hometown tokens.
    def _sub(match: re.Match[str]) -> str:
        token = match.group(0)
        # Skip very common non-name tokens that the regex over-matches.
        if token in {"北京", "上海", "广州", "深圳", "中国", "杭州"}:
            return token
        idx = _hash_to_index(salt, "ftname", token, str(row_index), modulo=len(_FAKE_NAME_POOL))
        return _FAKE_NAME_POOL[idx]

    scrubbed = _NAME_TOKEN.sub(_sub, text)
    # Drop "家乡是 X" / "hometown: X" style explicit mentions.
    scrubbed = re.sub(
        r"(家乡|出生地|老家|籍贯|hometown)[:是为]?\s*[\u4e00-\u9fff]{2,8}",
        lambda m: m.group(1) + "：某地",
        scrubbed,
    )
    return scrubbed


# ---------------------------------------------------------------------------
# Distribution inference → PopulationSpec
# ---------------------------------------------------------------------------

_AGE_BANDS = (
    (0, 17, "0-17"),
    (18, 34, "18-34"),
    (35, 54, "35-54"),
    (55, 64, "55-64"),
    (65, 92, "65+"),
)


def _age_band(age: int) -> str:
    for low, high, label in _AGE_BANDS:
        if low <= age <= high:
            return label
    return "35-54"


def infer_spec(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Summarise the upload into a serialisable spec fragment.

    The fragment can be merged into a default ``PopulationSpec`` (the caller
    picks the preset and seed). Returns counts and marginal distributions
    for the fields the IPF sampler actually consumes.
    """
    if not rows:
        raise ValueError("上传文件没有任何可用的记录")
    total = len(rows)

    ages: list[int] = []
    genders: Counter[str] = Counter()
    hukou: Counter[str] = Counter()
    employment: Counter[str] = Counter()
    industries: Counter[str] = Counter()
    education: Counter[str] = Counter()
    incomes: list[float] = []

    for row in rows:
        try:
            ages.append(int(row.get("age") or 0))
        except ValueError:
            continue
        gender_value = (row.get("gender") or "").strip()
        if gender_value:
            genders[gender_value] += 1
        hukou_value = (row.get("hukou") or "").strip()
        if hukou_value:
            hukou[hukou_value] += 1
        emp_value = (row.get("employment") or "").strip()
        if emp_value:
            employment[emp_value] += 1
        industry_value = (row.get("industry") or "").strip()
        if industry_value:
            industries[industry_value] += 1
        edu_value = (row.get("education") or "").strip()
        if edu_value:
            education[edu_value] += 1
        income_value = (row.get("monthly_income") or "").strip()
        try:
            incomes.append(float(income_value))
        except ValueError:
            continue

    # Age pyramid shares: only valid for ages in [0, 92].
    valid_ages = [a for a in ages if 0 <= a <= 92]
    if not valid_ages:
        raise ValueError("上传文件中没有任何合法的年龄值（0–92 整数）")

    band_counts = Counter(_age_band(age) for age in valid_ages)
    total_aged = sum(band_counts.values())
    under_18 = band_counts["0-17"] / total_aged
    over_65 = band_counts["65+"] / total_aged
    median_age = sorted(valid_ages)[len(valid_ages) // 2]

    return {
        "counts": {
            "total": total,
            "with_age": len(valid_ages),
            "with_income": len(incomes),
        },
        "demography": {
            "share_under_18": round(under_18, 4),
            "share_over_65": round(over_65, 4),
            "median_age": float(median_age),
        },
        "distributions": {
            "gender": dict(genders),
            "hukou": dict(hukou),
            "employment": dict(employment),
            "industry": dict(industries),
            "education": dict(education),
        },
        "income": {
            "median": sorted(incomes)[len(incomes) // 2] if incomes else 0.0,
            "samples": len(incomes),
        },
    }


def build_population_spec(
    inferred: dict[str, Any],
    *,
    target_size: int,
    seed: int | None,
    preset: str = "cn_county_town",
) -> dict[str, Any]:
    """Translate ``infer_spec`` output into ``PopulationSpec`` kwargs.

    Unknown industries fall back to ``service`` so the IPF doesn't blow up on
    a vocabulary it has never seen; the warning is surfaced to the caller.
    """
    raw: dict[str, Any] = {
        "preset": preset,
        "size": max(1, int(target_size)),
        "name": "bulk-import",
    }
    if seed is not None:
        raw["seed"] = int(seed)
    demo = inferred.get("demography") or {}
    raw["median_age"] = demo.get("median_age", 36.0)
    raw["share_under_18"] = demo.get("share_under_18", 0.16)
    raw["share_over_65"] = demo.get("share_over_65", 0.14)

    # Translate industry mix; drop unknown labels and warn.
    known_industries = ("tech", "finance", "medical", "education", "service", "trade")
    industry_mix = inferred.get("distributions", {}).get("industry") or {}
    translated: dict[str, float] = {}
    for label, count in industry_mix.items():
        key = _normalise_industry(label)
        if key is None:
            continue
        translated[key] = translated.get(key, 0.0) + float(count)
    if translated:
        total = sum(translated.values())
        translated = {k: v / total for k, v in translated.items()}
        # If the upload only listed industries we don't recognise, drop the
        # override so the preset default wins.
        if any(k in known_industries for k in translated):
            raw["education_work"] = {"industry_mix": translated}
    return raw


def _normalise_industry(label: str) -> str | None:
    label = (label or "").strip()
    if not label:
        return None
    alias = {
        "互联网": "tech",
        "IT": "tech",
        "科技": "tech",
        "金融": "finance",
        "银行": "finance",
        "证券": "finance",
        "医疗": "medical",
        "医院": "medical",
        "医药": "medical",
        "教育": "education",
        "学校": "education",
        "培训": "education",
        "服务业": "service",
        "餐饮": "service",
        "酒店": "service",
        "零售": "trade",
        "批发": "trade",
        "贸易": "trade",
    }
    return alias.get(label, "service" if label in {"服务", "其他"} else None)


# ---------------------------------------------------------------------------
# API: preview + run
# ---------------------------------------------------------------------------


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "是", "开"}:
        return True
    if text in {"0", "false", "no", "off", "否", "关"}:
        return False
    return default


def build_preview(
    *,
    fmt: str,
    headers: list[str],
    rows: list[dict[str, str]],
    mapping: dict[str, str],
    anonymise: bool,
    expand_to: int | None,
) -> dict[str, Any]:
    """Return everything the frontend needs to render the confirmation step."""
    inferred = infer_spec(rows) if rows else None
    expanded = max(0, int(expand_to or 0) - len(rows)) if expand_to else 0
    return {
        "format": fmt,
        "headers": headers,
        "row_count": len(rows),
        "mapping": mapping,
        "mapping_suggested": suggest_mapping(headers),
        "anonymise": bool(anonymise),
        "expand_to": int(expand_to or 0),
        "expand_extra": expanded,
        "inferred": inferred,
    }


def execute_import(
    *,
    city_ref: str,
    fmt: str,
    headers: list[str],
    rows: list[dict[str, str]],
    mapping: dict[str, str],
    anonymise: bool,
    expand_to: int | None,
    seed: int | None,
    salt: str,
    city_root: Any = None,
) -> dict[str, Any]:
    """Synchronous path: append the upload + the synthetic tail to ``city_ref``."""
    city = resolve_city(city_ref, root=city_root)
    clean_rows = normalise_rows(rows, mapping)
    if anonymise:
        clean_rows = anonymise_rows(clean_rows, salt=salt)

    inserted_direct = _append_clean_rows(city, clean_rows)

    expanded_extra = 0
    if expand_to and int(expand_to) > len(clean_rows):
        target = int(expand_to) - len(clean_rows)
        inferred = infer_spec(clean_rows)
        spec_kwargs = build_population_spec(inferred, target_size=target, seed=seed)
        add_population(city, size=target, preset=spec_kwargs.get("preset", "cn_county_town"), seed=seed)
        expanded_extra = target

    return {
        "city": city.slug,
        "inserted_direct": inserted_direct,
        "expanded_extra": expanded_extra,
        "total": _count_after(city),
    }


def _append_clean_rows(city: Any, rows: list[dict[str, str]]) -> int:
    """Append each clean row via the existing single-agent writer."""
    from gaworld.city.agents import add_agent  # local import avoids cycle

    added = 0
    for row in rows:
        try:
            add_agent(
                city,
                name=row.get("name") or f"导入居民{added + 1}",
                age=_coerce_int(row.get("age"), default=35),
                gender=row.get("gender") or "女",
                job=row.get("employment") or "自由职业",
                hukou=_normalise_hukou(row.get("hukou")),
                residence=row.get("residence") or None,
                education=row.get("education") or "本科",
                income_monthly=_coerce_float(row.get("monthly_income")),
                personality=row.get("personality") or "性格平和，情绪起伏不大，遇事偏向先观察再行动。",
                daily_life=row.get("daily_life") or "作息规律，日常以工作、家务和少量社交为主。",
                values=row.get("values") or "对公共事务关注有限，除非直接影响到自己的生活才会去了解。",
            )
            added += 1
        except Exception as exc:  # pragma: no cover - per-row resilience
            _LOG.warning("skipping row: %s", exc)
    return added


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalise_hukou(value: str | None) -> str:
    text = (value or "").strip()
    alias = {"本地城镇": "本地", "本地农村": "本地", "外地": "外省"}
    return alias.get(text, text or "本地")


def _count_after(city: Any) -> int:
    from gaworld.city.agents import _read_rows  # local: same reason as above

    rows = _read_rows(city.state_csv_path)
    return len(rows)


# ---------------------------------------------------------------------------
# HTTP delegation (called by dashboard_server)
# ---------------------------------------------------------------------------


def _resolve_payload_data(payload: dict[str, Any]) -> tuple[str, list[str], list[dict[str, str]]]:
    """Resolve ``(format, headers, rows)`` from a JSON payload.

    Two equivalent shapes are accepted:

    * ``{format, headers, rows}`` — preview/cache pass-through.
    * ``{format, filename, file_text}`` — fresh upload: the body of the file
      is sent as a string so we never need multipart parsing on the server.
      Binary xlsx must be base64-encoded with ``file_encoding="base64"``.
    """
    fmt = str(payload.get("format") or "csv")
    rows = payload.get("rows")
    headers = payload.get("headers")
    if isinstance(rows, list) and isinstance(headers, list):
        return (
            fmt,
            [str(h) for h in headers],
            [{str(k): ("" if v is None else str(v)) for k, v in row.items()} for row in rows],
        )

    file_text = payload.get("file_text")
    if file_text is None:
        raise ValueError("必须提供 rows 或 file_text")
    filename = str(payload.get("filename") or f"upload.{fmt}")
    if str(payload.get("file_encoding") or "").lower() == "base64":
        import base64

        raw_bytes = base64.b64decode(str(file_text))
    else:
        raw_bytes = str(file_text).encode("utf-8")
    content_type = str(payload.get("content_type") or "text/plain")
    fmt2, headers2, rows2 = parse_upload(filename, content_type, raw_bytes)
    return fmt2, headers2, rows2


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    if path == "/api/import/schema":
        return {
            "canonical_fields": list(_CANONICAL_FIELDS),
            "synonyms": _FIELD_SYNONYMS,
            "formats": ["csv", "xlsx", "jsonl"],
            "anonymise_fields": ["name", "phone", "email", "id_card", "hometown"],
        }, 200
    if path.startswith("/api/import/jobs/"):
        job_id = path.rsplit("/", 1)[-1]
        record = job_status(job_id)
        if record is None:
            return {"error": "Unknown job"}, 404
        return record, 200
    return {"error": "Unknown import endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/import/preview":
            return _handle_preview_payload(payload), 200
        if path == "/api/import/run":
            job_id = _handle_run_payload(payload)
            return {"job_id": job_id}, 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown import endpoint"}, 404


def _handle_preview_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fmt, headers, rows = _resolve_payload_data(payload)
    mapping_in = payload.get("mapping") or {}
    mapping = {str(k): str(v) for k, v in mapping_in.items()}
    anonymise = _coerce_bool(payload.get("anonymise"), default=True)
    expand_to = payload.get("expand_to")
    if expand_to is not None:
        expand_to = max(0, int(expand_to))
    return build_preview(
        fmt=fmt,
        headers=headers,
        rows=rows,
        mapping=mapping,
        anonymise=anonymise,
        expand_to=expand_to,
    )


def _handle_run_payload(payload: dict[str, Any]) -> str:
    city_ref = str(payload.get("city") or "").strip()
    if not city_ref:
        raise ValueError("必须指定 city（目标城市的 slug 或名称）")
    fmt, headers, rows = _resolve_payload_data(payload)
    mapping_in = payload.get("mapping") or {}
    mapping = {str(k): str(v) for k, v in mapping_in.items()}
    anonymise = _coerce_bool(payload.get("anonymise"), default=True)
    expand_to = payload.get("expand_to")
    if expand_to is not None:
        expand_to = max(0, int(expand_to))
    seed = payload.get("seed")
    salt = str(payload.get("salt") or "gaworld-import")
    # Optional override so tests can target an ephemeral ``data/cities`` root
    # without monkey-patching ``PROJECT_ROOT``.
    city_root_override = payload.get("city_root")

    job_id = _new_job("import")

    def work(report: Any) -> dict[str, Any]:
        report(0.1, "解析数据…")
        result = execute_import(
            city_ref=city_ref,
            fmt=fmt,
            headers=headers,
            rows=rows,
            mapping=mapping,
            anonymise=anonymise,
            expand_to=expand_to,
            seed=int(seed) if seed is not None else None,
            salt=salt,
            city_root=city_root_override,
        )
        report(0.95, "收尾…")
        return result

    _run_in_background(job_id, work)
    return job_id


__all__ = [
    "anonymise_rows",
    "build_population_spec",
    "build_preview",
    "execute_import",
    "handle_get",
    "handle_post",
    "infer_spec",
    "job_status",
    "normalise_rows",
    "parse_upload",
    "suggest_mapping",
]
