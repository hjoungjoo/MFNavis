// LiveCam consumes the same read-only snapshots as the INDI panel. Pulse events
// carry both the submitted duration and transport acceptance for each axis.
const WINDOW_S = 120;
const FRESH_SOLVE_S = 12;
const finite = Number.isFinite;

function coordinates(ra, dec) {
  return finite(ra) && finite(dec) && Math.abs(dec) <= 90 ? [ra, dec] : null;
}

function deltaRA(target, actual) {
  return ((target - actual) % 360 + 540) % 360 - 180;
}

export function guideTarget(guide) {
  const tracking = coordinates(guide.tracking_target_ra, guide.tracking_target_dec);
  if (tracking) return tracking;
  if (guide.service_state === 'running' && /goto|pulse_align/.test(guide.phase)) {
    return coordinates(guide.active_target_ra, guide.active_target_dec);
  }
  return null;
}

export function measuredError(solved, target, now, since) {
  if (!target || !solved?.valid || solved.source !== 'solve' || solved.quality !== 'high') return null;
  const meta = solved.metadata || {};
  const t = meta.last_solve_success ?? solved.timestamp;
  if (!finite(t) || t < since || t < now - FRESH_SOLVE_S || t > now + 1 ||
      meta.last_solve_attempt > t) return null;
  const ra = meta.source_ra ?? meta.unstabilized_ra ?? solved.ra;
  const dec = meta.source_dec ?? meta.unstabilized_dec ?? solved.dec;
  if (!coordinates(ra, dec)) return null;
  return { t, ra: deltaRA(target[0], ra) * 3600 * Math.cos(dec * Math.PI / 180),
    dec: (target[1] - dec) * 3600 };
}

export function acceptedPulses(lines, target, since, now) {
  const events = [];
  const marker = 'Guide pulse event ';
  for (const line of lines) {
    const at = line.indexOf(marker);
    if (at < 0) continue;
    let e;
    try { e = JSON.parse(line.slice(at + marker.length)); } catch { continue; }
    if (e?.accepted !== true || !finite(e.sent_wall) || e.sent_wall < since ||
        e.sent_wall > now + 1 || !finite(e.duration_ms) || e.duration_ms <= 0 ||
        !Array.isArray(e.target) || !coordinates(...e.target) ||
        Math.abs(deltaRA(target[0], e.target[0])) > 1e-7 ||
        Math.abs(target[1] - e.target[1]) > 1e-7 ||
        !['east', 'west', 'north', 'south'].includes(e.direction)) continue;
    const ra = e.direction === 'east' || e.direction === 'west';
    const positive = e.direction === 'east' || e.direction === 'north';
    events.push({ t: e.sent_wall, axis: ra ? 'ra' : 'dec', direction: e.direction,
      value: positive ? e.duration_ms : -e.duration_ms });
  }
  return events;
}

export function rms(samples) {
  if (!samples.length) return null;
  const meanSquare = axis => samples.reduce((sum, p) => sum + p[axis] ** 2, 0) / samples.length;
  const ra = Math.sqrt(meanSquare('ra')), dec = Math.sqrt(meanSquare('dec'));
  return { ra, dec, total: Math.hypot(ra, dec) };
}

function draw(canvas, points, now, pulses, colors) {
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.font = '11px sans-serif';
  let peak = pulses ? 100 : 1;
  for (const p of points) peak = Math.max(peak, pulses ? Math.abs(p.value) : Math.max(Math.abs(p.ra), Math.abs(p.dec)));
  const power = 10 ** Math.floor(Math.log10(peak));
  const limit = [1, 2, 5, 10].find(n => n * power >= peak) * power;
  // Reserve the same axis gutter for both units so a command lines up with its exposure.
  const left = 54, right = width - 8;
  const top = 12, bottom = height - (pulses ? 22 : 12), zero = (top + bottom) / 2;
  const x = t => right - (now - t) / WINDOW_S * (right - left);
  const y = v => zero - v / limit * (zero - top);
  const line = (x1, y1, x2, y2) => {
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  };
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.fillStyle = colors.text;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (const v of [-limit, 0, limit]) {
    ctx.strokeStyle = v === 0 ? colors.text : colors.grid;
    line(left, y(v), right, y(v));
    ctx.fillText(String(v), left - 5, y(v));
  }
  for (let age = WINDOW_S; age >= 0; age -= 30) {
    const position = x(now - age);
    ctx.strokeStyle = colors.grid;
    line(position, top, position, bottom);
    if (pulses) {
      ctx.textAlign = age === 0 ? 'right' : age === WINDOW_S ? 'left' : 'center';
      ctx.fillText((age ? '−' + age : '0') + ' s', position, height - 9);
    }
  }
  ctx.save();
  ctx.beginPath(); ctx.rect(left - 2, top - 2, right - left + 4, bottom - top + 4); ctx.clip();
  for (const axis of ['ra', 'dec']) {
    ctx.fillStyle = ctx.strokeStyle = colors[axis];
    if (pulses) {
      for (const p of points) {
        if (p.axis !== axis) continue;
        const pos = x(p.t) + (axis === 'ra' ? -1.5 : 1.5);
        ctx.fillRect(pos - 1.25, Math.min(zero, y(p.value)), 2.5, Math.max(1, Math.abs(y(p.value) - zero)));
      }
    } else {
      ctx.lineWidth = 1.7;
      ctx.setLineDash(axis === 'dec' ? [4, 3] : []);
      ctx.beginPath();
      let prev;
      for (const p of points) {
        if (!prev || p.gap || p.t - prev.t > 5) ctx.moveTo(x(p.t), y(p[axis]));
        else ctx.lineTo(x(p.t), y(p[axis]));
        prev = p;
      }
      ctx.stroke();
      for (const p of points) ctx.fillRect(x(p.t) - 1.2, y(p[axis]) - 1.2, 2.4, 2.4);
    }
  }
  ctx.restore();
}

export function mountGuideHistory(preview) {
  let root = document.getElementById('livecam-guide');
  if (!root) {
    // A running observation may still serve the cached LiveCam template.
    root = document.createElement('section');
    root.id = 'livecam-guide';
    root.className = 'card grey darken-2';
    preview.closest('.card').after(root);
  }
  if (root.childElementCount) return;
  const ko = document.documentElement.lang === 'ko';
  const tr = (en, kr) => ko ? kr : en;
  const title = tr('Guide history', '가이드 그래프');
  const errorTitle = tr('Target offset (″)', '목표까지의 오차 (″)');
  const pulseTitle = tr('Guide commands (ms)', '미세 보정 명령 (ms)');
  const polarity = tr('+ East / + North', '+ 동쪽 / + 북쪽');
  root.hidden = false;
  root.setAttribute('aria-label', title);
  root.innerHTML = `<div class="card-content">
    <div class="guide-heading"><h5 class="grey-text">${title}</h5><span class="guide-state"></span></div>
    <div class="guide-readout"><strong>${errorTitle}</strong>
      <span><span class="guide-ra"></span><span class="guide-dec"></span></span></div>
    <canvas class="guide-errors" role="img" aria-label="${errorTitle} · ${polarity}"></canvas>
    <div class="guide-readout"><strong>${pulseTitle}</strong><span>${polarity}</span></div>
    <canvas class="guide-pulses" role="img" aria-label="${pulseTitle} · ${polarity}"></canvas>
    <div class="guide-readout"><span class="guide-rms"></span><span class="guide-last"></span></div>
  </div>`;
  const el = name => root.querySelector('.guide-' + name);
  const waiting = tr('Waiting for plate solve', '플레이트 솔브 대기');
  const unavailable = tr('Telemetry unavailable', '상태 수신 대기');
  const directions = ko ? {east:'동', west:'서', north:'북', south:'남'} : {east:'E', west:'W', north:'N', south:'S'};
  const stateLabels = ko ? {
    enabled: '가이드 켜짐', off: '가이드 꺼짐', suspended: '가이드 일시정지',
    paused: '가이드 일시정지', waiting_target: '대상 대기', settling: '안정화 중',
    complete: '허용 오차 이내', pulse: '펄스 보정 중', solve_holdover: '솔브 대기 중 보정',
    waiting_solve: waiting, waiting_coordinate: '좌표 대기', waiting_mount: '마운트 대기',
    native_tracking: '마운트 자체 추적', manual_move: '수동 이동 중', disturbed: '흔들림 감지',
    recovery_wait: '복구 대기', recovering_manual: '수동 이동 복구 중', recovering_goto: 'GoTo 복구 중',
    limit_exceeded: '이동 한계 초과', unsupported: '펄스 보정 미지원', reacquire: '재포착 중', failed: '실패'
  } : {enabled: 'Guide on', off: 'Guide off', complete: 'Within tolerance'};
  const label = value => stateLabels[value] || (value || '').replaceAll('_', ' ');
  let samples = [];
  let pulses = [];
  let sessionKey, since, lastDeadline;
  let cursor = 0;
  let lastLogRead = -Infinity;
  let gap = true;
  let pulseUnavailable = false;
  let clockOffset = Date.now() / 1000 - performance.now() / 1000;
  const clock = () => clockOffset + performance.now() / 1000;
  const fresh = (t, now, age) => finite(t) && t > 0 && t <= now + 1 && now - t <= age;
  const format = v => finite(v) ? v.toFixed(1) + '″' : '—';
  const signed = v => finite(v) && v > 0 ? '+' + format(v) : format(v);

  async function read(url) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 4500);
    try {
      const response = await fetch(url, {cache:'no-store', signal:controller.signal});
      if (!response.ok) throw Error('Telemetry request failed');
      const data = await response.json();
      return {data, date: Date.parse(response.headers.get('date'))};
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function readPulses(deadline, target, now) {
    if (!target || !finite(deadline) || deadline < Math.max(since, now - WINDOW_S)) return;
    if (Math.abs(deadline - lastDeadline) < 0.01 && deadline < now - 2 && !pulseUnavailable) return;
    // Heartbeats overwrite command messages, and two axes can share an end
    // time. Only tail the structured log when there has been pulse activity.
    try {
      const position = now - lastLogRead > 10 ? 0 : cursor;
      const {data} = await read('/logs/stream?position=' + position);
      if (data.error || data.file_not_found || !Array.isArray(data.logs)) throw Error('Pulse log unavailable');
      const events = acceptedPulses(data.logs, target, Math.max(since, now - WINDOW_S), clock());
      const known = new Set(pulses.map(p => p.t + p.axis));
      for (const event of events) {
        const id = event.t + event.axis;
        if (!known.has(id)) pulses.push(event);
        known.add(id);
      }
      pulses.sort((a, b) => a.t - b.t);
      cursor = data.position;
      lastLogRead = now;
      lastDeadline = deadline;
      pulseUnavailable = false;
    } catch { pulseUnavailable = true; }
  }

  async function poll() {
    if (!root.isConnected) return;
    let state = unavailable, measured = false;
    try {
      const {data, date} = await read('/indi/pointing_status');
      if (!root.isConnected) return;
      if (finite(date)) clockOffset = (date + 500 - performance.now()) / 1000;
      const now = clock();
      const guide = data.goto_guide_status || {}, mount = data.mount_control_status || {};
      if (!fresh(guide.updated, now, 5) || !fresh(mount.updated, now, 5)) throw Error();
      const target = guideTarget(guide);
      const start = guide.goto_timing?.started_wall || guide.started || 0;
      const key = JSON.stringify([guide.started, start, target, mount.connection_epoch]);
      if (key !== sessionKey) {
        // A manual retarget can take place during the same GoTo session.
        since = sessionKey === undefined ? start : Math.max(start, guide.updated);
        sessionKey = key;
        samples = [];
        pulses = [];
        gap = true;
        cursor = 0;
        lastLogRead = -Infinity;
        lastDeadline = undefined;
        pulseUnavailable = false;
      }
      const tracking = mount.tracking_enabled === true ? tr('Tracking on', '추적 중') :
        mount.tracking_enabled === false ? tr('Tracking off', '추적 꺼짐') : tr('Tracking unknown', '추적 상태 미확인');
      const details = [tracking, label(guide.tracking_guide_state)];
      if (mount.guide_correction_enabled && mount.guide_correction_mode !== 'off') {
        details.push(label(mount.guide_correction_mode));
      }
      if (!target) details.push(tr('No target', '대상 없음'));
      const solved = guide.pointing?.solved;
      const p = guide.pointing?.fresh && measuredError(solved, target, now, since);
      const last = samples.at(-1);
      if (p && (!last || p.t > last.t)) {
        samples.push({...p, gap});
        gap = false;
      }
      const failed = solved?.metadata?.last_solve_attempt > solved?.metadata?.last_solve_success;
      if (failed || !guide.pointing?.fresh) gap = true;
      measured = !!target && !gap && fresh(samples.at(-1)?.t, now, FRESH_SOLVE_S);
      if (target && !measured) details.push(waiting);
      state = [...new Set(details.filter(Boolean))].join(' · ');

      await readPulses(mount.guide_pulse_until_wall, target, now);
    } catch { gap = true; }
    if (!root.isConnected) return;
    const now = clock();
    samples = samples.filter(p => p.t >= now - WINDOW_S);
    pulses = pulses.filter(p => p.t >= now - WINDOW_S);
    const latest = measured ? samples.at(-1) : null, stats = rms(samples);
    el('state').textContent = state;
    el('ra').textContent = 'RA ' + signed(latest?.ra);
    el('dec').textContent = 'Dec ' + signed(latest?.dec);
    el('rms').textContent = `RMS · RA ${format(stats?.ra)}  /  Dec ${format(stats?.dec)}  /  ${tr('Total', '합계')} ${format(stats?.total)}  (N=${samples.length})`;
    const pulse = pulses.at(-1);
    const age = pulse ? Math.max(0, Math.round(now - pulse.t)) : 0;
    const command = pulse ? `${directions[pulse.direction]} ${Math.abs(pulse.value)} ms (${age}${tr('s ago', '초 전')})` : '—';
    el('last').textContent = pulseUnavailable ? tr('Pulse log unavailable', '펄스 기록 수신 대기') :
      tr('Last pulse', '최근 펄스') + ' · ' + command;
    const style = getComputedStyle(root);
    const color = key => style.getPropertyValue(key).trim();
    const colors = {ra:color('--guide-ra'), dec:color('--guide-dec'), text:color('--pf-text'), grid:color('--pf-border')};
    draw(el('errors'), samples, now, false, colors);
    draw(el('pulses'), pulses, now, true, colors);
    window.setTimeout(poll, 1000);
  }
  poll();
}
