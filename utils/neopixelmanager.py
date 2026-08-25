"""MicroPython NeoPixel driver extension with a subset-based API: split a
strip into independently-addressable pixel groups and apply animated
Patterns to each group.

NeoPixelManager methods:
- add_subset(length=None) -> register a contiguous block of pixels,
  returns an id. length=None claims all pixels not yet claimed.
- set_pattern(pattern, id=None) -> apply a Pattern to a subset (id=None
  targets pixels not claimed by any subset). Replaces any pattern
  already on that id.
- clear_patterns() -> remove all patterns; pixels left as-is.
- clear() -> clear_patterns() + blank every pixel; subsets stay valid.
- reset() -> clear() + forget the subset structure entirely.
- update() -> recompute animated patterns' colours (does not write()).
- poll() -> update() then write().

Pattern classes:
- Pattern -> base class; implement get_pixel_color(pixel_index,
  num_pixels, elapsed_ms, bpp).
- Solid(color) -> static colour.
- Off() -> blanks the subset (all channels zero).
- Pulse(color1, color2, period_ms, phase_deg=0) -> sine-wave breathing
  pulse between two colours.
- Flash(color1, color2=(0, 0, 0), period_ms=200, duty=0.5, repeats=None,
  phase_deg=0) -> square-wave on/off flash.
- Wave(color1, color2, period_ms, phase_deg=0, spread=None) -> a
  Gaussian "comet" that travels along the subset in a loop.

Colour tuples are plain (r, g, b) or (r, g, b, w) tuples. Mismatched
lengths (e.g. RGB vs RGBW) are padded with zeros or truncated
automatically -- see `_normalize_color()`.

Type hints use only builtin types since MicroPython has no `typing`
module and doesn't support subscripting builtin generics.

Example, NeoPixels on GPIO 4:

    from machine import Pin
    from neopixelmanager import NeoPixelManager, Solid, Off, Pulse, Wave
    import time

    np = NeoPixelManager(Pin(4), 30)
    np.reset()

    id_a = np.add_subset(8)   # pixels 0-7
    id_b = np.add_subset(16)  # pixels 8-23

    np.set_pattern(Solid((0, 0, 255)), id=id_a)
    np.set_pattern(
        Wave((255, 0, 0), (0, 0, 0), period_ms=2000, spread=2.5), id=id_b
    )
    np.set_pattern(Solid((0, 255, 0)), id=None)  # pixels 24-29

    np.write()

    while True:
        np.poll()
        time.sleep_ms(20)

    np.set_pattern(Off(), id=id_b)
    np.clear()  # subsets 0 and 1 still valid
    np.reset()  # subsets forgotten too
"""

import time
import math
import neopixel
from machine import Pin


# ----------------------------------------------------------------------
# Colour helpers
# ----------------------------------------------------------------------
def _normalize_color(color: tuple, length: int) -> tuple:
    """Pad or truncate a colour tuple to exactly `length` channels.

    Missing trailing channels are filled with 0; extra channels are
    dropped. Lets callers freely mix RGB/RGBW tuples with each other or
    with a strip of a different `bpp`.
    """
    n: int = len(color)
    if n == length:
        return color
    if n > length:
        return tuple(color[:length])
    return tuple(color) + (0,) * (length - n)


def _interp(color1: tuple, color2: tuple, t: float, length: int) -> tuple:
    """Linearly interpolate between two colours at fraction t in [0, 1].

    Both colours are normalised to `length` channels first, so color1 and
    color2 need not match each other's length or `length`.
    """
    c1: tuple = _normalize_color(color1, length)
    c2: tuple = _normalize_color(color2, length)
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(length))


_MIN_SPREAD: float = 0.05  # smallest allowed Wave `spread`, in pixels


# ----------------------------------------------------------------------
# Pattern classes
# ----------------------------------------------------------------------
class Pattern:
    """Base class for a colour pattern applied to a subset of pixels.

    Subclass and implement `get_pixel_color()`. Override `is_animated()`
    to return True if the pattern must be recomputed on every `update()`
    (e.g. anything time-based); static patterns are only rendered once,
    when `set_pattern()` is called.
    """

    def is_animated(self) -> bool:
        """Return True if this pattern must be recomputed every update()."""
        return False

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        """Return the colour for one pixel in the subset.

        Args:
            pixel_index (int): 0-indexed position within the subset (not
                the strip). Patterns that colour every pixel the same can
                ignore this.
            num_pixels (int): total number of pixels in the subset.
            elapsed_ms (int): milliseconds since set_pattern() was called.
            bpp (int): 3 for RGB, 4 for RGBW; the returned tuple must have
                this many channels (see `_normalize_color()`).
        """
        raise NotImplementedError


class Solid(Pattern):
    """A static, unchanging colour."""

    def __init__(self, color: tuple) -> None:
        """
        Args:
            color (tuple): colour tuple, e.g. (r, g, b).
        """
        self.color: tuple = tuple(color)

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        return _normalize_color(self.color, bpp)


class Off(Pattern):
    """Blanks the subset (all channels zero).

    Also the way to stop/forget whatever pattern was previously running
    on a subset -- there is no separate "remove" call.
    """

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        return (0,) * bpp


class Pulse(Pattern):
    """A sine-wave 'breathing' pulse between two colours."""

    def __init__(
        self,
        color1: tuple,
        color2: tuple,
        period_ms: int,
        phase_deg: float = 0,
    ) -> None:
        """
        Args:
            color1 (tuple): colour at the trough (t = 0).
            color2 (tuple): colour at the peak (t = 1).
            period_ms (int): full color1 -> color2 -> color1 cycle length.
            phase_deg (float, optional): phase offset in degrees, so
                multiple pulses can run out of sync.
        """
        self.color1: tuple = tuple(color1)
        self.color2: tuple = tuple(color2)
        self.period_ms: int = period_ms
        self.phase: float = math.radians(phase_deg)

    def is_animated(self) -> bool:
        return True

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        theta: float = (2 * math.pi * elapsed_ms / self.period_ms) + self.phase
        t: float = (math.sin(theta) + 1) / 2  # normalised to [0, 1]
        return _interp(self.color1, self.color2, t, bpp)


class Flash(Pattern):
    """A hard on/off (square-wave) flash between two colours."""

    def __init__(
        self,
        color1: tuple,
        color2: tuple = (0, 0, 0),
        period_ms: int = 200,
        duty: float = 0.5,
        repeats: int = None,
        phase_deg: float = 0,
    ) -> None:
        """
        Args:
            color1 (tuple): colour during the "on" phase.
            color2 (tuple, optional): colour during the "off" phase.
                Defaults to black.
            period_ms (int, optional): full on+off cycle length.
            duty (float, optional): fraction of `period_ms` spent on
                `color1`, in (0, 1). Defaults to 0.5.
            repeats (int, optional): number of on/off cycles to run.
                None (default) flashes indefinitely; once exhausted, the
                pattern holds on `color2` (call set_pattern() again to
                change it).
            phase_deg (float, optional): phase offset in degrees, so
                multiple subsets can flash out of sync.
        """
        self.color1: tuple = tuple(color1)
        self.color2: tuple = tuple(color2)
        self.period_ms: int = period_ms
        self.duty: float = duty
        self.repeats: int = repeats
        self.phase_ms: float = (phase_deg / 360.0) * period_ms

    def is_animated(self) -> bool:
        return True

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        if self.repeats is not None:
            total_ms: int = self.repeats * self.period_ms
            if elapsed_ms >= total_ms:
                return _normalize_color(self.color2, bpp)

        t: float = (elapsed_ms + self.phase_ms) % self.period_ms
        on_time: float = self.duty * self.period_ms
        chosen: tuple = self.color1 if t < on_time else self.color2
        return _normalize_color(chosen, bpp)


class Wave(Pattern):
    """A Gaussian "comet" that travels along the subset in a loop.

    Same constructor as Pulse, plus `spread`. Only one pixel -- the
    current peak -- is fully at color2; pixels either side fade towards
    color1 following a Gaussian curve, and the peak position advances
    continuously along the subset, wrapping back to the start once it
    reaches the end.
    """

    def __init__(
        self,
        color1: tuple,
        color2: tuple,
        period_ms: int,
        phase_deg: float = 0,
        spread: float = None,
    ) -> None:
        """
        Args:
            color1 (tuple): colour pixels fade towards, away from the peak.
            color2 (tuple): colour of the current peak pixel.
            period_ms (int): time for the peak to complete one full pass
                along the subset and wrap back to the start.
            phase_deg (float, optional): phase offset in degrees, so
                multiple subsets can run the wave out of sync.
            spread (float, optional): how many pixels either side of the
                peak the glow extends over (the Gaussian sigma, in
                pixels). Defaults to None, auto-scaling to roughly a
                sixth of the subset's pixel count (min 0.6px). Values
                <= 0 are clamped to a small positive floor (`_MIN_SPREAD`)
                rather than raising an error or dividing by zero.
        """
        self.color1: tuple = tuple(color1)
        self.color2: tuple = tuple(color2)
        self.period_ms: int = period_ms
        self.phase_ms: float = (phase_deg / 360.0) * period_ms
        self.spread: float = spread

    def is_animated(self) -> bool:
        return True

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        if num_pixels <= 0:
            return _normalize_color(self.color1, bpp)

        t: float = ((elapsed_ms + self.phase_ms) / self.period_ms) % 1.0
        peak: float = t * num_pixels

        # Continuous distance to the peak -- gives neighbouring pixels a
        # smooth fade in/out as the wave approaches and departs.
        raw_dist: float = abs(pixel_index - peak)
        distance: float = min(raw_dist, num_pixels - raw_dist)  # circular

        # Force the single nearest pixel to full brightness for its whole
        # turn (instead of only for an instant), so it holds steady
        # rather than flickering; every other pixel still uses the smooth
        # continuous distance above.
        nearest_index: int = int(peak + 0.5) % num_pixels
        if pixel_index == nearest_index:
            distance = 0.0

        if self.spread is not None:
            sigma: float = max(self.spread, _MIN_SPREAD)  # avoid div-by-0
        else:
            sigma = max(0.6, num_pixels / 6.0)
        weight: float = math.exp(-(distance * distance) / (2 * sigma * sigma))

        return _interp(self.color1, self.color2, weight, bpp)


# ----------------------------------------------------------------------
# NeoPixelManager
# ----------------------------------------------------------------------
class NeoPixelManager(neopixel.NeoPixel):
    """NeoPixel strip with named pixel subsets and per-subset Patterns."""

    def __init__(self, pin_id: int, n: int, bpp: int = 3, timing: int = 1) -> None:
        """
        Args:
            pin_id (int): machine pin ID.
            n (int): number of LEDs in the array.
            bpp (int, optional): 3 for RGB LEDs, 4 for RGBW LEDs.
            timing (int, optional): 0 for 400KHz, 1 for 800kHz (most LEDs).
        """
        super().__init__(Pin(pin_id), n, bpp, timing)
        self._subsets: dict = {}  # id -> (start, length)
        self._next_subset_id: int = 0
        self._cursor: int = 0  # first pixel not yet claimed by a subset
        self._patterns: dict = {}  # id (or None) -> pattern state dict

    # ------------------------------------------------------------------
    # Subset management
    # ------------------------------------------------------------------
    def add_subset(self, length: int = None) -> int:
        """Register a contiguous block of pixels for later addressing.

        The block starts wherever the previous subset left off.

        Args:
            length (int, optional): number of pixels to claim; None
                claims every pixel not yet owned by an earlier subset.

        Returns:
            int: auto-generated id (0, 1, 2, ...) for use with
            set_pattern().
        """
        n: int = len(self)
        start: int = self._cursor
        if length is None:
            length = max(0, n - start)

        subset_id: int = self._next_subset_id
        self._next_subset_id += 1
        self._subsets[subset_id] = (start, length)
        self._cursor = min(n, start + length)
        return subset_id

    def _resolve_range(self, subset_id: int) -> tuple:
        """Translate a subset id (or None) into a (start, length) tuple.

        None maps to whatever pixels remain unclaimed by any subset.
        """
        if subset_id is None:
            n: int = len(self)
            start: int = self._cursor
            length: int = max(0, n - start)
            return start, length

        return self._subsets[subset_id]

    # ------------------------------------------------------------------
    # Basic pixel operations
    # ------------------------------------------------------------------
    def clear(self) -> None:
        """Stop all patterns and blank every pixel; subsets stay valid.

        Call write() afterwards to push the change to the physical strip.
        """
        self.clear_patterns()
        off: tuple = (0,) * self.bpp
        n: int = len(self)
        for i in range(n):
            self[i] = off

    def reset(self) -> None:
        """Like clear(), but also forgets the subset structure entirely.

        add_subset() must be called again afterwards to re-establish ids.
        Call write() afterwards to push the change to the physical strip.
        """
        self.clear()
        self._subsets = {}
        self._next_subset_id = 0
        self._cursor = 0

    # ------------------------------------------------------------------
    # Pattern support
    # ------------------------------------------------------------------
    def set_pattern(self, pattern: Pattern, id: int = None) -> int:
        """Attach a Pattern to a subset, replacing any pattern already there.

        Args:
            pattern (Pattern): a Solid, Off, Pulse, Flash, Wave (or custom
                Pattern subclass) instance. To stop a subset's pattern,
                call this again with Off().
            id (int, optional): id from add_subset(); None targets pixels
                not yet claimed by any subset.

        Returns:
            int: the id this pattern is attached to (echoes `id`).
        """
        start, length = self._resolve_range(id)

        self._patterns[id] = {
            "pattern": pattern,
            "start": start,
            "length": length,
            "t0": time.ticks_ms(),
        }

        self._render(self._patterns[id], elapsed_ms=0)
        return id

    def clear_patterns(self) -> None:
        """Remove all registered patterns (pixels are left as-is)."""
        self._patterns.clear()

    def _render(self, entry: dict, elapsed_ms: int) -> None:
        """Write a pattern entry's colours into the pixel buffer."""
        pattern: Pattern = entry["pattern"]
        n: int = len(self)
        first: int = max(0, entry["start"])
        last: int = min(n, entry["start"] + entry["length"])
        length: int = last - first

        for offset, i in enumerate(range(first, last)):
            self[i] = pattern.get_pixel_color(offset, length, elapsed_ms, self.bpp)

    def update(self) -> None:
        """Recompute every animated pattern's colours from elapsed time.

        Static patterns (Solid, Off) were already rendered once by
        set_pattern(), so they're skipped here. Does NOT call write() --
        use poll() for that, or call write() yourself afterwards.
        """
        now: int = time.ticks_ms()

        for entry in self._patterns.values():
            pattern: Pattern = entry["pattern"]
            if not pattern.is_animated():
                continue
            elapsed: int = time.ticks_diff(now, entry["t0"])
            self._render(entry, elapsed)

    def poll(self) -> None:
        """Convenience helper: update() all patterns then push to the strip."""
        self.update()
        self.write()
