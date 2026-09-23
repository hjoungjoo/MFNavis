// Same-document navigation for the MFNavis web UI.
//
// The Fullscreen API is bound to the document, so a normal link navigation
// always drops fullscreen and cannot be restored without a fresh user gesture.
// Swapping <main> in place keeps the document -- and therefore fullscreen --
// alive, which is what the red night theme needs.
//
// Three constraints shape this file:
//   1. Page scripts define globals used by inline onclick= handlers, so they
//      cannot be wrapped in a function scope. They run through indirect eval:
//      `function`/`var` still land on window, while `let`/`const` stay in the
//      eval scope so revisiting a page does not throw on redeclaration.
//   2. Page scripts hook DOMContentLoaded, which never fires again once the
//      document is loaded, so that listener is shimmed.
//   3. Several pages drive themselves with self-rescheduling setTimeout polls.
//      Timers are tracked per page epoch and dropped on navigation, and the
//      pages guard their own reschedule points with pfPageAlive().
(function() {
  'use strict';

  const nativeSetTimeout = window.setTimeout;
  const nativeSetInterval = window.setInterval;
  const nativeClearTimeout = window.clearTimeout;
  const nativeClearInterval = window.clearInterval;

  const pendingTimeouts = new Set();
  const pendingIntervals = new Set();

  let epoch = 0;
  let navigating = false;

  window.pfPageEpoch = function() {
    return epoch;
  };

  // Re-created for every page. A page script must capture the reference while
  // it runs (`const PAGE_ALIVE = window.pfPageAlive;`) -- reading
  // window.pfPageAlive later would resolve to whichever page is current and
  // always report alive, which is exactly the leak this guards against.
  function publishAliveCheck() {
    const pageEpoch = epoch;
    window.pfPageAlive = function() {
      return pageEpoch === epoch;
    };
  }

  function supported() {
    return Boolean(
      window.history && window.history.pushState && window.fetch && window.DOMParser
    );
  }

  // Escape hatch. If same-document navigation misbehaves in the field, load any
  // page with ?nospa=1 to turn it off for this browser; ?nospa=0 re-enables it.
  // Plain link navigation then takes over again -- fullscreen falls back to the
  // "first gesture restores it" behaviour in init.js.
  function disabled() {
    try {
      const flag = new URLSearchParams(window.location.search).get('nospa');
      if (flag === '1') {
        localStorage.setItem('pifinderSpa', 'off');
      } else if (flag === '0') {
        localStorage.removeItem('pifinderSpa');
      }
      return localStorage.getItem('pifinderSpa') === 'off';
    } catch (error) {
      return false;
    }
  }

  // Bail out before patching anything: when the SPA is off, the timer and
  // listener shims below must not be installed at all. Pages still get a
  // pfPageAlive() that always reports alive, since nothing swaps them out.
  if (!supported() || disabled()) {
    publishAliveCheck();
    // Callers use pfNavigate unconditionally; with the SPA off it is just a
    // normal navigation.
    window.pfNavigate = function(url) {
      window.location.href = url;
    };
    return;
  }

  // --- timer tracking -------------------------------------------------------

  window.setTimeout = function(handler, delay) {
    if (typeof handler !== 'function') {
      return nativeSetTimeout.apply(window, arguments);
    }
    const scheduledEpoch = epoch;
    const extra = Array.prototype.slice.call(arguments, 2);
    const id = nativeSetTimeout.call(window, function() {
      pendingTimeouts.delete(id);
      if (scheduledEpoch !== epoch) {
        return;
      }
      handler.apply(window, extra);
    }, delay);
    pendingTimeouts.add(id);
    return id;
  };

  window.setInterval = function(handler, delay) {
    if (typeof handler !== 'function') {
      return nativeSetInterval.apply(window, arguments);
    }
    const scheduledEpoch = epoch;
    const extra = Array.prototype.slice.call(arguments, 2);
    const id = nativeSetInterval.call(window, function() {
      if (scheduledEpoch !== epoch) {
        nativeClearInterval.call(window, id);
        pendingIntervals.delete(id);
        return;
      }
      handler.apply(window, extra);
    }, delay);
    pendingIntervals.add(id);
    return id;
  };

  window.clearTimeout = function(id) {
    pendingTimeouts.delete(id);
    return nativeClearTimeout.call(window, id);
  };

  window.clearInterval = function(id) {
    pendingIntervals.delete(id);
    return nativeClearInterval.call(window, id);
  };

  function stopPageTimers() {
    pendingTimeouts.forEach(function(id) {
      nativeClearTimeout.call(window, id);
    });
    pendingIntervals.forEach(function(id) {
      nativeClearInterval.call(window, id);
    });
    pendingTimeouts.clear();
    pendingIntervals.clear();
  }

  // --- DOMContentLoaded shim ------------------------------------------------

  const nativeAddEventListener = document.addEventListener.bind(document);
  document.addEventListener = function(type, listener, options) {
    // After the first load this event never fires again, so page scripts that
    // wait for it would silently do nothing on every SPA navigation.
    if (type === 'DOMContentLoaded' && document.readyState !== 'loading') {
      if (typeof listener === 'function') {
        nativeSetTimeout.call(window, function() {
          listener.call(document, new Event('DOMContentLoaded'));
        }, 0);
      } else if (listener && typeof listener.handleEvent === 'function') {
        nativeSetTimeout.call(window, function() {
          listener.handleEvent(new Event('DOMContentLoaded'));
        }, 0);
      }
      return;
    }
    return nativeAddEventListener(type, listener, options);
  };

  // --- content swap ---------------------------------------------------------

  // Absolute URLs of every external script already in the document.
  const loadedScripts = new Set();

  function absoluteUrl(value) {
    return new URL(value, window.location.href).href;
  }

  // Page blocks may pull in their own bundle (the catalog pages load
  // /js/catalogs.js and then call into it from the next inline script), so an
  // external script has to finish loading before the rest of the block runs.
  function loadExternalScript(src) {
    const url = absoluteUrl(src);
    if (loadedScripts.has(url)) {
      // Already defined its globals; the inline init call below re-runs anyway.
      return Promise.resolve();
    }
    return new Promise(function(resolve) {
      const element = document.createElement('script');
      element.src = url;
      element.async = false;
      element.onload = function() {
        loadedScripts.add(url);
        resolve();
      };
      element.onerror = function() {
        console.error('MFNavis SPA: failed to load ' + url);
        resolve();
      };
      document.head.appendChild(element);
    });
  }

  function runPageScripts(container) {
    const scripts = Array.prototype.slice.call(container.querySelectorAll('script'));
    return scripts.reduce(function(chain, script) {
      return chain.then(function() {
        const src = script.getAttribute('src');
        if (src) {
          return loadExternalScript(src);
        }
        try {
          // Indirect eval: sloppy-mode global scope for function/var, private
          // lexical scope for let/const. A <script> element would instead put
          // let/const on the global lexical scope and throw on the second visit.
          (0, eval)(script.textContent);
        } catch (error) {
          console.error('MFNavis SPA: page script failed', error);
        }
        return undefined;
      });
    }, Promise.resolve());
  }

  // Page blocks can also carry their own stylesheet. Hoisting it into <head>
  // keeps it out of the swapped subtree and avoids a flash of unstyled content
  // on every visit -- which matters a lot on the red night theme.
  function hoistStylesheets(container) {
    const links = container.querySelectorAll('link[rel="stylesheet"][href]');
    for (let i = 0; i < links.length; i += 1) {
      const href = absoluteUrl(links[i].getAttribute('href'));
      if (!document.querySelector('link[rel="stylesheet"][data-pf-spa="' + href + '"]')) {
        const element = document.createElement('link');
        element.rel = 'stylesheet';
        element.href = href;
        element.setAttribute('data-pf-spa', href);
        document.head.appendChild(element);
      }
      links[i].parentNode.removeChild(links[i]);
    }
  }

  function reinitMaterialize(container) {
    if (window.M && typeof window.M.AutoInit === 'function') {
      try {
        window.M.AutoInit(container);
      } catch (error) {
        console.error('MFNavis SPA: Materialize init failed', error);
      }
    }
  }

  function closeSidenav() {
    if (!window.M || !window.M.Sidenav) {
      return;
    }
    const sidenav = document.querySelector('.sidenav');
    if (!sidenav) {
      return;
    }
    const instance = window.M.Sidenav.getInstance(sidenav);
    if (instance) {
      instance.close();
    }
  }

  function swapDocument(html, url, push) {
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const nextMain = parsed.querySelector('main');
    const currentMain = document.querySelector('main');
    if (!nextMain || !currentMain) {
      return Promise.reject(new Error('Page has no <main> to swap'));
    }

    // Everything scheduled by the outgoing page stops here.
    epoch += 1;
    stopPageTimers();

    hoistStylesheets(nextMain);
    currentMain.innerHTML = nextMain.innerHTML;
    document.title = parsed.title;
    if (parsed.body && parsed.body.className) {
      document.body.className = parsed.body.className;
    }

    // Update the address before the page scripts run: they may read
    // location.pathname to decide what to fetch.
    if (push) {
      window.history.pushState({ pfSpa: true }, '', url);
    }

    publishAliveCheck();
    reinitMaterialize(currentMain);
    window.scrollTo(0, 0);

    return runPageScripts(parsed.body).then(function() {
      document.dispatchEvent(new CustomEvent('pf:navigated', { detail: { url: url } }));
    });
  }

  function loadPage(url, push) {
    if (navigating) {
      return;
    }
    navigating = true;
    document.documentElement.classList.add('pf-spa-loading');

    fetch(url, {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'PiFinderSPA' },
    }).then(function(response) {
      const type = response.headers.get('Content-Type') || '';
      if (!response.ok || type.indexOf('text/html') === -1) {
        throw new Error('Unsupported response for SPA navigation');
      }
      // A login redirect lands elsewhere; keep the address bar honest.
      const finalUrl = response.redirected ? response.url : url;
      return response.text().then(function(html) {
        return { html: html, finalUrl: finalUrl };
      });
    }).then(function(result) {
      return swapDocument(result.html, result.finalUrl, push);
    }).then(function() {
      navigating = false;
      document.documentElement.classList.remove('pf-spa-loading');
    }).catch(function(error) {
      // Any doubt at all: hand the navigation back to the browser. Losing
      // fullscreen is far better than showing a broken control page.
      console.warn('MFNavis SPA: falling back to full navigation', error);
      window.location.href = url;
    });
  }

  function isSpaLink(anchor, event) {
    if (event.defaultPrevented) {
      return false;
    }
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return false;
    }
    if (anchor.hasAttribute('download') || anchor.hasAttribute('data-pf-no-spa')) {
      return false;
    }
    if (anchor.target && anchor.target !== '_self') {
      return false;
    }
    const href = anchor.getAttribute('href');
    if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) {
      return false;
    }
    const url = new URL(href, window.location.href);
    if (url.origin !== window.location.origin) {
      return false;
    }
    // Let the browser handle in-page anchors and non-page assets.
    if (url.pathname === window.location.pathname && url.hash) {
      return false;
    }
    return true;
  }

  // Rows that navigate by assigning window.location bypass the click handler
  // below entirely, which drops fullscreen. They call this instead.
  window.pfNavigate = function(url) {
    loadPage(absoluteUrl(url), true);
  };

  // The first page was delivered by the browser, not by swapDocument().
  publishAliveCheck();

  // Whatever the browser already loaded must not be fetched again.
  const initialScripts = document.querySelectorAll('script[src]');
  for (let i = 0; i < initialScripts.length; i += 1) {
    loadedScripts.add(absoluteUrl(initialScripts[i].getAttribute('src')));
  }

  document.addEventListener('click', function(event) {
    const anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
    if (!anchor || !isSpaLink(anchor, event)) {
      return;
    }
    event.preventDefault();
    closeSidenav();
    const url = new URL(anchor.getAttribute('href'), window.location.href);
    loadPage(url.href, true);
  });

  window.addEventListener('popstate', function() {
    loadPage(window.location.href, false);
  });

  window.history.replaceState({ pfSpa: true }, '', window.location.href);
})();
