/* Shared recruitment controls. Category values come from /api/population/schema. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GAWorldResidentFilters = api;
})(globalThis, function (root) {
  "use strict";
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
  const fallback = {education:"已获最高学历", student_status:"当前在读阶段", gender:"性别", age_min:"最小年龄", age_max:"最大年龄", job:"职业关键词", query:"搜索姓名 / 编号 / 背景", any:"不限", unknown:"未知", count:"符合条件 {count} / {total} 人"};
  function label(key) {
    const value = typeof root.__ === "function" ? root.__("sample." + key) : "";
    return value && value !== "sample." + key ? value : fallback[key] || key;
  }
  function valueLabel(value) {
    const key = "sample.value." + value;
    const translated = typeof root.__ === "function" ? root.__(key) : "";
    return translated && translated !== key ? translated : value;
  }
  function matches(person, filters) {
    filters = filters || {};
    const hasAgeFilter = [filters.age_min, filters.age_max].some(v => v != null && v !== "");
    if (hasAgeFilter && (person.age == null || person.age === "" || !Number.isFinite(Number(person.age)))) return false;
    if (filters.age_min != null && filters.age_min !== "" && Number(person.age) < Number(filters.age_min)) return false;
    if (filters.age_max != null && filters.age_max !== "" && Number(person.age) > Number(filters.age_max)) return false;
    if (filters.gender && person.gender !== filters.gender) return false;
    if (filters.education && (person.education || "未知") !== filters.education) return false;
    const status = person.student_status || "未知";
    const accepted = {"大学生":["大学生", "大专", "本科"], "研究生":["研究生", "硕士", "博士"]};
    if (filters.student_status === "在读" && ["未知", "非在读"].includes(status)) return false;
    if (filters.student_status && filters.student_status !== "在读" && !(accepted[filters.student_status] || [filters.student_status]).includes(status)) return false;
    if (filters.job && !String(person.job || "").toLowerCase().includes(String(filters.job).toLowerCase())) return false;
    const hay = [person.name, "#" + person.id, person.job, person.education, person.student_status].join(" ").toLowerCase();
    return !filters.query || hay.includes(String(filters.query).toLowerCase());
  }
  function controls(schema, filters, prefix, options) {
    schema = schema || {}; filters = filters || {}; options = options || {};
    const select = (key, values) => {
      const entries = [...new Set(["", ...values, filters[key] || ""])];
      return '<label class="field"><span>' + esc(label(key)) + '</span><select id="' + esc(prefix + "-" + key) + '" data-rf="' + key + '">' + entries.map(value => '<option value="' + esc(value) + '"' + (value === (filters[key] || "") ? " selected" : "") + '>' + esc(value ? valueLabel(value) : label("any")) + '</option>').join("") + '</select></label>';
    };
    const input = (key, numeric) => '<label class="field"><span>' + esc(label(key)) + '</span><input id="' + esc(prefix + "-" + key) + '" data-rf="' + key + '" type="' + (numeric ? 'number" min="0" max="120' : 'search') + '" value="' + esc(filters[key]) + '" /></label>';
    return '<div class="resident-filters">' + select("education", ["未知", ...(schema.education_levels || [])]) + select("student_status", schema.student_statuses || []) + select("gender", ["女", "男"]) + input("age_min", true) + input("age_max", true) + input("job", false) + (options.query === false ? "" : input("query", false)) + '</div>';
  }
  function read(host) {
    const result = {};
    host.querySelectorAll("[data-rf]").forEach(el => {
      const key = el.dataset.rf;
      result[key] = el.value === "" ? null : key.startsWith("age_") ? Number(el.value) : el.value.trim();
    });
    return result;
  }
  function count(matching, total) { return label("count").replace("{count}", matching).replace("{total}", total); }
  return {matches, controls, read, count, label, valueLabel};
});
