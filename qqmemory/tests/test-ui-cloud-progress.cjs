// Exercise running and completed states without a QQ account or server.
const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
class Element {
  constructor() {
    this.hidden = false;
    this.textContent = "";
    this.checked = false;
    this.children = [];
  }
  addEventListener() {}
  removeAttribute() {}
  replaceChildren(...children) {
    this.children = children;
  }
  appendChild(e) {
    this.children.push(e);
  }
}
const elements = new Map();
for (const [, id] of fs
  .readFileSync("qqmemory/qqmemory/cloud_ui/index.html", "utf8")
  .matchAll(/id="([^"]+)"/g))
  elements.set(id, new Element());
const context = vm.createContext({
  Date,
  console,
  setTimeout() {
    return 1;
  },
  clearTimeout() {},
  document: { getElementById: (id) => elements.get(id), createElement: () => new Element() },
  fetch: async () => ({ ok: true, json: async () => ({ csrf: "synthetic", jobs: [] }) }),
});
vm.runInContext(fs.readFileSync("qqmemory/qqmemory/cloud_ui/app.js", "utf8"), context);
const job = {
  id: "test",
  active: true,
  phase: "collecting",
  message: "collecting",
  expires: 0,
  counts: {
    posts: 68,
    photos_found: 350,
    photos_saved: 120,
    photos_failed: 2,
    earliest_published: 1577836800,
    earliest_interaction: 1230768000,
  },
  collection_elapsed: 600,
  collection_limit: 1800,
  progress: {
    stage: "deep",
    label: "深度扫描",
    done: 10,
    total: 100,
    percent: 10,
    elapsed: 630,
    eta: [60, 240],
  },
};
context.job = job;
vm.runInContext("render(job)", context);
assert.equal(elements.get("live-status").hidden, false);
assert.match(elements.get("live-counts").textContent, /68 条记录.*120.*350.*失败 2/);
assert.match(elements.get("live-time").textContent, /20 分 0 秒/);
assert.match(elements.get("live-time").textContent, /当前阶段粗估/);
assert.match(elements.get("progress").textContent, /10 \/ 100.*非恢复比例/);
assert.equal(elements.get("stage-meter").value, 10);
assert.match(elements.get("earliest-date").textContent, /2020.*01.*01.*08:00/);
assert.match(elements.get("earliest-date").textContent, /最早已知互动.*不代表发帖时间/);
context.job = { ...job, phase: "stopping" };
vm.runInContext("render(job)", context);
assert.equal(elements.get("stop").disabled, true);
assert.match(elements.get("phase").textContent, /暂停/);
assert.match(elements.get("progress").textContent, /停止新采集/);
context.job = job;
job.progress = { stage: "visible", elapsed: 1 };
job.counts = {};
vm.runInContext("render(job)", context);
assert.equal(elements.get("stage-meter").hidden, true);
assert.match(elements.get("live-counts").textContent, /第一批/);
assert.match(elements.get("earliest-date").textContent, /暂未取得/);
job.phase = "exporting";
job.collection_elapsed = 1900;
vm.runInContext("render(job)", context);
assert.match(elements.get("live-time").textContent, /正在打包/);
assert.doesNotMatch(elements.get("live-time").textContent, /-/);
job.active = false;
job.ready = true;
job.inline_ready = false;
job.stats = { exported_posts: 68, exported_photos: 350 };
job.parts = [
  { kind: "part-001", size: 64 },
  { kind: "part-002", size: 65 },
];
vm.runInContext("render(job)", context);
assert.equal(elements.get("live-status").hidden, true);
assert.equal(elements.get("zip-parts").children.length, 2);
assert.equal(elements.get("html").hidden, true);
console.log("云端实时数量、阶段进度、采集时限、打包与分包入口检查通过");

context.liveData = {
  total: 1,
  offset: 0,
  posts: [
    {
      id: "p",
      author: "测试",
      date: "2020",
      time_basis: "published",
      content: "<script>alert(1)</script>",
      likes: 1,
      comment_count: 0,
      comments: [],
      media: [{ id: "m", state: "pending", url: null, quality_verified: false }],
    },
  ],
};
vm.runInContext("renderLivePreview(liveData)", context);
const cardNode = elements.get("preview-cards").children[0];
assert.equal(cardNode.children[2].textContent, "<script>alert(1)</script>");
const photoNode = cardNode.children[3].children[0];
assert.equal(photoNode.children[0].hidden, true);
context.liveData.posts[0].media[0] = {
  id: "m",
  state: "saved",
  url: "/api/jobs/test/media/m?v=one",
  quality_verified: false,
};
vm.runInContext("renderLivePreview(liveData)", context);
assert.equal(elements.get("preview-cards").children[0], cardNode);
assert.equal(photoNode.children[0].hidden, false);
assert.match(photoNode.children[1].textContent, /高清待检查/);
Object.defineProperty(photoNode.children[0], "src", {
  set() {
    assert.fail("unchanged images must not reload on every poll");
  },
  configurable: true,
});
vm.runInContext("renderLivePreview(liveData)", context);
context.liveData.posts[0].media[0].quality_verified = true;
vm.runInContext("renderLivePreview(liveData)", context);
assert.match(photoNode.children[1].textContent, /清晰度已检查.*不保证原图/);
console.log("云端正文安全展示、图片逐张出现、清晰度状态与轮询图片复用检查通过");
