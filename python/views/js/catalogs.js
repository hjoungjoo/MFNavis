/* MFNavis Web Catalogs — home search, catalog table, object detail */
/* global fetch */

function pfcatEsc(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

/* ── home ─────────────────────────────────────────────────────── */

function pfcatInitHome() {
  const input = document.getElementById("pfcat-global-search");
  const box = document.getElementById("pfcat-search-results");
  if (!input || !box) return;
  let timer = null;

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    timer = setTimeout(() => {
      fetch("/catalogs/api/search?q=" + encodeURIComponent(q))
        .then((r) => r.json())
        .then((data) => {
          if (!data.results.length) {
            box.innerHTML = "<a>" + pfcatEsc(pfT("No results")) + "</a>";
          } else {
            box.innerHTML = data.results
              .map(
                (r) =>
                  `<a href="/catalogs/object/${r.object_id}">` +
                  `<b>${pfcatEsc(pfT(r.display))}</b>` +
                  `<span class="hit-name">${pfcatEsc(r.matched_name)} · ` +
                  `${pfcatEsc(pfT(r.type_label))} · ${pfcatEsc(r.const)}</span></a>`
              )
              .join("");
          }
          box.hidden = false;
        })
        .catch(() => {});
    }, 250);
  });
  document.addEventListener("click", (ev) => {
    if (!box.contains(ev.target) && ev.target !== input) box.hidden = true;
  });
}

function pfcatNearbyNote(data) {
  let note = `${pfT("RA")} ${data.center.ra.toFixed(3)}° / ${pfT("Dec")} ${data.center.dec.toFixed(3)}° · ` +
    (data.ranking === "visibility_distance" ? pfT("visibility, then distance") : pfT("nearest first"));
  if (data.sky) {
    const sky = data.sky;
    if (sky.configured_bortle !== null) note += ` · ${pfT("Configured Bortle")} ${sky.configured_bortle}`;
    if (sky.measured_bortle !== null) note += ` · ${pfT("Measured Bortle")} ≈${sky.measured_bortle} (SQM ${sky.measured_sqm.toFixed(2)})`;
    if (sky.enabled) {
      note += ` · ${pfT("Applied Bortle")} ≈${sky.bortle} · ${sky.aperture_mm} mm / ${sky.magnification.toFixed(0)}×`;
    } else {
      note += sky.sqm !== null ? " · Set telescope and eyepiece for visibility ranking"
        : sky.measurement_state === "stale" ? " · SQM reading expired; using distance"
          : " · No sky measurement or configured Bortle; using distance";
    }
  }
  const sourceLabels = {
    solve: pfT("Plate solve"),
    pifinder_imu_estimate: pfT("Solve + IMU"),
    mount: pfT("Mount"),
    mount_imu_delta: pfT("Mount + IMU"),
    imu_fallback: data.center.unaligned
      ? pfT("IMU estimate (heading not aligned)") : pfT("IMU estimate"),
  };
  if (sourceLabels[data.center.source]) {
    note += " · " + sourceLabels[data.center.source];
  }
  return note;
}

/* ── catalog table ────────────────────────────────────────────── */

function pfcatInitCatalog() {
  const root = document.querySelector(".pfcat[data-catalog]");
  if (!root) return;
  const catalog = root.dataset.catalog;
  const state = { page: 1 };
  const el = (id) => document.getElementById(id);
  let timer = null;
  let requestSerial = 0;
  const nearbyOn = () => el("pfcat-nearby").getAttribute("aria-pressed") === "true";

  function setNearbyColumns(show) {
    root.querySelectorAll("[data-nearby-column]").forEach((column) => { column.hidden = !show; });
  }

  function params() {
    const p = new URLSearchParams({ catalog: catalog, page: state.page });
    const q = el("pfcat-q").value.trim();
    if (q) p.set("q", q);
    if (el("pfcat-type").value) p.set("types", el("pfcat-type").value);
    if (el("pfcat-const").value) p.set("const", el("pfcat-const").value);
    if (el("pfcat-mag").value) p.set("mag_max", el("pfcat-mag").value);
    if (el("pfcat-observed").value) p.set("observed", el("pfcat-observed").value);
    if (el("pfcat-upnow").getAttribute("aria-pressed") === "true") p.set("up_now", "1");
    p.set("sort", nearbyOn() ? "nearby" : el("pfcat-sort").value);
    return p;
  }

  function render(data) {
    const rows = el("pfcat-rows");
    const nearby = data.sort === "nearby";
    setNearbyColumns(nearby);
    if (!data.objects.length) {
      rows.innerHTML = `<tr><td colspan="${nearby ? 9 : 7}" class="pfcat-muted">${pfcatEsc(pfT("No objects match"))}</td></tr>`;
    } else {
      rows.innerHTML = data.objects
        .map((o) => {
          let alt = "—";
          if (o.alt !== null && o.alt !== undefined) {
            const cls = o.alt > 0 ? "pfcat-alt-up" : "pfcat-alt-down";
            const arrow = o.alt > 0 ? (o.rising ? " ↑" : " ↓") : "";
            alt = `<span class="${cls}">${o.alt > 0 ? "+" : ""}${o.alt}°${arrow}</span>`;
          }
          return (
            `<tr data-href="${o.href || "/catalogs/object/" + o.object_id}">` +
            `<td><span class="pfcat-objname">${pfcatEsc(pfT(o.display))}</span>` +
            (o.common_name ? `<span class="pfcat-objalias">${pfcatEsc(o.common_name)}</span>` : "") +
            `</td>` +
            `<td><span class="pfcat-typechip">${pfcatEsc(pfT(o.type_label))}</span></td>` +
            `<td>${pfcatEsc(o.const)}</td>` +
            `<td class="num">${pfcatEsc(o.mag)}</td>` +
            `<td class="num">${pfcatEsc(o.size)}</td>` +
            `<td class="num">${alt}</td>` +
            `<td>${o.observed ? "✓" : ""}</td>` +
            (nearby ? `<td>${pfcatEsc(pfT(o.visibility.label))}</td>` +
              `<td class="num">${o.distance == null ? "—" : o.distance.toFixed(2) + "°"}</td>` : "") +
            `</tr>`
          );
        })
        .join("");
      rows.querySelectorAll("tr[data-href]").forEach((tr) => {
        // pfNavigate keeps this a same-document navigation so fullscreen
        // survives; it falls back to a normal load when the SPA is off.
        tr.addEventListener("click", () => {
          const href = tr.dataset.href;
          if (window.pfNavigate) {
            window.pfNavigate(href);
          } else {
            window.location = href;
          }
        });
      });
    }
    el("pfcat-shown").textContent = `${data.total} ${pfT("shown")}`;
    const notes = [];
    if (nearby) notes.push(pfcatNearbyNote(data));
    if (!data.alt_available) notes.push(pfT("Altitude unavailable (waiting for GPS lock)"));
    el("pfcat-foot-note").textContent = notes.join(" · ");

    const pages = el("pfcat-pages");
    pages.innerHTML = "";
    if (data.pages > 1) {
      const mk = (n, label) => {
        const b = document.createElement("button");
        b.textContent = label || n;
        if (n === data.page) b.setAttribute("aria-current", "true");
        b.addEventListener("click", () => {
          state.page = n;
          load();
        });
        return b;
      };
      const win = 7;
      let start = Math.max(1, data.page - 3);
      const end = Math.min(data.pages, start + win - 1);
      start = Math.max(1, end - win + 1);
      if (start > 1) pages.appendChild(mk(1, "1…"));
      for (let n = start; n <= end; n++) pages.appendChild(mk(n));
      if (end < data.pages) pages.appendChild(mk(data.pages, "…" + data.pages));
    }
  }

  async function load() {
    const serial = ++requestSerial;
    const columns = nearbyOn() ? 9 : 7;
    setNearbyColumns(nearbyOn());
    el("pfcat-rows").innerHTML = `<tr><td colspan="${columns}" class="pfcat-muted">${pfcatEsc(pfT("Loading…"))}</td></tr>`;
    el("pfcat-pages").innerHTML = "";
    el("pfcat-shown").textContent = "";
    el("pfcat-foot-note").textContent = "";
    root.setAttribute("aria-busy", "true");
    try {
      const response = await fetch("/catalogs/api/objects?" + params().toString(), { cache: "no-store" });
      const data = await response.json();
      if (serial !== requestSerial) return;
      if (!response.ok) throw new Error(data.error || pfT("Load failed"));
      render(data);
    } catch (error) {
      if (serial !== requestSerial) return;
      el("pfcat-rows").innerHTML = `<tr><td colspan="${columns}" class="pfcat-muted">${pfcatEsc(error.message || pfT("Load failed"))}</td></tr>`;
    } finally {
      if (serial === requestSerial) root.setAttribute("aria-busy", "false");
    }
  }

  ["pfcat-type", "pfcat-const", "pfcat-mag", "pfcat-observed", "pfcat-sort"].forEach((id) =>
    el(id).addEventListener("change", () => {
      state.page = 1;
      load();
    })
  );
  el("pfcat-q").addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.page = 1;
      load();
    }, 300);
  });
  el("pfcat-upnow").addEventListener("click", () => {
    const btn = el("pfcat-upnow");
    if (btn.disabled) return;
    btn.setAttribute(
      "aria-pressed",
      btn.getAttribute("aria-pressed") === "true" ? "false" : "true"
    );
    state.page = 1;
    load();
  });
  el("pfcat-nearby").addEventListener("click", () => {
    el("pfcat-nearby").setAttribute("aria-pressed", nearbyOn() ? "false" : "true");
    el("pfcat-sort").disabled = nearbyOn();
    // Nearby computes altitude for filtering even on large catalogs.
    el("pfcat-upnow").disabled = !nearbyOn() && root.dataset.altEnabled !== "1";
    if (el("pfcat-upnow").disabled) el("pfcat-upnow").setAttribute("aria-pressed", "false");
    state.page = 1;
    load();
  });

  load();
}

/* ── object detail ────────────────────────────────────────────── */

function pfcatDrawAltChart(canvas, data) {
  const ctx = canvas.getContext("2d");
  const style = getComputedStyle(document.body);
  const lineColor = style.getPropertyValue("--pf-link").trim() || "#d0d0d0";
  const gridColor = style.getPropertyValue("--pf-border").trim() || "#777";
  const textColor = style.getPropertyValue("--pf-text-muted").trim() || "#9e9e9e";
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const pad = { l: 36, r: 8, t: 10, b: 26 };
  const y0 = H - pad.b;
  const yFor = (alt) => y0 - ((alt + 10) / 100) * (y0 - pad.t);

  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = gridColor;
  ctx.fillStyle = textColor;
  ctx.font = "20px system-ui";
  ctx.textAlign = "right";
  [0, 30, 60, 90].forEach((a) => {
    ctx.beginPath();
    ctx.moveTo(pad.l, yFor(a));
    ctx.lineTo(W - pad.r, yFor(a));
    ctx.stroke();
    ctx.fillText(a + "°", pad.l - 6, yFor(a) + 6);
  });
  ctx.setLineDash([]);

  const n = data.samples.length;
  const xFor = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);

  // time labels every ~6h
  ctx.textAlign = "center";
  const stepLabel = Math.round(n / 4);
  for (let i = 0; i < n; i += stepLabel) {
    const t = new Date(data.samples[i].t);
    ctx.fillText(
      String(t.getHours()).padStart(2, "0") + "h",
      xFor(i),
      H - 6
    );
  }

  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 3;
  ctx.beginPath();
  data.samples.forEach((s, i) => {
    const y = yFor(Math.max(-10, s.alt));
    if (i === 0) ctx.moveTo(xFor(i), y);
    else ctx.lineTo(xFor(i), y);
  });
  ctx.stroke();

  // now marker
  const nowT = new Date(data.now).getTime();
  let nowIdx = 0;
  data.samples.forEach((s, i) => {
    if (Math.abs(new Date(s.t).getTime() - nowT) <
        Math.abs(new Date(data.samples[nowIdx].t).getTime() - nowT)) nowIdx = i;
  });
  ctx.setLineDash([2, 3]);
  ctx.strokeStyle = textColor;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(xFor(nowIdx), pad.t);
  ctx.lineTo(xFor(nowIdx), y0);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = lineColor;
  ctx.beginPath();
  ctx.arc(xFor(nowIdx), yFor(Math.max(-10, data.samples[nowIdx].alt)), 5, 0, 7);
  ctx.fill();
}

function pfcatInitObject() {
  const root = document.querySelector(".pfcat[data-object-id], .pfcat[data-planet]");
  if (!root) return;
  const planet = root.dataset.planet;
  const objectId = root.dataset.objectId;
  const altUrl = planet
    ? "/catalogs/api/altitude_planet/" + planet
    : "/catalogs/api/altitude/" + objectId;
  const pushUrl = planet
    ? "/catalogs/api/push_planet/" + planet
    : "/catalogs/api/push/" + objectId;

  fetch(altUrl)
    .then((r) => r.json())
    .then((data) => {
      const note = document.getElementById("pfcat-alt-note");
      if (!data.available) {
        note.textContent = pfT("Waiting for GPS lock");
        return;
      }
      pfcatDrawAltChart(document.getElementById("pfcat-altchart"), data);
      const t = new Date(data.transit_time);
      document.getElementById("pfcat-transit").textContent =
        String(t.getHours()).padStart(2, "0") + ":" +
        String(t.getMinutes()).padStart(2, "0") + " · max +" + data.transit_alt + "°";
      document.getElementById("pfcat-now-altaz").textContent =
        pfT("Alt ") + data.alt_now + "° · Az " + data.az_now + "°";
    })
    .catch(() => {});

  const pushBtn = document.getElementById("pfcat-push");
  const result = document.getElementById("pfcat-push-result");
  const observeBtn = document.getElementById("pfcat-observe");
  const observeResult = document.getElementById("pfcat-observe-result");
  const pageAlive = window.pfPageAlive || (() => true);
  observeBtn.addEventListener("click", async () => {
    if (observeBtn.disabled) return;
    observeBtn.disabled = true;
    observeResult.textContent = pfT("Saving observation…");
    try {
      const response = await fetch(planet
        ? "/catalogs/api/observe_planet/" + planet
        : "/catalogs/api/observe/" + objectId, {method: "POST"});
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || "Could not record observation.");
      if (!pageAlive()) return;
      if (window.pfNavigate) window.pfNavigate(data.url);
      else window.location.href = data.url;
    } catch (error) {
      if (!pageAlive()) return;
      observeResult.textContent = pfT(error.message in (window.pfMessages || {})
        ? error.message : "Could not record observation.");
      observeBtn.disabled = false;
    }
  });

  // GoTo progress panel: per-axis angles remaining + service phase.
  const gotoPanel = document.getElementById("pfcat-goto-status");
  const gotoState = document.getElementById("pfcat-goto-state");
  const gotoDelta = document.getElementById("pfcat-goto-delta");
  const gotoError = document.getElementById("pfcat-goto-error");
  let gotoTimer = null;

  function fmtDelta(value, plusDir, minusDir) {
    if (value === undefined || value === null) return null;
    const dir = value >= 0 ? plusDir : minusDir;
    return Math.abs(value).toFixed(2) + "°" + dir;
  }

  function renderGotoStatus(data) {
    if (!gotoPanel) return;
    gotoPanel.style.display = "";
    let state = pfT(data.last_action || data.state || "—");
    if (data.attempt && data.max_gotos) {
      state += " (" + data.attempt + "/" + data.max_gotos + ")";
    }
    if (data.mount_state === "slewing") {
      state += " · slewing";
    }
    gotoState.textContent = state;
    if (data.available && data.delta) {
      const parts = [];
      const az = fmtDelta(data.delta.az_deg, "→", "←");
      const alt = fmtDelta(data.delta.alt_deg, "↑", "↓");
      if (az !== null && alt !== null) parts.push(pfT("Az ") + az + " · Alt " + alt);
      const ra = fmtDelta(data.delta.ra_deg, pfT(" E"), pfT(" W"));
      const dec = fmtDelta(data.delta.dec_deg, pfT(" N"), pfT(" S"));
      if (ra !== null && dec !== null) parts.push(pfT("RA ") + ra + " · Dec " + dec);
      gotoDelta.textContent = parts.length ? parts.join("  |  ") : "—";
    } else {
      gotoDelta.textContent = "—";
    }
    if (data.error_arcmin !== undefined && data.error_arcmin !== null) {
      gotoError.textContent = Number(data.error_arcmin).toFixed(1) + "′";
    } else {
      gotoError.textContent = "—";
    }
  }

  function pollGotoStatus() {
    fetch("/catalogs/api/goto_status")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return stopGotoPolling();
        renderGotoStatus(data);
        if (!data.active) stopGotoPolling();
      })
      .catch(() => stopGotoPolling());
  }

  function startGotoPolling() {
    if (gotoTimer !== null || !gotoPanel) return;
    pollGotoStatus();
    gotoTimer = setInterval(pollGotoStatus, 2000);
  }

  function stopGotoPolling() {
    if (gotoTimer !== null) {
      clearInterval(gotoTimer);
      gotoTimer = null;
    }
  }

  // A GoTo may already be running when the page opens (or after a reload).
  fetch("/catalogs/api/goto_status")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data && data.active) startGotoPolling();
    })
    .catch(() => {});

  pushBtn.addEventListener("click", () => {
    pushBtn.disabled = true;
    result.textContent = "…";
    fetch(pushUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then((r) => r.json().then((data) => ({ ok: r.ok, status: r.status, data: data })))
      .then(({ ok, status, data }) => {
        pushBtn.disabled = false;
        if (ok && data.success) {
          let msg = pfT("Pushed ") + data.pushed;
          if (data.goto && data.goto.action !== "none") {
            msg += " · GoTo started";
            startGotoPolling();
          }
          if (data.track_freq && data.track_freq.action === "reset") {
            msg += " · tracking reset to sidereal";
          } else if (data.track_freq && data.track_freq.action === "set") {
            msg += " · tracking " + Number(data.track_freq.hz).toFixed(3) + " Hz";
          }
          result.textContent = msg;
        } else if (status === 401) {
          result.innerHTML = pfcatEsc(pfT('Login Required')) + ' — <a href="/login">' + pfcatEsc(pfT('Login')) + '</a>';
        } else {
          result.textContent = data.error || pfT("Push failed");
        }
      })
      .catch(() => {
        pushBtn.disabled = false;
        result.textContent = pfT("Push failed");
      });
  });

  const stopBtn = document.getElementById("pfcat-stop");
  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      stopBtn.disabled = true;
      result.textContent = "…";
      fetch("/catalogs/api/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })
        .then((r) => r.json().then((data) => ({ ok: r.ok, status: r.status, data: data })))
        .then(({ ok, status, data }) => {
          stopBtn.disabled = false;
          if (ok && data.success) {
            result.textContent = pfT("GoTo stopped");
            stopGotoPolling();
            if (gotoState) gotoState.textContent = pfT("stopped");
          } else if (status === 401) {
            result.innerHTML = pfcatEsc(pfT('Login Required')) + ' — <a href="/login">' + pfcatEsc(pfT('Login')) + '</a>';
          } else {
            result.textContent = data.error || pfT("Stop failed");
          }
        })
        .catch(() => {
          stopBtn.disabled = false;
          result.textContent = pfT("Stop failed");
        });
    });
  }
}
