import builtins
from types import SimpleNamespace

# The app installs gettext's ``_`` as a builtin at startup; provide a passthrough
# here so mount-command messages resolve during unit tests.
if not hasattr(builtins, "_"):
    builtins._ = lambda text: text

from PiFinder.ui.base import GuideKeyMixin, UIModule
from PiFinder.ui.preview import UIPreview


class DummyQueue:
    def __init__(self):
        self.commands = []

    def put(self, command):
        self.commands.append(command)


class DummyGuideScreen(GuideKeyMixin, UIModule):
    pass


def _screen(mount_control=True):
    screen = DummyGuideScreen.__new__(DummyGuideScreen)
    values = {"mount_control": mount_control, "indi_goto_method": "mfnavis"}
    screen.config_object = SimpleNamespace(
        get_option=lambda name, default=None: values.get(name, default),
        set_option=lambda name, value: values.__setitem__(name, value),
    )
    screen.command_queues = {
        "mountcontrol": DummyQueue(),
        "ui_queue": DummyQueue(),
        "goto_guide": DummyQueue(),
    }
    screen.message = lambda *args, **kwargs: None
    screen._test_config_values = values
    return screen


def test_guide_mixin_cardinal_key_hold_to_move():
    # Cardinal number keys move the mount for as long as they are held:
    # press starts motion (with lease), release stops it.
    screen = _screen()

    screen.key_number_press(8)
    screen.key_number_release(8)

    assert screen.command_queues["mountcontrol"].commands == [
        {"type": "manual_movement", "direction": "north", "lease_seconds": 2.5},
        {"type": "stop_movement"},
    ]


def test_guide_mixin_discrete_commands_and_goto_type_toggle():
    # 0 = Stop is discrete, 1 cycles GoTo Type, and 9/3 adjust slew rate.
    screen = _screen()
    messages = []
    screen.message = lambda *args, **kwargs: messages.append(args)

    screen.key_number_press(0)
    screen.key_number_press(1)
    screen.key_number_press(3)
    screen.key_number_press(9)

    assert screen.command_queues["mountcontrol"].commands == [
        {"type": "stop_movement", "stop_tracking": True},
        {"type": "reduce_slew_rate", "notify_ui": True},
        {"type": "increase_slew_rate", "notify_ui": True},
    ]
    assert screen._test_config_values["indi_goto_method"] == "mfnavis"
    assert screen._test_config_values["session.indi_goto_method"] == "off"
    assert screen.command_queues["ui_queue"].commands == []
    assert screen.command_queues["goto_guide"].commands == [
        {"type": "stop_movement", "stop_tracking": True},
        {"type": "set_goto_method", "goto_method": "off"},
    ]
    assert messages[-1] == ("GoTo Type\nOff", 1)


def test_guide_mixin_goto_type_cycles_all_choices_for_plain_number_input():
    # A local/external keyboard and the Web Remote submit normal number events
    # (key_number), unlike the physical keypad's press/release events above.
    screen = _screen()

    screen.key_number(1)
    assert screen._test_config_values["session.indi_goto_method"] == "off"
    screen.key_number(1)
    assert screen._test_config_values["session.indi_goto_method"] == "indi_mount"
    screen.key_number(1)
    assert screen._test_config_values["session.indi_goto_method"] == "mfnavis"


def test_zero_stop_cancels_held_direction_keepalive():
    screen = _screen()
    screen.key_number_press(8)
    screen.key_number_press(0)
    before = list(screen.command_queues["mountcontrol"].commands)
    screen._guide_send_motion_keepalive()
    assert screen._guide_active_motion_direction is None
    assert screen.command_queues["mountcontrol"].commands == before
    assert before[-1] == {"type": "stop_movement", "stop_tracking": True}


def test_indi_indicator_matches_goto_type_and_connection_state():
    screen = _screen()
    screen._indi_indicator_state = lambda: "ok"

    assert screen._indi_indicator_spec() == ("M", "ok")

    screen._test_config_values["session.indi_goto_method"] = "indi_mount"
    screen._indi_indicator_state = lambda: "problem"
    assert screen._indi_indicator_spec() == ("I", "problem")

    screen._test_config_values["session.indi_goto_method"] = "off"
    assert screen._indi_indicator_spec() == (None, None)

    # Clearing a runtime override returns immediately to the saved setting.
    screen._test_config_values["session.indi_goto_method"] = None
    screen._test_config_values["indi_goto_method"] = "indi_mount"
    assert screen._indi_indicator_spec() == ("I", "problem")


def test_guide_mixin_text_keys_match_guide_layout():
    screen = _screen()

    screen.key_text_press("q")
    screen.key_text_release("q")
    screen.key_text("e")
    screen.key_text("s")

    assert screen.command_queues["mountcontrol"].commands == [
        {
            "type": "manual_movement",
            "direction": "northwest",
            "lease_seconds": 2.5,
        },
        {"type": "stop_movement"},
        {
            "type": "manual_movement",
            "direction": "northeast",
            "lease_seconds": 2.5,
        },
        {"type": "stop_movement"},
    ]


def test_guide_mixin_press_keeps_motion_alive_until_release():
    screen = _screen()

    screen.key_text_press("q")
    screen._guide_next_motion_keepalive_at = 0.0
    screen._guide_send_motion_keepalive()
    screen.key_text_release("q")
    screen._guide_next_motion_keepalive_at = 0.0
    screen._guide_send_motion_keepalive()

    assert screen.command_queues["mountcontrol"].commands == [
        {
            "type": "manual_movement",
            "direction": "northwest",
            "lease_seconds": 2.5,
        },
        {
            "type": "manual_movement_keepalive",
            "direction": "northwest",
            "lease_seconds": 2.5,
        },
        {"type": "stop_movement"},
    ]


def test_guide_mixin_long_hold_restarts_motion_before_controller_limit():
    screen = _screen()

    screen.key_text_press("q")
    screen._guide_next_motion_restart_at = -1.0
    screen._guide_send_motion_keepalive()

    assert screen.command_queues["mountcontrol"].commands == [
        {
            "type": "manual_movement",
            "direction": "northwest",
            "lease_seconds": 2.5,
        },
        {
            "type": "manual_movement",
            "direction": "northwest",
            "lease_seconds": 2.5,
        },
    ]


def test_guide_mixin_plain_text_event_does_not_keep_motion_alive():
    screen = _screen()

    screen.key_text("q")
    screen._guide_next_motion_keepalive_at = 0.0
    screen._guide_send_motion_keepalive()

    assert screen.command_queues["mountcontrol"].commands == [
        {
            "type": "manual_movement",
            "direction": "northwest",
            "lease_seconds": 2.5,
        },
    ]


def test_guide_mixin_9_3_adjust_slew_rate_and_plus_minus_do_not():
    # Slew rate lives on 9 (up) / 3 (down); +/- keep their per-screen
    # content meaning and never touch the mount.
    screen = _screen()

    screen.key_number(9)
    screen.key_number(3)
    screen.key_plus()
    screen.key_minus()

    assert screen.command_queues["mountcontrol"].commands == [
        {"type": "increase_slew_rate", "notify_ui": True},
        {"type": "reduce_slew_rate", "notify_ui": True},
    ]


def test_guide_mixin_is_noop_when_mount_control_is_off():
    screen = _screen(mount_control=False)

    screen.key_number_press(8)
    screen.key_number_press(9)
    screen.key_text_press("q")

    assert screen.command_queues["mountcontrol"].commands == []


def test_focus_preview_uses_guide_keys_without_overriding_zoom_controls():
    assert issubclass(UIPreview, GuideKeyMixin)
    # The mixin no longer touches +/- (slew rate moved to 9/3), so preview's
    # zoom stays on its own key_plus/key_minus overrides.
    assert not hasattr(GuideKeyMixin, "key_plus")
    assert UIPreview.key_plus is not UIModule.key_plus
    assert UIPreview.key_minus is not UIModule.key_minus
