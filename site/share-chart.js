(function () {
  "use strict";
  const sources = document.querySelectorAll("[data-embed-view]");
  if (!sources.length) return;
  const base = document.body.dataset.base || "";
  const type = new URLSearchParams(location.search).get("embed");
  const view = Array.from(sources).find((section) => section.dataset.embedView === type);
  if (view) {
    document.body.classList.add("chart-embed");
    document.getElementById("main").replaceChildren(view);
    const attribution = document.createElement("a");
    attribution.href = location.pathname + "#" + view.id;
    attribution.target = "_blank";
    attribution.rel = "noopener noreferrer";
    attribution.textContent = "Source: Landosaur";
    view.appendChild(attribution);
    const notice = document.createElement("p");
    notice.className = "small notice";
    notice.textContent = "It is not an offer to sell. Landosaur publishes land market data for comparison.";
    view.appendChild(notice);
    view.querySelectorAll("[data-share-chart]").forEach((button) => button.remove());
    return;
  }

  let dataRequest;
  function csvRows(atlas, section, chart) {
    if (chart === "momentum") {
      return [["State", "Farm real estate USD per acre", "Nominal appreciation percent", "Active parcels"]]
        .concat(atlas.states.map((state) => [state.name, state.fre, state.chg_all, state.active]));
    }
    if (chart === "regions") {
      return [["Region", "Farm real estate USD per acre", "5-year CAGR percent", "Active parcels", "Reporting states"]]
        .concat(atlas.regions.map((region) => [region.name, region.farm_real_estate, region.five_year_cagr_pct, region.active, region.reporting_states]));
    }
    const single = section.dataset.chartState;
    const selected = Array.from(section.querySelectorAll("select[id^='cmp-st-']"));
    const selectedStates = single ? [single] : Array.from(new Set(selected.map((input) => input.value).filter(Boolean)));
    const metric = section.querySelector("#cmp-metric")?.value;
    const metrics = metric ? [metric] : ["farm_real_estate", "cropland", "pasture"];
    return [["Year", "State", "USDA measure", "Nominal USD per acre", "Inflation-adjusted USD per acre"]].concat(
      selectedStates.flatMap((state) => metrics.flatMap((key) => (atlas.series[state]?.[key] || []).map((value, index) => {
        const year = atlas.years[index], cpi = atlas.inflation;
        const factor = cpi?.years[cpi.reference_year]?.mean / cpi?.years[year]?.mean;
        return [year, state, key, value, value != null && Number.isFinite(factor) ? Math.round(value * factor) : null];
      })))
    );
  }

  document.querySelectorAll("[data-share-chart]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = button.closest("[data-embed-view]");
      const chart = button.dataset.shareChart;
      const url = new URL(location.pathname, location.origin);
      url.searchParams.set("embed", chart);
      const dialog = document.createElement("dialog");
      dialog.className = "chart-share-dialog";
      dialog.innerHTML = '<form method="dialog"><h2>Embed or cite this chart</h2>' +
        '<label>Embed code<textarea rows="3" readonly></textarea></label><label>Attribution link<input type="url" readonly></label>' +
        '<div class="btn-row"><button type="button" class="button ghost" data-chart-csv>Download CSV</button>' +
        '<button type="submit" class="button">Done</button></div><p role="status" class="small"></p></form>';
      dialog.querySelector("textarea").value = `<iframe title="Landosaur land data chart" src="${url.href}" width="720" height="550" loading="lazy" style="max-width:100%;border:0"></iframe>`;
      dialog.querySelector("input").value = location.origin + location.pathname + "#" + section.id;
      dialog.querySelectorAll("textarea,input").forEach((field) => field.addEventListener("focus", () => field.select()));
      dialog.querySelector("[data-chart-csv]").addEventListener("click", async () => {
        const report = dialog.querySelector("[role=status]");
        try {
          dataRequest ||= fetch(base + "/data/atlas.json").then((response) => {
            if (!response.ok) throw Error("Atlas request failed");
            return response.json();
          });
          const rows = csvRows(await dataRequest, section, chart);
          const csv = rows.map((row) => row.map((item) => '"' + String(item ?? "").replaceAll('"', '""') + '"').join(",")).join("\r\n");
          const file = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
          const link = document.createElement("a");
          link.href = file;
          link.download = "landosaur-" + chart + ".csv";
          link.click();
          setTimeout(() => URL.revokeObjectURL(file), 350);
          report.textContent = "CSV downloaded.";
        } catch {
          dataRequest = null;
          report.textContent = "The Atlas CSV could not be downloaded.";
        }
      });
      dialog.addEventListener("close", () => { dialog.remove(); button.focus(); }, { once: true });
      document.body.appendChild(dialog);
      dialog.showModal();
    });
  });
})();
