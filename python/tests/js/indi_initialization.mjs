import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Run the rendered initializer with its optional OnStep form present or absent.
// All requests and timers remain local; no telescope commands are executed.
const {script, hasGuideForm} = JSON.parse(readFileSync(0, 'utf8'));
const events = new Map();
const requests = [];
const intervals = [];
const elements = new Map();
function element(id, value = '') {
  const handlers = new Map();
  const result = {value, handlers, textContent: '', addEventListener: (name, callback) => handlers.set(name, callback)};
  elements.set(id, result);
  return result;
}
const restart = element('restart_indi_button');
element('indi_action_status');
if (hasGuideForm) {
  element('pulse_guide_rate_form');
  element('guide_rate', '0.5');
}
const document = {
  getElementById: id => elements.get(id) || null,
  querySelectorAll: () => [],
  addEventListener: (name, callback) => events.set(name, callback),
};
vm.runInNewContext(script, {
  document,
  window: {addEventListener() {}, confirm: () => true},
  M: {FormSelect: {init() {}}, updateTextFields() {}},
  URLSearchParams,
  setInterval: (_callback, ms) => {intervals.push(ms); return intervals.length;},
  clearInterval() {}, setTimeout() {},
  fetch: (url, options) => {
    requests.push({url, options});
    return Promise.resolve({ok: true, json: () => Promise.resolve({ok: true})});
  },
  pfT: value => value,
});
events.get('DOMContentLoaded')();
assert.equal(typeof restart.handlers.get('click'), 'function', 'initialize controls after the optional form');
assert.ok(intervals.includes(5000), 'start INDI polling after the optional form');
assert.ok(requests.some(r => r.url === '/indi/pointing_status'));
assert.ok(requests.some(r => r.url === '/indi/location_time/status'));
if (hasGuideForm) {
  let prevented = false;
  elements.get('pulse_guide_rate_form').handlers.get('submit')({preventDefault() {prevented = true;}});
  assert.ok(prevented);
  const request = requests.find(r => r.url === '/indi/guide_rate');
  assert.equal(request.options.method, 'POST');
  assert.equal(new URLSearchParams(request.options.body).get('guide_rate'), '0.5');
}
await new Promise(resolve => setImmediate(resolve));
