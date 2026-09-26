import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const source = readFileSync(new URL('../../views/js/spa.js', import.meta.url), 'utf8');

function page(fetchResponse) {
  const documentEvents = new Map();
  const windowEvents = new Map();
  const classes = new Set();
  const requests = [];
  const document = {
    readyState: 'complete',
    documentElement: {classList: {add: value => classes.add(value), remove: value => classes.delete(value)}},
    addEventListener: (name, callback) => documentEvents.set(name, callback),
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  const window = {
    location: {href: 'http://example.test/login', origin: 'http://example.test', pathname: '/login', search: ''},
    history: {pushState() {}, replaceState() {}},
    addEventListener: (name, callback) => windowEvents.set(name, callback),
    setTimeout, clearTimeout, setInterval, clearInterval,
    DOMParser: class {},
    fetch: url => {requests.push(url); return fetchResponse();},
  };
  vm.runInNewContext(source, {
    window, document, fetch: window.fetch, URL, URLSearchParams,
    localStorage: {getItem: () => null}, console: {warn() {}},
  });
  function click(href) {
    const anchor = {getAttribute: () => href, hasAttribute: () => false, target: ''};
    const event = {target: {closest: () => anchor}, button: 0, defaultPrevented: false,
      preventDefault() {this.defaultPrevented = true;}};
    documentEvents.get('click')(event);
    return event;
  }
  return {window, requests, classes, click, windowEvents};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const plainText = () => Promise.resolve({ok: true, headers: {get: () => 'text/plain'}});

for (const path of ['/legal/THIRD_PARTY_NOTICES.md', '/legal/THIRD_PARTY_NOTICES_ko.md', '/legal/docs/MFNAVIS_RELEASE_en.md', '/legal/docs/MFNAVIS_RELEASE_ko.md']) {
  test('document links use native navigation: ' + path, () => {
    const p = page(plainText);
    assert.equal(p.click(path).defaultPrevented, false);
    p.windowEvents.get('pageshow')({persisted: true});
    assert.equal(p.click(path).defaultPrevented, false);
    assert.equal(p.requests.length, 0);
    assert.equal(p.classes.has('pf-spa-loading'), false);
  });
}

test('non-HTML fallback releases its lock before navigating away', async () => {
  const p = page(plainText);
  assert.equal(p.click('/plain-document').defaultPrevented, true);
  await settle();
  assert.equal(p.window.location.href, 'http://example.test/plain-document');
  assert.equal(p.classes.has('pf-spa-loading'), false);
  // Restore the same JS heap, as the browser back/forward cache does.
  p.window.location.href = 'http://example.test/login';
  p.click('/plain-document');
  await settle();
  assert.equal(p.requests.length, 2);
});

test('failed fetch permits a subsequent internal navigation', async () => {
  const p = page(() => Promise.reject(new Error('offline')));
  p.click('/network');
  await settle();
  assert.equal(p.classes.has('pf-spa-loading'), false);
  p.click('/tools');
  await settle();
  assert.equal(p.requests.length, 2);
});

test('restoring an interrupted navigation releases the lock', () => {
  const p = page(() => new Promise(() => {}));
  p.click('/network');
  assert.equal(p.classes.has('pf-spa-loading'), true);
  p.click('/tools');
  assert.equal(p.requests.length, 1, 'prevent concurrent SPA requests before restoration');
  p.windowEvents.get('pageshow')({persisted: true});
  assert.equal(p.classes.has('pf-spa-loading'), false);
  p.click('/tools');
  assert.equal(p.requests.length, 2);
});
