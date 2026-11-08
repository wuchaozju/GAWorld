"use strict";

/**
 * Pure helpers for the cooperation page's organization-method picker.
 *
 * They live outside the page script so the wording and the option list can be
 * unit-tested without a DOM, and so the picker and the note under it always
 * describe a method the same way.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.OrganizationPickerCore = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  const EVIDENCE = {
    better: ["有优势证据", "Evidence of improvement"],
    worse: ["本次表现较差", "Lower scores in the study"],
    uncertain: ["尚无优势证据", "No established advantage"],
    incomplete: ["尚未验证", "Not validated"],
    builtin: ["内置基本组织方式", "Built-in structure"],
  };

  function evidence(verdict, en) {
    const entry = EVIDENCE[verdict] || EVIDENCE.incomplete;
    return en ? entry[1] : entry[0];
  }

  function roleCount(method) {
    const roles = (method && method.method && method.method.roles) || [];
    return roles.length;
  }

  function entries(methods) {
    return (methods || []).map(function (method) {
      return {
        id: method.id,
        name: method.name || "",
        version: method.version || 1,
        roles: roleCount(method),
        builtin: Boolean(method.builtin),
        verdict: (method.evidence && method.evidence.verdict) || "incomplete",
        description: method.description || "",
        rolesText: ((method.method && method.method.roles) || []).join(" → "),
      };
    });
  }

  function label(entry, en) {
    if (entry.builtin) {
      return en
        ? `${entry.name} · built-in structure`
        : `${entry.name} · 内置基本组织方式`;
    }
    const members = en ? `${entry.roles} members` : `${entry.roles} 位`;
    return `${entry.name} · v${entry.version} · ${members}`;
  }

  function describe(entry, members, en) {
    if (!entry) {
      return en
        ? "Use the existing planning, execution, review and synthesis flow. The built-in structures take their role count from the team you pick; saved methods come from Research → Organization intelligence."
        : "使用现有的分工、执行、审阅和汇总流程。内置的基本组织方式会按你选的人数生成角色；保存过的组织方式来自「研究工作台 → 组织智能」。";
    }
    if (entry.builtin) {
      const team = en
        ? `A team of ${members} will run ${members} roles.`
        : `当前团队 ${members} 位成员，将生成 ${members} 个角色。`;
      const scope = en
        ? "This structure has not been validated on this task."
        : "该结构未在本任务上验证。";
      return [entry.description, team, scope].filter(Boolean).join(" ");
    }
    const membersText = en ? `${entry.roles} members` : `${entry.roles} 位成员`;
    const version = en ? `version ${entry.version}` : `版本${entry.version}`;
    const status = evidence(entry.verdict, en);
    const head = en
      ? `${membersText} · ${version} · ${entry.rolesText}.`
      : `${membersText} · ${version} · ${entry.rolesText}。`;
    const mismatch =
      members && entry.roles !== members
        ? en
          ? ` The saved method has ${entry.roles} roles but the team has ${members} members.`
          : `保存的组织方式有 ${entry.roles} 个角色，与当前 ${members} 位成员不符。`
        : "";
    const scope = en
      ? "This task is outside the tested benchmark, so treat it as an unvalidated configuration."
      : "本任务超出原研究题库，作为未验证配置使用。";
    const statusText = en ? `Evidence: ${status}.` : `验证状态：${status}。`;
    return head + mismatch + statusText + scope;
  }

  return {
    evidence: evidence,
    entries: entries,
    label: label,
    describe: describe,
  };
});
