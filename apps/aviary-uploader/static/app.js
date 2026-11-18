(function () {
  "use strict";

  const root = document.querySelector("main");
  const COLLECTIONS_URL = root.dataset.collectionsUrl;
  const PARSE_URL = root.dataset.parseUrl;
  const CREATE_URL = root.dataset.createUrl;
  const MAX_BYTES = Number(root.dataset.maxMb) * 1024 * 1024;
  const CONFIGURED = root.dataset.configured === "true";

  const collectionSel = document.getElementById("collection");
  const reloadBtn = document.getElementById("reload-btn");
  const collectionMsg = document.getElementById("collection-msg");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const queueEl = document.getElementById("queue");
  const queueTitle = document.getElementById("queue-title");
  const queueMsg = document.getElementById("queue-msg");
  const listEl = document.getElementById("row-list");
  const rowTemplate = document.getElementById("row-template");
  const uploadBtn = document.getElementById("upload-btn");
  const stopBtn = document.getElementById("stop-btn");
  const resultsBtn = document.getElementById("results-btn");
  const clearBtn = document.getElementById("clear-btn");

  let items = [];
  let fileName = "";
  let running = false;
  let stopRequested = false;

  // ---- helpers -----------------------------------------------------------

  async function fetchJSON(url, options) {
    let res;
    try {
      res = await fetch(url, options);
    } catch (_) {
      throw new Error("Could not reach the server");
    }
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON error page */ }
    if (!res.ok) throw new Error((body && body.error) || `Server error (${res.status})`);
    return body;
  }

  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  // ---- collections -------------------------------------------------------

  async function loadCollections() {
    if (!CONFIGURED) {
      collectionSel.replaceChildren(new Option("Not available", ""));
      reloadBtn.disabled = true;
      return;
    }
    const previous = collectionSel.value;
    collectionSel.disabled = true;
    collectionSel.replaceChildren(new Option("Loading collections…", ""));
    collectionMsg.hidden = true;
    try {
      const { collections } = await fetchJSON(COLLECTIONS_URL);
      const options = [new Option(collections.length ? "Select a collection…"
        : "No collections found", "")];
      for (const c of collections) options.push(new Option(`${c.title} (#${c.id})`, c.id));
      collectionSel.replaceChildren(...options);
      if (previous && collections.some((c) => String(c.id) === previous)) {
        collectionSel.value = previous;
      }
      collectionSel.disabled = running || collections.length === 0;
    } catch (err) {
      collectionSel.replaceChildren(new Option("Couldn’t load collections", ""));
      collectionMsg.textContent = err.message;
      collectionMsg.className = "hint error";
      collectionMsg.hidden = false;
    }
    refresh();
  }

  // ---- rows --------------------------------------------------------------

  function describe(row) {
    const parts = [`Row ${row.row}`];
    if (row.cuid) parts.push(row.cuid);
    parts.push(plural(row.metadata.length, "metadata value"));
    parts.push(plural(row.media.length, "media file"));
    return parts.join(" · ");
  }

  function buildRow(item) {
    const el = rowTemplate.content.firstElementChild.cloneNode(true);
    el.querySelector(".file-name").textContent = item.row.title || "(no title)";
    el.querySelector(".row-meta").textContent = describe(item.row);
    return el;
  }

  function setState(item, state, status, note, link) {
    item.state = state;
    item.status = status;
    item.note = note || "";
    const el = item.el;
    el.dataset.state = state;
    el.querySelector(".file-status").textContent = status;

    const meta = el.querySelector(".row-meta");
    meta.textContent = describe(item.row);
    if (link) {
      meta.append(" · ");
      const a = document.createElement("a");
      a.href = link;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Open in Aviary";
      meta.append(a);
    }

    const notesEl = el.querySelector(".file-notes");
    notesEl.textContent = item.note;
    notesEl.hidden = !item.note;
  }

  function showRows(rows) {
    listEl.replaceChildren();
    items = rows.map((row) => {
      const item = { row, state: "pending", status: "", note: "", result: null };
      item.el = buildRow(item);
      listEl.appendChild(item.el);
      if (row.errors.length) setState(item, "invalid", "Needs fixing", row.errors.join("; "));
      else setState(item, "pending", "Ready");
      return item;
    });
    refresh();
  }

  async function loadFile(file) {
    if (running || !file) return;
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      showMessage(/\.xls$/i.test(file.name)
        ? "Old .xls workbooks aren’t supported. Save the file as .xlsx or .csv first."
        : "Only .csv and .xlsx files can be read.", true);
      return;
    }
    if (file.size > MAX_BYTES) {
      showMessage(`The file is larger than ${root.dataset.maxMb} MB.`, true);
      return;
    }
    fileName = file.name;
    items = [];
    listEl.replaceChildren();
    showMessage(`Reading ${file.name}…`);
    const form = new FormData();
    form.append("file", file);
    try {
      const { rows } = await fetchJSON(PARSE_URL, { method: "POST", body: form });
      showRows(rows);
    } catch (err) {
      showMessage(err.message, true);
    }
  }

  function showMessage(text, isError) {
    queueEl.hidden = false;
    queueMsg.textContent = text;
    queueMsg.className = isError ? "hint error" : "hint";
    refresh();
  }

  function refresh() {
    queueEl.hidden = items.length === 0 && !queueMsg.textContent;
    const invalid = items.filter((it) => it.state === "invalid").length;
    const todo = items.filter((it) => it.state === "pending" || it.state === "error").length;
    const finished = items.filter((it) => it.result).length;
    const collectionChosen = Boolean(collectionSel.value);

    queueTitle.textContent = items.length
      ? `${fileName}: ${plural(items.length, "row")}` : "Rows";

    if (items.length && !running) {
      if (invalid) {
        queueMsg.textContent = `${plural(invalid, "row")} need fixing. Correct the ` +
          "spreadsheet and add it again. Nothing is uploaded until every row is valid.";
        queueMsg.className = "hint error";
      } else if (!collectionChosen && todo) {
        queueMsg.textContent = "Choose a collection above to upload these rows.";
        queueMsg.className = "hint";
      } else if (finished) {
        queueMsg.textContent = summary();
        queueMsg.className = "hint";
      } else {
        queueMsg.textContent = "";
      }
    }

    uploadBtn.disabled = running || !CONFIGURED || invalid > 0 || todo === 0 || !collectionChosen;
    uploadBtn.textContent = running ? "Uploading…"
      : todo && items.some((it) => it.state === "error") ? `Retry ${plural(todo, "row")}`
      : todo ? `Upload ${plural(todo, "row")}` : "Upload";
    stopBtn.hidden = !running;
    resultsBtn.disabled = running || finished === 0;
    clearBtn.disabled = running;
    collectionSel.disabled = running || collectionSel.options.length < 2;
    dropzone.classList.toggle("disabled", running);
    fileInput.disabled = running;
  }

  function summary() {
    const count = (s) => items.filter((it) => it.state === s).length;
    const parts = [];
    if (count("done")) parts.push(`${count("done")} created`);
    if (count("partial")) parts.push(`${count("partial")} created with media errors`);
    if (count("skipped")) parts.push(`${count("skipped")} skipped (already in Aviary)`);
    if (count("error")) parts.push(`${count("error")} failed`);
    if (count("pending")) parts.push(`${count("pending")} not uploaded`);
    return parts.join(", ") + ".";
  }

  // ---- upload ------------------------------------------------------------

  async function uploadOne(item, collectionId) {
    setState(item, "working", "Creating…");
    try {
      const result = await fetchJSON(CREATE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ collection_id: collectionId, row: item.row }),
      });
      item.result = result;
      const failed = result.media.filter((m) => m.error);
      if (result.status === "skipped") {
        setState(item, "skipped", "Skipped", result.message, result.url);
      } else if (failed.length) {
        setState(item, "partial", `Created · ${failed.length} of ${result.media.length} media failed`,
          failed.map((m) => `${m.url}: ${m.error}`).join("\n"), result.url);
      } else {
        setState(item, "done", result.media.length
          ? `Created · ${plural(result.media.length, "media file")} queued` : "Created",
          "", result.url);
      }
    } catch (err) {
      item.result = { status: "failed", error: err.message, media: [] };
      setState(item, "error", "Failed", err.message);
    }
  }

  async function uploadAll() {
    const collectionId = collectionSel.value;
    if (running || !collectionId) return;
    const todo = items.filter((it) => it.state === "pending" || it.state === "error");
    const name = collectionSel.selectedOptions[0].textContent;
    if (!todo.length || !window.confirm(
      `Create ${plural(todo.length, "resource")} in “${name}”?`)) return;

    running = true;
    stopRequested = false;
    stopBtn.disabled = false;
    refresh();
    // One row at a time: keeps load on Aviary low and the order predictable.
    for (const [i, item] of todo.entries()) {
      if (stopRequested) break;
      queueMsg.textContent = `Uploading row ${i + 1} of ${todo.length}…`;
      queueMsg.className = "hint";
      item.el.scrollIntoView({ block: "nearest" });
      await uploadOne(item, collectionId);
    }
    running = false;
    refresh();
  }

  // ---- results -----------------------------------------------------------

  function csvCell(value) {
    const s = value == null ? "" : String(value);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function downloadResults() {
    const lines = [["Row", "Title", "Custom Unique Identifier", "Status",
      "Resource ID", "Aviary URL", "Media OK", "Media failed", "Messages"]];
    for (const it of items) {
      const r = it.result || {};
      const media = r.media || [];
      lines.push([it.row.row, it.row.title, it.row.cuid,
        r.status || "not uploaded", r.resource_id, r.url,
        media.filter((m) => !m.error).length, media.filter((m) => m.error).length,
        it.note.replace(/\n/g, "; ")]);
    }
    const csv = lines.map((l) => l.map(csvCell).join(",")).join("\r\n") + "\r\n";
    const blob = new Blob(["﻿" + csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName.replace(/\.(csv|xlsx)$/i, "") + "_aviary-results.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---- wiring ------------------------------------------------------------

  fileInput.addEventListener("change", () => {
    loadFile(fileInput.files[0]);
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (e) => {
    e.preventDefault();
    if (!running) dropzone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragging");
  }));
  dropzone.addEventListener("drop", (e) => loadFile(e.dataTransfer.files[0]));

  // Stop a file dropped just outside the zone from opening in the browser.
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  window.addEventListener("beforeunload", (e) => {
    if (running) e.preventDefault();
  });

  collectionSel.addEventListener("change", refresh);
  reloadBtn.addEventListener("click", loadCollections);
  uploadBtn.addEventListener("click", uploadAll);
  stopBtn.addEventListener("click", () => {
    stopRequested = true;
    stopBtn.disabled = true;
    queueMsg.textContent = "Stopping after the current row…";
  });
  resultsBtn.addEventListener("click", downloadResults);
  clearBtn.addEventListener("click", () => {
    items = [];
    fileName = "";
    listEl.replaceChildren();
    queueMsg.textContent = "";
    refresh();
  });

  loadCollections();
})();
