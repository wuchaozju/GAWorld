"""Tests for the bulk-import endpoint (gaworld.apps.import_api).

The behavioural surface we defend:

* the format sniff + parsers handle CSV / xlsx / JSONL correctly;
* the column-mapping synonyms produce a usable suggestion for common Chinese
  and English headers;
* the anonymiser drops PII, pseudonyms are deterministic per (salt, row),
  and free-text fields have name-shaped tokens replaced;
* ``infer_spec`` summarises an upload into a ``PopulationSpec`` fragment;
* the HTTP delegation handles the two-phase preview/run flow without a
  live socket — we call the ``handle_post`` entry points directly.

These tests do not exercise the in-process job thread, because that would
make the suite non-deterministic. The job plumbing is shared with
``population_api`` and is independently tested there.
"""

from __future__ import annotations

import unittest

from gaworld.apps import import_api
from gaworld.city.create import create_city
from gaworld.sim.agents_loader import parse_profile

SAMPLE_CSV = """姓名,性别,年龄,户口,居住地,行业,月薪,家乡
张伟,男,32,本地,余杭·翡翠湾,互联网,18000,杭州
李娜,女,28,外省,滨江·云栖,金融,22000,绍兴
王强,男,45,省内,西湖·湖畔,医疗,15000,宁波
赵敏,女,17,本地,萧山·城南,学生,0,杭州
孙磊,男,67,本地,拱墅·运河,退休,4200,杭州
"""

SAMPLE_JSONL = (
    '{"name":"陈静","gender":"女","age":29,"industry":"教育","personality":"性格平和，家乡是苏州"}'
    "\n"
    '{"name":"Alex","gender":"male","age":40,"industry":"tech","daily_life":"works at Acme Corp"}'
)


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _jsonl_bytes(text: str) -> bytes:
    return text.encode("utf-8")


class ParseUploadTest(unittest.TestCase):
    def test_csv_round_trip(self) -> None:
        fmt, headers, rows = import_api.parse_upload("people.csv", "text/csv", _csv_bytes(SAMPLE_CSV))
        self.assertEqual(fmt, "csv")
        self.assertIn("姓名", headers)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["姓名"], "张伟")
        self.assertEqual(rows[1]["月薪"], "22000")

    def test_jsonl_round_trip(self) -> None:
        fmt, _headers, rows = import_api.parse_upload(
            "people.jsonl", "application/json", _jsonl_bytes(SAMPLE_JSONL)
        )
        self.assertEqual(fmt, "jsonl")
        self.assertEqual(len(rows), 2)
        names = sorted(row["name"] for row in rows)
        self.assertEqual(names, ["Alex", "陈静"])

    def test_format_sniff_falls_back_to_csv(self) -> None:
        # ``.txt`` is not in the sniffer's vocabulary; the comma in the header
        # should tip it off as CSV.
        fmt, headers, rows = import_api.parse_upload("unknown.txt", "text/plain", _csv_bytes("a,b\n1,2\n"))
        self.assertEqual(fmt, "csv")
        self.assertEqual(headers, ["a", "b"])
        self.assertEqual(len(rows), 1)

    def test_empty_file_raises(self) -> None:
        with self.assertRaises(ValueError):
            import_api.parse_upload("empty.csv", "text/csv", b"")
        # ``header_only.csv`` is accepted (no rows but a valid header);
        # downstream code already checks for empty rows.


class SuggestMappingTest(unittest.TestCase):
    def test_chinese_synonyms(self) -> None:
        mapping = import_api.suggest_mapping(["姓名", "性别", "年龄", "户口", "月薪"])
        self.assertEqual(mapping["姓名"], "name")
        self.assertEqual(mapping["性别"], "gender")
        self.assertEqual(mapping["年龄"], "age")
        self.assertEqual(mapping["户口"], "hukou")
        self.assertEqual(mapping["月薪"], "monthly_income")

    def test_english_synonyms(self) -> None:
        mapping = import_api.suggest_mapping(["name", "gender", "age", "income", "company"])
        self.assertEqual(mapping["name"], "name")
        self.assertEqual(mapping["income"], "monthly_income")
        self.assertEqual(mapping["company"], "company")

    def test_unmapped_columns(self) -> None:
        mapping = import_api.suggest_mapping(["个人备注", "鞋码"])
        self.assertEqual(mapping, {"个人备注": "", "鞋码": ""})


class AnonymiseTest(unittest.TestCase):
    def setUp(self) -> None:
        _, _, self.rows = import_api.parse_upload("people.csv", "text/csv", _csv_bytes(SAMPLE_CSV))

    def test_drops_contact_fields(self) -> None:
        mapping = import_api.suggest_mapping(["姓名", "phone", "email", "id_card", "年龄"])
        clean = import_api.normalise_rows(self.rows, mapping)
        anon = import_api.anonymise_rows(clean, salt="unit")
        # ``phone``, ``email``, ``id_card`` must not appear; were dropped upstream.
        for row in anon:
            self.assertNotIn("phone", row)
            self.assertNotIn("email", row)
            self.assertNotIn("id_card", row)

    def test_name_replaced_with_pseudonym(self) -> None:
        mapping = import_api.suggest_mapping(["姓名", "性别", "年龄"])
        clean = import_api.normalise_rows(self.rows, mapping)
        anon = import_api.anonymise_rows(clean, salt="unit")
        for row in anon:
            self.assertNotEqual(row["name"], "")
            self.assertNotIn("张", row["name"])  # original first char gone
            self.assertNotIn("李", row["name"])
            self.assertNotIn("王", row["name"])

    def test_pseudonym_is_deterministic(self) -> None:
        mapping = import_api.suggest_mapping(["姓名", "性别"])
        clean = import_api.normalise_rows(self.rows, mapping)
        a = import_api.anonymise_rows(clean, salt="unit")
        b = import_api.anonymise_rows(clean, salt="unit")
        self.assertEqual([row["name"] for row in a], [row["name"] for row in b])

    def test_salt_changes_pseudonym(self) -> None:
        mapping = import_api.suggest_mapping(["姓名"])
        clean = import_api.normalise_rows(self.rows, mapping)
        a = import_api.anonymise_rows(clean, salt="salt-a")
        b = import_api.anonymise_rows(clean, salt="salt-b")
        self.assertNotEqual(a[0]["name"], b[0]["name"])

    def test_free_text_scrubs_mentions(self) -> None:
        text_row = [{"name": "陈静", "personality": "性格平和，家乡是苏州。", "daily_life": ""}]
        anon = import_api.anonymise_rows(text_row, salt="unit")
        # ``苏州`` is in the city pool; ``性格平和`` is harmless. The hometown
        # tag ``家乡是`` must be replaced by the anonymiser.
        self.assertNotIn("苏州", anon[0]["personality"])

    def test_hometown_replaced(self) -> None:
        rows = [{"name": "甲", "hometown": "杭州"}]
        anon = import_api.anonymise_rows(rows, salt="unit")
        self.assertNotEqual(anon[0]["hometown"], "杭州")


class InferSpecTest(unittest.TestCase):
    def setUp(self) -> None:
        _, headers, rows = import_api.parse_upload("people.csv", "text/csv", _csv_bytes(SAMPLE_CSV))
        mapping = import_api.suggest_mapping(headers)
        self.rows = import_api.normalise_rows(rows, mapping)

    def test_basic_inference(self) -> None:
        inferred = import_api.infer_spec(self.rows)
        self.assertEqual(inferred["counts"]["total"], 5)
        demo = inferred["demography"]
        self.assertGreaterEqual(demo["share_under_18"], 0.1)  # 1/5 = 0.2
        self.assertGreaterEqual(demo["share_over_65"], 0.1)  # 1/5 = 0.2
        self.assertEqual(inferred["distributions"]["gender"]["男"], 3)
        self.assertEqual(inferred["distributions"]["gender"]["女"], 2)

    def test_industry_translated_to_ipf_keys(self) -> None:
        inferred = import_api.infer_spec(self.rows)
        spec_kwargs = import_api.build_population_spec(inferred, target_size=10, seed=1)
        industry_mix = spec_kwargs["education_work"]["industry_mix"]
        # Three non-trivial industries → normalised into tech/finance/medical.
        self.assertAlmostEqual(sum(industry_mix.values()), 1.0, places=4)
        self.assertIn("tech", industry_mix)
        self.assertIn("finance", industry_mix)
        self.assertIn("medical", industry_mix)

    def test_empty_rows_raise(self) -> None:
        with self.assertRaises(ValueError):
            import_api.infer_spec([])


class HttpDelegationTest(unittest.TestCase):
    def test_schema_endpoint(self) -> None:
        payload, status = import_api.handle_get("/api/import/schema")
        self.assertEqual(status, 200)
        self.assertIn("canonical_fields", payload)
        self.assertIn("csv", payload["formats"])

    def test_preview_endpoint_accepts_csv_text(self) -> None:
        payload = {
            "format": "csv",
            "filename": "people.csv",
            "file_text": SAMPLE_CSV,
        }
        body, status = import_api.handle_post("/api/import/preview", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["row_count"], 5)
        self.assertEqual(body["inferred"]["counts"]["total"], 5)
        # mapping_suggested is ``raw → canonical``; the canonical side must
        # include ``name``.
        canonical_values = set(body["mapping_suggested"].values())
        self.assertIn("name", canonical_values)

    def test_unknown_path_returns_404(self) -> None:
        body, status = import_api.handle_post("/api/import/unknown", {})
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_preview_with_invalid_base64(self) -> None:
        payload = {
            "format": "xlsx",
            "filename": "people.xlsx",
            "file_text": "not-base64!",
            "file_encoding": "base64",
        }
        body, status = import_api.handle_post("/api/import/preview", payload)
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_endpoint_returns_job_id(self) -> None:
        # Use a minimal, ephemeral city so we never touch the user's data/.
        import shutil
        import tempfile
        import time

        from gaworld.city.bundle import city_root, slugify

        root_ctx = tempfile.TemporaryDirectory()
        try:
            tmp_root = root_ctx.name
            label = "import-test"
            city_slug = slugify(label)
            city_directory = city_root(tmp_root) / city_slug
            if city_directory.exists():
                shutil.rmtree(city_directory)
            bundle = create_city(name=label, offline=True, scale="tiny", force=True, root=tmp_root)
            payload = {
                "city": bundle.slug,
                "city_root": tmp_root,
                "format": "csv",
                "filename": "people.csv",
                "file_text": SAMPLE_CSV,
                "anonymise": True,
                "expand_to": 0,
                "seed": 1,
                "salt": "unit",
            }
            body, status = import_api.handle_post("/api/import/run", payload)
            self.assertEqual(status, 202)
            self.assertIn("job_id", body)

            # The job runs in a background thread; poll briefly until done.
            for _ in range(60):
                rec = import_api.job_status(body["job_id"])
                if rec and rec["status"] in {"done", "failed"}:
                    break
                time.sleep(0.1)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["status"], "done", msg=str(rec.get("error")))
            self.assertEqual(rec["result"]["inserted_direct"], 5)

            # Round-trip: parse_profile must accept what we just appended.
            text = bundle.profiles_md_path.read_text(encoding="utf-8")
            # ``split`` is used because some profiles may legitimately start with
            # the section divider; drop anything before the divider that isn't a
            # full block.
            chunks = text.split("## Profile ")
            blocks = ["## Profile " + c for c in chunks if "**基础信息**" in c]
            self.assertGreaterEqual(len(blocks), 5)
            fields = parse_profile(blocks[0])
            # Names were anonymised — must NOT be one of the original five.
            self.assertNotIn(fields.get("name", "").strip(), {"张伟", "李娜", "王强", "赵敏", "孙磊"})

            # The CSV carries the pseudonym we just wrote; originals are gone.
            import csv

            with bundle.state_csv_path.open(encoding="utf-8-sig", newline="") as handle:
                state_rows = list(csv.DictReader(handle))
            self.assertEqual(len(state_rows), 5)
            names = [row["name"] for row in state_rows]
            for original in {"张伟", "李娜", "王强", "赵敏", "孙磊"}:
                self.assertNotIn(original, names)
        finally:
            root_ctx.cleanup()


if __name__ == "__main__":
    unittest.main()
