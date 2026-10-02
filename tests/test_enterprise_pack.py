import csv
import io
import json
import zipfile

from gaworld.enterprise.__main__ import main
from gaworld.enterprise.pack import anonymise, build_package
from gaworld.sim.agents_loader import parse_profile

SOURCE = (
    "用户ID,姓名,性别,年龄,手机,邮箱,身份证,公司,住址,家乡,行业,月薪,性格,会员等级\n"
    "u001,张伟明,男,34,13812345678,zwm@corp.cn,330106199001011234,星辰科技,杭州市西湖区文三路1号,"
    "绍兴,互联网,18234,张伟明性格开朗，常在星辰科技加班，电话13812345678,金卡\n"
    "u002,李娜,F,,13900001111,ln@corp.cn,,,,,,,喜欢旅游，邮箱 ln@corp.cn,银卡\n"
)


def _pack(tmp_path, **kwargs):
    src = tmp_path / "users.csv"
    src.write_text(SOURCE, encoding="utf-8")
    out = tmp_path / "agents.zip"
    report = build_package(src, out, salt="s", **kwargs)
    return report, zipfile.ZipFile(out)


def test_package_contains_no_raw_identifiers(tmp_path):
    _, zf = _pack(tmp_path)
    blob = "".join(zf.read(n).decode("utf-8-sig") for n in zf.namelist())
    for secret in (
        "张伟明",
        "李娜",
        "13812345678",
        "zwm@corp.cn",
        "ln@corp.cn",
        "330106199001011234",
        "星辰科技",
        "文三路",
        "u001",
        "金卡",
        "18234",
    ):
        assert secret not in blob, secret


def test_free_text_is_scrubbed_not_mangled():
    rows, hits = anonymise(
        [{"name": "张伟明", "personality": "张伟明性格开朗，电话13812345678", "company": "星辰科技"}],
        salt="s",
    )
    text = rows[0]["personality"]
    assert "性格开朗" in text and "[电话]" in text
    assert text.startswith(rows[0]["name"])
    assert hits["phone"] == 1 and "company" not in rows[0]


def test_pseudonyms_are_unique_and_salted():
    rows = [{"name": "同名"}, {"name": "同名"}]
    names = [r["name"] for r in anonymise(rows, salt="a")[0]]
    assert len(set(names)) == 2
    assert anonymise(rows, salt="a")[0] == anonymise(rows, salt="a")[0]


def test_profiles_parse_and_csv_matches(tmp_path):
    report, zf = _pack(tmp_path, districts=["柯桥区"])
    assert report["agents"] == 2
    assert {report["columns"][c] for c in ("用户ID", "手机", "会员等级")} == {"dropped"}
    assert report["imputed"]["age"] == 1
    blocks = zf.read("profiles.md").decode().split("\n## Profile ")[1:]
    parsed = [parse_profile("## Profile " + b) for b in blocks]
    assert parsed[0]["age"] == 34 and parsed[0]["living"].startswith("柯桥区·")
    assert parsed[0]["monthly_income"] == 18000  # rounded to 500
    rows = list(csv.DictReader(io.StringIO(zf.read("agents.csv").decode("utf-8-sig"))))
    assert [r["name"] for r in rows] == [p["name"] for p in parsed]
    assert rows[1]["gender"] == "女"
    assert len(zf.read("agents.jsonl").decode().splitlines()) == 2


def test_drop_free_text(tmp_path):
    report, zf = _pack(tmp_path, drop_free_text=True)
    assert report["free_text"] == "dropped"
    assert "性格开朗" not in zf.read("profiles.md").decode()


def test_cli_dry_run_and_map_override(tmp_path, capsys):
    src = tmp_path / "users.csv"
    src.write_text(SOURCE, encoding="utf-8")
    assert main([str(src), "--dry-run", "--map", "会员等级=values"]) == 0
    assert "会员等级" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.zip"))
    assert main([str(src), "--map", "不存在=name"]) == 1


def test_cli_writes_zip(tmp_path, capsys):
    src = tmp_path / "users.csv"
    src.write_text(SOURCE, encoding="utf-8")
    assert main([str(src)]) == 0
    report = json.loads(zipfile.ZipFile(tmp_path / "users_agents.zip").read("report.json"))
    assert report["salt"] == "random (not stored)"
