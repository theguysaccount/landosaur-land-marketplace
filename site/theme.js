/* Landosaur light/dark theme toggle — honors prefers-color-scheme by default and persists explicit user choice. */
(function () {
  "use strict";
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  var root = document.documentElement;
  function currentMode() {
    var explicit = root.getAttribute("data-theme");
    if (explicit === "dark" || explicit === "light") return explicit;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function render() {
    var dark = currentMode() === "dark";
    btn.textContent = dark ? "☀ Light" : "☾ Dark";
    btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }
  btn.addEventListener("click", function () {
    var next = currentMode() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("landosaur_theme", next); } catch (e) {}
    render();
  });
  render();
})();
