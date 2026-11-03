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
