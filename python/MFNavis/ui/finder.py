"""Camera/chart finder with GoTo at the displayed alignment reticle."""

import math

from PiFinder.mf_manual_lens import manual_focal_from_state
from PiFinder.optics import OpticalTrainResolver
from PiFinder.ui.base import GuideKeyMixin
from PiFinder.ui.camera_guidance import (
    camera_fov,
    draw_reticle,
    render_camera_view,
)
from PiFinder.ui.chart import UIChart
from PiFinder.ui.marking_menus import MarkingMenu, MarkingMenuOption


class UIFinder(GuideKeyMixin, UIChart):
    __title__ = "Finder"
    __help_name__ = "finder"
    allow_object_details = False
    _display_mode_list = ["camera", "chart"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.camera_zoom_level = 0
        self._camera_optics = OpticalTrainResolver()
        self._displayed_center = None
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(label=_("Settings"), menu_jump="chart_settings"),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(
                label=_("ALIGN"),
                callback=MarkingMenu(
                    up=MarkingMenuOption(),
                    left=MarkingMenuOption(label=_("CANCEL"), callback=self.mm_cancel),
                    down=MarkingMenuOption(),
                    right=MarkingMenuOption(label=_("ALIGN"), callback=self.mm_align),
                ),
            ),
        )

    @staticmethod
    def _reticle_radec(solution):
        # Both the camera's saved target_pixel and the chart centre represent
        # aligned pointing, not the camera sensor centre or a nearby object.
        if solution is None or not solution.has_pointing():
            return None
        aligned = solution.pointing.aligned.estimate
        if aligned is None:
            return None
        ra, dec = aligned.RA, aligned.Dec
        if (
            ra is None
            or dec is None
            or not math.isfinite(ra)
            or not math.isfinite(dec)
            or not 0 <= ra < 360
            or not -90 <= dec <= 90
        ):
            return None
        return ra, dec

    def active(self):
        super().active()
        self._displayed_center = None

    def update(self, force=False):
        if self.display_mode == "chart":
            result = super().update(force=force)
            self._displayed_center = self._chart_center
            return result

        self.clear_screen()
        solution = self.shared_state.solution()
        target = self.shared_state.target_pixel()
        center, side = render_camera_view(
            self.screen,
            self.camera_image,
            self.colors.get(255),
            self.camera_zoom_level,
            target,
        )
        self._displayed_center = None
        if center is not None:
            optics = self._camera_optics.resolve(
                self.shared_state.camera_type(),
                self.shared_state.camera_lens(),
                manual_focal_from_state(self.shared_state),
            )
            fov = camera_fov(solution, optics.fov_degrees)
            draw_reticle(
                self.draw,
                center,
                side * 2**self.camera_zoom_level / fov,
                self.colors.get(255),
                outline=self.colors.get(0),
                diameters=(2, 0.5) if self.camera_zoom_level == 2 else (4, 2, 0.5),
            )
            # Use the same plate-anchored/absolute-IMU pointing as the chart,
            # including before the first successful plate solve.
            self._displayed_center = self._reticle_radec(self._chart_solution())
        return self.screen_update(title_bar=False, button_hints=False)

    def key_square(self):
        self.cycle_display_mode()
        self._displayed_center = None
        self.update(force=True)

    def key_plus(self):
        if self.display_mode == "chart":
            return super().key_plus()
        self.camera_zoom_level = min(2, self.camera_zoom_level + 1)
        self.update()

    def key_minus(self):
        if self.display_mode == "chart":
            return super().key_minus()
        self.camera_zoom_level = max(0, self.camera_zoom_level - 1)
        self.update()

    def _mount_command(self, number, target=None, target_object=None):
        if number == 5:
            available = self._chart_solution() is not None
            if self._displayed_center is None or not available:
                self.message(_("No solve"), 1)
                return False
            # Freeze exactly the displayed centre, even if a newer estimate
            # arrived between drawing this frame and receiving the key.
            target = self._displayed_center
            target_object = None
        return super()._mount_command(
            number, target=target, target_object=target_object
        )

    def mm_align(self, _marking_menu, _menu_item):
        self._mount_command(5)
        return True

    def mm_cancel(self, _marking_menu, _menu_item):
        return True

    def serialize_ui_state(self):
        state = super().serialize_ui_state() if self.display_mode == "chart" else {}
        state.update(
            display_mode=self.display_mode,
            camera_zoom=2**self.camera_zoom_level,
            goto_center=self._displayed_center,
        )
        return state
