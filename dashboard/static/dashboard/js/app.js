/* San Pedro Bay · moteur d'interface : palette des graphiques, animations d'apparition, compteurs, courbes, boussole,
   navigation mobile, transitions de page. Tout est optionnel : sans JavaScript, la page reste complète et lisible. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // ------------------------------------------------------------------ palette (les anciens noms désignent désormais les teintes du port)
  const C = {
    cyan: "#D8571A",     // orange conteneur : série principale
    blue: "#3E6A78",     // ardoise de mer
    violet: "#7A4B2E",   // brun chocolat
    teal: "#8A9A5B",     // sauge
    amber: "#C48A1C",    // ocre
    red: "#A6321E",      // brique
    green: "#4F7A3A",    // feuille
    sand: "#DFD0B6", sea: "#6B8C93",
    text: "#2B1B12", muted: "#6F5846",
    grid: "rgba(74,48,30,.11)", line: "rgba(74,48,30,.3)", paper: "#FFFCF7",
  };
  const reduit = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const etroit = () => window.innerWidth < 720;
  const nf0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  const FONT = "DM Sans, Segoe UI, system-ui, sans-serif";

  // ------------------------------------------------------------------ graphiques Plotly
  function layout(extra) {
    const m = etroit();
    const base = {
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { family: FONT, color: C.muted, size: m ? 11 : 12.5 },
      separators: ", ", margin: m ? { l: 46, r: 10, t: 14, b: 34 } : { l: 58, r: 20, t: 18, b: 44 }, hovermode: "x unified",
      colorway: [C.cyan, C.blue, C.amber, C.teal, C.violet, C.red, C.green],
      xaxis: { gridcolor: C.grid, linecolor: C.line, zeroline: false, tickfont: { size: m ? 10 : 11.5, color: C.muted }, ticks: "outside", tickcolor: C.line },
      yaxis: { gridcolor: C.grid, linecolor: "rgba(0,0,0,0)", zeroline: false, tickfont: { size: m ? 10 : 11.5, color: C.muted } },
      legend: { orientation: "h", y: m ? 1.2 : 1.13, x: 0, font: { size: m ? 11 : 12.5, color: C.text }, bgcolor: "rgba(0,0,0,0)" },
      hoverlabel: { bgcolor: C.paper, bordercolor: "rgba(74,48,30,.35)", font: { color: C.text, family: FONT, size: 13 } },
    };
    const out = Object.assign({}, base, extra || {});
    // légende ancrée par le bas, juste au-dessus du tracé : Plotly agrandit la marge haute selon le nombre de lignes (pas de recouvrement)
    out.legend = Object.assign({}, base.legend, (extra && extra.legend) || {}, { y: 1.02, yanchor: "bottom" });
    ["xaxis", "yaxis", "yaxis2"].forEach(function (k) {
      if (extra && extra[k]) out[k] = Object.assign({}, k === "xaxis" ? base.xaxis : base.yaxis, extra[k]);
    });
    if (m) { // sur téléphone : pas de titres d'axes, marges serrées
      ["xaxis", "yaxis", "yaxis2"].forEach(function (k) { if (out[k] && out[k].title) { out[k] = Object.assign({}, out[k]); delete out[k].title; } });
      if (extra && extra.margin) out.margin = Object.assign({}, base.margin, { r: Math.min(extra.margin.r || 10, 44), t: extra.margin.t != null ? extra.margin.t : base.margin.t });
    }
    return out;
  }
  function plot(id, traces, lay, cfg) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!window.Plotly) { el.innerHTML = '<p class="muted small" style="padding:20px">Bibliothèque de graphiques introuvable.</p>'; return; }
    el.classList.add("skeleton");
    const fin = function () { el.classList.remove("skeleton"); aVoir(el, function () { el.classList.add("ready"); }); };
    try {
      Promise.resolve(Plotly.react(el, traces, layout(lay), Object.assign({ displayModeBar: false, responsive: true }, cfg || {}))).then(fin, fin);
    } catch (e) { fin(); }
  }

  // ------------------------------------------------------------------ observation d'apparition
  const obs = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { e.target._cb(); obs.unobserve(e.target); } });
  }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }) : null;
  function aVoir(el, cb) { if (!obs || reduit) { cb(); return; } el._cb = cb; obs.observe(el); }

  function reveal() {
    document.querySelectorAll("[data-stagger]").forEach(function (p) {
      Array.prototype.forEach.call(p.children, function (c, i) { c.style.setProperty("--d", Math.min(i, 9) * 70 + "ms"); });
    });
    document.querySelectorAll(".reveal").forEach(function (el) {
      aVoir(el, function () { el.classList.add("in"); el.querySelectorAll("[data-count]").forEach(compter); });
    });
  }

  // ------------------------------------------------------------------ compteurs « 1 026 872 » → animation de 0 à la valeur
  function compter(el) {
    if (reduit || el._fait) return;
    el._fait = true;
    const src = el.textContent, re = /\d[\d  ]*(?:,\d+)?/g;
    const morceaux = [];
    let m, dernier = 0;
    while ((m = re.exec(src))) {
      const brut = m[0], dec = (brut.split(",")[1] || "").length, val = parseFloat(brut.replace(/[  \s]/g, "").replace(",", "."));
      if (isNaN(val)) continue;
      morceaux.push({ avant: src.slice(dernier, m.index), val: val, dec: dec, groupe: /[  ]/.test(brut) || val >= 10000 });
      dernier = m.index + brut.length;
    }
    if (!morceaux.length) return;
    const fin = src.slice(dernier), t0 = performance.now(), duree = 1150;
    const fmt = function (p, x) { return (p.dec ? x.toFixed(p.dec).replace(".", ",") : String(Math.round(x))).replace(/\B(?=(\d{3})+(?!\d))/g, p.groupe ? " " : ""); };
    (function pas(t) {
      const k = Math.min(1, (t - t0) / duree), e = 1 - Math.pow(1 - k, 3);
      el.textContent = morceaux.map(function (p) { return p.avant + fmt(p, p.val * e); }).join("") + fin;
      if (k < 1) requestAnimationFrame(pas); else el.textContent = src;
    })(t0);
  }

  // ------------------------------------------------------------------ mini-courbes qui se dessinent
  function spark(el, values, color) {
    const v = (values || []).filter(function (x) { return x !== null && !isNaN(x); });
    if (!el || v.length < 2) return;
    const w = 200, h = 46, min = Math.min.apply(null, v), max = Math.max.apply(null, v), span = (max - min) || 1;
    const pts = v.map(function (x, i) { return [(i / (v.length - 1)) * w, h - 6 - ((x - min) / span) * (h - 14)]; });
    const d = pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" ");
    const id = "g" + Math.random().toString(36).slice(2, 8), last = pts[pts.length - 1];
    el.innerHTML = '<svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" role="img" aria-label="Évolution récente"><defs><linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + color + '" stop-opacity=".32"/><stop offset="1" stop-color="' + color + '" stop-opacity="0"/></linearGradient></defs>' +
      '<path class="area" d="' + d + " L" + w + " " + h + " L0 " + h + ' Z" fill="url(#' + id + ')"/><path class="line" d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' +
      '<circle class="dot" cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) + '" r="3.6" fill="' + color + '" stroke="#fffcf7" stroke-width="1.6"/></svg>';
    const ln = el.querySelector(".line");
    try { ln.style.setProperty("--len", Math.ceil(ln.getTotalLength() * 1.02)); } catch (e) { ln.style.setProperty("--len", 600); }
  }
  function sparks() {
    document.querySelectorAll("[data-spark]").forEach(function (el) {
      const tile = el.closest(".tile"), col = (tile && getComputedStyle(tile).getPropertyValue("--c").trim()) || C.cyan;
      try { spark(el, JSON.parse(el.dataset.spark), col); } catch (e) { /* pas de mini-courbe */ }
    });
  }

  // ------------------------------------------------------------------ horloges, boussole, barre d'outils
  function clocks() {
    const u = document.getElementById("clock-utc"), l = document.getElementById("clock-la");
    if (!u) return;
    function tick() {
      const d = new Date();
      u.textContent = d.toISOString().slice(11, 19) + " UTC";
      l.textContent = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "America/Los_Angeles" }).format(d) + " Los Angeles";
    }
    tick(); setInterval(tick, 1000);
  }
  function boussole() {
    const n = document.getElementById("needle");
    if (!n) return;
    const deg = parseFloat(n.dataset.deg);
    if (isNaN(deg)) return;
    // la tête orange pointe vers la direction d'où VIENT le vent (comme une girouette)
    if (reduit) { n.style.transform = "rotate(" + deg + "deg)"; return; }
    setTimeout(function () { n.style.transform = "rotate(" + deg + "deg)"; }, 450);
  }
  function barre() {
    const t = document.querySelector(".toolbar");
    if (!t) return;
    const f = function () { t.classList.toggle("stuck", window.scrollY > 6); };
    f(); window.addEventListener("scroll", f, { passive: true });
  }

  // ------------------------------------------------------------------ navigation mobile (tiroir « Plus »), transitions de repli, tuiles tactiles
  function navigation() {
    const plus = document.getElementById("tab-more"), scrim = document.querySelector(".sheet-scrim");
    const ferme = function () { document.body.classList.remove("sheet-open"); if (plus) plus.setAttribute("aria-expanded", "false"); };
    if (plus) plus.addEventListener("click", function () { const o = document.body.classList.toggle("sheet-open"); plus.setAttribute("aria-expanded", o ? "true" : "false"); });
    if (scrim) scrim.addEventListener("click", ferme);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") ferme(); });
    if (!("startViewTransition" in document) && !reduit) { // navigateurs sans transitions inter-pages : fondu maison
      document.addEventListener("click", function (e) {
        const a = e.target.closest && e.target.closest("a[href]");
        if (!a || a.target === "_blank" || e.metaKey || e.ctrlKey || e.shiftKey || a.origin !== location.origin || a.pathname === location.pathname && a.hash) return;
        e.preventDefault(); document.body.classList.add("leaving"); setTimeout(function () { location.href = a.href; }, 170);
      });
      window.addEventListener("pageshow", function () { document.body.classList.remove("leaving"); });
    }
    if (window.matchMedia && matchMedia("(hover: none)").matches) { // sur écran tactile, un appui ouvre la décision éclairée par la tuile
      document.querySelectorAll(".tile").forEach(function (t) {
        t.addEventListener("click", function (e) { if (e.target.closest("a")) return; const o = t.classList.contains("open"); document.querySelectorAll(".tile.open").forEach(function (x) { x.classList.remove("open"); }); if (!o) t.classList.add("open"); });
      });
    }
  }

  function polices() {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;600&display=swap";
    document.head.appendChild(l);
  }

  // ------------------------------------------------------------------ actualisation, notifications, formats
  function csrf() { const m = document.querySelector('meta[name="csrf"]'); return m ? m.content : ""; }
  function toast(msg) {
    let t = document.getElementById("toast");
    if (!t) {
      t = document.createElement("div"); t.id = "toast"; t.setAttribute("role", "status"); t.setAttribute("aria-live", "polite");
      t.style.cssText = "position:fixed;right:20px;bottom:calc(22px + env(safe-area-inset-bottom,0px));z-index:120;max-width:min(380px,calc(100vw - 40px));padding:14px 18px;border-radius:16px;background:#2b1b12;color:#fbf7ef;font:500 14px/1.45 " + FONT + ";box-shadow:0 24px 40px -16px rgba(30,18,11,.7);border-left:5px solid #d8571a;transition:opacity .26s cubic-bezier(.22,1,.36,1),transform .26s cubic-bezier(.22,1,.36,1);opacity:0;transform:translateY(12px);pointer-events:none";
      document.body.appendChild(t);
    }
    t.textContent = msg; t.style.opacity = 1; t.style.transform = "none";
    clearTimeout(t._h); t._h = setTimeout(function () { t.style.opacity = 0; t.style.transform = "translateY(12px)"; }, 4000);
  }
  function refresh(force) {
    const btn = document.getElementById("btn-refresh");
    if (!btn) return;
    if (document.body.dataset.export) { toast("Instantané exporté : lancer l'application Django pour actualiser les données."); return; }
    btn.disabled = true; btn.querySelector("svg").classList.add("spin");
    fetch("/api/refresh/", { method: "POST", headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" }, body: force ? "force=1" : "" })
      .then(function (r) { return r.json(); })
      .then(function (j) { toast(j.message || "Actualisé."); setTimeout(function () { location.reload(); }, 900); })
      .catch(function () { toast("Actualisation impossible : le serveur ne répond pas."); btn.disabled = false; btn.querySelector("svg").classList.remove("spin"); });
  }
  function fmtLA(iso, opts) {
    return new Intl.DateTimeFormat("fr-FR", Object.assign({ timeZone: "America/Los_Angeles", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }, opts || {})).format(new Date(iso));
  }
  function moisFr(ym) { const p = ym.split("-"); return MOIS[parseInt(p[1], 10) - 1] + " " + p[0]; }

  window.SPB = { C: C, plot: plot, spark: spark, nf0: nf0, nf1: nf1, fmtLA: fmtLA, moisFr: moisFr, toast: toast, layout: layout, aVoir: aVoir };
  document.addEventListener("DOMContentLoaded", function () {
    polices(); sparks(); clocks(); boussole(); barre(); navigation(); reveal();
    const b = document.getElementById("btn-refresh");
    if (b) b.addEventListener("click", function (e) { refresh(e.shiftKey); });
    // si la fenêtre change de taille (rotation du téléphone), Plotly se redessine seul ; on retire seulement les titres d'axes déjà posés
    let w = window.innerWidth;
    window.addEventListener("resize", function () { if ((w < 720) !== (window.innerWidth < 720)) { w = window.innerWidth; location.reload(); } }, { passive: true });
  });
})();
