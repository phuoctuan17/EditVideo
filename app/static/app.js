"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  file: null,
  bgmId: null,
  highlight: "#FFD400",
  aspect: "original",
  mode: "blur",
  analyzeTimer: null,
  customAssPath: null,
  segments: []
};

const fmt = (s) => {
  s = Math.max(0, s);
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

/* ---------- Mobile Tab Switcher ---------- */
document.querySelectorAll(".m-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".m-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    const target = tab.dataset.tab;
    $("paneLeft").classList.toggle("active", target === "col-left");
    $("paneRight").classList.toggle("active", target === "col-right");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});

/* ---------- GPU chip ---------- */
fetch("/api/info")
  .then(r => r.json())
  .then(i => {
    const c = $("gpuChip");
    c.textContent = i.nvenc ? "GPU NVENC sẵn sàng" : "Không có NVENC – dùng CPU";
    c.classList.add(i.nvenc ? "ok" : "warn");
    if (!i.nvenc) $("useGpu").value = "false";
  })
  .catch(() => {
    $("gpuChip").textContent = "Mất kết nối server";
  });

/* ---------- option cards ---------- */
document.querySelectorAll(".opt[data-opt]").forEach(card => {
  const cb = card.querySelector(".opt-head input[type=checkbox]");
  const sync = () => card.classList.toggle("on", cb.checked);
  cb.addEventListener("change", () => {
    sync();
    if (card.dataset.opt === "silence") scheduleAnalyze();
  });
  sync();
});

const bindRange = (id, fn) => {
  const el = $(id);
  const upd = () => {
    $(id + "V").textContent = fn ? fn(el.value) : el.value;
  };
  el.addEventListener("input", upd);
  upd();
};
bindRange("minSilence");
bindRange("noiseDb");
bindRange("rate", v => (v >= 0 ? "+" : "") + v + "%");
bindRange("bgmVol");
["minSilence", "noiseDb"].forEach(id => $(id).addEventListener("input", scheduleAnalyze));

$("swatches").addEventListener("click", e => {
  const b = e.target.closest(".sw");
  if (!b) return;
  document.querySelectorAll(".sw").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  state.highlight = b.dataset.c;
});

function bindSeg(id, key) {
  $(id).addEventListener("click", e => {
    const b = e.target.closest("button");
    if (!b) return;
    $(id).querySelectorAll("button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    state[key] = b.dataset.v;
  });
}
bindSeg("aspectSeg", "aspect");
bindSeg("modeSeg", "mode");

/* ---------- upload ---------- */
const dz = $("dropzone"), fileInput = $("fileInput");
dz.addEventListener("click", () => fileInput.click());
dz.addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});
["dragenter", "dragover"].forEach(ev =>
  dz.addEventListener(ev, e => {
    e.preventDefault();
    dz.classList.add("drag");
  })
);
["dragleave", "drop"].forEach(ev =>
  dz.addEventListener(ev, e => {
    e.preventDefault();
    dz.classList.remove("drag");
  })
);
dz.addEventListener("drop", e => {
  if (e.dataTransfer.files[0]) uploadVideo(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) uploadVideo(fileInput.files[0]);
});
$("changeFile").addEventListener("click", () => fileInput.click());

function xhrUpload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);
    const x = new XMLHttpRequest();
    x.open("POST", "/api/upload");
    x.upload.onprogress = e =>
      e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () =>
      x.status < 300
        ? resolve(JSON.parse(x.responseText))
        : reject(new Error(JSON.parse(x.responseText).detail || x.statusText));
    x.onerror = () => reject(new Error("Lỗi mạng khi upload"));
    x.send(fd);
  });
}

async function uploadVideo(file) {
  const bar = $("uploadBar");
  bar.hidden = false;
  try {
    state.file = await xhrUpload(file, p =>
      (bar.firstElementChild.style.width = p * 100 + "%")
    );
  } catch (e) {
    alert(e.message);
    bar.hidden = true;
    return;
  }
  bar.hidden = true;
  dz.hidden = true;
  $("playerWrap").hidden = false;
  $("player").src = state.file.url;
  $("fileMeta").textContent = `${state.file.name} · ${state.file.width}×${state.file.height} · ${fmt(state.file.duration)}`;
  $("renderBtn").disabled = false;
  state.customAssPath = null;
  $("customAssStatus").hidden = true;
  drawTimeline({
    duration: state.file.duration,
    keep: [[0, state.file.duration]],
    silences: []
  });
  $("tlStats").textContent = "Bật 'Cắt khoảng lặng' để xem trước";
  scheduleAnalyze(true);
}

$("bgmFile").addEventListener("change", async () => {
  const f = $("bgmFile").files[0];
  if (!f) {
    state.bgmId = null;
    return;
  }
  try {
    state.bgmId = (await xhrUpload(f, () => {})).id;
  } catch (e) {
    alert(e.message);
  }
});

/* ---------- timeline ---------- */
function scheduleAnalyze(force) {
  clearTimeout(state.analyzeTimer);
  if (!state.file || (!force && !$("cutSilence").checked)) return;
  state.analyzeTimer = setTimeout(analyze, 350);
}

async function analyze() {
  $("tlBusy").hidden = false;
  const q = new URLSearchParams({
    id: state.file.id,
    min_silence: $("minSilence").value,
    noise_db: $("noiseDb").value
  });
  try {
    const d = await (await fetch("/api/analyze?" + q)).json();
    drawTimeline(d);
    const removed = d.duration - d.result_duration;
    $("tlStats").textContent = `${fmt(d.duration)} → ${fmt(d.result_duration)} · cắt ${removed.toFixed(1)}s (${((removed / d.duration) * 100).toFixed(0)}%)`;
  } catch {
    $("tlStats").textContent = "Không phân tích được âm thanh";
  }
  $("tlBusy").hidden = true;
}

function drawTimeline(d) {
  const t = $("tlTrack");
  t.innerHTML = "";
  const add = (s, e, cls) => {
    const el = document.createElement("div");
    el.className = "tl-seg " + cls;
    el.style.left = (s / d.duration) * 100 + "%";
    el.style.width =
      Math.max(((Math.min(e, d.duration) - s) / d.duration) * 100, 0.15) + "%";
    el.title = `${fmt(s)} – ${fmt(Math.min(e, d.duration))}`;
    t.appendChild(el);
  };
  (d.silences || []).forEach(([s, e]) => add(s, e, "cut"));
  d.keep.forEach(([s, e]) => add(s, e, "keep"));
}

$("timeline").addEventListener("click", e => {
  if (!state.file) return;
  const r = $("timeline").getBoundingClientRect();
  $("player").currentTime = ((e.clientX - r.left) / r.width) * state.file.duration;
});

$("player").addEventListener("timeupdate", () => {
  const p = $("player");
  if (p.duration)
    $("tlHead").style.left = (p.currentTime / p.duration) * 100 + "%";
});

/* ---------- AI script writer ---------- */
$("toggleAiBtn").addEventListener("click", () => {
  const f = $("aiForm");
  f.hidden = !f.hidden;
});

$("aiProvider").addEventListener("change", () => {
  $("geminiKeyField").hidden = $("aiProvider").value !== "gemini";
});

try {
  const savedKey = localStorage.getItem("gemini_key");
  if (savedKey) $("geminiKey").value = savedKey;
} catch (e) {}

$("genScriptBtn").addEventListener("click", async () => {
  if (!state.file) {
    alert("Vui lòng tải video lên trước để AI phân tích!");
    return;
  }
  const btn = $("genScriptBtn");
  const msg = $("aiMsg");
  btn.disabled = true;
  btn.firstElementChild.textContent = "⏳ Đang phân tích video & viết kịch bản...";
  msg.textContent = "";

  const fd = new FormData();
  fd.append("file_id", state.file.id);
  fd.append("style", $("aiStyle").value);
  fd.append("topic", $("aiTopic").value);
  fd.append("provider", $("aiProvider").value);
  const key = $("geminiKey").value.trim();
  if (key) {
    fd.append("api_key", key);
    try {
      localStorage.setItem("gemini_key", key);
    } catch (e) {}
  }

  try {
    const res = await fetch("/api/ai-script", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Không thể tạo kịch bản");
    }
    const data = await res.json();
    $("script").value = data.script;
    $("dubOn").checked = true;
    $("dubOn").dispatchEvent(new Event("change"));
    msg.textContent = `✅ Đã tạo kịch bản (${data.target_words} từ, ~${Math.round(data.duration)}s, nguồn: ${data.provider})`;
  } catch (err) {
    alert(err.message);
    msg.textContent = "❌ Lỗi: " + err.message;
  } finally {
    btn.disabled = false;
    btn.firstElementChild.textContent = "Tạo kịch bản AI ngay";
  }
});

/* ---------- Interactive Subtitle Editor Modal ---------- */
$("openSubEditorBtn").addEventListener("click", async () => {
  if (!state.file) {
    alert("Vui lòng tải video lên trước để xem và sửa phụ đề!");
    return;
  }
  const modal = $("subModal");
  modal.hidden = false;
  $("subList").innerHTML = `<p class="muted" style="text-align:center; padding:24px;">⏳ Đang nhận diện lời thoại bằng Whisper AI...</p>`;

  const fd = new FormData();
  fd.append("file_id", state.file.id);
  fd.append("sub_model", $("subModel").value);
  fd.append("sub_language", $("subLang").value);

  try {
    const res = await fetch("/api/subtitles/transcribe", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Lỗi khi trích xuất phụ đề");
    }
    const data = await res.json();
    state.segments = data.segments || [];
    renderSubList();
  } catch (err) {
    $("subList").innerHTML = `<p class="error" style="margin:10px;">Lỗi: ${err.message}</p>`;
  }
});

function renderSubList() {
  const container = $("subList");
  if (!state.segments.length) {
    container.innerHTML = `<p class="muted" style="text-align:center; padding:20px;">Không tìm thấy lời thoại nào trong video.</p>`;
    return;
  }
  container.innerHTML = state.segments
    .map(
      (s, i) => `
    <div class="sub-item">
      <span class="sub-time">${fmt(s.start)} - ${fmt(s.end)}</span>
      <input type="text" class="sub-input" data-idx="${i}" value="${s.text.replace(/"/g, "&quot;")}">
    </div>`
    )
    .join("");

  container.querySelectorAll(".sub-input").forEach(inp => {
    inp.addEventListener("input", e => {
      const idx = +e.target.dataset.idx;
      state.segments[idx].text = e.target.value;
    });
  });
}

function closeSubModal() {
  $("subModal").hidden = true;
}
$("closeSubModal").addEventListener("click", closeSubModal);
$("cancelSubBtn").addEventListener("click", closeSubModal);
$("subModal").addEventListener("click", (e) => {
  if (e.target === $("subModal")) closeSubModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("subModal").hidden) closeSubModal();
});

$("saveSubBtn").addEventListener("click", async () => {
  if (!state.file || !state.segments.length) {
    closeSubModal();
    return;
  }
  const btn = $("saveSubBtn");
  btn.disabled = true;
  btn.textContent = "Đang lưu...";

  const fd = new FormData();
  fd.append("file_id", state.file.id);
  fd.append("segments_json", JSON.stringify(state.segments));
  fd.append("aspect", state.aspect);
  fd.append("aspect_mode", state.mode);
  fd.append("sub_font_size", $("subFontSize").value);
  fd.append("sub_highlight", state.highlight);

  try {
    const res = await fetch("/api/subtitles/save", { method: "POST", body: fd });
    if (!res.ok) throw new Error("Không thể lưu phụ đề");
    const data = await res.json();
    state.customAssPath = data.ass_path;
    $("customAssStatus").hidden = false;
    $("subsOn").checked = true;
    $("subsOn").dispatchEvent(new Event("change"));
    closeSubModal();
  } catch (err) {
    alert("Lỗi lưu phụ đề: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Lưu thay đổi phụ đề";
  }
});

/* ---------- job submission ---------- */
let ws = null;
$("renderBtn").addEventListener("click", async () => {
  if (!state.file) return;
  const fd = new FormData();
  fd.append("file_id", state.file.id);
  fd.append("cut_silence", $("cutSilence").checked);
  fd.append("min_silence", $("minSilence").value);
  fd.append("noise_db", $("noiseDb").value);
  fd.append("dub", $("dubOn").checked);
  fd.append("script", $("script").value);
  fd.append("voice", $("voice").value);
  const r = +$("rate").value;
  fd.append("rate", (r >= 0 ? "+" : "") + r + "%");
  if (state.bgmId) fd.append("bgm_id", state.bgmId);
  fd.append("bgm_volume", $("bgmVol").value / 100);

  fd.append("subtitles", $("subsOn").checked);
  fd.append("sub_model", $("subModel").value);
  fd.append("sub_language", $("subLang").value);
  fd.append("sub_highlight", state.highlight);
  fd.append("sub_font_size", $("subFontSize").value);
  if (state.customAssPath) {
    fd.append("custom_ass_path", state.customAssPath);
  }

  // Visual effects
  const isFx = $("fxOn").checked;
  fd.append("color_preset", isFx ? $("colorPreset").value : "none");
  fd.append("auto_zoom", isFx && $("autoZoom").checked);
  fd.append("watermark_text", isFx ? $("watermarkText").value : "");

  fd.append("aspect", state.aspect);
  fd.append("aspect_mode", state.mode);
  fd.append("fps", $("fps").value);
  fd.append("use_gpu", $("useGpu").value);

  const res = await fetch("/api/jobs", { method: "POST", body: fd });
  if (!res.ok) {
    alert((await res.json()).detail || "Không tạo được job");
    return;
  }
  const { id } = await res.json();
  openJobPanel();
  listen(id);
});

function openJobPanel() {
  const p = $("jobPanel");
  p.hidden = false;
  $("result").hidden = true;
  $("errorBox").hidden = true;
  $("jobTitle").textContent = "Đang xử lý…";
  $("barFill").style.width = "0%";
  $("jobPct").textContent = "0%";
  $("renderBtn").disabled = true;
  p.scrollIntoView({ behavior: "smooth", block: "start" });
}

function listen(id) {
  if (ws) ws.close();
  ws = new WebSocket(
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${id}`
  );
  ws.onmessage = e => render(JSON.parse(e.data));
  ws.onclose = () => {
    $("renderBtn").disabled = !state.file;
  };
}

function render(j) {
  const pct = Math.round(j.progress * 100);
  $("barFill").style.width = pct + "%";
  $("jobPct").textContent = pct + "%";
  $("jobMsg").textContent =
    j.status === "queued" ? `Đang chờ (vị trí ${j.position || 1})…` : j.message;
  $("stageList").innerHTML = j.stages
    .map(
      s =>
        `<li class="${s.state}"><span class="st"></span><span class="grow">${s.label}</span><span class="p">${Math.round(s.progress * 100)}%</span></li>`
    )
    .join("");
  if (j.status === "done") {
    $("jobTitle").textContent = "Xong rồi! 🎉";
    $("result").hidden = false;
    $("resultVideo").src = j.url;
    $("downloadBtn").href = j.url + "?dl=1";
  } else if (j.status === "error") {
    $("jobTitle").textContent = "Có lỗi xảy ra";
    $("errorBox").hidden = false;
    $("errorBox").textContent = j.message;
  }
}

$("newJob").addEventListener("click", () => {
  $("jobPanel").hidden = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
});

