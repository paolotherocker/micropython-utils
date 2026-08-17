"""A MicroPython class that extends the built-in `neopixel.NeoPixel` driver
with a *subset-based* API:

- add_subset(length=None) -> pre-register a contiguous block of `length`
                              pixels (taken from wherever the previous
                              subset left off). Returns an auto-incrementing
                              integer id (0, 1, 2, ...) used to address that
                              block later. If `length` is None, the subset
                              swallows every pixel not yet claimed by an
                              earlier subset.
- set_pattern(pattern, id=None) -> apply a Pattern instance (Solid, Off, or
                              Pulse) to a previously-registered subset (by
                              id). If `id` is None, targets whatever pixels
                              are still unclaimed by any subset ("the rest
                              of the strip"). Re-calling with the same id
                              replaces that subset's pattern. To stop a
                              subset's animation and blank it, just call
                              set_pattern(Off(), id=...) again.
- clear_patterns()        -> remove all registered patterns (pixels left
                              as-is).
- clear()                 -> stop all patterns AND blank every pixel, but
                              keep the subset structure (ids stay valid).
- reset()                  -> like clear(), but also forgets the subset
                              structure -- add_subset() must be called again
                              from scratch afterwards.
- update()                 -> recomputes the current colour of every active
                              (animated) pattern based on elapsed time (does
                              NOT call write()).
- poll()                   -> convenience helper: calls update() then
                              write().

Pattern classes (importable from this module):

- Pattern  -> abstract base class. Subclass this to add new effects.
             Must implement `get_color(self, elapsed_ms, bpp)` returning a
             colour tuple, and may override `is_animated()` (default False)
             to tell the manager whether `update()` needs to keep
             recomputing it every poll, or whether it only needs to be
             rendered once when set.
- Solid    -> Solid(color): fills the subset with a single static colour.
- Off      -> Off(): blanks the subset (all channels zero). Also serves as
             the way to "remove" a pattern from a subset -- just set an
             Off() pattern on it instead of calling a separate remove
             method.
- Pulse    -> Pulse(color1, color2, period_ms, phase_deg=0): sine-wave
             breathing effect between two colours.

Type hints use only builtin types (int, float, str, bool, tuple, dict, list)
so no extra imports (e.g. `typing`) are required -- important on MicroPython
where the `typing` module is usually unavailable and generic subscripting
such as `tuple[int, int]` is not supported on the class objects themselves.
Where a value may legitimately be `None` (e.g. an un-set default), that is
called out in the docstring rather than via `Optional[...]`.

Typical usage on a board with NeoPixels on GPIO 4:

    from machine import Pin
    from neopixelmanager import NeoPixelManager, Solid, Off, Pulse
    import time

    np = NeoPixelManager(Pin(4), 30)  # 30 pixel strip
    np.reset()

    # Pre-declare two subsets: first 8 pixels, next 16 pixels.
    id_a = np.add_subset(8)   # id_a == 0, covers pixels 0-7
    id_b = np.add_subset(16)  # id_b == 1, covers pixels 8-23

    # Static fill on subset 0
    np.set_pattern(Solid((0, 0, 255)), id=id_a)

    # Pulse subset 1 between two colours
    np.set_pattern(Pulse((255, 0, 0), (0, 0, 0), period_ms=2000), id=id_b)

    # Anything left over (pixels 24-29) can be addressed with id=None
    np.set_pattern(Solid((0, 255, 0)), id=None)

    np.write()

    while True:
        np.poll()  # updates animated patterns and pushes to the strip
        time.sleep_ms(20)

    # Turn subset 1 off (no separate "remove" call needed)
    np.set_pattern(Off(), id=id_b)

    np.clear()  # stop patterns + blank strip, subsets 0 and 1 still valid
    np.reset()  # stop patterns + blank strip + forget subsets entirely
"""

import time
import math
import neopixel
from machine import Pin


# ----------------------------------------------------------------------
# Pattern classes
# ----------------------------------------------------------------------
class Pattern:
    """Abstract base class for a pixel pattern applied to a subset.

    Subclass and implement `get_color()` to add new effect types. Override
    `is_animated()` to return True if the pattern needs to be recomputed on
    every `update()` call (e.g. anything time-based); static patterns only
    need to be rendered once when `set_pattern()` is called.
    """

    def is_animated(self) -> bool:
        """Return True if this pattern must be recomputed every update()."""
        return False

    def get_color(self, elapsed_ms: int, bpp: int) -> tuple:
        """Return the colour tuple for the current point in time.

        Args:
            elapsed_ms (int): milliseconds elapsed since this pattern was
                attached via set_pattern().
            bpp (int): bytes-per-pixel of the strip (3 = RGB, 4 = RGBW),
                so the pattern can size its colour tuple correctly.
        """
        raise NotImplementedError


class Solid(Pattern):
    """A static, unchanging colour."""

    def __init__(self, color: tuple) -> None:
        """
        Args:
            color (tuple): tuple matching the strip's bpp, e.g. (r, g, b).
        """
        self.color: tuple = tuple(color)

    def get_color(self, elapsed_ms: int, bpp: int) -> tuple:
        return self.color


class Off(Pattern):
    """Blanks the subset (all channels zero).

    Setting this pattern on a subset is also the way to stop/forget
    whatever pattern was previously running there -- there is no separate
    "remove" call.
    """

    def get_color(self, elapsed_ms: int, bpp: int) -> tuple:
        return (0, 0, 0) if bpp == 3 else (0, 0, 0, 0)


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
            color1 (tuple): colour at the trough of the sine wave (t = 0).
            color2 (tuple): colour at the peak of the sine wave (t = 1).
            period_ms (int): full pulse period in milliseconds (one
                complete color1 -> color2 -> color1 cycle).
            phase_deg (float, optional): optional phase offset in degrees,
                so multiple pulses can be started out of sync.
        """
        self.color1: tuple = tuple(color1)
        self.color2: tuple = tuple(color2)
        self.period_ms: int = period_ms
        self.phase: float = math.radians(phase_deg)

    def is_animated(self) -> bool:
        return True

    def get_color(self, elapsed_ms: int, bpp: int) -> tuple:
        theta: float = (2 * math.pi * elapsed_ms / self.period_ms) + self.phase
        t: float = (math.sin(theta) + 1) / 2  # normalised to [0, 1]
        return _interp(self.color1, self.color2, t)


def _interp(color1: tuple, color2: tuple, t: float) -> tuple:
    """Linearly interpolate between two colours at fraction t in [0, 1]."""
    return tuple(
        int(color1[i] + (color2[i] - color1[i]) * t) for i in range(len(color1))
    )


# ----------------------------------------------------------------------
# NeoPixelManager
# ----------------------------------------------------------------------
class NeoPixelManager(neopixel.NeoPixel):
    """NeoPixel strip with pre-declared subsets and per-subset Patterns."""

    def __init__(self, pin_id: int, n: int, bpp: int = 3, timing: int = 1) -> None:
        """
        Args:
            pin_id (int): machine pin ID
            n (int): number of LEDs in the array
            bpp (int, optional): is 3 for RGB LEDs, and 4 for RGBW LEDs.
            timing (int, optional): is 0 for 400KHz, and 1 for 800kHz LEDs
                (most are 800kHz)
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
        """Pre-register a contiguous block of pixels for later addressing.

        The block starts wherever the previous subset (if any) left off.

        Args:
            length (int, optional): number of pixels to claim; None claims
                every pixel not yet owned by an earlier subset.

        Returns:
            int: auto-generated numeric id (0, 1, 2, ...) for this subset,
            used with set_pattern().
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

        `subset_id=None` maps to whatever pixels remain unclaimed by any
        subset (from the current cursor to the end of the strip).
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
        """
        Stop all active patterns and blank every pixel, keeping the
        underlying subset structure intact (ids remain valid).

        Call write() afterwards to push the change to the physical strip.
        """
        self.clear_patterns()
        off: tuple = (0, 0, 0) if self.bpp == 3 else (0, 0, 0, 0)
        n: int = len(self)
        for i in range(n):
            self[i] = off

    def reset(self) -> None:
        """
        Stop all active patterns, blank every pixel, and forget the subset
        structure entirely. add_subset() must be called again afterwards
        to re-establish ids.

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
            pattern (Pattern): a Solid, Off, Pulse (or custom Pattern
                subclass) instance describing the desired effect. To stop
                a subset's current pattern, call this again with Off().
            id (int, optional): id returned from add_subset(); None targets
                whatever pixels are not yet claimed by any subset.

        Returns:
            int: the id this pattern is attached to (echoes `id`).

        Note:
            Calling set_pattern() again with the same `id` replaces any
            existing pattern on that subset. The pattern is rendered
            immediately; animated patterns (is_animated() == True) are then
            kept up to date by update()/poll().
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
        """Compute and write a pattern entry's colour into the pixel buffer."""
        color: tuple = entry["pattern"].get_color(elapsed_ms, self.bpp)
        n: int = len(self)
        first: int = max(0, entry["start"])
        last: int = min(n, entry["start"] + entry["length"])
        for i in range(first, last):
            self[i] = color

    def update(self) -> None:
        """
        Recompute the colour of every *animated* pattern's subset based on
        the current time and write those values into the pixel buffer.
        Static patterns (Solid, Off) were already rendered once when
        set_pattern() was called, so they are skipped here for efficiency.

        This does NOT push data to the physical strip -- call write()
        (or the poll() helper below) afterwards to do that.
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
