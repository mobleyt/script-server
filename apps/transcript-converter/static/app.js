(function () {
  "use strict";

  const root = document.querySelector("main");
  const CONVERT_URL = root.dataset.convertUrl;
  const MAX_BYTES = Number(root.dataset.maxMb) * 1024 * 1024;
  const CONCURRENCY = 2;

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const queueEl = document.getElementById("queue");
  const queueTitle = document.getElementById("queue-title");
  const listEl = document.getElementById("file-list");
  const rowTemplate = document.getElementById("row-template");
  const convertBtn = document.getElementById("convert-btn");
  const zipBtn = document.getElementById("zip-btn");
  const clearBtn = document.getElementById("clear-btn");
  const optionInputs = document.querySelectorAll(".options input[type=checkbox]");

  let items = [];
  let nextId = 1;
  let running = false;

  // ---- options -----------------------------------------------------------

  function currentOptions() {
    const opts = {};
    optionInputs.forEach((input) => { opts[input.name] = input.checked; });
    return opts;
  }

  const optionsKey = (opts) => JSON.stringify(opts);

  // ---- queue management --------------------------------------------------

  function txtName(pdfName) {
    return pdfName.replace(/\.pdf$/i, "") + ".txt";
  }

  function addFiles(fileList) {
    for (const file of fileList) {
      const duplicate = items.some((it) =>
        it.file.name === file.name && it.file.size === file.size &&
        it.file.lastModified === file.lastModified);
      if (duplicate) continue;

      const item = { id: nextId++, file, state: "pending", text: null, notes: [], key: null };
      item.el = buildRow(item);
      listEl.appendChild(item.el);
      items.push(item);

      if (!/\.pdf$/i.test(file.name)) {
        setState(item, "error", "Not a PDF file");
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
    el.querySelector(".preview-btn").addEventListener("click", () => togglePreview(item));
    el.querySelector(".remove-btn").addEventListener("click", () => removeItem(item));
    return el;
  }

  function removeItem(item) {
    if (item.state === "working") return;
    items = items.filter((it) => it !== item);
    item.el.remove();
    refresh();
  }

  function setState(item, state, status) {
    item.state = state;
    const el = item.el;
    el.dataset.state = state;
    el.querySelector(".file-status").textContent = status;
    const done = state === "done";
    el.querySelector(".download-btn").hidden = !done;
    el.querySelector(".preview-btn").hidden = !done;
    el.querySelector(".remove-btn").disabled = state === "working";

    const notesEl = el.querySelector(".file-notes");
    notesEl.textContent = done ? item.notes.join(" ") : "";
    notesEl.hidden = !(done && item.notes.length);
    if (!done) {
      el.querySelector(".preview").hidden = true;
      el.querySelector(".preview-btn").textContent = "Preview";
    }
  }

  // Items that need (re)converting: not yet done, or done with other options.
  function needsWork(item, key) {
    if (item.state === "working") return false;
    if (item.state === "error" && !isConvertible(item)) return false;
    return item.state !== "done" || item.key !== key;
  }

  function isConvertible(item) {
    return /\.pdf$/i.test(item.file.name) && item.file.size <= MAX_BYTES;
  }

  function refresh() {
    queueEl.hidden = items.length === 0;
    const doneCount = items.filter((it) => it.state === "done").length;
    const key = optionsKey(currentOptions());
    const todo = items.filter((it) => needsWork(it, key)).length;

    queueTitle.textContent = `Files (${doneCount} of ${items.length} converted)`;
    convertBtn.disabled = running || todo === 0;
    convertBtn.textContent = running ? "Converting…"
      : todo === 0 ? "Convert"
      : `Convert ${todo} file${todo === 1 ? "" : "s"}`;
    zipBtn.disabled = running || doneCount === 0;
    clearBtn.disabled = running;
  }

  // ---- conversion --------------------------------------------------------

  async function convertOne(item, opts, key) {
    setState(item, "working", "Converting…");
    const form = new FormData();
    form.append("file", item.file);
    for (const [name, value] of Object.entries(opts)) form.append(name, value ? "1" : "0");

    try {
      const res = await fetch(CONVERT_URL, { method: "POST", body: form });
      let body = null;
      try { body = await res.json(); } catch (_) { /* non-JSON error page */ }
      if (!res.ok) {
        throw new Error((body && body.error) || `Server error (${res.status})`);
      }
      item.text = body.text;
      item.notes = body.notes || [];
      item.key = key;
      setState(item, "done", "Converted");
    } catch (err) {
      item.text = null;
      setState(item, "error", err.message === "Failed to fetch"
        ? "Could not reach the server" : err.message);
    }
    refresh();
  }

  async function convertAll() {
    if (running) return;
    const opts = currentOptions();
    const key = optionsKey(opts);
    const todo = items.filter((it) => needsWork(it, key));
    if (!todo.length) return;

    running = true;
    refresh();
    const queue = todo.slice();
    const worker = async () => {
      while (queue.length) await convertOne(queue.shift(), opts, key);
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
    saveBlob(new Blob([item.text], { type: "text/plain;charset=utf-8" }), txtName(item.file.name));
  }

  function downloadZip() {
    const encoder = new TextEncoder();
    const used = new Set();
    const entries = items.filter((it) => it.state === "done").map((it) => {
      let name = txtName(it.file.name);
      for (let n = 2; used.has(name.toLowerCase()); n++) {
        name = txtName(it.file.name).replace(/\.txt$/, ` (${n}).txt`);
      }
      used.add(name.toLowerCase());
      return { name, data: encoder.encode(it.text) };
    });
    if (entries.length) saveBlob(window.makeZip(entries), "transcripts.zip");
  }

  function togglePreview(item) {
    const pre = item.el.querySelector(".preview");
    const btn = item.el.querySelector(".preview-btn");
    if (pre.hidden) {
      pre.textContent = item.text || "(empty)";
      pre.hidden = false;
      btn.textContent = "Hide preview";
    } else {
      pre.hidden = true;
      btn.textContent = "Preview";
    }
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
  optionInputs.forEach((input) => input.addEventListener("change", refresh));
})();
