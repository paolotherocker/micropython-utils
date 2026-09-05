"""MicroPython NeoPixel driver extension with a subset-based API: split a
strip into independently-addressable pixel groups and apply animated
Patterns to each group.

Colour tuples are plain (r, g, b) or (r, g, b, w) tuples; mismatched
lengths are padded or truncated automatically. Type hints use only
builtin types since MicroPython has no `typing` module.

See ../examples/neopixelmanager/main.py for usage.
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

    Args:
        color (tuple): source colour tuple.
        length (int): target number of channels.

    Returns:
        tuple: colour tuple with exactly `length` channels.
    """
    n: int = len(color)
    if n == length:
        return color
    if n > length:
        return tuple(color[:length])
    return tuple(color) + (0,) * (length - n)


def _interp(color1: tuple, color2: tuple, t: float, length: int) -> tuple:
    """Linearly interpolate between two colours.

    Args:
        color1 (tuple): colour at t = 0.
        color2 (tuple): colour at t = 1.
        t (float): interpolation fraction in [0, 1].
        length (int): number of channels in the result.

    Returns:
        tuple: interpolated colour with `length` channels.
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

    Subclass and implement `get_pixel_color()`; override `is_animated()`
    for time-based patterns.
    """

    def is_animated(self) -> bool:
        """Return True if this pattern must be recomputed every update().

        Returns:
            bool
        """
        return False

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        """Return the colour for one pixel in the subset.

        Args:
            pixel_index (int): 0-indexed position within the subset.
            num_pixels (int): total number of pixels in the subset.
            elapsed_ms (int): milliseconds since set_pattern() was called.
            bpp (int): number of colour channels (3 for RGB, 4 for RGBW).

        Returns:
            tuple: colour with `bpp` channels.

        Raises:
            NotImplementedError: always, unless overridden by a subclass.
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
    """Blanks the subset (all channels zero)."""

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
            color1 (tuple): colour at the trough.
            color2 (tuple): colour at the peak.
            period_ms (int): full cycle length, in milliseconds.
            phase_deg (float, optional): phase offset in degrees.
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
            period_ms (int, optional): full on+off cycle length, in ms.
            duty (float, optional): fraction of `period_ms` spent on
                `color1`, in (0, 1).
            repeats (int, optional): number of on/off cycles to run.
                None (default) flashes indefinitely.
            phase_deg (float, optional): phase offset in degrees.
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
    """A Gaussian "comet" that travels along the subset in a loop."""

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
            period_ms (int): time for the peak to complete one full pass.
            phase_deg (float, optional): phase offset in degrees.
            spread (float, optional): Gaussian sigma, in pixels. Defaults
                to roughly a sixth of the subset's pixel count.
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
            timing (int, optional): 0 for 400kHz, 1 for 800kHz (most LEDs).
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

        Args:
            length (int, optional): number of pixels to claim; None
                claims every pixel not yet owned by an earlier subset.

        Returns:
            int: auto-generated subset id.
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

        Args:
            subset_id (int): id from add_subset(), or None for pixels
                unclaimed by any subset.

        Returns:
            tuple: (start, length).

        Raises:
            KeyError: if `subset_id` does not exist.
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
        """Stop all patterns and blank every pixel; subsets stay valid."""
        self.clear_patterns()
        off: tuple = (0,) * self.bpp
        n: int = len(self)
        for i in range(n):
            self[i] = off

    def reset(self) -> None:
        """Like clear(), but also forgets the subset structure entirely."""
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
            pattern (Pattern): pattern instance to render.
            id (int, optional): id from add_subset(); None targets pixels
                not yet claimed by any subset.

        Returns:
            int: the id this pattern is attached to.

        Raises:
            KeyError: if `id` does not exist.
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
        """Write a pattern entry's colours into the pixel buffer.

        Args:
            entry (dict): pattern state dict (pattern, start, length, t0).
            elapsed_ms (int): milliseconds since the pattern was set.
        """
        pattern: Pattern = entry["pattern"]
        n: int = len(self)
        first: int = max(0, entry["start"])
        last: int = min(n, entry["start"] + entry["length"])
        length: int = last - first

        for offset, i in enumerate(range(first, last)):
            self[i] = pattern.get_pixel_color(offset, length, elapsed_ms, self.bpp)

    def update(self) -> None:
        """Recompute every animated pattern's colours from elapsed time."""
        now: int = time.ticks_ms()

        for entry in self._patterns.values():
            pattern: Pattern = entry["pattern"]
            if not pattern.is_animated():
                continue
            elapsed: int = time.ticks_diff(now, entry["t0"])
            self._render(entry, elapsed)

    def poll(self) -> None:
        """Recompute animated patterns and push the result to the strip."""
        self.update()
        self.write()
