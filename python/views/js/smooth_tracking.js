(() => {
  const panel = document.getElementById('smooth_tracking_panel');
  if (!panel || panel.dataset.bound) return;
  panel.dataset.bound = 'true';
  const result = document.getElementById('smooth_tracking_result');
  let initialized = false, candidateUrl;
  async function poll() {
    if (!document.contains(panel)) {
      if (candidateUrl) URL.revokeObjectURL(candidateUrl);
      return;
    }
    try {
      const response = await fetch('/indi/smooth_tracking', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      document.getElementById('smooth_tracking_status').textContent = `${data.mode}: ${data.state} — ${data.reason || ''}`;
      if (!initialized) {
        document.getElementById('smooth_mode').value = data.configured_mode;
        initialized = true;
      }
      if (data.calibration_candidate) {
        if (candidateUrl) URL.revokeObjectURL(candidateUrl);
        candidateUrl = URL.createObjectURL(new Blob([JSON.stringify(data.calibration_candidate, null, 2)], {type: 'application/json'}));
        const link = document.getElementById('smooth_calibration_download');
        link.href = candidateUrl;
        link.download = 'tracking-calibration-candidate.json';
        link.hidden = false;
      }
    } catch (error) { document.getElementById('smooth_tracking_status').textContent = String(error); }
    setTimeout(poll, 1500);
  }
  panel.querySelectorAll('[data-smooth-action]').forEach(button => {
    button.addEventListener('click', async () => {
      const action = button.dataset.smoothAction, payload = {action};
      try {
        if (action === 'configure') {
          payload.mode = document.getElementById('smooth_mode').value;
          const file = document.getElementById('smooth_profile').files[0];
          if (file) {
            if (file.size > 65536) throw new Error(panel.dataset.size);
            payload.profile = JSON.parse(await file.text());
          }
        } else if (action !== 'stop') {
          const ra = document.getElementById('smooth_ra'), dec = document.getElementById('smooth_dec');
          if (!ra.value || !dec.value || !ra.checkValidity() || !dec.checkValidity()) throw new Error(panel.dataset.coordinates);
          Object.assign(payload, {ra: Number(ra.value), dec: Number(dec.value), frame: 'catalog'});
        }
        button.disabled = true;
        const response = await fetch('/indi/smooth_tracking', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
        result.textContent = data.queued ? panel.dataset.queued : panel.dataset.saved;
      } catch (error) { result.textContent = String(error); }
      finally { button.disabled = false; }
    });
  });
  poll();
})();
