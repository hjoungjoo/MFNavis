import json
import re
from pathlib import Path


VIEWS_DIR = Path(__file__).resolve().parents[1] / "views"
SERVER_PATH = Path(__file__).resolve().parents[1] / "PiFinder" / "server.py"


def test_base_template_exposes_theme_selector():
    base_html = (VIEWS_DIR / "base.html").read_text()

    assert 'data-theme="grey"' in base_html
    assert "pifinderWebTheme" in base_html
    assert 'rel="manifest"' in base_html
    assert "apple-mobile-web-app-capable" in base_html
    assert "apple-touch-icon" in base_html
    assert "pf-theme-select" in base_html
    assert "pf-fullscreen-button" in base_html
    assert "pf-fullscreen-restore" in base_html
    assert 'value="grey"' in base_html
    assert 'value="red"' in base_html


def test_base_template_exposes_browser_language_selector():
    base_html = (VIEWS_DIR / "base.html").read_text()
    init_js = (VIEWS_DIR / "js" / "init.js").read_text()
    server_py = SERVER_PATH.read_text()

    assert 'action="/language"' not in base_html
    assert base_html.count("pf-language-select") == 2
    assert 'web_language() if web_language is defined else "en"' in base_html
    assert 'value="en"' in base_html
    assert 'value="ko"' in base_html

    assert "pf-language-select" in init_js
    assert "document.cookie = 'mfnavis_web_language='" in init_js
    assert "window.location.reload()" in init_js
    assert "this.form.submit()" not in init_js

    assert "WEB_LANGUAGE_COOKIE" not in server_py
    assert "SUPPORTED_WEB_LANGUAGES" not in server_py
    assert "BABEL_TRANSLATION_DIRECTORIES" in server_py
    assert '@app.route("/language", methods=["POST"])' not in server_py


def test_korean_lcd_translations_cover_recent_pages():
    ko_po = (
        Path(__file__).resolve().parents[1]
        / "locale"
        / "ko"
        / "LC_MESSAGES"
        / "messages.po"
    ).read_text()

    expected_pairs = {
        "INDI": "INDI",
        "Backlash": "백래시",
        "Multi Align": "멀티 정렬",
        "Set Location": "위치 설정",
        "Restart INDI": "INDI 재시작",
        "Align Complete": "정렬 완료",
        "Square : Confirm": "네모 : 확정",
        "Point Confirmed": "정렬점 확정",
        "Mount Control Off": "마운트 제어 꺼짐",
        "Guide Correction": "가이드 보정",
    }
    for msgid, msgstr in expected_pairs.items():
        assert f'msgid "{msgid}"' in ko_po
        assert f'msgstr "{msgstr}"' in ko_po


def test_desktop_nav_controls_share_one_alignment_context():
    style_css = (VIEWS_DIR / "css" / "style.css").read_text()
    base_html = (VIEWS_DIR / "base.html").read_text()

    assert "pf-nav-top-row" in base_html
    assert "pf-nav-controls" in base_html
    assert "pf-nav-links hide-on-med-and-down" in base_html
    assert "pf-main-nav" in style_css
    assert ".pf-nav-top-row" in style_css
    assert ".pf-nav-controls" in style_css
    assert ".pf-nav-links" in style_css
    assert "display: flex" in style_css
    assert "align-items: center" in style_css
    assert ".pf-nav-icon-button .material-icons" in style_css
    assert ".pf-language-form" not in style_css
    assert "height: 2.5rem" in style_css
    assert "line-height: 1" in style_css


def test_indi_backlash_controls_are_present():
    indi_html = (VIEWS_DIR / "indi_mount.html").read_text()
    server_py = SERVER_PATH.read_text()

    assert 'id="indi_backlash_form"' in indi_html
    assert 'id="backlash_current_value"' in indi_html
    assert 'id="backlash_auto_status"' in indi_html
    assert 'id="backlash_motion_start"' in indi_html
    assert 'id="backlash_motion_control"' in indi_html
    assert 'id="backlash_motion_repeats"' in indi_html
    assert 'name="backlash_ra"' in indi_html
    assert 'name="backlash_de"' in indi_html
    assert 'data-axis="ra"' in indi_html
    assert 'data-axis="de"' in indi_html
    assert "/indi/backlash/auto" in indi_html
    assert "/indi/backlash/auto/stop" in indi_html

    assert '@app.route("/indi/backlash", methods=["POST"])' in server_py
    assert '@app.route("/indi/backlash/auto", methods=["POST"])' in server_py
    assert '@app.route("/indi/backlash/auto/stop", methods=["POST"])' in server_py
    assert "WEB_BACKLASH_DEFAULT_REPEATS = 10" in server_py
    assert '"repeats": repeats' in server_py


def test_indi_serial_auto_discovery_controls_are_present():
    indi_html = (VIEWS_DIR / "indi_mount.html").read_text()
    server_py = SERVER_PATH.read_text()

    assert 'value="__auto__"' in indi_html
    assert "Auto (Find connected OnStep)" in indi_html
    assert "Auto (Detect with port)" in indi_html
    assert 'id="serial_discovery_status_value"' in indi_html
    assert "updateSerialAutoControls" in indi_html
    assert "updateSerialDiscovery" in indi_html
    assert '"type": "discover_serial_connection"' in server_py


def test_indi_multipoint_align_controls_are_present():
    indi_html = (VIEWS_DIR / "indi_mount.html").read_text()
    server_py = SERVER_PATH.read_text()

    assert 'id="indi_multipoint_align_form"' in indi_html
    assert 'id="multipoint_align_status"' in indi_html
    assert 'name="align_points"' in indi_html
    assert 'name="align_mode"' in indi_html
    assert 'name="align_star"' in indi_html
    assert 'id="multipoint_align_start"' in indi_html
    assert 'id="multipoint_align_goto"' in indi_html
    assert 'id="multipoint_align_confirm"' in indi_html
    assert 'id="multipoint_align_cancel"' in indi_html
    assert "updateMultipointAlignButtons" in indi_html
    assert 'value="confirm"' in indi_html
    assert 'value="cancel"' in indi_html
    assert "/indi/multipoint_align" in indi_html

    assert '@app.route("/indi/multipoint_align", methods=["POST"])' in server_py
    assert "multipoint_align_start" in server_py
    assert "multipoint_align_confirm" in server_py


def test_indi_mount_state_splits_home_park_and_raw_status():
    indi_html = (VIEWS_DIR / "indi_mount.html").read_text()
    sys_utils_py = (
        Path(__file__).resolve().parents[1] / "PiFinder" / "sys_utils.py"
    ).read_text()

    assert "OnStep Status.Park" in sys_utils_py
    assert "OnStep Status.:GU# return" in sys_utils_py
    assert "Home State" in indi_html
    assert "Park State" in indi_html
    assert "Raw Mount Status" in indi_html
    assert "indi_home_state_value" in indi_html
    assert "TELESCOPE_PARK.PARK" in sys_utils_py
    assert "TELESCOPE_PARK.UNPARK" in sys_utils_py


def test_red_theme_is_defined_without_overriding_log_viewer_colors():
    style_css = (VIEWS_DIR / "css" / "style.css").read_text()
    logs_html = (VIEWS_DIR / "logs.html").read_text()

    assert 'html[data-theme="red"]' in style_css
    assert "--pf-bg: #080000" in style_css
    assert 'html[data-theme="red"] .log-container' not in style_css
    assert ".pf-fullscreen-menu" in style_css
    assert ".log-container" in logs_html
    assert "color: #d4d4d4" in logs_html
    assert "logLine.style.color = '#ff6b6b'" in logs_html


def test_log_toolbar_controls_wrap_and_center_button_content():
    logs_html = (VIEWS_DIR / "logs.html").read_text()

    assert "flex-wrap: wrap" in logs_html
    assert ".controls .btn" in logs_html
    assert "display: inline-flex" in logs_html
    assert "align-items: center" in logs_html
    assert ".controls .btn .material-icons.left" in logs_html
    assert "float: none" in logs_html
    assert "flex: 1 1 16rem" in logs_html


def test_pwa_manifest_and_assets_are_present():
    manifest = json.loads((VIEWS_DIR / "manifest.webmanifest").read_text())
    server_py = SERVER_PATH.read_text()

    assert manifest["name"] == "MFNavis"
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "fullscreen"
    assert "standalone" in manifest["display_override"]
    assert "/manifest.webmanifest" in server_py
    assert "/service-worker.js" in server_py

    icon_sources = {icon["src"] for icon in manifest["icons"]}
    assert "/images/mfnavis-logo.png" in icon_sources
    assert (VIEWS_DIR / "images" / "mfnavis-logo.png").is_file()


def test_fullscreen_script_is_present():
    init_js = (VIEWS_DIR / "js" / "init.js").read_text()

    assert "requestFullscreen" in init_js
    assert "pifinderWantFullscreen" in init_js
    assert "sessionStorage" in init_js
    assert "webkitRequestFullscreen" in init_js
    assert "exitFullscreen" in init_js
    assert "fullscreenchange" in init_js


def test_fullscreen_restores_on_the_first_gesture_after_navigation():
    init_js = (VIEWS_DIR / "js" / "init.js").read_text()

    # requestFullscreen() needs a transient user activation, so the restore has
    # to hang off a real gesture rather than run on load.
    assert "armFullscreenRestore" in init_js
    assert "addEventListener('pointerdown', restore, true)" in init_js
    assert "addEventListener('keydown', restore, true)" in init_js
    assert "fullscreenSupported" in init_js

    # The gesture must not be swallowed by the restore listener, so the function
    # body itself must never cancel the event it rides on.
    arm_body = init_js.split("function armFullscreenRestore")[1].split(
        "function onFullscreenChange"
    )[0]
    assert "preventDefault" not in arm_body
    assert "stopPropagation" not in arm_body

    # Leaving fullscreen deliberately (Esc/F11) must not be undone on next tap.
    assert "navigatingAway" in init_js
    assert "beforeunload" in init_js
    assert "onFullscreenChange" in init_js


def test_spa_engine_is_wired_into_base_template():
    base_html = (VIEWS_DIR / "base.html").read_text()

    # Must load before the page block so page scripts can capture pfPageAlive.
    assert "/js/spa.js" in base_html
    assert base_html.index("/js/spa.js") < base_html.index("{% block scripts %}")
    assert base_html.index("/js/init.js") < base_html.index("/js/spa.js")


def test_spa_engine_handles_the_three_page_script_hazards():
    spa_js = (VIEWS_DIR / "js" / "spa.js").read_text()

    # 1. Page scripts define globals for inline onclick=, so they cannot be
    #    wrapped in a scope; indirect eval keeps let/const out of global lexical
    #    scope so a second visit does not throw on redeclaration.
    assert "(0, eval)" in spa_js

    # 2. DOMContentLoaded never fires again after the first load.
    assert "DOMContentLoaded" in spa_js
    assert "readyState" in spa_js

    # 3. Self-rescheduling poll loops must not survive or multiply.
    assert "stopPageTimers" in spa_js
    assert "pfPageAlive" in spa_js
    assert "pfPageEpoch" in spa_js
    assert "scheduledEpoch" in spa_js

    # Any failure hands the navigation back to the browser.
    assert "window.location.href = url" in spa_js
    # Field escape hatch.
    assert "nospa" in spa_js


def test_spa_loads_page_owned_external_scripts():
    spa_js = (VIEWS_DIR / "js" / "spa.js").read_text()

    # The catalog pages load /js/catalogs.js in their scripts block and call
    # into it from the very next inline script, so external scripts must be
    # fetched, deduped, and awaited in order -- skipping them leaves the
    # catalog table stuck on "Loading...".
    assert "loadExternalScript" in spa_js
    assert "loadedScripts" in spa_js
    assert "element.onload" in spa_js
    assert "hoistStylesheets" in spa_js

    catalog_pages = list((VIEWS_DIR / "catalogs").glob("*.html"))
    assert catalog_pages, "catalog templates missing"
    for page in catalog_pages:
        text = page.read_text()
        if "<script src" not in text:
            continue
        # The pattern the loader has to support: external bundle then init call.
        assert "catalogs.js" in text, page.name


def test_row_click_navigation_goes_through_the_spa():
    spa_js = (VIEWS_DIR / "js" / "spa.js").read_text()
    catalogs_js = (VIEWS_DIR / "js" / "catalogs.js").read_text()
    obs_sessions = (VIEWS_DIR / "obs_sessions.html").read_text()

    # Assigning window.location bypasses the anchor click handler, so those
    # navigations reload the document and drop fullscreen.
    assert "window.pfNavigate" in spa_js
    for source, name in (
        (catalogs_js, "catalogs.js"),
        (obs_sessions, "obs_sessions.html"),
    ):
        assert "pfNavigate" in source, name

    # Clickable rows must not navigate unconditionally.
    assert "() => (window.location = tr.dataset.href)" not in catalogs_js
    assert 'onClick="window.location.href=' not in obs_sessions


def test_polling_pages_guard_their_reschedule_points():
    # These pages reschedule themselves from async callbacks, which run after
    # the epoch has already advanced -- the timer shim alone cannot catch them.
    for name in ["remote.html", "index.html", "livecam.html", "logs.html"]:
        page = (VIEWS_DIR / name).read_text()
        assert "const PAGE_ALIVE = window.pfPageAlive;" in page, name
        assert "PAGE_ALIVE()" in page, name
        # The capture must precede every use, or it reads the wrong page's check.
        assert page.index("const PAGE_ALIVE") < page.index("PAGE_ALIVE()"), name


def test_scrollbars_follow_the_theme():
    style_css = (VIEWS_DIR / "css" / "style.css").read_text()

    # Default scrollbars render light grey and break dark adaptation on the red
    # theme as soon as a pane overflows.
    assert "scrollbar-color: var(--pf-scrollbar-thumb) var(--pf-bg)" in style_css
    assert "scrollbar-width: thin" in style_css
    assert "::-webkit-scrollbar-thumb" in style_css
    assert "::-webkit-scrollbar-track" in style_css
    assert "::-webkit-scrollbar-corner" in style_css
    # Hover must not reuse the text colours; they are far too bright at night.
    assert "var(--pf-scrollbar-thumb-hover)" in style_css
    assert "background: var(--pf-text-muted)" not in style_css

    # Colours must come from the theme variables, not be hard coded.
    scrollbar_block = style_css[style_css.index("scrollbar-width: thin") :]
    scrollbar_block = scrollbar_block[: scrollbar_block.index("main {")]
    assert "#" not in scrollbar_block, "scrollbar colours must use theme variables"


def test_log_viewer_keeps_its_own_console_scrollbars():
    # The log viewer is deliberately a neutral dark console; style.css must not
    # reach into it, same rule as its text colours.
    style_css = (VIEWS_DIR / "css" / "style.css").read_text()
    logs_html = (VIEWS_DIR / "logs.html").read_text()

    assert ".log-container" not in style_css
    assert ".log-container::-webkit-scrollbar" in logs_html


def test_livecam_zoom_keeps_the_whole_frame_in_the_scroll_range():
    livecam_html = (VIEWS_DIR / "livecam.html").read_text()

    shell = _rule_block(livecam_html, ".livecam-preview-shell")
    stage = _rule_block(livecam_html, ".livecam-image-stage")
    placeholder = _rule_block(livecam_html, "#livecamPlaceholder")

    # Center alignment places half of an oversized flex item before the
    # scroll origin, where scrollLeft/scrollTop can never reach it.
    assert "align-items: flex-start" in shell
    assert "justify-content: flex-start" in shell
    assert "overflow: auto" in shell

    # Auto margins preserve the centred appearance until the image overflows;
    # they then collapse to zero so every edge remains reachable.
    assert "margin: auto" in stage
    assert "margin: auto" in placeholder


def test_livecam_has_persistent_solver_preprocess_control_below_stack():
    livecam_html = (VIEWS_DIR / "livecam.html").read_text()

    assert livecam_html.index('id="stackEnabled"') < livecam_html.index(
        'id="solverPreprocessEnabled"'
    )
    assert "solver_preprocess_enabled: controls.solver_preprocess_enabled.checked" in (
        livecam_html
    )
    assert 'id="statusPreprocess"' in livecam_html
    assert "const preprocess = data.preprocess || {};" in livecam_html
    assert (
        "frame.producer || frame.source || settings.input_frame_source" in livecam_html
    )


def _rule_block(css: str, selector: str) -> str:
    """Return the declarations of the first rule whose selector list has this one."""
    match = re.search(rf"^\s*{re.escape(selector)}\s*[,{{]", css, re.MULTILINE)
    assert match, f"no rule for {selector}"
    open_brace = css.index("{", match.start())
    return css[open_brace : css.index("}", open_brace)]


def test_light_materialize_widgets_are_themed_for_both_themes():
    # Materialize ships light defaults for these widgets (select
    # rgba(255,255,255,0.9), dropdown #fff, modal #fafafa, caret near-black).
    # They were overridden under html[data-theme="red"] only, which left the
    # grey theme with white boxes carrying the theme's light text. Every rule
    # below must stay theme-agnostic and variable-driven so both themes work.
    style_css = (VIEWS_DIR / "css" / "style.css").read_text()

    for selector in (
        "select.browser-default",
        "select option",
        ".select-wrapper .caret",
        ".dropdown-content",
        ".sidenav",
        ".sidenav li > a",
    ):
        assert f'html[data-theme="red"] {selector} {{' not in style_css, selector
        block = _rule_block(style_css, selector)
        assert "var(--pf-" in block, selector
        # A hard-coded colour here would pin one theme's palette.
        assert "#" not in block, selector

    # The white select box is the specific defect this guards.
    assert "background-color: var(--pf-input-bg)" in _rule_block(
        style_css, "select.browser-default"
    )
    # Disabled controls must not fall back to Materialize's rgba(0, 0, 0, 0.42),
    # which is black on black here.
    assert "input[type=number]:not(.browser-default):disabled" in style_css


def test_checkbox_outline_colour_never_reaches_the_checked_state():
    # Materialize renders the tick from the *same* ::before as the empty box: it
    # rotates it 40deg and keeps the top/left borders transparent. Setting the
    # `border-color` shorthand without excluding :checked paints those two sides
    # back in and the tick renders as a tilted rectangle.
    style_css = (VIEWS_DIR / "css" / "style.css").read_text()

    outline = '[type="checkbox"]:not(:checked):not(:indeterminate)'
    assert f"{outline} + span:not(.lever)::before" in style_css
    assert '[type="checkbox"] + span:not(.lever)::before' not in style_css

    # The checked state may only tint the two sides that form the tick.
    checked = _rule_block(
        style_css, '[type="checkbox"]:checked + span:not(.lever)::before'
    )
    assert "border-right-color" in checked
    assert "border-bottom-color" in checked
    assert "border-color" not in checked


def test_style_css_cache_buster_is_bumped_when_the_file_changes():
    # base.html pins ?v=N; browsers keep serving the old sheet until it moves.
    base_html = (VIEWS_DIR / "base.html").read_text()

    assert "/css/style.css?v=11" in base_html
