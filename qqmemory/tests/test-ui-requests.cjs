// Exercise delayed/out-of-order responses without a browser or account data.
const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const source = fs.readFileSync("qqmemory/qqmemory/ui/app.js", "utf8");
const coordinator = source.slice(
  source.indexOf("// BEGIN state request coordinator"),
  source.indexOf("// END state request coordinator"),
);
assert.ok(
  coordinator.includes("async function poll"),
  "Coordinator markers must identify polling code",
);
const elements = new Map();
const get = (id) => {
  if (!elements.has(id))
    elements.set(id, {
      classList: { toggle() {} },
      children: [],
      setAttribute() {},
      removeAttribute() {},
    });
  return elements.get(id);
};
const calls = [],
  renders = [];
const context = vm.createContext({
  AbortController,
  URLSearchParams,
  document: { hidden: false },
  location: { search: "?browse=1" },
  $: get,
  categoryNames: { blogs: "日志", interactions: "互动" },
  category: "",
  photosOnly: false,
  year: "",
  query: "",
  offset: 0,
  pageCache: new Map(),
  cache: new Map(),
  requestNumber: 0,
  stateRequest: null,
  refreshTimer: null,
  polling: false,
  boot: false,
  current: { account: "demo", active: false },
  clearTimeout() {},
  setTimeout() {
    return 1;
  },
  api(path, body, signal) {
    return new Promise((resolve) => calls.push({ path, signal, resolve }));
  },
  render(data) {
    renders.push(data.marker);
    context.current = data;
  },
});
vm.runInContext(coordinator, context);
(async () => {
  const first = context.poll();
  context.category = "blogs";
  const second = context.poll();
  assert.equal(calls.length, 2, "A click must not be dropped behind a background request");
  assert.equal(calls[0].signal.aborted, true, "New selection cancels the old request");
  const result = (marker) => ({
    marker,
    account: "demo",
    active: false,
    posts: [],
    total: 0,
    years: [],
    category_counts: {},
  });
  calls[1].resolve(result("new-selection"));
  await second;
  calls[0].resolve(result("stale-selection"));
  await first;
  assert.deepEqual(renders, ["new-selection"], "Late responses cannot replace the selected view");
  context.document.hidden = true;
  await context.poll(false);
  assert.equal(calls.length, 2, "Hidden windows must not keep polling");
  console.log("UI请求优先级、过期响应和后台暂停检查通过");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
