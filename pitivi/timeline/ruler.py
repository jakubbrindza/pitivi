# Pitivi video editor
#
#       pitivi/timeline/ruler.py
#
# Copyright (c) 2006, Edward Hervey <bilboed@bilboed.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.

"""
Widget for the complex view ruler
"""
import cairo

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Gst
from gi.repository import GLib
from gi.repository import GObject

from gettext import gettext as _

from pitivi.utils.pipeline import Seeker
from pitivi.utils.timeline import Zoomable
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import time_to_string, beautify_length

# Color #393f3f stolen from the dark variant of Adwaita.
# There's *no way* to get the GTK3 theme's bg color there (it's always black)
RULER_BACKGROUND_COLOR = (57, 63, 63)


def setCairoColor(context, color):
    if type(color) is Gdk.RGBA:
        cairo_color = (float(color.red), float(color.green), float(color.blue))
    elif type(color) is tuple:
        # Cairo's set_source_rgb function expects values from 0.0 to 1.0
        cairo_color = map(lambda x: max(0, min(1, x / 255.0)), color)
    else:
        raise Exception("Unexpected color parameter: %s, %s" % (type(color), color))
    context.set_source_rgb(*cairo_color)


class ScaleRuler(Gtk.DrawingArea, Zoomable, Loggable):

    __gsignals__ = {
        "button-press-event": "override",
        "button-release-event": "override",
        "motion-notify-event": "override",
        "scroll-event": "override",
        "seek": (GObject.SignalFlags.RUN_LAST, None,
                [GObject.TYPE_UINT64])
    }

    border = 0
    min_tick_spacing = 3
    scale = [0, 0, 0, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 3600]
    subdivide = ((1, 1.0), (2, 0.5), (10, .25))

    def __init__(self, instance, hadj):
        Gtk.DrawingArea.__init__(self)
        Zoomable.__init__(self)
        Loggable.__init__(self)
        self.log("Creating new ScaleRuler")

        # Allows stealing focus from other GTK widgets, prevent accidents:
        self.props.can_focus = True
        self.connect("focus-in-event", self._focusInCb)
        self.connect("focus-out-event", self._focusOutCb)

        self.app = instance
        self._seeker = Seeker()
        self.hadj = hadj
        hadj.connect("value-changed", self._hadjValueChangedCb)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.SCROLL_MASK)

        self.pixbuf = None

        # all values are in pixels
        self.pixbuf_offset = 0
        self.pixbuf_offset_painted = 0
        # This is the number of width we allocate for the pixbuf
        self.pixbuf_multiples = 4

        self.position = 0  # In nanoseconds
        self.pressed = False
        self.min_frame_spacing = 5.0
        self.frame_height = 5.0
        self.frame_rate = Gst.Fraction(1 / 1)
        self.ns_per_frame = float(1 / self.frame_rate) * Gst.SECOND
        self.connect('draw', self.drawCb)
        self.connect('configure-event', self.configureEventCb)
        self.callback_id = None
        self.callback_id_scroll = None
        self.set_size_request(0, 25)

    def _focusInCb(self, unused_widget, unused_arg):
        self.log("Ruler has grabbed focus")
        self.app.gui.timeline_ui.setActionsSensitivity(True)

    def _focusOutCb(self, unused_widget, unused_arg):
        self.log("Ruler has lost focus")
        self.app.gui.timeline_ui.setActionsSensitivity(False)

    def _hadjValueChangedCb(self, hadj):
        self.pixbuf_offset = self.hadj.get_value()
        if self.callback_id_scroll is not None:
            GLib.source_remove(self.callback_id_scroll)
        self.callback_id_scroll = GLib.timeout_add(100, self._maybeUpdate)

## Zoomable interface override

    def _maybeUpdate(self):
        self.queue_draw()
        self.callback_id = None
        self.callback_id_scroll = None
        return False

    def zoomChanged(self):
        if self.callback_id is not None:
            GLib.source_remove(self.callback_id)
        self.callback_id = GLib.timeout_add(100, self._maybeUpdate)

## timeline position changed method

    def timelinePositionChanged(self, value, unused_frame=None):
        self.position = value
        self.queue_draw()

## Gtk.Widget overrides
    def configureEventCb(self, widget, event, data=None):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        self.debug("Configuring, height %d, width %d", width, height)

        # Destroy previous buffer
        if self.pixbuf is not None:
            self.pixbuf.finish()
            self.pixbuf = None

        # Create a new buffer
        self.pixbuf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)

        return False

    def drawCb(self, widget, context):
        if self.pixbuf is None:
            self.info('No buffer to paint')
            return False

        pixbuf = self.pixbuf

        # Draw on a temporary context and then copy everything.
        drawing_context = cairo.Context(pixbuf)
        self.drawBackground(drawing_context)
        self.drawRuler(drawing_context)
        self.drawPosition(drawing_context)
        pixbuf.flush()

        context.set_source_surface(self.pixbuf, 0.0, 0.0)
        context.paint()

        return False

    def do_button_press_event(self, event):
        self.debug("button pressed at x:%d", event.x)
        self.pressed = True
        position = self.pixelToNs(event.x + self.pixbuf_offset)
        self._seeker.seek(position, on_idle=True)
        return True

    def do_button_release_event(self, event):
        self.debug("button released at x:%d", event.x)
        self.grab_focus()  # Prevent other widgets from being confused
        self.pressed = False
        return False

    def do_motion_notify_event(self, event):
        position = self.pixelToNs(event.x + self.pixbuf_offset)
        if self.pressed:
            self.debug("motion at event.x %d", event.x)
            self._seeker.seek(position, on_idle=True)

        human_time = beautify_length(position)
        cur_frame = int(position / self.ns_per_frame) + 1
        self.set_tooltip_text(human_time + "\n" + _("Frame #%d" % cur_frame))
        return False

    def do_scroll_event(self, event):
        if event.scroll.state & Gdk.ModifierType.CONTROL_MASK:
            # Control + scroll = zoom
            if event.scroll.direction == Gdk.ScrollDirection.UP:
                Zoomable.zoomIn()
                self.app.gui.timeline_ui.zoomed_fitted = False
            elif event.scroll.direction == Gdk.ScrollDirection.DOWN:
                Zoomable.zoomOut()
                self.app.gui.timeline_ui.zoomed_fitted = False
        else:
            # No modifier key held down, just scroll
            if (event.scroll.direction == Gdk.ScrollDirection.UP
            or event.scroll.direction == Gdk.ScrollDirection.LEFT):
                self.app.gui.timeline_ui.scroll_left()
            elif (event.scroll.direction == Gdk.ScrollDirection.DOWN
            or event.scroll.direction == Gdk.ScrollDirection.RIGHT):
                self.app.gui.timeline_ui.scroll_right()

    def setProjectFrameRate(self, rate):
        """
        Set the lowest scale based on project framerate
        """
        self.frame_rate = rate
        self.ns_per_frame = float(1 / self.frame_rate) * Gst.SECOND
        self.scale[0] = float(2 / rate)
        self.scale[1] = float(5 / rate)
        self.scale[2] = float(10 / rate)

## Drawing methods

    def drawBackground(self, context):
        style = self.get_style_context()
        setCairoColor(context, RULER_BACKGROUND_COLOR)
        width = context.get_target().get_width()
        height = context.get_target().get_height()
        context.rectangle(0, 0, width, height)
        context.fill()
        offset = int(self.nsToPixel(Gst.CLOCK_TIME_NONE)) - self.pixbuf_offset
        if offset > 0:
            setCairoColor(context, style.get_background_color(Gtk.StateFlags.ACTIVE))
            context.rectangle(0, 0, int(offset), context.get_target().get_height())
            context.fill()

    def drawRuler(self, context):
        # FIXME use system defaults
        context.set_font_face(cairo.ToyFontFace("Cantarell"))
        context.set_font_size(13)
        textwidth = context.text_extents(time_to_string(0))[2]

        for scale in self.scale:
            spacing = Zoomable.zoomratio * scale
            if spacing >= textwidth * 1.5:
                break

        offset = self.pixbuf_offset % spacing
        self.drawFrameBoundaries(context)
        self.drawTicks(context, offset, spacing, scale)
        self.drawTimes(context, offset, spacing, scale)

    def drawTick(self, context, paintpos, height):
        # We need to use 0.5 pixel offsets to get a sharp 1 px line in cairo
        paintpos = int(paintpos - 0.5) + 0.5
        height = int(context.get_target().get_height() * (1 - height))
        style = self.get_style_context()
        setCairoColor(context, style.get_color(Gtk.StateFlags.NORMAL))
        context.set_line_width(1)
        context.move_to(paintpos, height)
        context.line_to(paintpos, context.get_target().get_height())
        context.close_path()
        context.stroke()

    def drawTicks(self, context, offset, spacing, scale):
        for subdivide, height in self.subdivide:
            spc = spacing / float(subdivide)
            if spc < self.min_tick_spacing:
                break
            paintpos = -spacing + 0.5
            paintpos += spacing - offset
            while paintpos < context.get_target().get_width():
                self.drawTick(context, paintpos, height)
                paintpos += spc

    def drawTimes(self, context, offset, spacing, scale):
        # figure out what the optimal offset is
        interval = long(Gst.SECOND * scale)
        seconds = self.pixelToNs(self.pixbuf_offset)
        paintpos = float(self.border) + 2
        if offset > 0:
            seconds = seconds - (seconds % interval) + interval
            paintpos += spacing - offset

        state = Gtk.StateFlags.NORMAL
        style = self.get_style_context()
        setCairoColor(context, style.get_color(state))
        y_bearing = context.text_extents("0")[1]
        while paintpos < context.get_target().get_width():
            timevalue = time_to_string(long(seconds))
            context.move_to(int(paintpos), 1 - y_bearing)
            context.show_text(timevalue)
            paintpos += spacing
            seconds += interval

    def drawFrameBoundaries(self, context):
        """
        Draw the alternating rectangles that represent the project frames at
        high zoom levels. These are based on the framerate set in the project
        settings, not the actual frames on a video codec level.
        """
        frame_width = self.nsToPixel(self.ns_per_frame)
        if not frame_width >= self.min_frame_spacing:
            return

        offset = self.pixbuf_offset % frame_width
        height = context.get_target().get_height()
        y = int(height - self.frame_height)
        # INSENSITIVE is a dark shade of gray, but lacks contrast
        # SELECTED will be bright blue and more visible to represent frames
        style = self.get_style_context()
        states = [style.get_background_color(Gtk.StateFlags.ACTIVE),
                  style.get_background_color(Gtk.StateFlags.SELECTED)]

        frame_num = int(self.pixelToNs(self.pixbuf_offset) * float(self.frame_rate) / Gst.SECOND)
        paintpos = self.pixbuf_offset - offset
        max_pos = context.get_target().get_width() + self.pixbuf_offset
        while paintpos < max_pos:
            paintpos = self.nsToPixel(1 / float(self.frame_rate) * Gst.SECOND * frame_num)
            setCairoColor(context, states[(frame_num + 1) % 2])
            context.rectangle(0.5 + paintpos - self.pixbuf_offset, y, frame_width, height)
            context.fill()
            frame_num += 1

    def drawPosition(self, context):
        # a simple RED line will do for now
        xpos = self.nsToPixel(self.position) + self.border - self.pixbuf_offset
        context.save()
        context.set_line_width(1.5)
        context.set_source_rgb(1.0, 0, 0)
        context.move_to(xpos, 0)
        context.line_to(xpos, context.get_target().get_height())
        context.stroke()
        context.restore()
