(() => {
  const panel = document.getElementById('smooth_tracking_panel');
  if (!panel || panel.dataset.smoothBound) return;
  panel.dataset.smoothBound = 'true';
  const result = document.getElementById('smooth_tracking_result');
  let initialized = false, candidateUrl, opticsUrl;
  async function poll() {
    if (!document.contains(panel)) {
      if (candidateUrl) URL.revokeObjectURL(candidateUrl);
      if (opticsUrl) URL.revokeObjectURL(opticsUrl);
      return;
    }
    try {
      const response = await fetch('/indi/smooth_tracking', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      document.getElementById('smooth_tracking_status').textContent = `${data.mode}: ${data.state} — ${data.reason || ''}`;
      const measurement = data.measurement;
      const details = [];
      if (measurement) {
        const counts = measurement.roi_counts || {};
        details.push(measurement.reason, `${panel.dataset.stars}: ${measurement.stars}`);
        if (counts.saturated) details.push(`${panel.dataset.saturated}: ${counts.saturated}`);
        if (counts.low_signal) details.push(`${panel.dataset.lowSignal}: ${counts.low_signal}`);
        const budget = Number.isFinite(data.error_budget_arcsec) ? ` / ${data.error_budget_arcsec.toFixed(1)}″` : '';
        details.push(`${panel.dataset.bound}: ${measurement.bound_arcsec.toFixed(1)}″${budget}`);
        if (Number.isFinite(measurement.relative_bound_arcsec)) details.push(`${panel.dataset.motionNoise}: ${measurement.relative_bound_arcsec.toFixed(1)}″`);
        if (!measurement.timing.verified) details.push(panel.dataset.unverifiedTiming);
      }
      if (data.response_axes && data.response_axes.length < 2) details.push(`${panel.dataset.controlledAxes}: ${data.response_axes.map(axis => axis === 0 ? 'RA' : 'Dec').join('/')}`);
      const measurementStatus = document.getElementById('smooth_measurement_status');
      if (measurementStatus) measurementStatus.textContent = details.join(' · ');
      if (!initialized) {
        document.getElementById('smooth_mode').value = data.configured_mode;
        document.getElementById('smooth_target_integration').checked = data.target_integration_enabled;
        initialized = true;
      }
      const alignment = data.alignment;
      document.getElementById('smooth_alignment_status').textContent = alignment && alignment.state !== 'idle'
        ? `${alignment.state}: ${alignment.result || alignment.reason || ''}${alignment.remaining_s === undefined ? '' : ` (${Math.ceil(alignment.remaining_s)} s)`}` : '';
      const opticsLink = document.getElementById('smooth_local_optics_download');
      opticsLink.hidden = !data.local_optical_candidate;
      if (data.local_optical_candidate) {
        if (opticsUrl) URL.revokeObjectURL(opticsUrl);
        opticsUrl = URL.createObjectURL(new Blob([JSON.stringify(data.local_optical_candidate, null, 2)], {type: 'application/json'}));
        opticsLink.href = opticsUrl;
        opticsLink.download = 'tracking-local-optics-candidate.json';
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
          payload.target_integration_enabled = document.getElementById('smooth_target_integration').checked;
          const file = document.getElementById('smooth_profile').files[0];
          if (file) {
            if (file.size > 65536) throw new Error(panel.dataset.size);
            payload.profile = JSON.parse(await file.text());
          }
        } else if (action !== 'stop') {
          const ra = document.getElementById('smooth_ra'), dec = document.getElementById('smooth_dec');
          if (!ra.value || !dec.value || !ra.checkValidity() || !dec.checkValidity()) throw new Error(panel.dataset.coordinates);
          Object.assign(payload, {ra: Number(ra.value), dec: Number(dec.value), frame: 'catalog'});
          const targetType = document.getElementById('smooth_body').value;
          payload.identify_planets = targetType === 'auto';
          if (targetType !== 'auto' && targetType !== 'fixed') payload.body = targetType;
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
