(function () {
  "use strict";

  document.querySelectorAll(".progress-bar[data-width]").forEach(function (el) {
    el.style.width = Math.max(0, Math.min(100, parseInt(el.dataset.width, 10) || 0)) + "%";
  });

  document.querySelectorAll("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      if (!window.confirm(el.dataset.confirm)) e.preventDefault();
    });
  });

  // Payment status polling (server reconciles with Daraja; the browser never decides success).
  var pay = document.getElementById("payment-status");
  if (pay && pay.dataset.final !== "1") {
    var tries = 0;
    var poll = function () {
      tries += 1;
      fetch(pay.dataset.url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) return;
          var badge = pay.querySelector("[data-role=badge]");
          badge.textContent = d.label;
          badge.className = "badge fs-6 pay-" + d.status;
          if (d.final) {
            pay.querySelector("[data-role=desc]").textContent = d.description || "";
            pay.querySelector(d.status === "success" ? "[data-role=success]" : "[data-role=retry]").classList.remove("d-none");
          }
          if (!d.final && tries < 60) setTimeout(poll, 5000);
        })
        .catch(function () { if (tries < 60) setTimeout(poll, 8000); });
    };
    setTimeout(poll, 4000);
  }

  // Candlestick chart.
  var el = document.getElementById("chart");
  if (!el || !window.LightweightCharts) return;
  var LC = window.LightweightCharts;
  var chart = LC.createChart(el, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: "#cbd5e1" },
    grid: { vertLines: { color: "#1f2a3d" }, horzLines: { color: "#1f2a3d" } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1f2a3d" },
    rightPriceScale: { borderColor: "#1f2a3d" },
    localization: {
      timeFormatter: function (t) {
        return new Date(t * 1000).toLocaleString("en-GB", { timeZone: "Africa/Nairobi", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
      }
    }
  });
  var series = chart.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444" });
  var lines = [];
  var zones = [];

  function load(tf) {
    var url = new URL(el.dataset.url, window.location.origin);
    url.searchParams.set("tf", tf);
    if (el.dataset.signal) url.searchParams.set("signal", el.dataset.signal);
    fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      series.setData(d.candles || []);
      lines.forEach(function (l) { series.removePriceLine(l); });
      zones.forEach(function (z) { chart.removeSeries(z); });
      lines = []; zones = [];
      (d.levels || []).forEach(function (lv) {
        lines.push(series.createPriceLine({ price: lv.price, color: lv.color, lineWidth: 1, lineStyle: lv.label.indexOf("CRT") === 0 ? 2 : 0, axisLabelVisible: true, title: lv.label }));
      });
      (d.zones || []).forEach(function (z) {
        [z.top, z.bottom].forEach(function (p) {
          lines.push(series.createPriceLine({ price: p, color: "rgba(229,153,247,.6)", lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: z.label }));
        });
      });
      series.setMarkers((d.markers || []).sort(function (a, b) { return a.time - b.time; }));
      if (!d.candles || !d.candles.length) {
        el.setAttribute("data-empty", "1");
      }
      chart.timeScale().fitContent();
    }).catch(function () {});
  }

  document.querySelectorAll("[data-tf]").forEach(function (btn) {
    if (btn === el) return;
    btn.addEventListener("click", function () {
      document.querySelectorAll("button[data-tf]").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      load(btn.dataset.tf);
    });
  });
  load(el.dataset.tf || "1h");
})();
