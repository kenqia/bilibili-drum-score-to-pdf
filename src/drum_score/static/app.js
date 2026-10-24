"use strict";
const $ = (id) => document.getElementById(id);
const active = new Set(["queued", "running", "cancelling", "finishing"]);
const titles = {queued:"正在排队",running:"正在整理鼓谱",cancelling:"正在停止",finishing:"马上就好",complete:"鼓谱整理好了",failed:"这个视频没能整理出来",cancelled:"任务已取消",interrupted:"处理被中断了"};
const stages = {starting:"正在准备。",downloading:"正在获取视频。",probing:"正在检查视频。",sampling:"正在读取视频里的谱面。",registering:"正在对齐前后画面。",composing:"正在把谱行接起来。",paginating:"正在排成 A4 页面。",finishing:"正在保存 PDF 和预览。",cancelling:"正在停止处理并清理临时文件。"};
// Progress bar steps, in order; each backend stage maps onto one of them.
const steps = ["queue", "fetch", "read", "stitch", "layout"];
const stepOf = {queued:"queue",starting:"fetch",downloading:"fetch",probing:"read",sampling:"read",registering:"stitch",composing:"stitch",paginating:"layout",finishing:"layout"};
// Plain-language explanations for drummers; the server message stays available as detail.
const friendly = {
  invalid_bilibili_url:"请复制完整 B站 BV、b23.tv 或 YouTube 单视频链接再试。",
  invalid_request:"请复制完整 B站 BV、b23.tv 或 YouTube 单视频链接再试。",
  short_link_unavailable:"这个短链接没能打开。请重新复制，或在浏览器打开后复制完整的 BV 链接。",
  ip_busy:"你所在的网络已经有一个任务在处理了。等它完成或取消后再提交。学校、公司等共用网络也会占用名额。",
  queue_full:"现在排队的人太多了，请过几分钟再试。",
  service_busy:"服务器正忙，请稍后再试。",
  storage_full:"服务器空间暂时不够，请稍后再试。",
  unsupported_layout:"视频里没找到白底的鼓谱。这个工具只适合白色背景、从下往上滚动的鼓谱视频。",
  discontinuity:"视频里有一段谱面接不上（可能跳过了、翻页了或被挡住了）。为了不给你一份缺行的谱子，这次没有生成 PDF。",
  source_changed:"处理期间视频发生了变化，请重新整理。",
  resource_limit:"视频太长或画面太大。目前支持 10 分钟以内、4K 以下的视频。",
  download_too_large:"视频文件太大了。目前支持 10 分钟以内、4K 以下的视频。",
  http_unavailable:"拿不到这个视频。它可能需要登录、是会员专享、有地区限制或者已经下架。",
  public_api_unavailable:"拿不到这个视频。它可能需要登录、是会员专享、有地区限制或者已经下架。",
  youtube_challenge:"YouTube 要求机器人或身份验证。请稍后重试，或换一个无需登录的公开视频。",
  unsupported_stream:"这个视频的格式暂时处理不了。",
  undecodable_video:"视频读取失败。可以点「重新整理」再试一次。",
  decode_failed:"视频读取失败。可以点「重新整理」再试一次。",
  network_timeout:"获取视频超时了。可以点「重新整理」再试一次。",
  acquisition_interrupted:"获取视频时被中断了。可以点「重新整理」再试一次。",
  incomplete_video:"下载到的视频不完整。可以点「重新整理」再试一次。",
  expired:"结果已经过了 24 小时的保存期，被自动删除了。重新提交链接就能再整理一次。",
  not_found:"找不到这个任务。请打开提交时保存的完整链接。"
};
let taskId, capability, timer, previewLoaded = false;
const blobs = [];

function showError(box, code, raw) {
  const text = friendly[code] || raw || "出了点问题，请稍后再试。";
  if (box === "submit-error") { $(box).textContent = text; $(box).hidden = false; return; }
  $("task-error-text").textContent = text;
  const extra = raw && raw !== text;
  $("task-error-detail").hidden = !extra;
  $("task-error-raw").textContent = extra ? raw : "";
  $("task-error").hidden = false;
}
async function api(path, options = {}) {
  const headers = {...options.headers};
  if (capability) headers.Authorization = "Bearer " + capability;
  let response;
  try { response = await fetch(path, {...options, headers, cache:"no-store", credentials:"omit", referrerPolicy:"no-referrer"}); }
  catch (_) { const error = new Error("网络连接不稳定，请检查网络后重试。"); error.code = "offline"; throw error; }
  if (!response.ok) {
    let message = "请求没有完成，请稍后再试。", code = "";
    try { const body = (await response.json()).error; message = body.message; code = body.code; } catch (_) {}
    const error = new Error(message); error.status = response.status; error.code = code; throw error;
  }
  return response;
}

// Accept a pasted link or share message; discard share tracking parameters.
function normalizeLink(text) {
  const value = text.trim();
  const bv = /(?:bilibili\.com\/video\/|^|[^A-Za-z0-9])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])/.exec(value);
  if (bv) {
    const page = /[?&]p=([1-9][0-9]{0,5})(?![0-9])/.exec(value);
    return {url:`https://www.bilibili.com/video/${bv[1]}` + (page ? `?p=${page[1]}` : "")};
  }
  const short = /(?:^|[\s（(【])(?:https?:\/\/)?b23\.tv\/([0-9A-Za-z]{1,64})(?=$|[\s/?#）)】。，！!])/i.exec(value);
  if (short) return {url:`https://b23.tv/${short[1]}`};
  const youtube = /https:\/\/(?:www\.)?(?:youtube\.com|youtu\.be)\/[^\s<>"'）)】。，！!]+/i.exec(value);
  if (youtube) {
    try {
      const url = new URL(youtube[0]);
      let id;
      if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) throw new Error();
      if (url.hostname === "youtu.be") id = /^\/([A-Za-z0-9_-]{11})\/?$/.exec(url.pathname)?.[1];
      else if (["youtube.com", "www.youtube.com"].includes(url.hostname)) {
        if (url.pathname === "/watch" && url.searchParams.getAll("v").length === 1) id = url.searchParams.get("v");
        else id = /^\/shorts\/([A-Za-z0-9_-]{11})\/?$/.exec(url.pathname)?.[1];
      }
      if (/^[A-Za-z0-9_-]{11}$/.test(id || "")) return {url:`https://www.youtube.com/watch?v=${id}`};
    } catch (_) {}
  }
  if (!value) return {error:"先粘贴一个 B站或 YouTube 视频链接。"};
  return {error:friendly.invalid_bilibili_url};
}

$("submit-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("submit-error").hidden = true;
  const link = normalizeLink($("source").value);
  if (link.error) { $("submit-error").textContent = link.error; $("submit-error").hidden = false; $("source").focus(); return; }
  $("submit-button").disabled = true; $("submit-button").textContent = "正在提交…";
  try {
    const response = await api("/api/tasks", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url:link.url})});
    const created = await response.json(); window.location.assign(created.link);
  } catch (error) {
    showError("submit-error", error.code, error.message);
    $("submit-button").disabled = false; $("submit-button").textContent = "整理鼓谱";
  }
});

async function loadPreviews(count) {
  $("reload-previews").hidden = true;
  $("previews").replaceChildren();
  for (const url of blobs.splice(0)) URL.revokeObjectURL(url);
  try {
    for (let page = 1; page <= count; page++) {
      const response = await api(`/api/tasks/${taskId}/pages/${page}`);
      const url = URL.createObjectURL(await response.blob()); blobs.push(url);
      const figure = document.createElement("figure");
      const image = document.createElement("img"); image.src = url; image.alt = `鼓谱第 ${page} 页，共 ${count} 页`; image.decoding = "async";
      const caption = document.createElement("figcaption"); caption.textContent = `第 ${page} 页 / 共 ${count} 页`;
      figure.append(image, caption); $("previews").append(figure);
    }
    previewLoaded = true;
  } catch (error) { showError("task-error", "", "预览没加载出来。" + error.message); $("reload-previews").hidden = false; }
}

function showProgress(state) {
  const show = active.has(state.state);
  $("progress").hidden = !show;
  if (!show) return;
  const current = steps.indexOf(stepOf[state.stage] || (state.state === "queued" ? "queue" : "layout"));
  for (const item of $("progress").children) {
    const index = steps.indexOf(item.dataset.step);
    item.className = index < current ? "done" : index === current ? "now" : "";
    if (index === current) item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
  }
}

function formatExpiry(seconds) {
  const date = new Date(seconds * 1000);
  const hours = Math.max(0, Math.round((date - Date.now()) / 3600000));
  const clock = date.toLocaleString("zh-CN", {month:"numeric", day:"numeric", hour:"2-digit", minute:"2-digit", hour12:false});
  return `保留到 ${clock}（约 ${hours} 小时后删除）`;
}

async function refresh() {
  clearTimeout(timer);
  try {
    const state = await (await api(`/api/tasks/${taskId}`)).json();
    $("task-error").hidden = true;
    $("task-title").textContent = titles[state.state] || "正在读取任务";
    let description = stages[state.stage] || "";
    if (state.state === "queued") description = state.queue_position > 1 ? `前面还有 ${state.queue_position - 1} 个任务。关掉页面也会继续排队。` : "马上轮到你了。关掉页面也会继续。";
    if (state.state === "complete") description = `一共 ${state.result.page_count} 页 A4。先翻一遍预览，没问题就下载。`;
    if (state.state === "cancelled") description = "已经停止，临时文件也清理了。需要的话可以重新整理。";
    if (state.state === "interrupted") description = "服务器重启打断了处理。点「重新整理」继续。";
    if (state.state === "failed") description = "";
    $("task-description").textContent = description;
    $("task-description").hidden = !description;
    if (state.error) showError("task-error", state.error.code, state.error.message);
    document.title = `${titles[state.state] || "鼓谱整理"} · 鼓谱整理`;
    showProgress(state);
    $("task-meta").hidden = false;
    const source = state.result?.source || state.source;
    $("source-label").textContent = source.video_id ? `YouTube · ${source.video_id}` : source.bvid ? `${source.bvid}` + (source.page > 1 ? ` · 第 ${source.page} P` : "") : "B站分享短链接";
    $("source-link").href = source.url;
    $("save-link").hidden = !active.has(state.state) && state.state !== "complete";
    $("task-link").value = window.location.href;
    $("cancel").hidden = !["queued","running"].includes(state.state);
    $("retry").hidden = !["failed","cancelled","interrupted"].includes(state.state);
    $("download").hidden = state.state !== "complete";
    $("result").hidden = state.state !== "complete";
    if (state.state === "complete") {
      $("expiry").textContent = formatExpiry(state.expires_at);
      $("warnings").replaceChildren();
      for (const warning of state.result.warnings) {
        if (warning.code === "not_musically_proofread") continue;
        const item = document.createElement("li"); item.textContent = warning.message; $("warnings").append(item);
      }
      if (!previewLoaded) await loadPreviews(state.result.page_count);
      $("reload-previews").onclick = () => loadPreviews(state.result.page_count);
    }
    if (active.has(state.state)) timer = setTimeout(refresh, 1500);
  } catch (error) {
    if (error.status === 404 || error.status === 410) {
      $("task-title").textContent = error.status === 410 ? "结果已过期" : "找不到这个任务";
      $("task-description").hidden = true;
      showError("task-error", error.status === 410 ? "expired" : "not_found", "");
      for (const id of ["download","cancel","retry","result","progress","save-link"]) $(id).hidden = true;
    } else { showError("task-error", error.code, error.message + " 正在自动重试…"); timer = setTimeout(refresh, 3000); }
  }
}

for (const action of ["cancel","retry"]) $(action).addEventListener("click", async () => {
  if (action === "cancel" && !window.confirm("确定取消这次整理吗？")) return;
  $(action).disabled = true; $("task-error").hidden = true;
  try { await api(`/api/tasks/${taskId}/${action}`, {method:"POST"}); previewLoaded = false; await refresh(); }
  catch (error) { showError("task-error", error.code, error.message); }
  finally { $(action).disabled = false; }
});
$("download").addEventListener("click", async () => {
  const label = $("download").textContent;
  $("download").disabled = true; $("download").textContent = "正在下载…"; $("task-error").hidden = true;
  try {
    const response = await api(`/api/tasks/${taskId}/pdf`);
    if (Number(response.headers.get("Content-Length")) > 256 * 1024 * 1024) throw new Error("PDF 超过 256 MiB，浏览器无法下载。");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = "鼓谱.pdf"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) { showError("task-error", error.code, error.message); }
  finally { $("download").disabled = false; $("download").textContent = label; }
});
$("copy-link").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(window.location.href); $("copy-status").textContent = "已复制。可以发给自己或存到备忘录。"; }
  catch (_) { $("task-link").focus(); $("task-link").select(); $("copy-status").textContent = "已选中链接，请手动复制。"; }
});
window.addEventListener("pagehide", () => { clearTimeout(timer); for (const url of blobs) URL.revokeObjectURL(url); });
window.addEventListener("pageshow", (event) => { if (event.persisted && taskId && capability) { previewLoaded = false; refresh(); } });

const match = /^\/task\/([A-Za-z0-9_-]+)$/.exec(window.location.pathname);
if (match) {
  taskId = match[1]; capability = window.location.hash.slice(1);
  for (const id of ["landing-hero", "landing-body", "landing-nav"]) $(id).hidden = true;
  $("task").hidden = false;
  if (/^[A-Za-z0-9_-]{43}$/.test(capability)) refresh();
  else { $("task-title").textContent = "链接不完整"; $("task-description").textContent = "请打开提交时保存的完整链接，# 号后面的部分也要带上。"; }
}
