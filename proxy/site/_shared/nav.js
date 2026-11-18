// Site header and tool menu, shared by the landing page and every app.
//
// Served by the proxy at /_shared/nav.js (with nav.css). Include it as the
// first thing in <body>:
//
//   <link rel="stylesheet" href="/_shared/nav.css">        (in <head>)
//   <script src="/_shared/nav.js"></script>                (first in <body>)
//
// It runs synchronously and inserts the header in place of the script tag, so
// the page doesn't jump when it appears. If an app runs on its own, without the
// proxy, the file 404s and the app simply has no header.
//
// When adding an app, add it to TOOLS (and a card to index.html).

(function () {
  "use strict";

  var TOOLS = [
    { name: "Transcript Converter", href: "/transcripts/" },
    { name: "Rev Transcript Reformatter", href: "/rev/" },
    { name: "Aviary Uploader", href: "/aviary/" },
  ];

  var here = location.pathname;
  var current = null;
  TOOLS.forEach(function (t) {
    if (here === t.href.slice(0, -1) || here.indexOf(t.href) === 0) current = t;
  });

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text) node.textContent = text;
    return node;
  }

  var header = el("header", { class: "ss-header" });
  var inner = el("div", { class: "ss-inner" });
  header.appendChild(inner);

  var home = el("a", { class: "ss-home", href: "/" }, "Staff Tools");
  if (!current) home.setAttribute("aria-current", "page");
  inner.appendChild(home);

  if (current) {
    inner.appendChild(el("span", { class: "ss-sep", "aria-hidden": "true" }, "/"));
    inner.appendChild(el("span", { class: "ss-current" }, current.name));
  }

  var nav = el("nav", { class: "ss-nav", "aria-label": "Tools" });
  var toggle = el("button", {
    class: "ss-toggle", type: "button",
    "aria-expanded": "false", "aria-controls": "ss-menu",
  }, "Tools");
  var menu = el("ul", { class: "ss-menu", id: "ss-menu" });
  TOOLS.forEach(function (t) {
    var li = el("li");
    var a = el("a", { href: t.href }, t.name);
    if (t === current) a.setAttribute("aria-current", "page");
    li.appendChild(a);
    menu.appendChild(li);
  });
  nav.appendChild(toggle);
  nav.appendChild(menu);
  inner.appendChild(nav);

  function setOpen(open) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    header.classList.toggle("ss-open", open);
  }
  toggle.addEventListener("click", function () {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("click", function (e) {
    if (!nav.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && header.classList.contains("ss-open")) {
      setOpen(false);
      toggle.focus();
    }
  });

  var script = document.currentScript;
  if (script && script.parentNode) script.parentNode.insertBefore(header, script);
  else document.body.insertBefore(header, document.body.firstChild);
})();
