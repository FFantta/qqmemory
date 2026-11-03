"use strict";
function matchesOffline(card, query, category, year, photosOnly) {
  return (
    card.textContent.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) &&
    (!category || card.dataset.category === category) &&
    (!year || card.dataset.year === year) &&
    (!photosOnly || card.dataset.photos === "true")
  );
}
const get = (id) => document.getElementById(id);
const cards = [...document.querySelectorAll("article.card")];
function filterOffline() {
  let shown = 0;
  for (const card of cards) {
    card.hidden = !matchesOffline(
      card,
      get("search").value,
      get("category").value,
      get("year-filter").value,
      get("photos-only").checked,
    );
    if (!card.hidden) shown++;
  }
  get("empty").hidden = shown > 0;
  get("results").textContent = `${shown} / ${cards.length} 条记录 · 按时间归档`;
  for (const button of document.querySelectorAll("#offline-categories button"))
    button.classList.toggle("active", button.dataset.category === get("category").value);
  for (const button of get("years").children)
    button.classList.toggle("selected", button.dataset.year === get("year-filter").value);
}
for (const id of ["search", "category", "year-filter", "photos-only"])
  get(id).addEventListener(id === "search" ? "input" : "change", filterOffline);
for (const button of document.querySelectorAll("#offline-categories button")) {
  button.querySelector(".nav-count").textContent = cards.filter(
    (card) => !button.dataset.category || card.dataset.category === button.dataset.category,
  ).length;
  button.addEventListener("click", () => {
    get("category").value = button.dataset.category;
    filterOffline();
  });
}
for (const year of [...new Set(cards.map((card) => card.dataset.year))].sort().reverse()) {
  const option = document.createElement("option");
  option.value = year;
  option.textContent = year === "未知" ? "时间待确认" : year + " 年";
  get("year-filter").append(option);
  const button = document.createElement("button");
  button.className = "year";
  button.dataset.year = year;
  button.textContent = option.textContent;
  button.addEventListener("click", () => {
    get("year-filter").value = get("year-filter").value === year ? "" : year;
    filterOffline();
  });
  get("years").append(button);
}
if (window.matchMedia?.("(max-width: 780px)").matches) get("offline-nav").open = false;
let photos = [],
  imageIndex = 0;
function showOfflineImage() {
  get("large-image").hidden = false;
  get("large-image").src = photos[imageIndex].getAttribute("href");
  get("image-placeholder").textContent = "";
  get("image-index").textContent = `${imageIndex + 1} / ${photos.length}`;
  get("image-prev").disabled = imageIndex === 0;
  get("image-next").disabled = imageIndex === photos.length - 1;
}
for (const card of cards) {
  const links = [...card.querySelectorAll(".photos a")];
  for (const [index, link] of links.entries()) {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      photos = links;
      imageIndex = index;
      showOfflineImage();
      get("lightbox").showModal();
    });
    const image = link.querySelector("img");
    const missing = () => {
      image.hidden = true;
      const label = document.createElement("span");
      label.className = "offline-photo-missing";
      label.textContent = "图片文件缺失 · 请检查分包是否已合并";
      link.replaceChildren(label);
    };
    image.addEventListener("error", missing);
    if (image.complete && !image.naturalWidth) missing();
  }
}
get("large-image").addEventListener("error", () => {
  get("large-image").hidden = true;
  get("image-placeholder").textContent = "图片文件缺失，请检查所有分包是否已合并。";
});
get("lightbox-close").onclick = () => get("lightbox").close();
get("image-prev").onclick = () => {
  if (imageIndex > 0) {
    imageIndex--;
    showOfflineImage();
  }
};
get("image-next").onclick = () => {
  if (imageIndex + 1 < photos.length) {
    imageIndex++;
    showOfflineImage();
  }
};
document.addEventListener("keydown", (event) => {
  if (!get("lightbox").open) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    get("image-prev").click();
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    get("image-next").click();
  }
});
filterOffline();
