(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldGameExport = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  /* 游戏场结果 → Markdown。
   *
   * Every builder takes the same payload the page already holds in memory and
   * returns a string; none touch the DOM, so they run under
   * `node site/dashboard/game-export.test.js`. The browser glue at the bottom
   * (attach/sync) is the only part that needs a page.
   */

  const one = (s) => String(s == null ? "" : s).replace(/\s*\n\s*/g, " ").trim();
  const cell = (s) => one(s).replace(/\|/g, "\\|") || "—";
  const quote = (s) => String(s == null ? "" : s).trim().split("\n").map((l) => "> " + l).join("\n");
  const pct = (x) => Math.round((Number(x) || 0) * 100) + "%";
  const who = (id, name) => `#${id} ${name || ""}`.trim();

  function table(head, rows) {
    return [
      "| " + head.join(" | ") + " |",
      "| " + head.map(() => "---").join(" | ") + " |",
    ].concat(rows.map((r) => "| " + r.map(cell).join(" | ") + " |")).join("\n");
  }

  function counts(map) {
    const ranked = Object.entries(map || {}).sort((a, b) => b[1] - a[1]);
    return ranked.length ? ranked.map(([k, n]) => `${k} ×${n}`).join("、") : "—";
  }

  function stamp(now) {
    const d = now || new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  function doc(title, meta, sections, now) {
    const head = [`# ${title}`, ""];
    const line = [].concat(meta || [], [`导出时间：${stamp(now)}`]).filter(Boolean);
    return head.concat([line.join(" · "), ""], sections.filter(Boolean).join("\n\n"), [""]).join("\n");
  }

  // -- 说服游戏 -------------------------------------------------------------
  function persuasion(session, now) {
    const name = who(session.agent_id, session.agent_name);
    const settled = session.status === "settled";
    const lines = [`**${name}**（开场答复）\n\n${quote(session.initial_answer)}`];
    (session.messages || []).forEach((m) => {
      lines.push(`**${m.role === "player" ? "你" : name}**\n\n${quote(m.text)}`);
    });
    if (session.final_answer) lines.push(`**${name}**（复问）\n\n${quote(session.final_answer)}`);

    const verdict = settled
      ? [
        `## 结果：${session.outcome === "success" ? "说服成功" : "没说动"}`,
        `- 最初：${one(session.initial_answer)}`,
        `- 复问：${one(session.final_answer)}`,
        session.reason ? `- 裁判：${one(session.reason)}` : "",
      ].filter(Boolean).join("\n")
      : "## 结果\n\n对局尚未结算。";

    return doc(
      "说服游戏",
      [`对手：${name}`, `轮数：${(session.max_turns || 0) - (session.turns_left || 0)}/${session.max_turns}`],
      [`## 问题\n\n${quote(session.question)}`, "## 对话\n\n" + lines.join("\n\n"), verdict],
      now
    );
  }

  // -- 灾害模式 -------------------------------------------------------------
  function disaster(run, now) {
    const d = run.disaster || {};
    const overall = (run.stats || {}).overall || {};
    const perStage = (run.stats || {}).per_stage || [];
    const agents = run.agents || [];

    const sections = [
      run.summary ? `## 城市简报\n\n${run.summary.trim()}` : "",
      "## 总览\n\n" + [
        `- 平均恐慌：${overall.avg_panic == null ? "—" : overall.avg_panic} / 5`,
        `- 互助率：${pct(overall.help_rate)}`,
        `- 反应数：${overall.n == null ? "—" : overall.n}`,
        `- 选择分布：${counts(overall.actions)}`,
      ].join("\n"),
    ];

    perStage.forEach((stage, i) => {
      const rows = agents.map((p) => {
        const r = (p.reactions || [])[i];
        return r ? [who(p.agent_id, p.name), r.action, `${r.panic}/5`, r.help ? "是" : "否", r.detail, r.say ? `「${one(r.say)}」` : ""] : null;
      }).filter(Boolean);
      sections.push([
        `## 第 ${i + 1} 幕`,
        quote(stage.text || (run.stages || [])[i] || ""),
        `平均恐慌 ${stage.avg_panic} · 互助率 ${pct(stage.help_rate)} · ${counts(stage.actions)}`,
        table(["居民", "行动", "恐慌", "顾得上别人", "经过", "原话"], rows),
      ].join("\n\n"));
    });

    return doc(
      `灾害模式：${d.emoji || ""} ${d.name || ""}`.trim(),
      [run.city ? `城市：${run.city}` : "", `${agents.length} 人`, `${(run.stages || []).length} 幕`],
      sections,
      now
    );
  }

  // -- 传闻扩散 -------------------------------------------------------------
  function rumor(run, now) {
    const r = run.rumor || {};
    const stats = run.stats || {};
    const nodes = run.nodes || [];
    const names = {};
    nodes.forEach((n) => { names[n.agent_id] = n.name; });
    const seeds = (run.seeds || []).map((id) => who(id, names[id]));
    const sup = stats.superspreader;

    const rounds = (run.rounds || []).map((x) => [`第 ${x.round + 1} 轮`, x.reached, x.believers]);
    const hops = (run.transmissions || []).map((h) => [
      `第 ${h.round + 1} 轮`, who(h.from, names[h.from]), who(h.to, names[h.to]), h.label || h.kind,
    ]);
    const people = nodes.slice()
      .sort((a, b) => (a.heard_round == null ? 99 : a.heard_round) - (b.heard_round == null ? 99 : b.heard_round))
      .map((n) => n.heard_round == null
        ? [who(n.agent_id, n.name), "没听说", "—", "—", "—", ""]
        : [
          who(n.agent_id, n.name),
          `第 ${n.heard_round + 1} 轮`,
          n.heard_from != null ? names[n.heard_from] : "自己刷到的",
          n.action,
          `${n.belief}%${n.believes ? "（信）" : "（存疑）"}`,
          n.say ? `「${one(n.say)}」` : "",
        ]);

    return doc(
      `传闻扩散：${r.emoji || ""} ${r.title || ""}`.trim(),
      [run.city ? `城市：${run.city}` : "", `起点：${seeds.join("、") || "—"}`],
      [
        r.text ? `## 传闻\n\n${quote(r.text)}` : "",
        run.summary ? `## 简报\n\n${run.summary.trim()}` : "",
        "## 总览\n\n" + [
          `- 触达：${stats.reached}/${stats.total}（${stats.total ? Math.round((stats.reached / stats.total) * 100) : 0}%）`,
          `- 相信：${stats.believers} 人，平均信任度 ${stats.avg_belief}%`,
          `- 最大传播者：${sup ? `${sup.name} ×${sup.n}` : "—"}`,
        ].join("\n"),
        rounds.length ? "## 逐轮\n\n" + table(["轮次", "累计听说", "累计相信"], rounds) : "",
        "## 每个人\n\n" + table(["居民", "何时听说", "来自", "反应", "信任度", "原话"], people),
        hops.length ? "## 传播路径\n\n" + table(["轮次", "谁", "传给", "方式"], hops) : "",
      ],
      now
    );
  }

  // -- 团队对决 -------------------------------------------------------------
  function duel(run, now) {
    const task = run.task || {};
    const verdict = run.verdict || {};
    const scores = verdict.scores || {};
    const byKey = (key) => (run.teams || []).find((t) => t.key === key) || { members: [], plans: [], method: {} };
    const A = byKey("A");
    const B = byKey("B");
    const winner = verdict.winner;
    const label = winner === "tie" ? "打平" : `${winner === "A" ? A.name : B.name} 赢`;
    const criteria = verdict.criteria || [];
    const sheet = criteria.map((c) => [c.label, (scores.A || {})[c.key] || 0, (scores.B || {})[c.key] || 0]);
    sheet.push(["合计", (scores.A || {}).total || 0, (scores.B || {}).total || 0]);

    const board = (team) => {
      const plans = team.plans || [];
      const last = plans[plans.length - 1] || {};
      const members = (team.members || []).map((m) => {
        const mv = (m.moves || [])[(m.moves || []).length - 1] || {};
        return [m.name, m.job, mv.move, mv.why, mv.confidence];
      });
      return [
        `## ${team.name}：${(team.method || {}).title || ""}`,
        (team.method || {}).text ? quote(team.method.text) : "",
        `**最终方案：** ${one(last.headline)}`,
        (last.steps || []).map((s, i) => `${i + 1}. ${one(s)}`).join("\n"),
        last.risk ? `**最可能栽在：** ${one(last.risk)}` : "",
        plans.length > 1
          ? "**更早几轮：**\n" + plans.slice(0, -1).map((p) => `- 第 ${p.round + 1} 轮：${one(p.headline)}`).join("\n")
          : "",
        table(["成员", "职业", "出招", "理由", "把握"], members),
      ].filter(Boolean).join("\n\n");
    };

    return doc(
      `团队对决：${task.emoji || ""} ${task.title || ""}`.trim(),
      [run.city ? `城市：${run.city}` : "", `${A.name} vs ${B.name}`],
      [
        task.text ? `## 任务\n\n${quote(task.text)}` : "",
        [`## 结果：${label}`, one(verdict.reason)].filter(Boolean).join("\n\n"),
        "## 评分表\n\n" + table(["维度", A.name, B.name], sheet),
        board(A),
        board(B),
      ],
      now
    );
  }

  // -- 公投 -----------------------------------------------------------------
  function referendum(run, now) {
    const motion = run.motion || {};
    const stats = run.stats || {};
    const priv = stats.private || {};
    const pub = stats.public || {};
    const stances = ["支持", "反对", "弃权"];
    const tally = stances.map((s) => [s, priv[s] || 0, pub[s] || 0]);
    tally.push(["平均坚定度", priv.avg_strength, pub.avg_strength]);

    const flips = (run.flips || []).map((f) => [f.name, `${f.from} → ${f.to}`, f.say]);
    const voters = (run.voters || []).map((v) => {
      const p = v.public || {};
      return [
        who(v.agent_id, v.name),
        [v.job, v.residence].filter(Boolean).join(" · "),
        (v.private || {}).stance,
        p.stance,
        p.strength,
        p.say ? `「${one(p.say)}」` : "",
      ];
    });

    return doc(
      `公投：${motion.emoji || ""} ${motion.title || ""}`.trim(),
      [run.city ? `城市：${run.city}` : "", `${stats.total} 人`],
      [
        motion.text ? `## 议案\n\n${quote(motion.text)}` : "",
        run.campaign ? `## 宣传口径\n\n${quote(run.campaign)}` : "",
        [
          `## 结果：${stats.result}`,
          `支持 ${pub["支持"] || 0} · 反对 ${pub["反对"] || 0} · 弃权 ${pub["弃权"] || 0}；`
            + `较私下表态 ${stats.swing > 0 ? "+" : ""}${stats.swing}，${stats.flips} 人改票。`,
        ].join("\n\n"),
        "## 私下 vs 正式\n\n" + table(["立场", "私下", "正式"], tally),
        flips.length ? "## 改票的人\n\n" + table(["居民", "改票", "原话"], flips) : "",
        run.summary ? `## 简报\n\n${run.summary.trim()}` : "",
        "## 每位选民\n\n" + table(["居民", "身份", "私下", "正式", "坚定度", "原话"], voters),
      ],
      now
    );
  }

  // -- 读心游戏 -------------------------------------------------------------
  function guess(round, board, now) {
    const agent = round.agent || {};
    const dilemma = round.dilemma || {};
    const settled = round.settled;
    const samples = round.samples || [];
    const options = (dilemma.options || []).map((o) => {
      const tags = [];
      if (settled && o.key === round.guess) tags.push("你猜");
      if (settled && o.key === round.choice) tags.push("他选");
      return `- **${o.key}** ${one(o.text)}${tags.length ? `　（${tags.join("、")}）` : ""}`;
    });
    const meta = [agent.age ? agent.age + "岁" : "", agent.gender, agent.job, agent.residence].filter(Boolean).join(" · ");

    const result = !settled
      ? "## 结果\n\n尚未作答。"
      : [
        `## 结果：${round.correct ? "猜中了" : "没猜中"}`,
        round.why ? `他的理由：${one(round.why)}` : "",
        samples.length > 1
          ? `问了 ${samples.length} 次：${samples.map((s) => s.choice || "?").join(" / ")} — `
            + (new Set(samples.map((s) => s.choice)).size === 1 ? "每次都一样，这份档案很稳" : "答案不一致，这份档案撑不住这道题")
          : "",
      ].filter(Boolean).join("\n\n");

    const history = board && (board.history || []).length
      ? "## 战绩\n\n" + [
        `命中率 ${board.played ? pct(board.accuracy) : "—"}（${board.correct}/${board.played}） · 连胜 ${board.streak}（最佳 ${board.best_streak}）`
          + (board.resampled ? ` · 档案稳定 ${board.stable}/${board.resampled}` : ""),
        table(["", "居民", "题目", "你猜", "他选"],
          board.history.map((h) => [h.correct ? "✅" : "❌", h.name, h.dilemma, h.guess, h.choice || "?"])),
      ].join("\n\n")
      : "";

    return doc(
      "读心游戏",
      [`对象：${who(agent.agent_id, agent.name)}`, meta],
      [
        agent.file ? `## 档案\n\n${quote(agent.file)}` : "",
        `## 题目\n\n${quote(dilemma.text)}\n\n${options.join("\n")}`,
        result,
        history,
      ],
      now
    );
  }

  // -- 斗兽场 ---------------------------------------------------------------
  function arena(result, extra, now) {
    const rows = (result.leaderboard || []).map((row, i) => [
      i + 1,
      who(row.agent_id, row.name),
      `${(row.accuracy * 100).toFixed(0)}%（${row.correct}/${row.attempted}）`,
      `${Number(row.median_latency_s || 0).toFixed(2)}s`,
    ]);
    const eliminated = (extra && extra.eliminated) || [];
    return doc(
      "斗兽场",
      [
        result.city ? `城市：${result.city}` : "",
        `${rows.length} 位选手`,
        (result.task_ids || []).length ? `${result.task_ids.length} 道题` : "",
      ],
      [
        "## 排行榜\n\n" + table(["名次", "选手", "正确率", "响应中位数"], rows),
        eliminated.length ? `## 已淘汰\n\n${eliminated.map((id) => `#${id}`).join("、")}` : "",
      ],
      now
    );
  }

  // -- 浏览器胶水 -----------------------------------------------------------
  function download(filename, markdown) {
    const blob = new Blob(["﻿" + markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function safeName(s) {
    return one(s).replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "result";
  }

  function fileName(game, label, now) {
    const d = now || new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${game}-${safeName(label)}-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.md`;
  }

  /** `build()` returns `{game, label, markdown}` or null while there is nothing to save. */
  function attach(build) {
    const btn = document.getElementById("gameExportBtn");
    if (!btn) return { sync() {} };
    btn.addEventListener("click", () => {
      const out = build();
      if (out) download(fileName(out.game, out.label), out.markdown);
    });
    const sync = () => { btn.hidden = !build(); };
    sync();
    return { sync };
  }

  return { arena, attach, disaster, duel, fileName, guess, persuasion, referendum, rumor };
}));
