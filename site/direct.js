/* Landosaur /direct/?id=<id> — Live Direct Seller/Agent Parcel Dossier with Real Auction Bidding & Buy-It-Now Checkout/Reservation. */
(function () {
  "use strict";
  var root = document.getElementById("direct-app");
  if (!root) return;
  var base = document.body.getAttribute("data-base") || "";
  var params = new URLSearchParams(location.search);
  var id = params.get("id");

  function money(v) {
    if (v == null || isNaN(v)) return "–";
    return "$" + (Math.abs(v - Math.round(v)) < 0.005
      ? Math.round(v).toLocaleString("en-US")
      : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  if (!id) {
    // Directory mode: show all live direct listings (or honest empty state with CTA to /list/)
    root.innerHTML = "<p class='small'>Loading live Direct by Owner &amp; Agent listings…</p>";
    fetch(base + "/api/listings/")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var list = (d && d.listings) || [];
        if (!list.length) {
          root.innerHTML =
            "<div class='callout'><h2>No Direct Owner / Agent Listings Yet</h2>" +
            "<p>Landosaur never seeds fake listings. Be the first owner, real estate agent, or AI agent to publish a Buy It Now or Auction parcel in any of the 50 states—automatically enriched with 9 live federal GIS layers.</p>" +
            "<p><a class='button' href='" + base + "/list/'>List Your Land Free (60 sec or AI Agent) →</a></p></div>";
          return;
        }
        var cards = list.map(function (item) {
          var isAuc = item.sale_mode === "auction";
          var badge = isAuc
            ? "<span class='badge auction'>Auction · " + (item.current_high_bid ? ("High bid " + money(item.current_high_bid)) : ("Start " + money(item.price))) + "</span>"
            : "<span class='badge ok'>Buy It Now · " + money(item.price) + "</span>";
          var ppa = (item.price && item.acres) ? (money(item.price / item.acres) + "/ac") : "";
          return "<article class='info-card'><div class='card-top'>" + badge + "<span class='card-metric'>" + esc(item.acres) + " ac" + (ppa ? " · " + ppa : "") + "</span></div>" +
            "<h3><a href='" + base + "/direct/?id=" + encodeURIComponent(item.id) + "'>" + esc(item.title) + "</a></h3>" +
            "<p>" + esc(item.county) + ", " + esc(item.state) + " · Listed by " + (item.seller_type === "agent" ? ("Agent (" + esc(item.brokerage || item.contact_name) + ")") : "Owner") + "</p>" +
            "<a class='card-link' href='" + base + "/direct/?id=" + encodeURIComponent(item.id) + "'>" + (isAuc ? "View &amp; Place Bid →" : "View &amp; Buy It Now →") + "</a></article>";
        }).join("");
        root.innerHTML = "<div class='card-grid'>" + cards + "</div>";
      })
      .catch(function () {
        root.innerHTML = "<p class='callout'>Direct marketplace listings could not be loaded right now.</p>";
      });
    return;
  }

  root.innerHTML = "<p class='small'>Loading live parcel dossier and real-time bid status…</p>";
  Promise.all([
    fetch(base + "/api/listings/?id=" + encodeURIComponent(id)).then(function (r) { return r.ok ? r.json() : null; }),
    fetch(base + "/api/offers/?listing=" + encodeURIComponent(id)).then(function (r) { return r.ok ? r.json() : null; }),
  ])
    .then(function (res) {
      var lWrap = res[0], offers = res[1];
      if (!lWrap || !lWrap.listing) {
        root.innerHTML = "<div class='callout'><h2>Listing not found</h2><p>This direct listing may have been withdrawn or sold. <a href='" + base + "/'>Browse the land map →</a></p></div>";
        return;
      }
      var item = lWrap.listing;
      var isAuc = item.sale_mode === "auction";
      document.title = item.title + " | Landosaur Direct";
      var ppa = (item.price && item.acres) ? money(item.price / item.acres) + "/ac" : "–";
      var highBid = offers && offers.current_high_bid != null ? offers.current_high_bid : null;
      var minNext = offers && offers.minimum_next_bid != null ? offers.minimum_next_bid : item.price;
      var bidCount = offers ? offers.bid_count : null;
      var active = item.status === "active";
      var auctionOpen = active && isAuc && (!item.deadline || Date.parse(item.deadline) > Date.now());
      var canBuyNow = active && (!isAuc || auctionOpen && item.buy_now_price);
      var agentParams = new URLSearchParams({ service: "direct_closing", mode: "direct", parcel: item.id, title: item.title,
        state: item.state, county: item.county, price: highBid || item.buy_now_price || item.price, acres: item.acres,
        lat: item.lat, lon: item.lon, apn: item.apn || "" });
      var agentLink = base + "/services/?" + agentParams + "#start-land-agent";

      var dealBadge = isAuc
        ? "<span class='badge auction'>" + (auctionOpen ? "Auction open" : "Auction closed") +
          (bidCount == null ? "" : " · " + bidCount + " " + (bidCount === 1 ? "bid" : "bids")) + "</span>"
        : "<span class='badge ok'>Buy It Now · Fixed Price</span>";
      var sellerLine = item.seller_type === "agent"
        ? (esc(item.contact_name) + (item.brokerage ? " · " + esc(item.brokerage) : "") + (item.agent_license ? " (Lic #" + esc(item.agent_license) + ")" : ""))
        : (esc(item.contact_name) + " (Direct Owner)");

      var bidTapeHtml = "";
      if (isAuc) {
        if (offers && offers.recent_bids && offers.recent_bids.length) {
          bidTapeHtml = "<div class='scroll' style='margin-top:12px'><table class='data'><thead><tr><th>Bidder</th><th class='n'>Bid</th><th>Time (UTC)</th></tr></thead><tbody>" +
            offers.recent_bids.map(function (b) {
              return "<tr><td>" + esc(b.bidder) + " <code>" + esc(b.code) + "</code></td><td class='n'>" + money(b.amount) + "</td><td>" + esc((b.created_at || "").slice(0, 16).replace("T", " ")) + "</td></tr>";
            }).join("") + "</tbody></table></div>";
        } else if (offers) {
          bidTapeHtml = "<p class='small' style='margin-top:10px'>0 bids placed yet — opening bid is <strong>" + money(item.price) + "</strong>.</p>";
        }
      }

      var actionHtml =
        "<div class='dossier-card' id='deal-action-box'>" +
        "<div class='eyebrow'>" + (isAuc ? "Live Auction Bidding" : "Direct Buy It Now / Checkout") + "</div>" +
        "<h2 style='margin-bottom:8px'>" + (isAuc ? (highBid != null ? ("Current High Bid: " + money(highBid)) : ("Starting Bid: " + money(item.price))) : ("Buy It Now: " + money(item.price))) + "</h2>" +
        (isAuc && item.deadline ? "<p class='small'>Auction closes: <strong>" + esc(item.deadline.slice(0, 16).replace("T", " ")) + " UTC</strong>" + (item.buy_now_price ? (" · Optional Buy It Now: <strong>" + money(item.buy_now_price) + "</strong>") : "") + "</p>" : "") +
        (active ? "<p class='small'>Your request goes to the listing desk. Confirm the price and wiring instructions with the seller and closing professional before payment.</p>" : "") +
        (canBuyNow ? "<p class='small'>" + (item.checkout_url
          ? "The seller provided checkout instructions for " + esc(new URL(item.checkout_url).hostname) + "."
          : "The listing has no online escrow link. Confirm closing details with the seller.") + "</p>" : "") +
        (active ? "<form id='offer-form' class='worksheet' style='margin-top:10px'>" +
        "<label><span>Action</span><select name='action'>" +
        (auctionOpen ? "<option value='bid'>Place Auction Bid (min " + money(minNext) + ")</option>" : "") +
        (canBuyNow ? "<option value='buy_now'>Buy It Now — Reserve at " + money(item.buy_now_price || item.price) + "</option>" : "") +
        "<option value='offer'>Submit Written Offer</option>" +
        "</select></label>" +
        "<label id='offer-amt-wrap'><span>Amount ($)</span><input name='amount' type='number' min='1' step='any' value='" + (isAuc ? minNext : item.price) + "' required></label>" +
        "<label><span>Your full name</span><input name='buyer_name' type='text' required placeholder='Jane Doe'></label>" +
        "<label><span>Your email</span><input name='buyer_email' type='email' required placeholder='jane@example.com'></label>" +
        "<label><span>Phone (optional)</span><input name='buyer_phone' type='tel' placeholder='(555) 123-4567'></label>" +
        "<label><span>Funding</span><select name='financing'><option value='cash'>All cash</option><option value='land_loan'>Land loan</option><option value='seller_financing'>Seller financing</option></select></label>" +
        "<label style='grid-column:1/-1'><span>Notes / closing timeline</span><input name='notes' type='text' placeholder='e.g. 14-day title close, proof of funds ready'></label>" +
        "<input name='website_hp' type='text' tabindex='-1' autocomplete='off' style='display:none'>" +
        "<div style='grid-column:1/-1'><button type='submit' id='offer-submit' class='button'>" + (isAuc ? "Place Live Bid →" : "Reserve / Buy It Now →") + "</button></div>" +
        "</form>" : "<p>This listing is " + esc(item.status.replace(/_/g, " ")) + ".</p>") +
        "<div id='offer-receipt' class='callout' hidden style='margin-top:12px'></div>" +
        bidTapeHtml +
        (active || item.status === "under_contract" ?
          "<p class='no-print'><a class='button ghost sm' href='" + esc(agentLink) +
          "'>Request Land Agent closing coordination · $20 →</a></p>" : "") +
        "</div>";

      var anaQ = "?title=" + encodeURIComponent(item.title) + "&price=" + encodeURIComponent(item.price) + "&acres=" + encodeURIComponent(item.acres);

      root.innerHTML =
        "<div class='eyebrow'>Landosaur Direct · Listed by " + (item.seller_type === "agent" ? "Real Estate Agent" : "Owner") + "</div>" +
        "<h1>" + esc(item.title) + "</h1>" +
        "<div class='dossier-metrics'>" +
        "<div class='kpi-card'><span>" + (isAuc ? (highBid ? "Current High Bid" : "Starting Bid") : "Buy It Now") + "</span><strong>" + money(highBid || item.price) + "</strong><small>" + (isAuc ? (bidCount == null ? "Bid status unavailable" : bidCount + " bids recorded") : "Fixed direct price") + "</small></div>" +
        "<div class='kpi-card'><span>Parcel Size</span><strong>" + esc(item.acres) + " acres</strong><small>Seller-stated acreage</small></div>" +
        "<div class='kpi-card'><span>Implied $/Acre</span><strong>" + ppa + "</strong><small>" + esc(item.county) + ", " + esc(item.state) + "</small></div>" +
        "<div class='kpi-card'><span>Deal Status</span><strong style='font-size:19px'>" + esc(item.status) + "</strong><small>" + (item.financing_offered ? "Seller financing available" : "Title / escrow close") + "</small></div>" +
        "</div>" +
        "<div class='dossier'>" +
        "<div class='dossier-card'><dl class='kv'>" +
        "<dt>Deal Mode</dt><dd>" + dealBadge + "</dd>" +
        "<dt>Location</dt><dd>" + esc([item.address, item.locality, item.county, item.state].filter(Boolean).join(", ")) + "</dd>" +
        (item.apn ? "<dt>Parcel / APN</dt><dd><code>" + esc(item.apn) + "</code></dd>" : "") +
        (item.zoning ? "<dt>Zoning</dt><dd>" + esc(item.zoning) + "</dd>" : "") +
        (item.road_access ? "<dt>Road Access</dt><dd>" + esc(item.road_access) + "</dd>" : "") +
        (item.utilities ? "<dt>Utilities</dt><dd>" + esc(item.utilities) + "</dd>" : "") +
        "<dt>Listed By</dt><dd>" + sellerLine + "</dd>" +
        (item.notes ? "<dt>Seller Notes</dt><dd>" + esc(item.notes) + "</dd>" : "") +
        (item.escrow_notes ? "<dt>Closing / Escrow</dt><dd>" + esc(item.escrow_notes) + "</dd>" : "") +
        "</dl><div class='btn-row'>" +
        "<a class='button ghost' href='" + base + "/analyze/" + anaQ + "'>Open in Deal Analyzer</a>" +
        "<button type='button' id='direct-kml' class='button ghost sm'>Download KML</button>" +
        "<button type='button' id='direct-gpx' class='button ghost sm'>Download GPX</button>" +
        "<button type='button' id='direct-print' class='button ghost sm'>Print Field PDF</button>" +
        "</div><p class='small'>Always close through a licensed title company or real estate closing attorney and verify legal access, title, and survey before wiring funds.</p></div>" +
        "<div><div id='direct-map' class='map small'></div>" +
        "<p class='small' style='margin-top:8px'>Coordinates: " + item.lat + ", " + item.lon + " (GIS reference only).</p></div>" +
        "</div>" +
        "<section style='margin-top:24px'>" + actionHtml + "</section>" +
        "<section style='margin-top:18px'><details class='faq-item' id='seller-console'><summary>Seller / Agent Management Console (Update Price, Checkout URL, or Mark Sold)</summary><div class='faq-body'>" +
        "<p class='small'>Published this listing? Enter your <strong>Seller Edit Token</strong> to update the price, attach a Stripe/Escrow checkout link, or mark the parcel Under Contract, Sold, or Withdrawn live.</p>" +
        "<form id='manage-form' class='worksheet' style='margin-top:10px'>" +
        "<label style='grid-column:1/-1'><span>Seller Edit Token</span><input name='edit_token' type='password' required placeholder='Paste token returned when listing was published'></label>" +
        "<label><span>Listing Status</span><select name='status'>" +
        "<option value='active'" + (item.status === "active" ? " selected" : "") + ">Active</option>" +
        "<option value='under_contract'" + (item.status === "under_contract" ? " selected" : "") + ">Under Contract / Pending</option>" +
        "<option value='sold'" + (item.status === "sold" ? " selected" : "") + ">Sold</option>" +
        "<option value='withdrawn'" + (item.status === "withdrawn" ? " selected" : "") + ">Withdrawn</option>" +
        "</select></label>" +
        "<label><span>Price / Starting Bid ($)</span><input name='price' type='number' min='1' step='any' value='" + esc(item.price) + "'></label>" +
        "<label style='grid-column:1/-1'><span>Stripe / Escrow Checkout URL (optional HTTPS)</span><input name='checkout_url' type='url' value='" + esc(item.checkout_url || "") + "' placeholder='https://buy.stripe.com/... or https://www.escrow.com/...'></label>" +
        "<label style='grid-column:1/-1'><span>Seller Notes</span><input name='notes' type='text' value='" + esc(item.notes || "") + "'></label>" +
        "<div style='grid-column:1/-1'><button type='submit' id='manage-btn' class='button ghost'>Save Listing Changes →</button></div>" +
        "</form><div id='manage-msg' class='callout' hidden style='margin-top:10px'></div></div></details></section>" +
        "<section class='xray-section' style='margin-top:24px'>" +
        "<div class='xray-header'><div><div class='eyebrow'>Live Federal Screening</div><h2>Live Parcel X-Ray, Terrain Profile &amp; Land Potential</h2></div>" +
        "<a class='button ghost sm no-print' href='" + base + "/xray/#lat=" + item.lat + "&amp;lon=" + item.lon + "'>Open full-screen X-Ray →</a></div>" +
        "<div id='direct-xray-body'></div></section>";

      // Init map
      if (window.L) {
        var aerial = L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}", { maxNativeZoom: 16, maxZoom: 20, attribution: "USGS Imagery" });
        var streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxNativeZoom: 19, maxZoom: 20, attribution: "&copy; OpenStreetMap" });
        var fema = L.tileLayer.wms("https://hazards.fema.gov/arcgis/services/public/NFHLWMS/MapServer/WMSServer", { layers: "28", format: "image/png", transparent: true, opacity: 0.48, maxZoom: 20 });
        var m = L.map("direct-map", { scrollWheelZoom: true, doubleClickZoom: true, touchZoom: true, maxZoom: 20, layers: [aerial] }).setView([item.lat, item.lon], 16);
        L.control.layers({ "USGS Aerial": aerial, "Streets": streets }, { "FEMA Flood Zones": fema }).addTo(m);
        L.circleMarker([item.lat, item.lon], { radius: 8, color: "#fff", weight: 2.5, fillColor: "#c8f189", fillOpacity: 1 }).addTo(m);
      }

      // Wire KML/GPX/Print & Live X-Ray
      var kBtn = document.getElementById("direct-kml");
      var gBtn = document.getElementById("direct-gpx");
      var pBtn = document.getElementById("direct-print");
      if (kBtn && window.LandosaurXray) kBtn.addEventListener("click", function () { window.LandosaurXray.exportKml({ slug: item.id, lat: item.lat, lon: item.lon, title: item.title }); });
      if (gBtn && window.LandosaurXray) gBtn.addEventListener("click", function () { window.LandosaurXray.exportGpx({ slug: item.id, lat: item.lat, lon: item.lon, title: item.title }); });
      if (pBtn) pBtn.addEventListener("click", function () { window.print(); });
      if (window.LandosaurXray) {
        window.LandosaurXray.loadXray(document.getElementById("direct-xray-body"), item.lat, item.lon, {
          acres: item.acres, price: item.price, price_kind: item.price_kind, offering: item.sale_mode, zoning: item.zoning,
        });
      }

      // Wire Bid / Buy It Now / Offer submission
      var oForm = document.getElementById("offer-form");
      var oBtn = document.getElementById("offer-submit");
      var oRec = document.getElementById("offer-receipt");
      var amtWrap = document.getElementById("offer-amt-wrap");
      if (oForm) {
        var action = oForm.elements.action, amountInput = oForm.elements.amount;
        var lastRequest = "", requestKey = "";
        function syncAction() {
          var act = action.value;
          amtWrap.hidden = act === "buy_now";
          amountInput.disabled = act === "buy_now";
          amountInput.min = act === "bid" ? minNext : "0.01";
          if (act === "bid" && (!amountInput.value || Number(amountInput.value) < minNext)) amountInput.value = minNext;
          if (act === "bid") action.querySelector("[value=bid]").textContent = "Place auction bid (min " + money(minNext) + ")";
          oBtn.textContent = act === "bid" ? "Place live bid →" : act === "buy_now" ? "Request Buy It Now reservation →" : "Submit written offer →";
        }
        action.addEventListener("change", syncAction);
        syncAction();
        oForm.addEventListener("submit", function (ev) {
          ev.preventDefault();
          oBtn.disabled = true;
          oBtn.textContent = "Recording…";
          var payload = {
            listing_id: item.id,
            action: action.value,
            amount: parseFloat(oForm.amount.value),
            buyer_name: oForm.buyer_name.value.trim(),
            buyer_email: oForm.buyer_email.value.trim(),
            buyer_phone: oForm.buyer_phone.value.trim(),
            financing: oForm.financing.value,
            notes: oForm.notes.value.trim(),
            website_hp: oForm.website_hp.value,
          };
          var serialized = JSON.stringify(payload);
          if (serialized !== lastRequest) {
            requestKey = crypto.randomUUID();
            lastRequest = serialized;
          }
          payload.request_key = requestKey;
          fetch(base + "/api/offers/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (r2) {
              oRec.hidden = false;
              if (!r2.ok || !r2.d || !r2.d.ok) {
                if (r2.d?.minimum_next_bid) minNext = r2.d.minimum_next_bid;
                oRec.innerHTML = "<strong>Not recorded:</strong> " + esc((r2.d && r2.d.error) || "Please check your inputs.");
                return;
              }
              oRec.innerHTML = "<strong>Confirmed (" + esc(r2.d.confirmation_code) + "):</strong> " + esc(r2.d.message) +
                (r2.d.checkout_url ? (" <a class='button sm' style='margin-left:8px' href='" + esc(r2.d.checkout_url) + "' target='_blank' rel='noopener noreferrer'>Open seller-provided escrow link ↗</a>") : "");
              minNext = r2.d.summary?.minimum_next_bid ?? minNext;
              oForm.reset();
              lastRequest = "";
            })
            .catch(function () {
              oRec.hidden = false;
              oRec.textContent = "Network error submitting bid/offer. Please try again.";
            })
            .finally(function () {
              oBtn.disabled = false;
              syncAction();
            });
        });
      }

      // Wire Seller / Agent Management Console (PATCH /api/listings/)
      var mForm = document.getElementById("manage-form");
      var mBtn = document.getElementById("manage-btn");
      var mMsg = document.getElementById("manage-msg");
      if (mForm) {
        try {
          var savedTok = sessionStorage.getItem("landosaur_edit_" + item.id);
          if (savedTok) mForm.edit_token.value = savedTok;
        } catch (e) {}
        mForm.addEventListener("submit", function (ev) {
          ev.preventDefault();
          mBtn.disabled = true;
          mBtn.textContent = "Saving…";
          var patch = {
            edit_token: mForm.edit_token.value.trim(),
            status: mForm.status.value,
            price: parseFloat(mForm.price.value) || undefined,
            checkout_url: mForm.checkout_url.value.trim(),
            notes: mForm.notes.value.trim(),
          };
          fetch(base + "/api/listings/?id=" + encodeURIComponent(item.id), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(patch),
          })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (r2) {
              mMsg.hidden = false;
              if (!r2.ok || !r2.d || !r2.d.ok) {
                mMsg.innerHTML = "<strong>Update rejected:</strong> " + esc((r2.d && r2.d.error) || "Check your edit token.");
                return;
              }
              mMsg.innerHTML = "<strong>Listing updated!</strong> Reloading live status…";
              setTimeout(function () { location.reload(); }, 900);
            })
            .catch(function () {
              mMsg.hidden = false;
              mMsg.textContent = "Network error updating listing.";
            })
            .finally(function () {
              mBtn.disabled = false;
              mBtn.textContent = "Save Listing Changes →";
            });
        });
      }
    });
})();
