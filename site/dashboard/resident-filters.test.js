"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const filters = require("./resident-filters.js");

test("university enrollment excludes same-age workers and missing data", () => {
  const people = [
    {id:1, age:20, gender:"女", education:"高中/中专", student_status:"本科", job:"本科学生"},
    {id:2, age:20, gender:"女", education:"本科", student_status:"非在读", job:"工程师"},
    {id:3, age:20, gender:"女"},
    {id:4, age:20, gender:"男", student_status:"本科"},
  ];
  assert.deepEqual(people.filter(p => filters.matches(p, {age_min:18, age_max:24, gender:"女", student_status:"大学生"})).map(p=>p.id), [1]);
});

test("degree, job, and free-text searches intersect and escape markup", () => {
  const person = {id:5, name:"<学生>", age:24, education:"本科", student_status:"硕士", job:"硕士研究生"};
  assert.equal(filters.matches(person, {education:"本科", student_status:"研究生", job:"研究", query:"#5"}), true);
  assert.equal(filters.matches(person, {education:"大专"}), false);
  const html = filters.controls({education_levels:["本科"], student_statuses:["未知", "本科"]}, {query:'"><script>'}, "sample");
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(!html.includes('"><script>'));
});

test("unknown ages cannot satisfy an upper age bound", () => {
  assert.equal(filters.matches({name:"未知"}, {age_max:25}), false);
  assert.equal(filters.matches({age:0}, {age_max:25}), true);
});
