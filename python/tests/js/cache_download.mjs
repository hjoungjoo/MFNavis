import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const source = readFileSync(new URL('../../views/js/cache_download.js', import.meta.url), 'utf8');
const template = readFileSync(new URL('../../views/tools.html', import.meta.url), 'utf8');
const inline = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
const settle = () => new Promise(resolve => setImmediate(resolve));
const response = status => ({ok: true, json: async () => ({status, logs: []})});

function browser() {
  let epoch = 0, elements, root;
  const listeners = [], requests = [], timers = new Map();
  const window = {};
  const document = {
    getElementById: id => id === 'cache-download' ? root : elements.get(id),
    querySelectorAll: () => [],
    addEventListener: (name, listener) => {
      if (name === 'DOMContentLoaded') listeners.push(listener);
    },
  };
  const context = vm.createContext({
    window, document, console,
    M: {FormSelect: {init() {}}, Modal: {init() {}}},
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    setTimeout: callback => {const id = Symbol(); timers.set(id, callback); return id;},
    clearTimeout: id => timers.delete(id),
  });
  function enter(loadBundle = false) {
    epoch += 1;
    timers.clear(); // SPA navigation disposes the outgoing page's timers.
    const capturedEpoch = epoch;
    window.pfPageAlive = () => capturedEpoch === epoch;
    elements = new Map();
    for (const name of ['images', 'workers', 'skip-runtime', 'state', 'progress', 'counts', 'timing', 'log', 'error', 'start', 'stop', 'resume']) {
      elements.set('cache-' + name, {
        textContent: name === 'state' ? 'Loading' : '', disabled: true,
        handlers: [], addEventListener(name, handler) {this.handlers.push(handler);},
        removeAttribute() {},
      });
    }
    root = {dataset: {labels: JSON.stringify({idle: 'Ready', completed: 'Completed', connection_error: 'Connection failed'})},
      querySelector: selector => elements.get(selector.slice(1))};
    if (loadBundle) vm.runInContext(source, context);
    for (const script of inline) vm.runInContext(script, context);
    for (const listener of listeners.splice(0)) listener();
    return elements;
  }
  return {enter, requests, timers, window};
}

test('cached Tools script reconnects on every SPA visit without duplicate handlers', async () => {
  const b = browser();
  for (let visit = 0; visit < 3; visit += 1) {
    const elements = b.enter(visit === 0);
    assert.equal(b.requests.length, visit + 1, 'each visit requests current status');
    b.requests[visit].resolve(response('idle'));
    await settle();
    assert.equal(elements.get('cache-state').textContent, 'Ready');
    assert.equal(elements.get('cache-start').disabled, false);
    assert.equal(elements.get('cache-start').handlers.length, 1);
  }
});

test('a late response from the previous visit cannot overwrite the current page', async () => {
  const b = browser();
  b.enter(true);
  const current = b.enter();
  assert.equal(b.requests.length, 2);
  b.requests[1].resolve(response('completed'));
  await settle();
  b.requests[0].resolve(response('idle'));
  await settle();
  assert.equal(current.get('cache-state').textContent, 'Completed');
  assert.equal(b.timers.size, 1);
});

test('initial connection failure replaces Loading and retries successfully', async () => {
  const b = browser();
  const elements = b.enter(true);
  b.requests[0].reject(new Error('offline'));
  await settle();
  assert.equal(elements.get('cache-state').textContent, 'Connection failed');
  assert.equal(elements.get('cache-start').disabled, true);
  const retry = [...b.timers.values()][0];
  b.timers.clear();
  retry();
  b.requests[1].resolve(response('idle'));
  await settle();
  assert.equal(elements.get('cache-state').textContent, 'Ready');
  assert.equal(elements.get('cache-error').textContent, '');
  assert.equal(elements.get('cache-start').disabled, false);
});

for (const [status, disabled] of [
  ['idle', [false, true, true]],
  ['running', [true, false, true]],
  ['stopping', [true, true, true]],
  ['stopped', [false, true, false]],
  ['interrupted', [false, true, false]],
  ['failed', [false, true, false]],
  ['completed', [false, true, true]],
]) {
  test('download buttons follow job state: ' + status, async () => {
    const b = browser();
    const elements = b.enter(true);
    b.requests[0].resolve({ok: true, json: async () => ({
      status, logs: [], options: {images: 'both', workers: 4, skip_runtime: false},
    })});
    await settle();
    assert.deepEqual(['start', 'stop', 'resume'].map(name => elements.get('cache-' + name).disabled), disabled);
  });
}

test('a pending command disables all download actions until its result arrives', async () => {
  const b = browser();
  const elements = b.enter(true);
  b.requests[0].resolve(response('idle'));
  await settle();
  elements.get('cache-start').handlers[0]();
  const disabled = () => ['start', 'stop', 'resume'].map(name => elements.get('cache-' + name).disabled);
  assert.deepEqual(disabled(), [true, true, true]);
  assert.equal(b.requests[1].options.method, 'POST');
  b.requests[1].resolve(response('running'));
  await settle();
  assert.deepEqual(disabled(), [true, false, true]);
});
