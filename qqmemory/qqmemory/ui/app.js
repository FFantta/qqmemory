"use strict";
const $ = (id) => document.getElementById(id);
let current = null,
  query = "",
  year = "",
  offset = 0,
  photosOnly = false,
  category = "",
  polling = false,
  boot = true;
const cache = new Map(),
  pageCache = new Map();
let group = [],
  index = 0,
  requestNumber = 0,
  stateRequest = null,
  refreshTimer;
const node = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
function toast(message) {
  $("toast").textContent = message;
  $("toast").style.display = "block";
  setTimeout(() => ($("toast").style.display = "none"), 4500);
}
async function api(path, body, signal) {
  const options =
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        };
  let timer;
  if (signal) options.signal = signal;
  else if (["start", "upgrade", "stop", "qr/refresh"].includes(path)) {
    const controller = new AbortController();
    options.signal = controller.signal;
    timer = setTimeout(() => controller.abort(), 15000);
  }
  try {
    const response = await fetch("api/" + path, options);
    const data = await response.json();
    if (!response.ok) throw Error(data.error || "操作未完成");
    return data;
  } catch (error) {
    if (error.name === "AbortError" && !signal)
      throw Error("本地服务响应超时，请检查任务状态后重试");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
function qqHint(element, uin) {
  const value = String(uin || "");
  element.dataset.qq = /^\d{1,20}$/.test(value) ? "QQ：" + value : "QQ号未取得";
  element.setAttribute("aria-label", element.dataset.qq);
  element.tabIndex = 0;
}
function installQqHints() {
  const hint = node("div", "qq-hint");
  hint.id = "qq-hint";
  hint.setAttribute("role", "tooltip");
  hint.hidden = true;
  document.body.append(hint);
  let target = null;
  const hide = () => {
    if (target) target.removeAttribute("aria-describedby");
    target = null;
    hint.hidden = true;
  };
  const show = (element) => {
    hide();
    target = element;
    const value = element.dataset.qq;
    if (/^QQ：\d{1,20}$/.test(value)) {
      hint.replaceChildren(
        node("span", "qq-hint-label", "QQ"),
        node("span", "qq-hint-value", value.slice(3)),
      );
    } else hint.replaceChildren(node("span", "qq-hint-unknown", value));
    hint.hidden = false;
    element.setAttribute("aria-describedby", hint.id);
    const box = element.getBoundingClientRect();
    const width = hint.offsetWidth,
      height = hint.offsetHeight;
    hint.style.left = Math.max(8, Math.min(window.innerWidth - width - 8, box.left)) + "px";
    hint.style.top =
      (box.bottom + height + 14 < window.innerHeight
        ? box.bottom + 6
        : Math.max(8, box.top - height - 6)) + "px";
  };
  document.addEventListener("pointerover", (event) => {
    const element = event.target.closest("[data-qq]");
    if (element && element !== target) show(element);
  });
  document.addEventListener("pointerout", (event) => {
    if (target && !target.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("focusin", (event) => {
    const element = event.target.closest("[data-qq]");
    if (element) show(element);
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hide();
  });
}
installQqHints();
function avatar(uin, cls = "avatar") {
  const img = node("img", cls);
  img.alt = "头像";
  qqHint(img, uin);
  if (uin && /^\d+$/.test(uin)) {
    img.src = "avatar/" + uin;
  }
  img.addEventListener("error", () => {
    img.removeAttribute("src");
    img.alt = "忆";
  });
  return img;
}
function personName(p) {
  return p?.nickname || p?.uin || "空间好友";
}
function mediaLabel(m) {
  if (current?.media_running?.includes(m.id)) return "正在下载…";
  if (current?.media_queued?.includes(m.id)) return "排队下载中…";
  return m.state === "failed" ? "下载未成功 · 点击重试" : "尚未下载 · 点击补全";
}
async function retryMedia(m) {
  try {
    const result = await api("media/retry", { id: m.id });
    if (!result.ok) toast("当前没有可补全的图片");
    await poll();
  } catch (e) {
    toast(e.message);
  }
}
function showImage() {
  const m = group[index];
  $("large-image").removeAttribute("src");
  $("large-image").style.display = m.state === "saved" ? "block" : "none";
  $("image-placeholder").textContent = m.state === "saved" ? "" : mediaLabel(m);
  if (m.state === "saved")
    $("large-image").src =
      "media/" +
      m.id +
      "?account=" +
      encodeURIComponent(m.account || current.account) +
      "&v=" +
      (m.sha256 || "");
  $("image-index").textContent =
    `${index + 1} / ${group.length} · ${m.width && m.height ? m.width + " × " + m.height + " 像素" : "保持照片比例"}`;
  $("image-prev").disabled = index === 0;
  $("image-next").disabled = index === group.length - 1;
}
function openImages(media, i) {
  group = media;
  index = i;
  showImage();
  $("lightbox").showModal();
}
function personTag(p, prefix = "") {
  const e = node("span", "person", prefix + personName(p));
  const uin = String(p?.uin || "");
  qqHint(e, uin);
  if (prefix === "@") e.classList.add("mention");
  e.setAttribute("aria-label", e.textContent + "，" + e.dataset.qq);
  e.tabIndex = 0;
  return e;
}
function richText(value) {
  const fragment = document.createDocumentFragment();
  for (const token of Array.isArray(value) ? value : [{ type: "text", text: value || "" }]) {
    if (token.type === "mention") {
      fragment.append(personTag(token, "@"));
    } else if (token.type === "emoji") {
      const image = node("img", "qq-emoji");
      image.alt = "QQ表情";
      image.title = token.code;
      image.src = "emoji/" + token.code;
      image.addEventListener("error", () =>
        image.replaceWith(node("span", "emoji-missing", "〔表情〕")),
      );
      fragment.append(image);
    } else fragment.append(document.createTextNode(token.text));
  }
  return fragment;
}
function card(p) {
  const a = node("article", "card");
  a.dataset.id = p.id;
  const h = node("div", "card-head");
  h.append(avatar(p.author?.uin || current.account));
  const author = node("div");
  const name = node("div", "author");
  name.append(
    personTag({
      uin: p.author?.uin || current.account,
      nickname: p.author?.nickname || current.nickname || "我的空间",
    }),
  );
  author.append(name);
  const d = node("div", "date", p.date);
  if (p.time_basis === "interaction") d.append(node("span", "basis", "≈ 最早互动"));
  author.append(d);
  h.append(
    author,
    node(
      "span",
      "source",
      p.category === "blogs"
        ? "我的日志"
        : p.category === "gifts"
          ? "礼物与游戏"
          : p.is_related || (p.author?.uin && current.account && p.author.uin !== current.account)
            ? "与我相关"
            : p.time_basis === "published"
              ? "空间备份"
              : p.source_id
                ? "历史重建"
                : "互动线索",
    ),
  );
  a.append(h);
  if (p.notification_actions?.length)
    a.append(node("div", "basis", p.notification_actions.join(" · ")));
  if (p.category === "blogs")
    a.append(node("div", "basis", "日志线索 · 仅保存QQ仍提供的标题和摘要"));
  if (p.content) {
    const content = node("div", "content");
    content.append(richText(p.content_tokens || p.content));
    a.append(content);
  }
  if (p.media.length) {
    const grid = node("div", "photos" + (p.media.length === 1 ? " single" : ""));
    p.media.forEach((m, i) => {
      const button = node("button", "photo");
      button.setAttribute("aria-label", `查看第 ${i + 1} 张照片`);
      if (m.state === "saved") {
        const image = node("img");
        image.src =
          "media/" +
          m.id +
          "?account=" +
          encodeURIComponent(m.account || current.account) +
          "&v=" +
          (m.sha256 || "") +
          "&thumb=1";
        image.loading = "lazy";
        image.decoding = "async";
        image.alt = "说说照片";
        image.addEventListener("error", () => {
          image.remove();
          button.prepend(node("span", "", "本地图片暂不可用"));
        });
        button.append(image);
      } else button.append(node("span", "", mediaLabel(m)));
      button.append(node("span", "photo-number", `${i + 1}/${p.media.length}`));
      button.onclick = () => {
        if (m.state === "saved") openImages(p.media, i);
        else retryMedia(m);
      };
      grid.append(button);
    });
    a.append(grid);
  }
  const foot = node("div", "card-foot");
  foot.append(
    node("span", "", p.social_available ? `${p.like_count || 0} 人点赞` : "点赞待补全"),
    node("span", "", p.social_available ? `${p.comment_count || 0} 条评论` : "评论待补全"),
    node(
      "span",
      "",
      `${p.media.filter((m) => m.state === "saved").length}/${p.media.length} 张已存本地`,
    ),
  );
  a.append(foot);
  if (p.likes.length) {
    const likes = node("div", "likes", "");
    p.likes.forEach((like, i) => {
      if (i) likes.append(document.createTextNode("、"));
      likes.append(personTag(like));
    });
    likes.append(document.createTextNode(" 觉得很赞"));
    a.append(likes);
  }
  if (p.comments.length) {
    const section = node("details", "comments");
    section.open = p.comments.length <= 3;
    section.append(node("summary", "", `查看 ${p.comments.length} 条已取得评论`));
    for (const c of p.comments) {
      const line = node("div");
      const by = node("b");
      by.append(personTag(c), document.createTextNode("："));
      line.append(by, richText(c.content_tokens || c.content));
      section.append(line);
      for (const r of c.replies || []) {
        const reply = node("div", "reply");
        const by = node("b");
        by.append(personTag(r), document.createTextNode(" 回复："));
        reply.append(by, richText(r.content_tokens || r.content));
        section.append(reply);
      }
    }
    a.append(section);
  }
  return a;
}
const categoryNames = {
  posts: "我的说说",
  interactions: "与他人互动",
  gifts: "礼物与游戏",
  blogs: "我的日志",
};
function render(data) {
  current = data;
  for (const p of data.posts) for (const m of p.media) m.account = data.account;
  for (const [key, label] of Object.entries(categoryNames)) {
    let b = $("category-" + key);
    if (!b) {
      b = node("button", "nav");
      b.id = "category-" + key;
      b.onclick = () => {
        category = key;
        offset = 0;
        year = "";
        poll();
      };
      $("categories").append(b);
    }
    const count = String(data.category_counts?.[key] || 0);
    if (b.dataset.count !== count) {
      b.replaceChildren(node("span", "nav-name", label), node("span", "nav-count", count));
      b.dataset.count = count;
    }
    b.classList.toggle("active", category === key);
  }
  $("all").classList.toggle("active", !category && !photosOnly);
  $("archive-title").textContent =
    (categoryNames[category] || "全部回忆") +
    (photosOnly ? " / 有图" : "") +
    (year ? " · " + year : "");
  document.body.dataset.phase = data.phase;
  const s = data.stats || {};
  $("profile-name").textContent = data.nickname;
  qqHint($("profile-name"), data.account);
  qqHint($("profile-avatar"), data.account);
  $("nav-total").textContent = s.posts || 0;
  if (data.account && $("profile-avatar").dataset.uin !== data.account) {
    $("profile-avatar").dataset.uin = data.account;
    $("profile-avatar").src = "avatar/" + data.account;
  }
  $("post-count").textContent = s.posts || 0;
  $("photo-count").textContent = s.photos_saved || 0;
  $("photo-detail").textContent =
    `发现 ${s.photos_found || 0} 张 · 待存 ${s.photos_pending || 0} · 失败 ${s.photos_failed || 0}`;
  const candidates = [s.earliest, s.earliest_interaction].filter((v) => v && v !== "未知").sort();
  $("earliest").textContent = candidates[0]?.slice(0, 4) || "—";
  renderTask(data);
  const media = [...data.events].reverse().find((e) => e.kind === "media");
  $("media-progress").textContent = media?.message || "图片与文字同时保存";
  const batch = [...data.events].reverse().find((e) => e.kind === "batch");
  $("batch-progress").textContent = batch?.message || "";
  if (data.deep_scan && (!data.active || data.task_account === data.account)) {
    const d = data.deep_scan;
    $("batch-progress").textContent =
      `当前档案深扫断点：${d.segment}/${d.total} 个分段 · ${d.requests} 次请求${d.complete ? " · 本轮计划已完成" : ""}`;
  }
  $("logs").replaceChildren(
    ...data.events.slice(-20).map((e) => node("div", "", `${e.time} ${e.message}`)),
  );
  renderLogin(data);
  const years = data.years.join("|");
  if ($("years").dataset.values !== years) {
    $("years").dataset.values = years;
    $("years").replaceChildren(
      ...data.years.map((y) => {
        const b = node("button", "year", y + " 年");
        b.onclick = () => {
          year = year === y ? "" : y;
          offset = 0;
          poll();
        };
        b.dataset.year = y;
        return b;
      }),
    );
  }
  for (const b of $("years").children) b.classList.toggle("selected", b.dataset.year === year);
  if ($("lightbox").open && group[index]) {
    const updated = data.posts.flatMap((p) => p.media).find((m) => m.id === group[index].id);
    if (updated && JSON.stringify(updated) !== JSON.stringify(group[index])) {
      group[index] = updated;
      showImage();
    }
  }
  const posts = data.posts.filter((p) => !photosOnly || p.media.length),
    container = $("timeline");
  const needed = [];
  let lastYear;
  for (const p of posts) {
    if (p.year !== lastYear) {
      const headingKey = "year-" + p.year;
      let heading = cache.get(headingKey);
      if (!heading) {
        heading = {
          element: node("div", "year-heading", p.year === "未知" ? "时间待确认" : p.year),
        };
        cache.set(headingKey, heading);
      }
      needed.push(heading.element);
      lastYear = p.year;
    }
    const signature = JSON.stringify(p) + p.media.map(mediaLabel).join("|");
    let existing = cache.get(p.id);
    if (!existing || existing.signature !== signature) {
      existing = { signature, element: card(p) };
      cache.set(p.id, existing);
    }
    needed.push(existing.element);
  }
  if (cache.size > 120) {
    const visible = new Set(needed);
    for (const [key, value] of cache) if (!visible.has(value.element)) cache.delete(key);
  }
  const anchor = container.querySelector(".card");
  const anchorId = anchor?.dataset.id,
    position = anchor?.getBoundingClientRect().top;
  if (
    needed.length !== container.children.length ||
    needed.some((n, i) => container.children[i] !== n)
  )
    container.replaceChildren(...needed);
  if (anchorId && position < 0) {
    const found = container.querySelector(`[data-id="${anchorId}"]`);
    if (found) window.scrollBy(0, found.getBoundingClientRect().top - position);
  }
  $("empty").style.display = posts.length ? "none" : "block";
  $("results").textContent = `${data.total} 条记录 · 按时间归档`;
  $("page-label").textContent =
    `${offset + 1}–${Math.min(offset + 30, data.total)} / ${data.total}`;
  $("prev").disabled = offset === 0;
  $("next").disabled = offset + 30 >= data.total;
}
// BEGIN state request coordinator
function paintSelection() {
  $("all").classList.toggle("active", !category && !photosOnly);
  $("photos-only").classList.toggle("active", photosOnly);
  for (const [key] of Object.entries(categoryNames))
    $("category-" + key)?.classList.toggle("active", key === category);
  for (const b of $("years").children) b.classList.toggle("selected", b.dataset.year === year);
  $("archive-title").textContent =
    (categoryNames[category] || "全部回忆") +
    (photosOnly ? " / 有图" : "") +
    (year ? " · " + year : "");
}
async function poll(interactive = true) {
  if (!interactive && (document.hidden || polling)) return;
  if (polling) stateRequest?.abort();
  const number = ++requestNumber;
  polling = true;
  clearTimeout(refreshTimer);
  stateRequest = new AbortController();
  const signal = stateRequest.signal;
  const parameters = new URLSearchParams({
    search: query,
    year,
    category,
    offset,
    limit: 30,
    photos: photosOnly ? 1 : 0,
  });
  const key = parameters.toString();
  paintSelection();
  const previous = pageCache.get(key);
  if (interactive && previous && current) render({ ...current, ...previous });
  if (interactive) $("timeline").setAttribute("aria-busy", "true");
  try {
    const data = await api("state?" + key, undefined, signal);
    if (number !== requestNumber) return;
    if (current?.account !== data.account) {
      cache.clear();
      pageCache.clear();
    }
    render(data);
    pageCache.delete(key);
    pageCache.set(key, {
      posts: data.posts,
      total: data.total,
      years: data.years,
      category_counts: data.category_counts,
    });
    if (pageCache.size > 8) pageCache.delete(pageCache.keys().next().value);
    if (boot) boot = false;
  } catch (e) {
    if (number === requestNumber && e.name !== "AbortError") {
      $("task-message").textContent = "连接暂不可用，正在重试…";
      if (loginFlow?.step === "login")
        loginError("暂时无法连接本地服务。正在重试，也可取消后重新扫码。");
    }
  } finally {
    if (number === requestNumber) {
      polling = false;
      $("timeline").removeAttribute("aria-busy");
      refreshTimer = setTimeout(() => poll(false), current?.active ? 1200 : 8000);
    }
  }
}
// END state request coordinator
// BEGIN login flow
let loginIntent = "update",
  loginFlow = null,
  loginSequence = 0;
function loginError(message) {
  $("login-error").textContent = message;
  $("login-error").hidden = !message;
}
function loginSettings() {
  $("login-settings").hidden = false;
  $("login-qr").hidden = true;
  $("qr-start").disabled = false;
  $("qr-start").textContent = "下一步 · 扫码";
}
async function startLogin(intent = "update", media = false) {
  if (current?.active) {
    toast("已有任务正在运行，请先暂停并等待保存完成");
    return;
  }
  if (media && !current?.account) {
    toast("请先添加账号并备份内容");
    return;
  }
  if (media && current?.stats && !(current.stats.photos_pending || current.stats.photos_failed)) {
    toast("当前图片已全部保存到本地，无需扫码");
    return;
  }
  if (!current?.account) intent = "add";
  loginIntent = intent;
  loginFlow = {
    sequence: ++loginSequence,
    step: "settings",
    media,
    intent,
    account: current?.account,
  };
  $("qr-title").textContent = media
    ? "补全已有图片"
    : intent === "add"
      ? "添加账号并备份"
      : "更新当前档案";
  $("login-description").textContent = media
    ? "只尝试下载当前档案中尚未保存的图片，不搜索新增说说。请使用该档案的 QQ 扫码。"
    : intent === "add"
      ? "先选择本次设置，再使用手机 QQ 扫码建立独立档案。"
      : "请使用 QQ " + current.account + " 扫码更新已有档案。先选择本次设置。";
  $("mode-setting").hidden = media;
  $("missing-photos").hidden = !media;
  $("missing-photos").textContent =
    `本地尚未保存 ${(current?.stats?.photos_pending || 0) + (current?.stats?.photos_failed || 0)} 张图片（不保证全部可取得）`;
  $("login-budget").hidden = media;
  $("scan-mode").disabled = false;
  $("workers").disabled = false;
  loginError("");
  loginSettings();
  if (!$("qr-dialog").open) $("qr-dialog").showModal();
}
async function beginQr() {
  const flow = loginFlow;
  if (!flow || flow.step !== "settings") return;
  flow.step = "starting";
  loginError("");
  $("login-settings").hidden = true;
  $("login-qr").hidden = false;
  $("qr-image").removeAttribute("src");
  $("qr-image").style.display = "none";
  $("qr-loading").style.display = "block";
  $("qr-loading").textContent = "正在生成二维码…";
  $("qr-message").textContent = "正在连接 QQ 登录服务";
  $("qr-refresh").disabled = true;
  $("qr-back").disabled = true;
  let result;
  try {
    result = await api(flow.media ? "upgrade" : "start", {
      workers: Number($("workers").value),
      mode: $("scan-mode").value,
      intent: flow.intent,
    });
  } catch (error) {
    if (loginFlow !== flow) return;
    flow.step = "settings";
    loginSettings();
    loginError("无法开始扫码：" + error.message + "。请重试。");
    return;
  }
  if (loginFlow !== flow) {
    if (result.task_id) await api("stop", { task_id: result.task_id });
    return;
  }
  if (result.started === false) {
    loginFlow = null;
    $("qr-dialog").close();
    toast("当前图片已全部保存到本地，无需扫码");
    return;
  }
  flow.taskId = result.task_id;
  flow.step = "login";
  $("qr-back").disabled = false;
  $("qr-refresh").disabled = false;
  await poll();
}
function renderLogin(data) {
  const flow = loginFlow;
  // Older state requests, including cached pages, cannot dismiss a new dialog.
  if (flow?.step === "settings" && flow.awaitingCancel && data.task_id === flow.cancelledTaskId) {
    $("qr-start").disabled = data.active;
    if (!data.active) {
      flow.awaitingCancel = false;
      loginError("");
    }
  }
  if (!flow || flow.step !== "login" || !flow.taskId || data.task_id !== flow.taskId) return;
  $("qr-message").textContent = data.message;
  if (data.phase === "login") {
    $("qr-loading").textContent =
      data.qr_status === "expired" ? "二维码已过期，请刷新" : "正在生成二维码…";
    $("qr-image").style.display = data.qr ? "block" : "none";
    $("qr-loading").style.display = data.qr ? "none" : "block";
    if (data.qr) $("qr-image").src = data.qr;
    return;
  }
  if ((data.active && data.phase === "collecting") || data.phase === "done") {
    loginFlow = null;
    $("qr-dialog").close();
  } else if (!data.active) {
    flow.step = "settings";
    loginSettings();
    loginError(data.message || "扫码未完成，请重试");
  }
}
async function closeLogin(back = false) {
  const flow = loginFlow;
  if (!flow) return;
  if (flow.step === "starting") {
    loginFlow = null;
    $("qr-dialog").close();
    return;
  }
  if (flow.taskId && flow.step === "login") {
    $("qr-back").disabled = true;
    try {
      await api("stop", { task_id: flow.taskId });
    } catch (error) {
      loginError("取消扫码未确认：" + error.message);
      $("qr-back").disabled = false;
      return;
    }
  }
  if (back) {
    flow.step = "settings";
    flow.cancelledTaskId = flow.taskId;
    flow.taskId = null;
    flow.awaitingCancel = true;
    loginSettings();
    $("qr-start").disabled = true;
    loginError("已请求取消上次扫码。可修改设置；请等待取消完成后再次扫码。");
  } else {
    loginFlow = null;
    $("qr-dialog").close();
  }
  poll();
}
$("login").onclick = () => startLogin("update").catch((e) => toast(e.message));
$("qr-start").onclick = () => beginQr().catch((e) => loginError(e.message));
$("qr-close").onclick = () => closeLogin().catch((e) => loginError(e.message));
$("qr-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeLogin().catch((e) => loginError(e.message));
});
$("qr-back").onclick = () => closeLogin(true).catch((e) => loginError(e.message));
$("qr-refresh").onclick = async () => {
  const flow = loginFlow;
  if (!flow?.taskId) return;
  $("qr-refresh").disabled = true;
  try {
    await api("qr/refresh", { task_id: flow.taskId });
    $("qr-image").style.display = "none";
    $("qr-loading").style.display = "block";
    $("qr-message").textContent = "正在生成新二维码…";
    await poll();
  } catch (e) {
    loginError("刷新失败：" + e.message + "。请重试。");
  } finally {
    $("qr-refresh").disabled = false;
  }
};
$("download-speed").onchange = () => {
  if ($("download-speed").value !== "custom") $("workers").value = $("download-speed").value;
};
$("workers").onchange = () => {
  $("download-speed").value = ["2", "6", "10"].includes($("workers").value)
    ? $("workers").value
    : "custom";
};
$("upgrade").onclick = () => startLogin("update", true).catch((e) => toast(e.message));
$("relogin").onclick = () =>
  startLogin("update", current?.mode === "media").catch((e) => toast(e.message));
// END login flow
$("stop").onclick = async () => {
  try {
    await api("stop", {});
    poll();
    toast("正在暂停，已保存的内容可继续浏览");
  } catch (e) {
    toast(e.message);
  }
};
$("export").onclick = async () => {
  try {
    toast("正在准备离线 HTML…");
    await api("export", {});
  } catch (e) {
    toast(e.message);
  }
};
let searchTimer;
$("search").oninput = (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    query = e.target.value;
    offset = 0;
    poll();
  }, 250);
};
$("all").onclick = () => {
  category = "";
  photosOnly = false;
  year = "";
  offset = 0;
  $("all").classList.add("active");
  $("photos-only").classList.remove("active");
  poll();
};
$("photos-only").onclick = () => {
  photosOnly = !photosOnly;
  $("photos-only").classList.toggle("active", photosOnly);
  poll();
};
$("prev").onclick = () => {
  offset = Math.max(0, offset - 30);
  poll();
  window.scrollTo(0, 350);
};
$("next").onclick = () => {
  offset += 30;
  poll();
  window.scrollTo(0, 350);
};
$("lightbox-close").onclick = () => $("lightbox").close();
$("image-prev").onclick = () => {
  if (index > 0) {
    index--;
    showImage();
  }
};
$("image-next").onclick = () => {
  if (index < group.length - 1) {
    index++;
    showImage();
  }
};
document.addEventListener("keydown", (e) => {
  if (!$("lightbox").open) return;
  if (e.key === "ArrowLeft") $("image-prev").click();
  if (e.key === "ArrowRight") $("image-next").click();
});
poll();
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(refreshTimer);
    stateRequest?.abort();
  } else poll();
});

function duration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  return seconds >= 3600
    ? Math.floor(seconds / 3600) + "小时" + Math.floor((seconds % 3600) / 60) + "分"
    : seconds >= 60
      ? Math.floor(seconds / 60) + "分" + (seconds % 60) + "秒"
      : seconds + "秒";
}
function renderTask(data) {
  const p = data.progress || {},
    active = data.active,
    finished = !active && data.outcome === "completed";
  $("phase").textContent =
    data.phase === "stopping"
      ? "正在暂停"
      : active
        ? data.phase === "login"
          ? "等待扫码"
          : "运行中"
        : data.phase === "error"
          ? "需留意"
          : data.outcome === "paused"
            ? "已暂停"
            : finished
              ? "已完成"
              : "就绪";
  $("task-detail").textContent = active
    ? "任务账号：" + (data.task_account || "等待扫码")
    : "查看档案无需扫码";
  $("task-message").textContent =
    (data.task_account && data.task_account !== data.account
      ? "QQ " + data.task_account + " 的后台任务："
      : "") + data.message;
  $("stop").disabled = !active || data.phase === "stopping";
  $("relogin").disabled = active;
  $("upgrade").disabled = active;
  $("login").disabled = active;
  $("account-add").disabled = active;
  $("stage-label").textContent = active
    ? p.label || "准备任务"
    : finished
      ? "备份已完成"
      : data.outcome === "paused"
        ? "本轮已暂停"
        : "本地档案可浏览";
  $("scan-timing").textContent =
    p.elapsed && data.task_account ? "本轮用时 " + duration(p.elapsed) : "本地切换无需扫码";
  const stages =
    data.mode === "backfill"
      ? ["media"]
      : [
          "login",
          ...(data.mode === "media"
            ? []
            : [
                "visible",
                "mobile",
                ...(data.mode === "deep" ? ["deep"] : data.mode === "backup" ? [] : ["history"]),
              ]),
          "media",
          "export",
        ];
  const labels = {
    login: "扫码",
    visible: "当前说说",
    mobile: "互动补充",
    history: "历史线索",
    deep: "深度扫描",
    media: "图片保存",
    export: "导出",
  };
  const index = stages.indexOf(p.stage);
  $("scan-stages").replaceChildren(
    ...stages.map((stage, i) =>
      node(
        "li",
        finished || i < index ? "complete" : active && i === index ? "current" : "",
        labels[stage],
      ),
    ),
  );
  const bar = $("scan-progress");
  if (finished) bar.value = 100;
  else if (p.percent != null) bar.value = p.percent;
  else if (active) bar.removeAttribute("value");
  else bar.value = 0;
  bar.hidden = data.phase === "login" || (!active && !data.task_account);
  let description = active
    ? p.total
      ? `${p.label}：${p.done}/${p.total} · ${p.percent}%`
      : "本阶段总量未知，正在持续保存结果"
    : "已保存的档案可随时切换和导出";
  if (active && p.stage === "deep") description += " · 这是扫描计划进度，不代表历史内容找回比例";
  if (active && p.eta)
    description +=
      " · 完成本阶段预计还需 " +
      duration(p.eta[0]) +
      "–" +
      duration(p.eta[1]) +
      "（粗估，网络和分段大小会影响结果）";
  else if (active && p.stage !== "login") description += " · 正在积累速度样本，暂不估算剩余时间";
  if (active && data.mode !== "media" && data.mode !== "backfill")
    description +=
      " · " +
      (data.mode === "deep" ? "文字扫描本轮上限90分钟，可断点继续" : "文字采集本轮上限10分钟") +
      "，图片收尾另计";
  $("scan-estimate").textContent = data.phase === "login" ? data.message : description;
}
$("account-switch").onclick = async () => {
  try {
    const data = await api("accounts");
    $("account-list").replaceChildren(
      ...data.accounts.map((a) => {
        const button = node(
          "button",
          "account-choice" + (a.uin === data.selected ? " selected" : ""),
        );
        button.append(avatar(a.uin));
        const text = node("span");
        text.append(
          node("strong", "", a.nickname),
          node("small", "", `QQ ${a.uin} · ${a.posts} 条记录 · ${a.photos} 张照片`),
          node("small", "", `档案最近保存：${new Date(a.modified * 1000).toLocaleString("zh-CN")}`),
        );
        button.append(text);
        button.onclick = async () => {
          try {
            await api("accounts/select", { uin: a.uin });
            category = "";
            year = "";
            query = "";
            offset = 0;
            photosOnly = false;
            $("search").value = "";
            cache.clear();
            pageCache.clear();
            if ($("lightbox").open) $("lightbox").close();
            $("accounts-dialog").close();
            await poll();
            toast("已切换本地档案，无需重新采集");
          } catch (e) {
            toast(e.message);
          }
        };
        return button;
      }),
    );
    $("accounts-dialog").showModal();
  } catch (e) {
    toast(e.message);
  }
};
$("accounts-close").onclick = () => $("accounts-dialog").close();
$("account-add").onclick = () => {
  $("accounts-dialog").close();
  startLogin("add").catch((e) => toast(e.message));
};
