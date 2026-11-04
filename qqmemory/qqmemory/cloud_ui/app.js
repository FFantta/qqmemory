"use strict";
const $ = (id) => document.getElementById(id);
let csrf = "",
  current = null,
  polling = null,
  busy = false,
  pausePending = null;
let previewOffset = 0,
  previewTask = null,
  previewSequence = 0;
const previewCards = new Map();
const phases = {
  login: "等待 QQ 扫码",
  collecting: "正在整理回忆",
  stopping: "正在暂停并保存",
  exporting: "正在生成离线文件",
  done: "归档已生成",
  partial: "本轮结果已保存",
  error: "任务未完成",
  cancelled: "已取消",
};
// Keep CSRF and response errors consistent for all task actions.
async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("服务暂时不可用，请稍后重试");
  }
  if (!response.ok) throw new Error(data.error || "请求未完成，请重试");
  return data;
}
function duration(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  return n < 60 ? n + " 秒" : Math.floor(n / 60) + " 分 " + (n % 60) + " 秒";
}
// Render a server snapshot. A pending pause remains visible until the server acknowledges it.
function render(job) {
  if (pausePending === job.id && job.active && ["login", "collecting"].includes(job.phase))
    job = { ...job, phase: "stopping", message: "暂停请求已提交，正在等待后台确认并保存已有成果…" };
  if (!job.active && pausePending === job.id) pausePending = null;
  current = job;
  $("task").hidden = false;
  $("phase").textContent =
    job.mode === "quality" && job.phase === "collecting"
      ? "正在检查并补全高清"
      : phases[job.phase] || "正在处理";
  $("message").textContent = job.message;
  $("expiry").textContent = "最晚保留至 " + new Date(job.expires * 1000).toLocaleTimeString();
  const hasQR = typeof job.qr === "string" && job.qr.startsWith("data:image/png;base64,");
  $("qr-area").hidden = !hasQR;
  if (hasQR) {
    $("qr").src = job.qr;
    $("save-qr").href = job.qr;
  } else {
    $("qr").removeAttribute("src");
    $("save-qr").removeAttribute("href");
  }
  $("results").hidden = !job.ready;
  $("continue").hidden = !job.can_continue;
  $("quality").hidden =
    !job.can_continue || !(job.counts?.photos_saved || job.stats?.exported_photos);
  $("live-preview").hidden = !job.can_live_preview;
  $("preview-status").textContent = job.active
    ? "采集中，内容尚未完整；图片保存后逐张显示，评论与点赞会陆续补齐。"
    : "本轮已停止，以下为当前保存的内容；完整结果请下载离线档案。";
  $("html").hidden = !job.inline_ready;
  $("stop").hidden = !job.active;
  $("stop").disabled = ["stopping", "exporting"].includes(job.phase);
  $("stop").textContent =
    job.phase === "stopping"
      ? "正在暂停并保存…"
      : job.phase === "exporting"
        ? "正在生成下载文件…"
        : job.phase === "login"
          ? "取消本次扫码"
          : "暂停并生成已有结果";
  $("refresh-qr").hidden = !job.can_refresh;
  $("refresh-qr").disabled = job.active && !hasQR;
  $("refresh-qr").textContent = job.active ? "刷新二维码" : "重新扫码";
  $("start").disabled = job.active || !$("consent").checked;
  const p = job.progress || {};
  const collecting = job.active && ["collecting", "stopping", "exporting"].includes(job.phase);
  $("live-status").hidden = !collecting;
  $("earliest-date").hidden = !collecting && !job.ready;
  const c = job.counts || {};
  $("live-counts").textContent = Object.hasOwn(c, "posts")
    ? "已取得 " +
      c.posts +
      " 条记录 · 图片已保存 " +
      c.photos_saved +
      " / 已发现 " +
      c.photos_found +
      " 张" +
      (c.photos_quality_pending ? " · " + c.photos_quality_pending + " 张高清待检查" : "") +
      (c.photos_failed ? " · 失败 " + c.photos_failed + " 张" : "") +
      (c.details_pending ? " · " + c.details_pending + " 条线索的互动待整理" : "")
    : "正在请求第一批内容，取得后会显示数量…";
  const formatDate = (value) =>
    new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(value * 1000));
  const oldest = c.earliest_published;
  $("earliest-date").textContent =
    oldest != null
      ? "已取得说说中最早的发布时间：" + formatDate(oldest) + "（北京时间）"
      : "最早发布时间：暂未取得";
  if (c.earliest_interaction != null)
    $("earliest-date").textContent +=
      " · ≈ 最早已知互动：" + formatDate(c.earliest_interaction) + "（北京时间，不代表发帖时间）";
  let timing = "已用 " + duration(p.elapsed);
  if (job.collection_elapsed != null) {
    const left = Math.max(0, job.collection_limit - job.collection_elapsed);
    timing +=
      job.phase === "exporting"
        ? " · 正在打包，完成后出现下载入口"
        : left
          ? " · 本轮采集时限剩余 " + duration(left) + "，之后还需生成文件"
          : " · 已到本轮采集时限，正在收尾并生成文件";
  }
  if (Array.isArray(p.eta) && p.eta.length === 2)
    timing += " · 当前阶段粗估还需 " + duration(p.eta[0]) + "—" + duration(p.eta[1]);
  $("live-time").textContent = timing;
  const measured = p.total > 0 && p.percent != null;
  $("stage-meter").hidden = !collecting || !measured || job.phase === "stopping";
  if (measured) $("stage-meter").value = p.percent;
  $("progress").textContent =
    (p.label || p.stage || "") +
    (measured ? " · " + p.done + " / " + p.total + "（" + p.percent + "%）" : "") +
    (p.stage === "deep" ? " · 扫描计划进度，非恢复比例" : "");
  if (job.phase === "stopping")
    $("progress").textContent =
      "停止新采集 → 收尾当前网络请求 → 生成已有结果；此过程仍需一点时间。";
  if (job.ready) {
    const base = "/jobs/" + encodeURIComponent(job.id);
    $("preview").href = base + "/preview/index.html";
    $("html").href = base + "/download/html";
    $("zip").href = base + "/download/zip";
    const parts = job.parts || [];
    $("zip").hidden = parts.length !== 1;
    $("zip-parts").replaceChildren();
    if (parts.length > 1)
      for (const [i, part] of parts.entries()) {
        const a = document.createElement("a");
        a.href = base + "/download/" + encodeURIComponent(part.kind);
        a.textContent =
          (i === 0 ? "下载第 1 包：HTML + 首批图片" : "下载第 " + (i + 1) + " 包：后续图片") +
          " / 共 " +
          parts.length +
          " 包" +
          "（" +
          (part.size / 1024 / 1024).toFixed(1) +
          " MiB）";
        $("zip-parts").appendChild(a);
      }
    $("stats").textContent =
      "已保存 " +
      (job.stats.exported_posts || 0) +
      " 条记录、" +
      (job.stats.exported_photos || 0) +
      " 张照片。" +
      (job.incomplete ? "本轮范围或时间有限，结果可能不完整。" : "");
  }
  if (polling) clearTimeout(polling);
  if (job.active) polling = setTimeout(refresh, 2000);
}
// Poll only one request at a time; completed tasks stop scheduling refreshes.
async function refresh() {
  if (!current || busy) return;
  busy = true;
  try {
    const id = current.id;
    const job = await api("/api/jobs/" + encodeURIComponent(id));
    if (!current || current.id !== id) return;
    render(job);
    await refreshPreview();
    $("error").textContent = "";
  } catch (error) {
    $("error").textContent = error.message + "；可以刷新本页重新连接。";
    polling = setTimeout(refresh, 5000);
  } finally {
    busy = false;
  }
}
function make(tag, className, text) {
  const e = document.createElement(tag);
  e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}
function renderLivePreview(data) {
  const ids = data.posts.map((post) => post.id);
  const previousIds = [...previewCards.keys()];
  const orderChanged = ids.join("|") !== previousIds.join("|");
  const next = new Map();
  for (const post of data.posts) {
    let view = previewCards.get(post.id);
    if (!view) {
      const node = make("article", "live-card");
      view = {
        node,
        title: make("h4", ""),
        date: make("p", "hint"),
        body: make("p", "live-content"),
        media: make("div", "live-photos"),
        social: make("p", "hint"),
        comments: make("p", "live-comments"),
        images: new Map(),
      };
      for (const part of [view.title, view.date, view.body, view.media, view.social, view.comments])
        node.appendChild(part);
    }
    view.title.textContent = post.author;
    view.date.textContent =
      post.date + (post.time_basis === "interaction" ? " · ≈ 最早互动，并非发帖时间" : "");
    view.body.textContent = post.content;
    view.social.textContent = `已取得 ${post.likes} 个点赞 · ${post.comment_count} 条评论（可能尚未完整）`;
    view.comments.textContent = post.comments
      .map((c) =>
        [
          c.author + "：" + c.content,
          ...(c.replies || []).map((r) => "↳ " + r.author + "：" + r.content),
        ].join("\n"),
      )
      .join("\n");
    for (const media of post.media) {
      let item = view.images.get(media.id);
      if (!item) {
        item = {
          node: make("div", "live-photo"),
          image: make("img", ""),
          label: make("small", ""),
        };
        item.image.alt = "已保存的归档照片";
        item.image.loading = "lazy";
        item.node.appendChild(item.image);
        item.node.appendChild(item.label);
        view.media.appendChild(item.node);
        view.images.set(media.id, item);
      }
      item.image.hidden = !media.url;
      if (media.url && item.url !== media.url) {
        item.image.src = media.url;
        item.url = media.url;
      }
      item.label.textContent = media.url
        ? media.quality_verified
          ? "清晰度已检查 · 不保证原图"
          : "可用图片 · 高清待检查"
        : media.state === "failed"
          ? "下载失败，可继续任务重试"
          : "等待下载";
    }
    next.set(post.id, view);
  }
  previewCards.clear();
  for (const [id, view] of next) previewCards.set(id, view);
  // Keep existing image nodes while counts/comments update: no repeated image downloads.
  if (orderChanged) $("preview-cards").replaceChildren(...[...next.values()].map((v) => v.node));
  $("preview-page").textContent = data.total
    ? `${data.offset + 1}–${Math.min(data.offset + 20, data.total)} / ${data.total} 条（按最近入库分页）`
    : "等待第一批内容…";
  $("preview-prev").disabled = data.offset === 0;
  $("preview-next").disabled = data.offset + 20 >= data.total;
}
async function refreshPreview() {
  if (!current?.can_live_preview) return;
  const id = current.id;
  if (previewTask !== id) {
    previewTask = id;
    previewOffset = 0;
    previewCards.clear();
    $("preview-cards").replaceChildren();
  }
  const offset = previewOffset;
  const sequence = ++previewSequence;
  try {
    const data = await api(`/api/jobs/${encodeURIComponent(id)}/live?offset=${offset}`);
    if (current?.id !== id || previewOffset !== offset || sequence !== previewSequence) return;
    if (data.total && offset >= data.total) {
      previewOffset = 0;
      return refreshPreview();
    }
    renderLivePreview(data);
    $("preview-error").textContent = "";
  } catch (error) {
    if (current?.id === id && sequence === previewSequence && previewOffset === offset)
      $("preview-error").textContent = "预览暂未更新：" + error.message + "；采集继续进行。";
  }
}
$("preview-prev").addEventListener("click", () => {
  previewOffset = Math.max(0, previewOffset - 20);
  refreshPreview();
});
$("preview-next").addEventListener("click", () => {
  previewOffset += 20;
  refreshPreview();
});
$("quality").addEventListener("click", async () => {
  $("quality").disabled = true;
  try {
    render(await api("/api/jobs/" + current.id + "/continue", "POST", { quality_only: true }));
    $("error").textContent = "";
  } catch (error) {
    $("error").textContent = error.message;
  } finally {
    $("quality").disabled = false;
  }
});
// Task actions share the same rendering path as polling responses.
$("consent").addEventListener("change", () => {
  $("start").disabled = !$("consent").checked || Boolean(current && current.active);
});
$("start").addEventListener("click", async () => {
  $("start").disabled = true;
  $("error").textContent = "";
  try {
    render(await api("/api/jobs", "POST", { consent: $("consent").checked }));
  } catch (error) {
    $("error").textContent = error.message;
    $("start").disabled = !$("consent").checked;
  }
});
$("continue").addEventListener("click", async () => {
  $("continue").disabled = true;
  try {
    render(await api("/api/jobs/" + current.id + "/continue", "POST", {}));
    $("error").textContent = "";
  } catch (error) {
    $("error").textContent = error.message;
  } finally {
    $("continue").disabled = false;
  }
});
$("refresh-qr").addEventListener("click", async () => {
  $("refresh-qr").disabled = true;
  try {
    render(await api("/api/jobs/" + current.id + "/refresh", "POST", {}));
    $("error").textContent = "";
  } catch (error) {
    $("error").textContent = error.message;
    $("refresh-qr").disabled = false;
  }
});
$("stop").addEventListener("click", async () => {
  const id = current.id;
  pausePending = id;
  render(current);
  try {
    const job = await api("/api/jobs/" + id + "/stop", "POST", {});
    if (current && current.id === id) render(job);
    $("error").textContent = "";
  } catch (error) {
    pausePending = null;
    if (current) render(current);
    $("error").textContent = "暂停请求未确认：" + error.message + "。请重试暂停。";
  }
});
$("delete").addEventListener("click", async () => {
  if (!current) return;
  if (!window.confirm("删除本次云端数据？正在运行的任务也会停止，此操作无法恢复。")) return;
  try {
    await api("/api/jobs/" + current.id, "DELETE", {});
    if (polling) clearTimeout(polling);
    current = null;
    $("task").hidden = true;
    $("start").disabled = !$("consent").checked;
    $("error").textContent = "本次数据已撤销访问；如有正在进行的网络请求，将在退出后完成清理。";
  } catch (error) {
    $("error").textContent = error.message;
  }
});
(async () => {
  try {
    const data = await api("/api/session");
    csrf = data.csrf;
    if (data.jobs.length) {
      render(data.jobs.sort((a, b) => b.expires - a.expires)[0]);
      await refreshPreview();
    }
  } catch (error) {
    $("error").textContent = error.message;
  }
})();
