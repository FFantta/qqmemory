const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const source = fs.readFileSync("qqmemory/qqmemory/templates/offline.js", "utf8");
const context = vm.createContext({});
vm.runInContext(source.slice(0, source.indexOf("const get =")), context);
const card = {
  textContent: "Synthetic MEMORY 评论",
  dataset: { category: "posts", year: "2020", photos: "true" },
};
assert.equal(context.matchesOffline(card, " memory ", "posts", "2020", true), true);
assert.equal(context.matchesOffline(card, "missing", "", "", false), false);
assert.equal(context.matchesOffline(card, "", "blogs", "", false), false);
assert.equal(context.matchesOffline(card, "", "", "2021", false), false);
assert.equal(
  context.matchesOffline(
    { ...card, dataset: { ...card.dataset, photos: "false" } },
    "",
    "",
    "",
    true,
  ),
  false,
);
console.log("离线分类、年份、正文与评论搜索和有图筛选检查通过");

const records = [
  card,
  { textContent: "gift", dataset: { category: "gifts", year: "2018", photos: "false" } },
  { textContent: "gift photo", dataset: { category: "gifts", year: "2022", photos: "true" } },
  { ...card, dataset: { ...card.dataset, year: "2021" } },
];
const years = (...args) => Array.from(context.availableOfflineYears(...args));
assert.deepEqual(years(records, "", "posts", false), ["2021", "2020"]);
assert.deepEqual(years(records, "", "gifts", false), ["2022", "2018"]);
assert.deepEqual(years(records, "", "gifts", true), ["2022"]);
assert.deepEqual(years(records, "missing", "gifts", false), []);
assert.equal(context.validOfflineYear("2020", years(records, "", "gifts", false)), "");
assert.equal(context.validOfflineYear("2022", years(records, "", "gifts", false)), "2022");
console.log("分类切换、搜索和有图筛选联动年份及无效年份重置检查通过");
