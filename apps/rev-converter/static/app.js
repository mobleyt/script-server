(function () {
  "use strict";

  const root = document.querySelector("main");
  const CONVERT_URL = root.dataset.convertUrl;
  const MAX_BYTES = Number(root.dataset.maxMb) * 1024 * 1024;
  const CONCURRENCY = 2;
  const DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const queueEl = document.getElementById("queue");
  const queueTitle = document.getElementById("queue-title");
  const listEl = document.getElementById("file-list");
  const rowTemplate = document.getElementById("row-template");
  const convertBtn = document.getElementById("convert-btn");
  const zipBtn = document.getElementById("zip-btn");
  const clearBtn = document.getElementById("clear-btn");

  let items = [];
  let nextId = 1;
  let running = false;

  // ---- queue management --------------------------------------------------

  function outputName(docxName) {
    return docxName.replace(/\.docx$/i, "") + "_reformatted.docx";
  }

  function isConvertible(item) {
    return /\.docx$/i.test(item.file.name) && item.file.size <= MAX_BYTES;
  }

  function addFiles(fileList) {
    for (const file of fileList) {
      const duplicate = items.some((it) =>
        it.file.name === file.name && it.file.size === file.size &&
        it.file.lastModified === file.lastModified);
      if (duplicate) continue;

      const item = { id: nextId++, file, state: "pending", blob: null, count: 0 };
      item.el = buildRow(item);
      listEl.appendChild(item.el);
      items.push(item);

      if (/\.doc$/i.test(file.name)) {
        setState(item, "error", "Old .doc format — save as .docx in Word first");
      } else if (!/\.docx$/i.test(file.name)) {
        setState(item, "error", "Not a Word .docx file");
      } else if (file.size > MAX_BYTES) {
        setState(item, "error", `Larger than ${root.dataset.maxMb} MB`);
      } else {
        setState(item, "pending", "Ready");
      }
    }
    refresh();
  }

  function buildRow(item) {
    const el = rowTemplate.content.firstElementChild.cloneNode(true);
    el.querySelector(".file-name").textContent = item.file.name;
    el.querySelector(".download-btn").addEventListener("click", () => download(item));
    el.querySelector(".remove-btn").addEventListener("click", () => removeItem(item));
    return el;
  }

  function removeItem(item) {
    if (item.state === "working") return;
    items = items.filter((it) => it !== item);
    item.el.remove();
    refresh();
  }

  function setState(item, state, status, note) {
    item.state = state;
    const el = item.el;
    el.dataset.state = state;
    el.querySelector(".file-status").textContent = status;
    el.querySelector(".download-btn").hidden = state !== "done";
    el.querySelector(".remove-btn").disabled = state === "working";

    const notesEl = el.querySelector(".file-notes");
    notesEl.textContent = note || "";
    notesEl.hidden = !note;
  }

  function refresh() {
    queueEl.hidden = items.length === 0;
    const doneCount = items.filter((it) => it.state === "done").length;
    const todo = items.filter((it) => it.state === "pending" ||
      (it.state === "error" && isConvertible(it))).length;

    queueTitle.textContent = `Files (${doneCount} of ${items.length} reformatted)`;
    convertBtn.disabled = running || todo === 0;
    convertBtn.textContent = running ? "Reformatting…"
      : todo === 0 ? "Reformat"
      : `Reformat ${todo} file${todo === 1 ? "" : "s"}`;
    zipBtn.disabled = running || doneCount === 0;
    clearBtn.disabled = running;
  }

  // ---- conversion --------------------------------------------------------

  async function convertOne(item) {
    setState(item, "working", "Reformatting…");
    const form = new FormData();
    form.append("file", item.file);

    try {
      const res = await fetch(CONVERT_URL, { method: "POST", body: form });
      if (!res.ok) {
        let body = null;
        try { body = await res.json(); } catch (_) { /* non-JSON error page */ }
        throw new Error((body && body.error) || `Server error (${res.status})`);
      }
      item.blob = new Blob([await res.arrayBuffer()], { type: DOCX_TYPE });
      item.count = Number(res.headers.get("X-Reformatted-Count") || 0);
      if (item.count === 0) {
        setState(item, "done", "No changes",
          "No Rev speaker lines were found, e.g. “Name (00:00:00):” with a linked timestamp. The file is unchanged.");
      } else {
        setState(item, "done",
          `${item.count} speaker ${item.count === 1 ? "entry" : "entries"} reformatted`);
      }
    } catch (err) {
      item.blob = null;
      setState(item, "error", err.message === "Failed to fetch"
        ? "Could not reach the server" : err.message);
    }
    refresh();
  }

  async function convertAll() {
    if (running) return;
    const todo = items.filter((it) => it.state === "pending" ||
      (it.state === "error" && isConvertible(it)));
    if (!todo.length) return;

    running = true;
    refresh();
    const queue = todo.slice();
    const worker = async () => {
      while (queue.length) await convertOne(queue.shift());
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker));
    running = false;
    refresh();
  }

  // ---- output ------------------------------------------------------------

  function saveBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function download(item) {
    saveBlob(item.blob, outputName(item.file.name));
  }

  async function downloadZip() {
    const used = new Set();
    const done = items.filter((it) => it.state === "done");
    const entries = [];
    for (const it of done) {
      let name = outputName(it.file.name);
      for (let n = 2; used.has(name.toLowerCase()); n++) {
        name = outputName(it.file.name).replace(/\.docx$/, ` (${n}).docx`);
      }
      used.add(name.toLowerCase());
      entries.push({ name, data: new Uint8Array(await it.blob.arrayBuffer()) });
    }
    if (entries.length) saveBlob(window.makeZip(entries), "reformatted-transcripts.zip");
  }

  // ---- wiring ------------------------------------------------------------

  fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragging");
  }));
  dropzone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  // Stop a file dropped just outside the zone from opening in the browser.
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  convertBtn.addEventListener("click", convertAll);
  zipBtn.addEventListener("click", downloadZip);
  clearBtn.addEventListener("click", () => {
    items = [];
    listEl.replaceChildren();
    refresh();
  });
})();
