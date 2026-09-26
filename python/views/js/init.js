(function($){
  const themeStorageKey = 'pifinderWebTheme';
  const fullscreenStorageKey = 'pifinderWantFullscreen';
  const validThemes = ['grey', 'red'];
  let navigatingAway = false;

  function currentTheme() {
    let storedTheme = null;
    try {
      storedTheme = localStorage.getItem(themeStorageKey);
    } catch (error) {
      storedTheme = null;
    }
    return validThemes.indexOf(storedTheme) === -1 ? 'grey' : storedTheme;
  }

  function applyTheme(theme) {
    const selectedTheme = validThemes.indexOf(theme) === -1 ? 'grey' : theme;
    document.documentElement.setAttribute('data-theme', selectedTheme);
    $('#pf-theme-color').attr('content', selectedTheme === 'red' ? '#260303' : '#757575');
    try {
      localStorage.setItem(themeStorageKey, selectedTheme);
    } catch (error) {
      // Theme selection still applies for the current page if storage is blocked.
    }
    $('.pf-theme-select').val(selectedTheme);
  }

  function fullscreenElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  }

  function fullscreenWanted() {
    try {
      return sessionStorage.getItem(fullscreenStorageKey) === '1';
    } catch (error) {
      return false;
    }
  }

  function setFullscreenWanted(wanted) {
    try {
      sessionStorage.setItem(fullscreenStorageKey, wanted ? '1' : '0');
    } catch (error) {
      // Fullscreen can still be used for the current page if storage is blocked.
    }
  }

  function fullscreenSupported() {
    const root = document.documentElement;
    return Boolean(root.requestFullscreen || root.webkitRequestFullscreen);
  }

  function requestAppFullscreen() {
    const root = document.documentElement;
    const requestFullscreen = root.requestFullscreen || root.webkitRequestFullscreen;
    if (!requestFullscreen) {
      return Promise.reject(new Error('Fullscreen API is not available'));
    }
    return Promise.resolve(requestFullscreen.call(root));
  }

  function exitAppFullscreen() {
    const exitFullscreen = document.exitFullscreen || document.webkitExitFullscreen;
    if (!exitFullscreen) {
      return Promise.reject(new Error('Fullscreen exit API is not available'));
    }
    return Promise.resolve(exitFullscreen.call(document));
  }

  function updateFullscreenButtons() {
    const isFullscreen = fullscreenElement() !== null;
    const icon = isFullscreen ? 'fullscreen_exit' : 'fullscreen';
    const label = window.pfT(isFullscreen ? 'Exit Fullscreen' : 'Fullscreen');
    $('.pf-fullscreen-button').attr('title', label).attr('aria-label', label);
    $('.pf-fullscreen-button .material-icons').text(icon);
    $('#pf-fullscreen-restore').prop('hidden', isFullscreen || !fullscreenWanted());
  }

  function toggleFullscreen() {
    const enteringFullscreen = fullscreenElement() === null;
    const action = enteringFullscreen ? requestAppFullscreen() : exitAppFullscreen();
    action.then(function() {
      setFullscreenWanted(enteringFullscreen);
      updateFullscreenButtons();
    }).catch(function() {
      updateFullscreenButtons();
    });
  }

  // The Fullscreen API is bound to the document and every navigation drops it.
  // requestFullscreen() needs a transient user activation, so it cannot be called
  // on load -- instead the first tap or key press after the new page arrives
  // restores fullscreen without swallowing that interaction.
  function armFullscreenRestore() {
    if (!fullscreenSupported() || !fullscreenWanted() || fullscreenElement()) {
      return;
    }

    function disarm() {
      document.removeEventListener('pointerdown', restore, true);
      document.removeEventListener('keydown', restore, true);
    }

    function restore() {
      if (!fullscreenWanted()) {
        disarm();
        return;
      }
      requestAppFullscreen().then(function() {
        disarm();
        updateFullscreenButtons();
      }).catch(function() {
        // Keep listening: the next gesture gets another chance.
      });
    }

    document.addEventListener('pointerdown', restore, true);
    document.addEventListener('keydown', restore, true);
  }

  function onFullscreenChange() {
    // Leaving fullscreen while staying on the page (Esc, F11) means the user
    // wants windowed mode, so stop restoring it on the next page.
    if (!fullscreenElement() && !navigatingAway) {
      setFullscreenWanted(false);
    }
    updateFullscreenButtons();
  }

  function isInternalNavigationLink(anchor) {
    const href = anchor.getAttribute('href');
    if (!href || href === '#' || href.indexOf('javascript:') === 0) {
      return false;
    }
    if (anchor.target && anchor.target !== '_self') {
      return false;
    }
    const url = new URL(href, window.location.href);
    const nextUrl = url.href.split('#')[0];
    const currentUrl = window.location.href.split('#')[0];
    return url.origin === window.location.origin && nextUrl !== currentUrl;
  }

  $(function(){

    $('.sidenav').sidenav();
    applyTheme(currentTheme());
    updateFullscreenButtons();

    $('.pf-theme-select').on('change', function() {
      applyTheme(this.value);
    });

    $('.pf-language-select').on('change', function() {
      const language = this.value;
      if (['en', 'ko'].indexOf(language) === -1) return;
      document.cookie = 'mfnavis_web_language=' + language + '; Path=/; Max-Age=31536000; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
      if (fullscreenElement()) setFullscreenWanted(true);
      window.location.reload();
    });

    $('.pf-fullscreen-button').on('click', function() {
      toggleFullscreen();
    });

    $('a[href]').on('click', function() {
      if (fullscreenElement() && isInternalNavigationLink(this)) {
        setFullscreenWanted(true);
      }
    });

    armFullscreenRestore();

    window.addEventListener('beforeunload', function() {
      navigatingAway = true;
    });

    window.addEventListener('pageshow', function() {
      navigatingAway = false;
      updateFullscreenButtons();
    });

    document.addEventListener('fullscreenchange', onFullscreenChange);
    document.addEventListener('webkitfullscreenchange', onFullscreenChange);

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js').catch(function() {
        // PWA install still has useful manifest metadata when registration is unavailable.
      });
    }

  }); // end of document ready
})(jQuery); // end of jQuery name space
