/* Landosaur /tax-sales/ — Interactive 50-State U.S. Tax-Deed, Tax-Lien & Redemption Atlas. */
(function () {
  "use strict";
  var root = document.getElementById("tax-sales-app");
  if (!root) return;
  var base = document.body.getAttribute("data-base") || "";
  var dataEl = document.getElementById("tax-sales-data");
  if (!dataEl) return;
  var STATES = [];
  try { STATES = JSON.parse(dataEl.textContent || "[]"); } catch (e) { return; }

  var GRID = {
    AK:[0,0], ME:[10,0],
    VT:[9,1], NH:[10,1],
    WA:[0,2], ID:[1,2], MT:[2,2], ND:[3,2], MN:[4,2], WI:[5,2], MI:[7,2], NY:[8,2], MA:[9,2], RI:[10,2],
    OR:[0,3], NV:[1,3], WY:[2,3], SD:[3,3], IA:[4,3], IL:[5,3], IN:[6,3], OH:[7,3], PA:[8,3], NJ:[9,3], CT:[10,3],
    CA:[0,4], UT:[1,4], CO:[2,4], NE:[3,4], MO:[4,4], KY:[5,4], WV:[6,4], VA:[7,4], MD:[8,4], DE:[9,4],
    AZ:[1,5], NM:[2,5], KS:[3,5], AR:[4,5], TN:[5,5], NC:[6,5], SC:[7,5],
    OK:[3,6], LA:[4,6], MS:[5,6], AL:[6,6], GA:[7,6],
    HI:[0,7], TX:[3,7], FL:[8,7]
  };
  var MODE_COLORS = {
    deed: { bg: "#15803d", fg: "#ffffff", label: "Tax Deed" },
    lien: { bg: "#1d4ed8", fg: "#ffffff", label: "Tax Lien" },
    redeemable_deed: { bg: "#b45309", fg: "#ffffff", label: "Redeemable / Hybrid" }
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  var activeMode = "all";
  var searchQ = "";
  var gridEl = document.getElementById("tax-cartogram");
  var tipEl = document.getElementById("tax-tip");
  var tbody = document.getElementById("tax-tbody");
  var countEl = document.getElementById("tax-count");
  var qInput = document.getElementById("tax-search");
  var modeBtns = Array.prototype.slice.call(document.querySelectorAll("[data-tax-mode]"));

  function renderCartogram() {
    if (!gridEl) return;
    var byCode = {};
    STATES.forEach(function (s) { byCode[s.code] = s; });
    var html = [];
    for (var r = 0; r <= 7; r++) {
      for (var c = 0; c <= 10; c++) {
        var found = null;
        for (var code in GRID) {
          if (GRID[code][0] === c && GRID[code][1] === r) { found = byCode[code]; break; }
        }
        if (!found) {
          html.push("<span class='us-tile-empty' aria-hidden='true'></span>");
          continue;
        }
        var pal = MODE_COLORS[found.mode] || MODE_COLORS.deed;
        var dimmed = activeMode !== "all" && found.mode !== activeMode;
        html.push(
          "<a class='us-tile' data-ts-code='" + found.code + "' href='#state-" + found.code + "' style='background:" + pal.bg + ";color:" + pal.fg + ";opacity:" + (dimmed ? "0.24" : "1") + "' title='" + esc(found.name + ": " + found.mode_label + " · Redemption: " + found.redemption) + "'>" +
          "<strong>" + found.code + "</strong><span>" + (found.live_count > 0 ? found.live_count.toLocaleString("en-US") : pal.label.split(" ")[1] || found.mode) + "</span></a>"
        );
      }
    }
    gridEl.innerHTML = html.join("");
    Array.prototype.forEach.call(gridEl.querySelectorAll("[data-ts-code]"), function (tile) {
      tile.addEventListener("mouseenter", function () {
        var s = byCode[tile.getAttribute("data-ts-code")];
        if (s && tipEl) {
          tipEl.innerHTML =
            "<strong>" + esc(s.name) + " (" + s.code + ")</strong> · <strong>" + esc(s.mode_label) + "</strong> · Redemption: <strong>" + esc(s.redemption) + "</strong> · Rate/Penalty: <strong>" + esc(s.interest) + "</strong> · Live Landosaur parcels: <strong>" + s.live_count.toLocaleString("en-US") + "</strong>";
        }
      });
    });
  }

  function renderTable() {
    if (!tbody) return;
    var rows = STATES.filter(function (s) {
      if (activeMode !== "all" && s.mode !== activeMode) return false;
      if (searchQ && (s.name + " " + s.code + " " + s.mode_label + " " + s.redemption + " " + s.notes).toLowerCase().indexOf(searchQ) < 0) return false;
      return true;
    });
    if (countEl) countEl.textContent = "Showing " + rows.length + " of 50 U.S. states";
    tbody.innerHTML = rows.map(function (s) {
      var badgeCls = s.mode === "deed" ? "ok" : (s.mode === "redeemable_deed" ? "auction" : "");
      var liveLink = s.state_path
        ? "<a href='" + esc(base + s.state_path) + "'><strong>" + s.live_count.toLocaleString("en-US") + " active →</strong></a>"
        : "<a href='" + esc(base + "/land-prices/" + s.slug + "/") + "'>Benchmarks →</a>";
      var agentHref = base + "/services/?service=auction_proxy&state=" + encodeURIComponent(s.code);
      return (
        "<tr id='state-" + s.code + "'>" +
        "<th scope='row'><strong>" + esc(s.name) + "</strong> <span class='sub'>" + s.code + "</span></th>" +
        "<td data-label='Sale Type'><span class='badge " + badgeCls + "'>" + esc(s.mode_label) + "</span></td>" +
        "<td data-label='Redemption'>" + esc(s.redemption) + "</td>" +
        "<td data-label='Rate / Penalty'>" + esc(s.interest) + "</td>" +
        "<td data-label='Live Inventory'>" + liveLink + "</td>" +
        "<td data-label='Rules Summary' class='small'>" + esc(s.notes) + "</td>" +
        "<td data-label='Land Agent'><a class='chip-btn chip-link' href='" + esc(agentHref) + "'>Bid Concierge ($20)</a></td>" +
        "</tr>"
      );
    }).join("");
  }

  modeBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      activeMode = btn.getAttribute("data-tax-mode") || "all";
      modeBtns.forEach(function (b) { b.classList.toggle("active", b === btn); });
      renderCartogram();
      renderTable();
    });
  });

  if (qInput) {
    qInput.addEventListener("input", function () {
      searchQ = qInput.value.trim().toLowerCase();
      renderTable();
    });
  }

  renderCartogram();
  renderTable();
})();
