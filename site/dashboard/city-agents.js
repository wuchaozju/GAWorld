(function (root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GAWorldCityAgents = api;
  }
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  /* Shared renderers for "the residents of city X".
   *
   * Two panels show the same list and must not drift apart:
   *
   *   城市 page   — every resident of the city you are inspecting
   *   Agent Studio — the residents of whichever city you picked, so you can
   *                  look at another city's people without switching the run
   *
   * Pure functions, no DOM, so `node site/dashboard/city-agents.test.js`
   * covers them — the same split survey-charts.js and persona-view.js use.
   *
   * One rule runs through all of it: **an agent id is only unique inside its
   * city.** Every city has a #1. So the city's name travels with the list and
   * with the detail, and the id is always rendered next to it rather than on
   * its own. A panel that showed "#1 阿甲" with no city would be ambiguous in
   * a way that is impossible to notice and easy to act on.
   */

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /** i18n with an inline Chinese fallback, same contract as survey.js. */
  function t(key, fallback) {
    if (typeof globalThis.__ !== "function") return fallback;
    const value = globalThis.__("ca." + key);
    return value && value !== "ca." + key ? value : fallback;
  }

  function tf(key, fallback, params) {
    let text = t(key, fallback);
    Object.keys(params || {}).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(params[name]));
    });
    return text;
  }

  /** "共 80 人" / "共 80 人，显示前 200" / "搜索到 3 人". */
  function countLabel(payload) {
    const p = payload || {};
    const matched = p.matched || 0;
    const shown = (p.agents || []).length;
    if (!matched) return t("none", "没有居民");
    if (shown < matched) return tf("count_paged", "共 {matched} 人，显示 {shown} 人", { matched: matched, shown: shown });
    return tf("count", "共 {matched} 人", { matched: matched });
  }

  /** <option> list for a city picker; `selected` is a slug ("" = default world). */
  function cityOptions(cities, selected) {
    return (cities || []).map(function (city) {
      const label = city.name + (city.count != null ? "（" + city.count + "）" : "");
      const isOn = String(city.slug) === String(selected == null ? "" : selected);
      return '<option value="' + esc(city.slug) + '"' + (isOn ? " selected" : "") + ">" +
        esc(label) + "</option>";
    }).join("");
  }

  /** <option> list for an agent picker, ids rendered beside names. */
  function agentOptions(agents, selectedId) {
    return (agents || []).map(function (person) {
      const isOn = String(person.id) === String(selectedId);
      return '<option value="' + esc(person.id) + '"' + (isOn ? " selected" : "") + ">" +
        esc(person.id + " · " + (person.name || "")) + "</option>";
    }).join("");
  }

  /** The residents table. `linkHref(person)` opts each row into a link out. */
  function agentTable(payload, linkHref) {
    const agents = (payload || {}).agents || [];
    if (!agents.length) {
      return '<p class="ca-empty">' + esc(t("empty", "这座城市还没有居民。")) + "</p>";
    }
    const head =
      "<tr><th>" + esc(t("h_id", "ID")) + "</th><th>" + esc(t("h_name", "姓名")) +
      "</th><th>" + esc(t("h_who", "性别 · 年龄")) + "</th><th>" + esc(t("h_hukou", "户籍")) +
      "</th><th>" + esc(t("h_residence", "居住")) + "</th><th>" + esc(t("h_job", "职业")) +
      "</th>" + (linkHref ? "<th></th>" : "") + "</tr>";
    const rows = agents.map(function (person) {
      const who = [person.gender, person.age ? person.age + t("years", "岁") : ""]
        .filter(Boolean).join(" · ");
      const open = linkHref
        ? '<td><a class="ca-open" href="' + esc(linkHref(person)) + '">' +
          esc(t("open", "在工作台查看")) + "</a></td>"
        : "";
      return '<tr data-agent-id="' + esc(person.id) + '">' +
        "<td>" + esc(person.id) + "</td>" +
        "<td>" + esc(person.name || "—") + "</td>" +
        "<td>" + esc(who || "—") + "</td>" +
        "<td>" + esc(person.hukou || "—") + "</td>" +
        "<td>" + esc(person.residence || "—") + "</td>" +
        '<td class="ca-job">' + esc(person.job || "—") + "</td>" + open +
        "</tr>";
    }).join("");
    return '<table class="ca-table"><thead>' + head + "</thead><tbody>" + rows + "</tbody></table>";
  }

  /** Label/value pairs for one resident, city included on purpose. */
  function identityRows(agent, city) {
    const person = agent || {};
    const where = (city || {}).name || "";
    return [
      [t("f_city", "所属城市"), where],
      [t("f_id", "编号"), person.id == null ? "" : "#" + person.id],
      [t("f_who", "性别 · 年龄"), [person.gender, person.age ? person.age + t("years", "岁") : ""].filter(Boolean).join(" · ")],
      [t("f_hukou", "户籍"), person.hukou],
      [t("f_residence", "居住"), person.residence],
      [t("f_job", "职业"), person.job],
    ].filter(function (row) { return row[1]; });
  }

  /** The banner shown when Studio is looking at a city that is not running. */
  function browseNotice(city) {
    const name = (city || {}).name || "";
    return '<div class="ca-notice">' +
      "<b>" + esc(tf("browsing", "正在查看「{name}」，只读", { name: name })) + "</b>" +
      "<p>" + esc(t("browsing_why",
        "编辑、记忆、大五人格、社交与财务只对当前运行的城市可用：智能体编号在每座城市里各自从 1 开始，" +
        "而这些数据按编号存放，跨城市读会张冠李戴。要编辑这座城市的居民，先把它设为当前城市。")) + "</p>" +
      '<button type="button" class="button" id="caUseCityBtn">' +
        esc(t("use_city", "设为当前城市")) + "</button>" +
      "</div>";
  }

  return {
    agentOptions,
    agentTable,
    browseNotice,
    cityOptions,
    countLabel,
    esc,
    identityRows,
  };
}));
