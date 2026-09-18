from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "site" / "dashboard"
LOCALE_PATH = DASHBOARD / "locales" / "zh-CN.json"
CONSOLE = ROOT / "site" / "console"


def test_collaboration_core_node_suite():
    result = subprocess.run(
        [
            "node",
            "--test",
            str(DASHBOARD / "collaboration-core.test.js"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_external_transcript_content_uses_text_content_only():
    source = (DASHBOARD / "interaction.js").read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert re.search(r"speaker\.textContent\s*=", source)
    assert re.search(r"content\.textContent\s*=\s*String\(event\.content", source)
    assert 'document.createElement("article")' in source


def test_panel_and_assets_are_mounted_in_safe_order():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    css = (DASHBOARD / "interaction.css").read_text(encoding="utf-8")
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)

    assert 'id="collaborationPanel"' in html
    assert 'id="collaborationMembers"' in html
    assert 'id="collaborationTranscript"' in html
    assert 'id="collaborationStatus"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-labelledby="collaborationMembersLabel"' in html
    assert 'aria-labelledby="collaborationTranscriptLabel"' in html
    assert ".collaboration-panel [hidden]" in css
    assert html.index("/site/dashboard/styles.css") < html.index(
        "/site/dashboard/interaction.css"
    )
    i18n_index = scripts.index("/site/dashboard/i18n.js")
    core_index = scripts.index("/site/dashboard/collaboration-core.js")
    app_index = next(
        index
        for index, script in enumerate(scripts)
        if re.fullmatch(r"/site/dashboard/app\.js(?:\?[^/]*)?", script)
    )
    interaction_index = scripts.index("/site/dashboard/interaction.js")

    assert i18n_index < core_index < app_index < interaction_index


def test_polling_controller_queues_history_and_rejects_stale_responses():
    source = (DASHBOARD / "interaction.js").read_text(encoding="utf-8")
    refresh_source = source[
        source.index("async function refreshSession"):
        source.index("async function startDiscussion")
    ]

    assert "pendingFullHistoryGeneration" in source
    assert "pollingGeneration" in source
    assert "core.queueFullHistoryRequest" in source
    assert "core.consumeFullHistoryRequest" in source
    assert "core.isCurrentPoll" in source
    assert "core.releaseCurrentPoll" in source
    assert not re.search(r"\bpolling:\s*(?:true|false)", source)
    assert source.count("empty.remove();") <= 1
    assert refresh_source.index(
        "core.queueFullHistoryRequest"
    ) < refresh_source.index(
        "document.hidden"
    ) < refresh_source.index(
        "core.consumeFullHistoryRequest"
    )


def test_session_create_hides_old_actions_and_restores_on_failure():
    source = (DASHBOARD / "interaction.js").read_text(encoding="utf-8")
    start_source = source[
        source.index("async function startDiscussion"):
        source.index("async function changeSession")
    ]

    assert "const previousSession = state.session;" in start_source
    assert start_source.index(
        "state.session = null;"
    ) < start_source.index(
        'request(\n        "/api/collaboration/sessions"'
    )
    assert re.search(
        r"catch \(error\).*?"
        r"state\.session = previousSession;.*?"
        r"renderSession\(\);.*?"
        r"schedulePoll\(\);",
        start_source,
        re.DOTALL,
    )


def test_session_actions_exclude_polling_history_and_other_controls():
    source = (DASHBOARD / "interaction.js").read_text(encoding="utf-8")
    refresh_source = source[
        source.index("async function refreshSession"):
        source.index("async function startDiscussion")
    ]
    start_source = source[
        source.index("async function startDiscussion"):
        source.index("async function changeSession")
    ]
    action_source = source[
        source.index("async function changeSession"):
        source.index("function refreshLocale")
    ]

    assert "actionPending: null" in source
    assert "actionGeneration" in source
    assert refresh_source.index(
        "state.actionPending"
    ) < refresh_source.index(
        "core.queueFullHistoryRequest"
    )
    assert "state.actionPending" in start_source
    assert "state.actionPending" in action_source
    assert "els.pauseBtn.disabled = controlsDisabled;" in source
    assert "els.resumeBtn.disabled = controlsDisabled;" in source
    assert "els.cancelBtn.disabled = controlsDisabled;" in source
    assert "els.historyBtn.disabled = controlsDisabled;" in source
    assert "|| Boolean(state.actionPending)" in source
    assert re.search(
        r"visibilitychange.*?!state\.actionPending.*?"
        r"refreshSession\(false\);",
        source,
        re.DOTALL,
    )


def test_current_action_failure_releases_controls_and_reschedules_poll():
    source = (DASHBOARD / "interaction.js").read_text(encoding="utf-8")
    action_source = source[
        source.index("async function changeSession"):
        source.index("function refreshLocale")
    ]

    assert "core.isCurrentAction" in source
    assert "core.releaseCurrentAction" in source
    assert re.search(
        r"catch \(error\).*?"
        r"releaseAction\(identity\);.*?"
        r"renderSession\(\);.*?"
        r"reportError\(error\);.*?"
        r"schedulePoll\(\);",
        action_source,
        re.DOTALL,
    )
    assert "finally" not in action_source


def test_console_registers_persistent_cooperation_tab():
    html = (CONSOLE / "index.html").read_text(encoding="utf-8")
    source = (CONSOLE / "console.js").read_text(encoding="utf-8")

    # The tab is present; what changed under this assertion is that every tab's
    # Chinese label was wrapped in <span data-i18n="nav.*"> when i18n landed,
    # and the old regex pinned the pre-i18n byte sequence. Asserting structure
    # instead of exact markup: the button carries the right data-tab, the i18n
    # key the locale files are keyed on, and both labels. That survives the next
    # markup tweak and still fails if the tab is actually removed or renamed.
    button = re.search(r'<button[^>]*data-tab="collaboration"[^>]*>(.*?)</button>',
                       html, re.S)
    assert button, "console has no collaboration tab"
    label = button.group(1)
    assert 'data-i18n="nav.collaboration"' in label, label
    assert "合作任务" in label, label
    assert '<span class="en">Cooperation</span>' in label, label
    assert re.search(
        r'\{\s*id:\s*"collaboration",\s*'
        r'src:\s*"/site/dashboard/collaboration\.html"\s*\}',
        source,
    )


def test_cooperation_page_exposes_workspace_controls():
    html = (DASHBOARD / "collaboration.html").read_text(encoding="utf-8")
    required_ids = [
        "taskInput",
        "memberPicker",
        "leaderSelect",
        "roleOverrides",
        "startTaskBtn",
        "sessionList",
        "taskPlan",
        "taskProgress",
        "activityFeed",
        "artifactList",
        "taskStatus",
        "pauseTaskBtn",
        "resumeTaskBtn",
        "cancelTaskBtn",
    ]

    assert all(f'id="{element_id}"' in html for element_id in required_ids)
    assert 'aria-live="polite"' in html
    assert "/site/dashboard/collaboration-core.js" in html
    assert "/site/dashboard/collaboration.js" in html


def test_cooperation_page_uses_safe_nodes_and_core_payload():
    source = (DASHBOARD / "collaboration.js").read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert "outerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "window.GAWorldCollaborationCore" in source
    assert "core.cooperationPayload" in source
    assert "state.session.artifact_base_url" in source
    assert 'document.createElement("a")' in source
    assert re.search(r"\.textContent\s*=", source)


def test_cooperation_artifacts_offer_a_download_action():
    source = (DASHBOARD / "collaboration.js").read_text(encoding="utf-8")

    assert re.search(r"save\.download\s*=\s*name", source)
    assert 'save.href = safeUrl' in source
    assert 't("cl.artifact_download")' in source

    for locale in ("zh-CN.json", "en.json"):
        keys = json.loads(
            (DASHBOARD / "locales" / locale).read_text(encoding="utf-8")
        )
        assert "cl.artifact_download" in keys, locale


def test_cooperation_artifact_urls_are_same_origin_and_session_scoped():
    module_path = DASHBOARD / "collaboration.js"
    locale_json = json.dumps(str(LOCALE_PATH))
    script = f"""
      const assert = require("node:assert/strict");
      const LOCALE = require({locale_json});
      globalThis.__ = (key) => {{
        if (!Object.prototype.hasOwnProperty.call(LOCALE, key)) {{
          throw new Error("missing locale key: " + key);
        }}
        return LOCALE[key];
      }};
      globalThis.__f = (key, params) => {{
        let text = globalThis.__(key);
        for (const [name, value] of Object.entries(params || {{}})) {{
          text = text.split("{{" + name + "}}").join(String(value));
        }}
        return text;
      }};
      const page = require({json.dumps(str(module_path))});
      const base = "http://127.0.0.1:8000/site/dashboard/collaboration.html";
      const defaultScope =
        "/output/collaboration/sessions/cs_1/artifacts/";
      const runtimeScope = "/runtime/sessions/cs_1/artifacts/";
      assert.equal(
        page.safeArtifactUrl(
          "/output/collaboration/sessions/cs_1/artifacts/result.md",
          "cs_1",
          base,
          defaultScope,
        ),
        "/output/collaboration/sessions/cs_1/artifacts/result.md",
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md",
          "cs_1",
          base,
          runtimeScope,
        ),
        "/runtime/sessions/cs_1/artifacts/result.md",
      );
      assert.equal(
        page.safeArtifactUrl(
          "https://evil.example/cs_1/artifacts/x",
          "cs_1",
          base,
          defaultScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/x/cs_1/artifacts/result.md",
          "cs_1",
          base,
          runtimeScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_10/artifacts/result.md",
          "cs_1",
          base,
          runtimeScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/nested/result.md",
          "cs_1",
          base,
          runtimeScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/a%2Fb.md",
          "cs_1",
          base,
          runtimeScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/%252e%252e",
          "cs_1",
          base,
          runtimeScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md?download=1",
          "cs_1",
          base,
          runtimeScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md#preview",
          "cs_1",
          base,
          runtimeScope,
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md",
          "cs_1",
          base,
          "https://evil.example/runtime/sessions/cs_1/artifacts/",
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md",
          "cs_1",
          base,
          "/runtime/sessions/cs_1/artifacts/?scope=bad",
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md",
          "cs_1",
          base,
          "/runtime/sessions/cs_2/artifacts/",
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md",
          "cs_1",
          base,
          "/runtime/%2e%2e/sessions/cs_1/artifacts/",
        ),
        null,
      );
      assert.equal(
        page.safeArtifactUrl(
          "/runtime/sessions/cs_1/artifacts/result.md",
          "cs_1",
          base,
          "http://user@127.0.0.1:8000/runtime/sessions/cs_1/artifacts/",
        ),
        null,
      );
    """
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_cooperation_session_list_only_applies_latest_request():
    module_path = DASHBOARD / "collaboration.js"
    locale_json = json.dumps(str(LOCALE_PATH))
    source = module_path.read_text(encoding="utf-8")
    load_source = source[
        source.index("async function loadSessions"):
        source.index("function resetActivity")
    ]
    script = f"""
      const assert = require("node:assert/strict");
      const LOCALE = require({locale_json});
      globalThis.__ = (key) => {{
        if (!Object.prototype.hasOwnProperty.call(LOCALE, key)) {{
          throw new Error("missing locale key: " + key);
        }}
        return LOCALE[key];
      }};
      globalThis.__f = (key, params) => {{
        let text = globalThis.__(key);
        for (const [name, value] of Object.entries(params || {{}})) {{
          text = text.split("{{" + name + "}}").join(String(value));
        }}
        return text;
      }};
      const page = require({json.dumps(str(module_path))});
      assert.equal(page.isLatestRequest(4, 4), true);
      assert.equal(page.isLatestRequest(5, 4), false);
    """
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "listGeneration" in source
    assert "requestGeneration" in load_source
    assert load_source.count(
        "isLatestRequest(state.listGeneration, requestGeneration)"
    ) >= 3


def test_cooperation_layout_and_console_tabs_are_responsive():
    page_css = (DASHBOARD / "collaboration.css").read_text(encoding="utf-8")
    console_css = (CONSOLE / "console.css").read_text(encoding="utf-8")

    assert "grid-template-columns:" in page_css
    assert re.search(
        r"@media\s*\(max-width:\s*899px\).*?"
        r"grid-template-columns:\s*1fr",
        page_css,
        re.DOTALL,
    )
    assert re.search(
        r"@media\s*\(max-width:\s*860px\).*?"
        r"overflow-x:\s*auto",
        console_css,
        re.DOTALL,
    )
    assert "flex-shrink: 0" in console_css
    assert ":focus-visible" in page_css


def test_collaboration_locale_keys_match_in_order():
    zh = json.loads(
        (DASHBOARD / "locales" / "zh-CN.json").read_text(encoding="utf-8")
    )
    en = json.loads(
        (DASHBOARD / "locales" / "en.json").read_text(encoding="utf-8")
    )
    zh_keys = list(zh)
    en_keys = list(en)
    required = [
        "collaboration.title",
        "collaboration.members",
        "collaboration.make_friends",
        "collaboration.topic",
        "collaboration.rounds",
        "collaboration.start",
        "collaboration.pause",
        "collaboration.resume",
        "collaboration.cancel",
        "collaboration.status",
        "collaboration.empty_transcript",
    ]

    assert zh_keys == en_keys
    assert all(key in en for key in required)
    indexes = [en_keys.index(key) for key in required]
    assert indexes == sorted(indexes)


def test_cooperation_activity_entries_attribute_each_speaker():
    module_path = DASHBOARD / "collaboration.js"
    locale_json = json.dumps(str(LOCALE_PATH))
    script = f"""
      const assert = require("node:assert/strict");
      const LOCALE = require({locale_json});
      globalThis.__ = (key) => {{
        if (!Object.prototype.hasOwnProperty.call(LOCALE, key)) {{
          throw new Error("missing locale key: " + key);
        }}
        return LOCALE[key];
      }};
      globalThis.__f = (key, params) => {{
        let text = globalThis.__(key);
        for (const [name, value] of Object.entries(params || {{}})) {{
          text = text.split("{{" + name + "}}").join(String(value));
        }}
        return text;
      }};
      const page = require({json.dumps(str(module_path))});
      const context = {{
        names: {{4: "李明", 5: "陈静"}},
        roles: {{"4": "研究员", "5": "审阅者"}},
        leaderId: 4,
        plan: [{{title: "整理资料", agent_id: 4}}],
      }};

      const artifact = page.activityEntry(
        {{
          type: "artifact",
          agent_id: 4,
          content: "member_4.md",
          metadata: {{step_index: 0, excerpt: "本区共有三处闲置空地。"}},
        }},
        context,
      );
      assert.equal(artifact.speaker, "李明");
      assert.equal(artifact.role, "研究员 · 负责人");
      assert.equal(artifact.round, "第 1 轮");
      assert.equal(artifact.action, "提交了子任务产物");
      assert.equal(artifact.detail, "步骤 1 · 整理资料 · member_4.md");
      assert.equal(artifact.speech, "本区共有三处闲置空地。");

      const review = page.activityEntry(
        {{
          type: "review",
          agent_id: 5,
          content: "第二段需要补充数据来源。",
          metadata: {{
            approved: false,
            artifact: "member_4.md",
            step_index: 0,
          }},
        }},
        context,
      );
      assert.equal(review.speaker, "陈静");
      assert.equal(review.role, "审阅者");
      assert.equal(review.action, "提出了修改意见");
      assert.equal(review.speech, "第二段需要补充数据来源。");

      const approved = page.activityEntry(
        {{type: "review", agent_id: 5, content: "可以发布。",
          metadata: {{approved: true}}}},
        context,
      );
      assert.equal(approved.action, "审阅通过");

      const final = page.activityEntry(
        {{type: "artifact", agent_id: 4, content: "final.md",
          metadata: {{final: true}}}},
        context,
      );
      assert.equal(final.action, "汇总了最终成果");

      const system = page.activityEntry(
        {{type: "started", agent_id: null, content: "合作任务开始"}},
        context,
      );
      assert.equal(system.speaker, "系统");
      assert.equal(system.role, "");
      assert.equal(system.action, "合作任务开始");

      const unknown = page.activityEntry(
        {{type: "revision", agent_id: 9, content: "member_9.md"}},
        context,
      );
      assert.equal(unknown.speaker, "居民 9");
      assert.equal(unknown.action, "按审阅意见完成修订");

      const turn = page.activityEntry(
        {{
          type: "turn_started",
          agent_id: 5,
          content: "member_4.md",
          metadata: {{phase: "review", step_index: 0}},
        }},
        context,
      );
      assert.equal(turn.speaker, "陈静");
      assert.equal(turn.round, "第 1 轮");
      assert.equal(turn.action, "开始审阅成果");
      assert.equal(turn.detail, "步骤 1 · 整理资料 · member_4.md");

      const synthesis = page.activityEntry(
        {{
          type: "turn_started",
          agent_id: 4,
          content: "final.md",
          metadata: {{phase: "synthesis"}},
        }},
        context,
      );
      assert.equal(synthesis.round, "统稿");
      assert.equal(synthesis.action, "开始统稿最终成果");
    """
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_cooperation_activity_feed_renders_speaker_nodes():
    source = (DASHBOARD / "collaboration.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "collaboration.css").read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert re.search(r"speaker\.textContent\s*=\s*entry\.speaker", source)
    assert re.search(r"role\.textContent\s*=\s*entry\.role", source)
    assert re.search(r"speech\.textContent\s*=\s*entry\.speech", source)
    assert "activityEntry(event, context)" in source
    assert ".activity-speaker" in css
    assert ".activity-speech" in css
