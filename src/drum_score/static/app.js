"use strict";
const $ = (id) => document.getElementById(id);
const active = new Set(["queued", "running", "cancelling", "finishing"]);
const titles = {queued:"已加入等待队列",running:"正在整理鼓谱",cancelling:"正在停止处理",finishing:"正在保存结果",complete:"鼓谱整理完成",failed:"这次未能完成",cancelled:"任务已取消",interrupted:"处理已中断"};
const stages = {starting:"正在开始处理。",downloading:"正在获取公开视频。",probing:"正在检查视频。",sampling:"正在采集原生谱面。",registering:"正在核对相邻谱面的位置。",composing:"正在拼接连续谱面。",paginating:"正在安排 A4 页面。",finishing:"正在保存完整 PDF 和全部预览。",cancelling:"正在停止实际进程并清理临时文件。"};
let taskId, capability, timer, previewLoaded = false;
const blobs = [];
function showError(id, message) { $(id).textContent = message; $(id).hidden = false; }
async function api(path, options = {}) {
  const headers = {...options.headers};
  if (capability) headers.Authorization = "Bearer " + capability;
  const response = await fetch(path, {...options, headers, cache:"no-store", credentials:"omit", referrerPolicy:"no-referrer"});
  if (!response.ok) {
    let message = "请求未完成，请稍后重试。";
    try { message = (await response.json()).error.message; } catch (_) {}
    const error = new Error(message); error.status = response.status; throw error;
  }
  return response;
}
$("submit-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("submit-error").hidden = true; $("submit-button").disabled = true;
  try {
    const response = await api("/api/tasks", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url:$("source").value.trim()})});
    const created = await response.json(); window.location.assign(created.link);
  } catch (error) { showError("submit-error", error.message); $("submit-button").disabled = false; }
});
async function loadPreviews(count) {
  $("task-error").hidden = true;
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
  } catch (error) { showError("task-error", "预览加载失败。" + error.message); $("reload-previews").hidden = false; }
}
async function refresh() {
  clearTimeout(timer);
  try {
    const state = await (await api(`/api/tasks/${taskId}`)).json();
    $("task-error").hidden = true;
    $("task-title").textContent = titles[state.state] || "正在读取任务";
    let description = stages[state.stage] || "";
    if (state.state === "queued") description = `当前排在等待队列第 ${state.queue_position} 位。关掉页面后任务仍会继续。`;
    if (state.state === "complete") description = `已整理为 ${state.result.page_count} 页 A4 鼓谱，可查看全部页面并下载。`;
    if (state.error) description = state.error.message;
    if (state.state === "cancelled") description = "处理已停止，临时文件已清理。你可以显式重新排队。";
    $("task-description").textContent = description;
    $("task-meta").hidden = false; $("source-label").textContent = `${state.source.bvid} · 第 ${state.source.page} P`;
    $("source-link").href = state.source.url; $("save-link").hidden = false;
    $("task-link").value = window.location.href;
    $("cancel").hidden = !["queued","running"].includes(state.state);
    $("retry").hidden = !["failed","cancelled","interrupted"].includes(state.state);
    $("download").hidden = state.state !== "complete";
    $("result").hidden = state.state !== "complete";
    if (state.state === "complete") {
      $("expiry").textContent = "结果保留至 " + new Date(state.expires_at * 1000).toLocaleString("zh-CN", {hour12:false});
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
    showError("task-error", error.message);
    if (error.status === 404 || error.status === 410) {
      $("task-title").textContent = error.status === 410 ? "结果已到期" : "无法访问此任务";
      $("task-description").textContent = error.status === 410 ? "结果保留期为完成后 24 小时。请重新提交来源链接。" : "请使用提交后保存的完整链接，包含 # 后面的访问凭据。";
      for (const id of ["download","cancel","retry","result"]) $(id).hidden = true;
    } else timer = setTimeout(refresh, 3000);
  }
}
for (const action of ["cancel","retry"]) $(action).addEventListener("click", async () => {
  $(action).disabled = true; $("task-error").hidden = true;
  try { await api(`/api/tasks/${taskId}/${action}`, {method:"POST"}); previewLoaded = false; await refresh(); }
  catch (error) { showError("task-error", error.message); }
  finally { $(action).disabled = false; }
});
$("download").addEventListener("click", async () => {
  $("download").disabled = true; $("task-error").hidden = true;
  try {
    const response = await api(`/api/tasks/${taskId}/pdf`);
    if (Number(response.headers.get("Content-Length")) > 256 * 1024 * 1024) throw new Error("PDF 超过本页 256 MiB 下载上限，请联系维护者。");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = "鼓谱.pdf"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) { showError("task-error", error.message); }
  finally { $("download").disabled = false; }
});
$("copy-link").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(window.location.href); $("copy-status").textContent = "链接已复制。"; }
  catch (_) { $("task-link").focus(); $("task-link").select(); $("copy-status").textContent = "请复制已选中的完整链接。"; }
});
window.addEventListener("pagehide", () => { clearTimeout(timer); for (const url of blobs) URL.revokeObjectURL(url); });
window.addEventListener("pageshow", (event) => { if (event.persisted && taskId && capability) { previewLoaded = false; refresh(); } });
const match = /^\/task\/([A-Za-z0-9_-]+)$/.exec(window.location.pathname);
if (match) {
  taskId = match[1]; capability = window.location.hash.slice(1);
  $("submission").hidden = true; $("task").hidden = false;
  if (/^[A-Za-z0-9_-]{43}$/.test(capability)) refresh();
  else { $("task-title").textContent = "访问链接不完整"; $("task-description").textContent = "请打开提交后保存的完整链接，包含 # 后面的访问凭据。"; }
}
