"""Controlled browser acceptance; all APIs and model outcomes are fixtures."""

import json
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gaworld.research import reading, workbench  # noqa: E402
from gaworld.research.evaluate import evaluate  # noqa: E402
from gaworld.research.report import render_study_markdown  # noqa: E402
from tests.test_research_study import PLAN, make_protocol, runs_for, series  # noqa: E402

OUT = ROOT / "output" / "research-flow-verification"
OUT.mkdir(parents=True, exist_ok=True)
plan = dict(
    PLAN,
    provider="fixture",
    created_at="2026-11-08T00:00:00Z",
    estimated_cost={"llm_calls": "约 100 次，仅示例"},
)
plan["designs"] = [
    dict(PLAN["design"], name="机制检验"),
    dict(PLAN["design"], name="情境延伸", population="40 人"),
]
plan["recommended_design"] = 0
plan["reading"] = reading.plan_summary(plan)
plan["reading_designs"] = [reading.plan_summary(plan, i) for i in range(2)]
plan["markdown"] = workbench.render_markdown(workbench.ResearchPlan.from_dict(plan))
protocol = make_protocol().to_dict()
study = {
    "id": "Sfixture-0001",
    "plan_id": plan["id"],
    "title": "租金补贴研究 · 统计已完成",
    "created_at": plan["created_at"],
    "stage": "evaluated",
    "live": True,
    "active_job_id": "run-fixture",
    "protocol": protocol,
    "runs": [],
    "preflight": {"ok": True},
    "evaluation": evaluate(
        make_protocol(), runs_for((42, series(0.5, 0.3, 0.5)), (43, series(0.5, 0.3, 0.5)))
    ),
    "interpretation": {},
    "runtime": {},
}
study["reading"] = reading.study_summary(study)
state = {"plan_done": False, "compile_done": False, "fail_once": True, "posts": [], "digest_request_id": None}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def json(self, data, code=200):
        value = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(value)))
        self.end_headers()
        self.wfile.write(value)

    def do_POST(self):
        state["posts"].append(self.path)
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/research/digest":
            import socket

            state["digest_request_id"] = payload["request_id"]
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if self.path == "/api/research/analyze":
            return self.json({"job_id": "plan-fixture"})
        if self.path == "/api/research/studies":
            return self.json({"job_id": "study-fixture"})
        return self.json({"error": "Unexpected write blocked by fixture"}, 400)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/site/dashboard/research.html":
            html = (ROOT / path.lstrip("/")).read_text()
            script = '<script>window.__sent=[];window.__failures=[];window.addEventListener("error",e=>window.__failures.push(e.message));const originalFetch=window.fetch;window.fetch=function(...args){window.__sent.push([String(args[0]),args[1]&&args[1].method]);return originalFetch.apply(this,args);};</script>'
            value = html.replace("<head>", "<head>" + script).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(value)))
            self.end_headers()
            self.wfile.write(value)
            return
        if path == "/api/research/context":
            return self.json(
                {
                    "providers": [],
                    "plans": [],
                    "studies": [],
                    "catalogue": {"available": True},
                    "workspace": {"mode": "single_user", "owner_id": None, "world_id": ""},
                    "jobs": (
                        [
                            {
                                "id": "digest-fixture",
                                "kind": "digest",
                                "status": "done",
                                "request_id": state["digest_request_id"],
                            }
                        ]
                        if state["digest_request_id"]
                        else []
                    ),
                }
            )
        if path == "/api/research/jobs/digest-fixture":
            return self.json(
                {
                    "status": "done",
                    "result": {
                        "title": "论文恢复示例",
                        "paper_digest": {"theory": "论文理论", "method": "对照研究"},
                        "research_questions": ["补贴是否降低压力？"],
                        "hypotheses": ["H1 补贴降低压力"],
                        "source": {
                            "text": "这是用于恢复测试的原始论文材料。",
                            "title": "论文恢复示例",
                            "kind": "paper",
                            "provider": "",
                            "language": "zh-CN",
                        },
                    },
                }
            )
        if path == "/api/research/jobs/plan-fixture":
            if state["fail_once"]:
                state["fail_once"] = False
                return self.json({"error": "temporary disconnect"}, 503)
            return self.json(
                {
                    "status": "done" if state["plan_done"] else "running",
                    "progress": 0.1,
                    "elapsed_seconds": 42,
                    "message": "模型正在生成方案",
                    "result": {"plan_id": plan["id"]},
                }
            )
        if path == "/api/research/jobs/study-fixture":
            return self.json(
                {
                    "status": "done" if state["compile_done"] else "running",
                    "progress": 0.1,
                    "message": "编译协议中",
                    "result": {"study_id": study["id"]},
                }
            )
        if path == "/api/research/jobs/run-fixture":
            return self.json(
                {
                    "status": "running",
                    "progress": 0.9,
                    "message": "统计完成，补充解读中",
                    "elapsed_seconds": 90,
                }
            )
        if path == f"/api/research/plans/{plan['id']}":
            return self.json(plan)
        if path == f"/api/research/studies/{study['id']}":
            return self.json(study)
        if path.endswith("/logs"):
            return self.json({"text": "统计完成\n", "sources": [], "live": False})
        if path.endswith("/report"):
            return self.json({"filename": "report.md", "markdown": render_study_markdown(study)})
        if path == "/api/research/plans":
            return self.json({"plans": []})
        if path == "/api/research/studies":
            return self.json({"studies": []})
        if path.startswith("/api/"):
            return self.json({})
        return super().do_GET()


server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT)))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"
SESSION = "research-flow-acceptance"


def ab(*args, expected=True):
    result = subprocess.run(
        ["npx", "--yes", "agent-browser", "--session", SESSION, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=40,
    )
    if expected and result.returncode:
        raise AssertionError((args, result.stdout, result.stderr))
    return result.stdout.strip()


def evaluate_js(code):
    return ab("eval", code)


def check(condition):
    assert evaluate_js(condition) == "true", (condition, evaluate_js(condition))


try:
    ab("open", base + "/site/dashboard/research.html")
    ab("wait", "--fn", 'document.getElementById("rwRun") && !document.getElementById("rwRun").disabled')
    ab("fill", "#rwText", "租金补贴是否降低居民压力？")
    ab("click", "#rwRun")
    ab("wait", "--text", "连接暂时中断")
    assert len(state["posts"]) == 1
    ab("reload")
    ab("wait", "--text", "已等待")
    check('document.getElementById("rwRun").disabled')
    assert len(state["posts"]) == 1, state["posts"]
    state["plan_done"] = True
    ab("wait", "--text", "先读懂这份方案")
    check('document.querySelector("#rwResult .rw-reading").textContent.includes("机制检验")')
    ab("click", 'button.rw-design-tab[data-index="1"]')
    check('document.querySelector("#rwResult .rw-reading").textContent.includes("40 人")')
    ab("click", "#rwToStudy")
    ab("wait", "--text", "编译协议中")
    check('document.getElementById("rwToStudy").disabled')
    assert len(state["posts"]) == 2
    ab("reload")
    ab("wait", "--text", "编译协议中")
    assert len(state["posts"]) == 2
    state["compile_done"] = True
    ab("wait", "--text", "先看结果与下一步")
    check('document.querySelector("#rwStudy .rw-reading").textContent.includes("统计已完成")')
    check('!document.querySelector("#rwStudy .rw-log-panel").open')
    check('document.getElementById("rwRunLabel").textContent.includes("统计完成")')
    assert "study_id=Sfixture-0001" in ab("get", "url")
    results = []
    for width, theme in [(1440, "light"), (390, "light"), (390, "dark")]:
        ab("set", "viewport", str(width), "1000")
        evaluate_js(f'document.documentElement.dataset.theme="{theme}"')
        ab("scrollintoview", "#rwStudy .rw-reading")
        check("document.documentElement.scrollWidth <= innerWidth")
        check('document.querySelector("#rwStudy .rw-reading").getBoundingClientRect().width <= innerWidth')
        file = OUT / f"research-{width}-{theme}.png"
        ab("screenshot", str(file))
        results.append({"width": width, "theme": theme, "screenshot": str(file), "overflow": False})
    ab("reload")
    ab("wait", "--text", "先看结果与下一步")
    assert len(state["posts"]) == 2
    ab("click", "input[name=rwKind][value=paper]")
    ab("fill", "#rwText", "这是用于恢复测试的原始论文材料。")
    ab("click", "#rwRun")
    ab("wait", "--text", "论文解读好了")
    check('!document.getElementById("rwRun").disabled')
    assert len(state["posts"]) == 3, state["posts"]
    ab("reload")
    ab("wait", "--text", "论文解读好了")
    check('document.getElementById("rwText").value === "这是用于恢复测试的原始论文材料。"')
    check('document.querySelector("input[name=rwKind][value=paper]").checked')
    check('!document.getElementById("rwDesignFromDigest").disabled')
    assert len(state["posts"]) == 3
    errors = ab("errors")
    assert not errors or "No errors" in errors, errors
    output = {
        "posts": state["posts"],
        "checks": results,
        "errors": errors,
        "fixtures_only": True,
        "refreshes_without_extra_posts": 4,
        "lost_digest_post_reply_recovered": True,
    }
    (OUT / "browser-results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))
except Exception:
    print("POSTS", state["posts"])
    print("ERRORS", ab("errors", expected=False))
    print(
        "SENT",
        evaluate_js(
            "JSON.stringify({requests:window.__sent,failures:window.__failures,storage:{...localStorage},url:location.href})"
        ),
    )
    print("NETWORK", ab("network", "requests", expected=False))
    print("SNAPSHOT", ab("snapshot", expected=False))
    raise
finally:
    ab("close", expected=False)
    server.shutdown()
