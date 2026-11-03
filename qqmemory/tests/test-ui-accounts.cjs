// Offline UI contract: account navigation and progress use synthetic archives only.
const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.attrs = {};
    this.classList = { toggle() {}, add() {}, remove() {} };
    this.open = false;
    this.value = "collect";
    this.textContent = "";
  }
  set id(value) {
    this._id = value;
    elements.set(value, this);
  }
  get id() {
    return this._id;
  }
  append(...values) {
    this.children.push(...values);
  }
  prepend(...values) {
    this.children.unshift(...values);
  }
  replaceChildren(...values) {
    this.children = values;
  }
  setAttribute(k, v) {
    this.attrs[k] = v;
  }
  removeAttribute(k) {
    delete this.attrs[k];
  }
  addEventListener() {}
  querySelector() {
    return null;
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
  getBoundingClientRect() {
    return { left: 0, top: 0, bottom: 30 };
  }
  contains(v) {
    return v === this;
  }
}
const html = fs.readFileSync("qqmemory/qqmemory/ui/index.html", "utf8"),
  elements = new Map();
for (const [, id] of html.matchAll(/id="([^"]+)"/g)) elements.set(id, new Element());
elements.get("workers").value = "6";
const calls = [];
let selected = "123",
  active = false,
  intent,
  taskId = null,
  deferStart = false,
  resolveStart,
  mediaMode = false,
  missingPhotos = 0;
const posts = () => [
  {
    id: "post-" + selected,
    author: { uin: selected, nickname: selected },
    media: [],
    likes: [],
    comments: [],
    content: "archive-" + selected,
    year: "2020",
    date: "2020",
    category: "posts",
  },
];
const state = () => ({
  account: selected,
  nickname: selected,
  active,
  phase: active ? "login" : "ready",
  mode: mediaMode ? "media" : "collect",
  task_id: taskId,
  qr_status: "waiting",
  task_account: active && intent !== "add" ? selected : null,
  qr: active ? "data:image/png;base64,example" : null,
  posts: posts(),
  total: 1,
  years: ["2020"],
  category_counts: { posts: 1 },
  stats: { posts: 1, photos_pending: missingPhotos },
  events: [],
  message: "saved",
  progress: { stage: "login", elapsed: 0 },
});
const context = vm.createContext({
  URLSearchParams,
  AbortController,
  Date,
  console,
  location: { search: "" },
  clearTimeout() {},
  setTimeout() {
    return 1;
  },
  window: {
    addEventListener() {},
    innerWidth: 1200,
    innerHeight: 800,
    scrollBy() {},
    scrollTo() {},
  },
  document: {
    hidden: false,
    body: new Element(),
    getElementById(id) {
      return elements.get(id) || null;
    },
    createElement(tag) {
      return new Element(tag);
    },
    createDocumentFragment() {
      return new Element();
    },
    createTextNode(text) {
      return { textContent: text };
    },
    addEventListener() {},
  },
  async fetch(path, options = {}) {
    calls.push({ path, body: options.body && JSON.parse(options.body) });
    let data;
    if (path.startsWith("api/state")) data = state();
    else if (path === "api/accounts")
      data = {
        selected,
        accounts: [
          { uin: "123", nickname: "First", posts: 1, photos: 0, modified: 1 },
          { uin: "456", nickname: "Second", posts: 2, photos: 3, modified: 2 },
        ],
      };
    else if (path === "api/accounts/select") {
      selected = JSON.parse(options.body).uin;
      data = { ok: true };
    } else if (path === "api/start" || path === "api/upgrade") {
      intent = JSON.parse(options.body).intent;
      mediaMode = path === "api/upgrade";
      if (deferStart)
        await new Promise((resolve) => {
          resolveStart = resolve;
        });
      active = true;
      taskId = "task-" + calls.length;
      data = { ok: true, started: true, task_id: taskId };
    } else if (path === "api/stop") {
      active = false;
      data = { ok: true };
    } else throw Error("Unexpected request " + path);
    return { ok: true, json: async () => data };
  },
});
vm.runInContext(fs.readFileSync("qqmemory/qqmemory/ui/app.js", "utf8"), context);
const flush = () => new Promise((resolve) => setImmediate(resolve));
(async () => {
  await flush();
  assert.equal(
    calls.some((c) => c.path === "api/start"),
    false,
    "Opening local archives must not start QR login",
  );
  await elements.get("account-switch").onclick();
  assert.equal(elements.get("accounts-dialog").open, true);
  await elements.get("account-list").children[1].onclick();
  assert.equal(selected, "456");
  assert.equal(elements.get("profile-name").textContent, "456");
  assert.equal(
    calls.some((c) => c.path === "api/start"),
    false,
  );
  await vm.runInContext("startLogin('update')", context);
  assert.equal(elements.get("qr-dialog").open, true);
  assert.equal(
    calls.some((c) => c.path === "api/start"),
    false,
    "Settings must not start QR or network activity",
  );
  vm.runInContext("render(current)", context);
  assert.equal(elements.get("qr-dialog").open, true, "Ready polling must not close settings");
  elements.get("download-speed").value = "2";
  elements.get("download-speed").onchange();
  assert.equal(elements.get("workers").value, "2");
  deferStart = true;
  const starting = elements.get("qr-start").onclick();
  await flush();
  vm.runInContext("render(current)", context);
  assert.equal(elements.get("qr-dialog").open, true, "Old state during start must not dismiss QR");
  resolveStart();
  await starting;
  await flush();
  assert.equal(calls.find((c) => c.path === "api/start").body.intent, "update");
  assert.equal(calls.find((c) => c.path === "api/start").body.workers, 2);
  assert.match(elements.get("login-description").textContent, /456/);
  vm.runInContext("render({...current, phase:'ready', active:false, task_id:'old-task'})", context);
  assert.equal(elements.get("qr-dialog").open, true, "A different task snapshot cannot dismiss QR");
  vm.runInContext("render({...current, phase:'login', active:true})", context);
  assert.equal(
    elements.get("scan-progress").hidden,
    true,
    "Waiting for a person must not animate a progress bar",
  );
  await elements.get("qr-back").onclick();
  await flush();
  assert.equal(elements.get("login-settings").hidden, false);
  assert.equal(active, false);
  await elements.get("qr-close").onclick();
  const before = calls.length;
  await elements.get("upgrade").onclick();
  assert.equal(calls.length, before, "No missing photos must not request QR");
  assert.equal(elements.get("qr-dialog").open, false);
  missingPhotos = 3;
  deferStart = false;
  await vm.runInContext("poll()", context);
  await elements.get("upgrade").onclick();
  assert.equal(elements.get("mode-setting").hidden, true, "Image-only task has no collection mode");
  assert.equal(elements.get("workers").disabled, false);
  elements.get("download-speed").value = "10";
  elements.get("download-speed").onchange();
  await elements.get("qr-start").onclick();
  assert.equal(calls.find((c) => c.path === "api/upgrade").body.workers, 10);
  await elements.get("qr-close").onclick();
  vm.runInContext(
    "renderTask({active:true,phase:'collecting',task_account:'123',account:'456',mode:'deep',events:[],message:'working',progress:{stage:'deep',label:'深度扫描',done:10,total:100,percent:10,elapsed:30,eta:[100,400]}})",
    context,
  );
  assert.equal(elements.get("scan-progress").value, 10);
  assert.match(elements.get("scan-estimate").textContent, /不代表历史内容找回比例/);
  assert.match(elements.get("task-message").textContent, /123/);
  console.log("本地切换、无自动扫码、更新账号提示、任务归属和分阶段进度检查通过");
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
