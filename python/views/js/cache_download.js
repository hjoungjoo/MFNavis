/* Tools: reconnect to the server-owned cache download after navigation. */
(function () {
  "use strict";
  const alive = window.pfPageAlive || (() => true);

  function init() {
    const root = document.getElementById("cache-download");
    if (!root) return;
    const labels = JSON.parse(root.dataset.labels);
    const el = (name) => document.getElementById("cache-" + name);
    let state = null;
    let busy = false;
    let requestSerial = 0;
    let timer = null;

    function duration(seconds) {
      const value = Math.max(0, Math.round(seconds || 0));
      return Math.floor(value / 3600) + ":" +
        String(Math.floor(value / 60) % 60).padStart(2, "0") + ":" +
        String(value % 60).padStart(2, "0");
    }

    function buttons() {
      const active = state && ["running", "stopping"].includes(state.status);
      el("start").disabled = busy || !state || active;
      el("stop").disabled = busy || !state || state.status !== "running";
      el("resume").disabled = busy || !state || active || !state.options ||
        !["stopped", "interrupted", "failed"].includes(state.status);
      ["images", "workers", "skip-runtime"].forEach((name) => {
        el(name).disabled = busy || active;
      });
    }

    function render(data) {
      if (!state && data.options) {
        el("images").value = data.options.images;
        el("workers").value = data.options.workers;
        el("skip-runtime").checked = data.options.skip_runtime;
      }
      state = data;
      const p = data.progress || {};
      const parts = [labels[data.status] || data.status];
      if (data.stage) parts.push(labels[data.stage] || data.stage);
      if (p.current) parts.push(p.current);
      if (p.total !== undefined) {
        const percent = p.total ? Math.floor(p.completed * 100 / p.total) : 100;
        parts.push(p.completed + " / " + p.total + " (" + percent + "%)");
        el("progress").max = p.total || 1;
        el("progress").value = p.total ? p.completed : 1;
      } else if (["running", "stopping"].includes(data.status)) {
        el("progress").removeAttribute("value");
      } else {
        el("progress").max = 1;
        el("progress").value = data.status === "completed" ? 1 : 0;
      }
      el("state").textContent = parts.join(" · ");
      el("counts").textContent = data.stage === "images" ?
        labels.cached + ": " + (p.cached || 0) + " · " +
        labels.fetched + ": " + (p.fetched || 0) + " · " +
        labels.unavailable + ": " + (p.unavailable || 0) + " · " +
        labels.errors + ": " + (p.failed || 0) : "";
      const timing = [];
      if (data.started_at) timing.push(labels.elapsed + ": " + duration(data.elapsed));
      if (data.eta !== null && data.eta !== undefined) timing.push(labels.eta + ": " + duration(data.eta));
      if (data.free_bytes !== null && data.free_bytes !== undefined) {
        timing.push(labels.free + ": " + (data.free_bytes / (1024 ** 3)).toFixed(1) + " GiB");
      }
      el("timing").textContent = timing.join(" · ");
      el("log").textContent = (data.logs || []).join("\n");
      el("error").textContent = data.error || "";
      buttons();
    }

    async function poll() {
      if (!alive()) return;
      const serial = ++requestSerial;
      try {
        const response = await fetch("/tools/api/cache-download", { cache: "no-store" });
        if (!response.ok) throw new Error(labels.connection_error);
        const data = await response.json();
        if (alive() && serial === requestSerial) render(data);
      } catch (error) {
        if (alive() && serial === requestSerial) el("error").textContent = labels.connection_error;
      } finally {
        if (alive() && serial === requestSerial) timer = setTimeout(poll, 2000);
      }
    }

    async function action(name) {
      busy = true;
      buttons();
      clearTimeout(timer);
      ++requestSerial;
      const payload = { action: name };
      if (name === "start") {
        payload.images = el("images").value;
        payload.workers = Number(el("workers").value);
        payload.skip_runtime = el("skip-runtime").checked;
      }
      try {
        const response = await fetch("/tools/api/cache-download", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || labels.connection_error);
        if (alive()) render(data);
      } catch (error) {
        if (alive()) el("error").textContent = error.message;
      } finally {
        busy = false;
        if (alive()) {
          buttons();
          clearTimeout(timer);
          timer = setTimeout(poll, 2000);
        }
      }
    }

    ["start", "stop", "resume"].forEach((name) => {
      el(name).addEventListener("click", () => action(name));
    });
    poll();
  }
  document.addEventListener("DOMContentLoaded", init);
})();
