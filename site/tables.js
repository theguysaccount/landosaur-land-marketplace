/* Sortable tables: select a column heading (or press Enter on it) to sort. */
(function () {
  "use strict";
  Array.prototype.forEach.call(document.querySelectorAll("table.sortable"), function (table) {
    var heads = table.querySelectorAll("thead th");
    Array.prototype.forEach.call(heads, function (th, col) {
      th.tabIndex = 0;
      th.setAttribute("role", "columnheader button");
      function sort() {
        var dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
        Array.prototype.forEach.call(heads, function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", dir);
        var body = table.tBodies[0], rows = Array.prototype.slice.call(body.rows), sign = dir === "ascending" ? 1 : -1;
        rows.sort(function (a, b) {
          var ca = a.cells[col], cb = b.cells[col];
          var va = ca.getAttribute("data-v"), vb = cb.getAttribute("data-v");
          if (va !== null && vb !== null) {
            if (va === "" && vb === "") return 0;
            if (va === "") return 1;
            if (vb === "") return -1;
            return sign * (parseFloat(va) - parseFloat(vb));
          }
          return sign * ca.textContent.localeCompare(cb.textContent);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      }
      th.addEventListener("click", sort);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } });
    });
  });
})();
