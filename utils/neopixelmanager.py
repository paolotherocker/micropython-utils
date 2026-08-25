"""A MicroPython class that extends the built-in `neopixel.NeoPixel` driver
with a *subset-based* API:

- add_subset(length=None) -> pre-register a contiguous block of `length`
                              pixels (taken from wherever the previous
                              subset left off). Returns an auto-incrementing
                              integer id (0, 1, 2, ...) used to address that
                              block later. If `length` is None, the subset
                              swallows every pixel not yet claimed by an
                              earlier subset.
- set_pattern(pattern, id=None) -> apply a Pattern instance (Solid, Off,
                              Pulse, Flash, or Wave) to a previously-registered
                              subset (by id). If `id` is None, targets whatever
                              pixels are still unclaimed by any subset ("the
                              rest of the strip"). Re-calling with the same id
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

- Pattern  -> abstract base class. Subclass this to add new effects. Must
             implement `get_pixel_color(self, pixel_index, num_pixels,
             elapsed_ms, bpp)` returning a colour tuple for a single pixel
             within the subset, and may override `is_animated()` (default
             False) to tell the manager whether `update()` needs to keep
             recomputing it every poll, or whether it only needs to be
             rendered once when set. Patterns that colour every pixel the
             same (e.g. Solid, Pulse) simply ignore `pixel_index` and
             `num_pixels` and return the same colour regardless. Patterns
             that need a different colour per pixel (e.g. a travelling
             wave) use `pixel_index`/`num_pixels` to vary the result.
- Solid    -> Solid(color): fills the subset with a single static colour.
- Off      -> Off(): blanks the subset (all channels zero). Also serves as
             the way to "remove" a pattern from a subset -- just set an
             Off() pattern on it instead of calling a separate remove
             method.
- Pulse    -> Pulse(color1, color2, period_ms, phase_deg=0): sine-wave
             breathing effect between two colours.
- Flash    -> Flash(color1, color2=(0, 0, 0), period_ms=200,
             duty=0.5, repeats=None, phase_deg=0): hard on/off
             (square-wave) flash of the subset between two colours.
- Wave     -> Wave(color1, color2, period_ms, phase_deg=0): a travelling
             wave that loops continuously along the subset. At any instant
             only one pixel is fully at `color2`; pixels either side fade
             back towards `color1` following a Gaussian falloff, giving a
             smooth "comet" that runs along the strip and wraps around.
             Same constructor signature as Pulse, so it's a drop-in
             alternative wherever Pulse is used.

Type hints use only builtin types (int, float, str, bool, tuple, dict, list)
so no extra imports (e.g. `typing`) are required -- important on MicroPython
where the `typing` module is usually unavailable and generic subscripting
such as `tuple[int, int]` is not supported on the class objects themselves.
Where a value may legitimately be `None` (e.g. an un-set default), that is
called out in the docstring rather than via `Optional[...]`.

Colour tuples are plain (r, g, b) or (r, g, b, w) tuples -- there is no
dedicated colour type. Any colour a pattern is given, or any two colours a
pattern blends together (e.g. Pulse/Wave's color1/color2), are automatically
padded with trailing zeros (or truncated) to match the strip's `bpp` before
they are combined or written. This means you can freely mix RGB and RGBW
tuples when constructing patterns -- e.g. Pulse((255, 0, 0), (0, 0, 0, 255))
-- without raising an error; the shorter tuple's missing channel(s) are
simply treated as 0 (off). See `_normalize_color()` below.

Typical usage on a board with NeoPixels on GPIO 4:

    from machine import Pin
    from neopixelmanager import NeoPixelManager, Solid, Off, Pulse, Wave
    import time

    np = NeoPixelManager(Pin(4), 30)  # 30 pixel strip
    np.reset()

    # Pre-declare two subsets: first 8 pixels, next 16 pixels.
    id_a = np.add_subset(8)   # id_a == 0, covers pixels 0-7
    id_b = np.add_subset(16)  # id_b == 1, covers pixels 8-23

    # Static fill on subset 0
    np.set_pattern(Solid((0, 0, 255)), id=id_a)

    # Travelling wave along subset 1
    np.set_pattern(Wave((255, 0, 0), (0, 0, 0), period_ms=2000), id=id_b)

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
# Colour helpers
# ----------------------------------------------------------------------
def _normalize_color(color: tuple, length: int) -> tuple:
    """Pad or truncate a colour tuple to exactly `length` channels.

    Missing trailing channels (e.g. a 3-tuple RGB colour used where a
    4-channel RGBW value is expected) are filled with 0. Extra channels
    (e.g. a 4-tuple RGBW colour used where only 3 channels are expected)
    are simply dropped. This lets callers freely mix RGB and RGBW colour
    tuples across a pattern's arguments, or against a strip configured
    with a different `bpp`, without raising an error.

    Args:
        color (tuple): the colour tuple to normalise.
        length (int): the number of channels the result must have.

    Returns:
        tuple: a colour tuple with exactly `length` channels.
    """
    n: int = len(color)
    if n == length:
        return color
    if n > length:
        return tuple(color[:length])
    return tuple(color) + (0,) * (length - n)


def _interp(color1: tuple, color2: tuple, t: float, length: int) -> tuple:
    """Linearly interpolate between two colours at fraction t in [0, 1].

    Both colours are normalised to `length` channels first (see
    `_normalize_color()`), so color1 and color2 need not be the same
    length as each other, or match `length`, for this to work safely.
    """
    c1: tuple = _normalize_color(color1, length)
    c2: tuple = _normalize_color(color2, length)
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(length))


# ----------------------------------------------------------------------
# Pattern classes
# ----------------------------------------------------------------------
class Pattern:
    """Abstract base class for a pixel pattern applied to a subset.

    Subclass and implement `get_pixel_color()` to add new effect types.
    Override `is_animated()` to return True if the pattern needs to be
    recomputed on every `update()` call (e.g. anything time-based); static
    patterns only need to be rendered once when `set_pattern()` is called.

    Every pattern -- whether it paints the whole subset one flat colour
    (Solid, Pulse, Flash, ...) or a different colour per pixel (Wave) --
    is asked for its colour one pixel at a time via `get_pixel_color()`.
    Flat patterns simply ignore `pixel_index`/`num_pixels` and return the
    same colour regardless of which pixel is being asked about.
    """

    def is_animated(self) -> bool:
        """Return True if this pattern must be recomputed every update()."""
        return False

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        """Return the colour tuple for a single pixel within the subset.

        Called once per pixel in the subset on every render pass. The
        returned tuple must have exactly `bpp` channels -- implementations
        should route any colour(s) they hold through `_normalize_color()`
        (directly, or via `_interp()`) before returning, so mismatched
        RGB/RGBW inputs never reach the underlying strip buffer.

        Args:
            pixel_index (int): position of this pixel within the subset,
                0-indexed from the start of the subset (not the strip).
                Patterns that colour every pixel the same can ignore this.
            num_pixels (int): total number of pixels in the subset.
                Patterns that colour every pixel the same can ignore this.
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
                A tuple with a different length than the strip's bpp is
                accepted too -- it is padded with 0s or truncated to fit
                when rendered.
        """
        self.color: tuple = tuple(color)

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        return _normalize_color(self.color, bpp)


class Off(Pattern):
    """Blanks the subset (all channels zero).

    Setting this pattern on a subset is also the way to stop/forget
    whatever pattern was previously running there -- there is no separate
    "remove" call.
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
            color1 (tuple): colour at the trough of the sine wave (t = 0).
            color2 (tuple): colour at the peak of the sine wave (t = 1).
                color1 and color2 need not have the same number of
                channels as each other, or as the strip's bpp -- shorter
                tuples are zero-padded when rendered.
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
            color1 (tuple): colour shown during the "on" phase.
            color2 (tuple, optional): colour shown during the "off"
                phase. Defaults to black (0, 0, 0), i.e. a classic flash.
                color1 and color2 need not have the same number of
                channels as each other, or as the strip's bpp -- shorter
                tuples are zero-padded when rendered.
            period_ms (int, optional): full on+off cycle length in
                milliseconds.
            duty (float, optional): fraction of `period_ms` spent on
                `color1` before switching to `color2`, in (0, 1).
                Defaults to 0.5 (equal on/off time).
            repeats (int, optional): number of on/off cycles to run.
                None (default) flashes indefinitely. Once the requested
                number of cycles has elapsed, the pattern holds on
                `color2` permanently (call set_pattern() again, e.g.
                with Off() or Solid(), to change it further).
            phase_deg (float, optional): optional phase offset in
                degrees, so multiple subsets can flash out of sync.
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
    """A travelling wave that loops continuously along the subset.

    Same constructor signature as Pulse, so it can be used as a drop-in
    alternative wherever Pulse is used. Behaviourally, though, it is quite
    different: instead of pulsing every pixel in the subset together
    between color1 and color2, only *one* pixel at a time sits at color2
    (the "peak"). Pixels on either side of the peak fade back towards
    color1 following a Gaussian curve, and the peak's position travels
    continuously along the subset over time, wrapping back around to the
    start once it reaches the end -- like a comet or a lighthouse beam
    circling the strip.

    The width of the Gaussian "glow" around the peak is derived
    automatically from the subset's length (roughly a sixth of the subset,
    with a sensible minimum), so the effect looks proportionate whether
    it's applied to a tiny 4-pixel ring or a long 60-pixel strip, without
    needing any extra constructor arguments beyond Pulse's own.
    """

    def __init__(
        self,
        color1: tuple,
        color2: tuple,
        period_ms: int,
        phase_deg: float = 0,
    ) -> None:
        """
        Args:
            color1 (tuple): base colour that pixels fade towards away from
                the wave's peak (equivalent to Pulse's trough colour).
            color2 (tuple): colour of the single pixel at the wave's peak.
                color1 and color2 need not have the same number of
                channels as each other, or as the strip's bpp -- shorter
                tuples are zero-padded when rendered.
            period_ms (int): time in milliseconds for the peak to complete
                one full pass along the subset and wrap back to the start.
            phase_deg (float, optional): optional phase offset in degrees,
                so multiple subsets can run the wave out of sync (or in
                sync with a Pulse sharing the same period_ms/phase_deg).
        """
        self.color1: tuple = tuple(color1)
        self.color2: tuple = tuple(color2)
        self.period_ms: int = period_ms
        self.phase_ms: float = (phase_deg / 360.0) * period_ms

    def is_animated(self) -> bool:
        return True

    def get_pixel_color(
        self, pixel_index: int, num_pixels: int, elapsed_ms: int, bpp: int
    ) -> tuple:
        if num_pixels <= 0:
            return _normalize_color(self.color1, bpp)

        t: float = ((elapsed_ms + self.phase_ms) / self.period_ms) % 1.0
        peak: float = t * num_pixels

        # Circular distance so the glow wraps smoothly across the
        # start/end boundary instead of jumping.
        raw_dist: float = abs(pixel_index - peak)
        distance: float = min(raw_dist, num_pixels - raw_dist)

        sigma: float = max(0.6, num_pixels / 6.0)
        weight: float = math.exp(-(distance * distance) / (2 * sigma * sigma))

        return _interp(self.color1, self.color2, weight, bpp)


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
        off: tuple = (0,) * self.bpp
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
            pattern (Pattern): a Solid, Off, Pulse, Flash, Wave (or custom
                Pattern subclass) instance describing the desired effect.
                To stop a subset's current pattern, call this again with
                Off().
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
        """Compute and write a pattern entry's colours into the pixel buffer.

        Every pattern is asked for its colour one pixel at a time via
        get_pixel_color(). Patterns that colour every pixel the same
        (Solid, Pulse, Flash, ...) just return the same value regardless
        of pixel_index/num_pixels; patterns like Wave use those arguments
        to vary the colour across the subset. Every colour returned is
        already normalised to self.bpp channels by the pattern itself
        (via _normalize_color()/_interp()), so it is safe to write
        directly into the strip buffer here.
        """
        pattern: Pattern = entry["pattern"]
        n: int = len(self)
        first: int = max(0, entry["start"])
        last: int = min(n, entry["start"] + entry["length"])
        length: int = last - first

        for offset, i in enumerate(range(first, last)):
            self[i] = pattern.get_pixel_color(offset, length, elapsed_ms, self.bpp)

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
