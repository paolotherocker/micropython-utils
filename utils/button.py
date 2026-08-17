"""Debounced push-button driver with short/long press detection.

This module provides a `Button` class for MicroPython that *is* a
`machine.Pin` (via subclassing) configured as a digital input, using an
interrupt handler to detect edges, debounce noisy transitions, and
classify presses as either short or long based on configurable timing
thresholds.
"""

from machine import Pin
import time


class ButtonEvent:
    """Enumeration of button events returned by `Button.consume`.

    Attributes:
    - NONE: No new event is available.
    - PRESSED: The button was just pressed (rising edge of the logical
      "pressed" state). Fires immediately on press, independently of
      whether the eventual release is classified as short or long.
    - SHORT_PRESS: The button was pressed and released before the
      long-press threshold elapsed.
    - LONG_PRESS: The button has been held down for at least the
      configured long-press duration.
    """

    NONE = 0
    PRESSED = 1
    SHORT_PRESS = 2
    LONG_PRESS = 3


class _State:
    """Internal button state machine states (not part of the public API)."""

    IDLE = 0     # button released, nothing in progress
    PRESSED = 1  # button down, long-press threshold not yet reached
    HELD = 2     # button down, long-press already fired this cycle


class Button(Pin):
    """Debounced button with press, short-press and long-press detection.

    `Button` is a `machine.Pin` subclass: instead of wrapping a pin
    object, it *is* a pin, always configured as a digital input
    (`Pin.IN`). Only `id` and `pull` need to be supplied; the button
    is active low (pressed == 0).

    Debouncing is level-confirmed rather than edge-spacing-based: the
    pin-change interrupt only restarts a debounce timer (it never
    decides on its own that a transition is "real"). `consume` commits
    a state transition only once the pin has been electrically stable
    for `debounce_ms`, and always re-checks `is_pressed()` as ground
    truth at that point. This means the internal state machine
    (`_State.IDLE` -> `_State.PRESSED` -> `_State.HELD` -> `_State.IDLE`)
    can never get stuck out of sync with the physical pin, even if a
    genuine press/release happens to occur close together in time.

    Call `consume` periodically (e.g. from a main loop) to read and
    clear the pending event.
    """

    def __init__(
        self,
        id,
        pull: int = Pin.PULL_UP,
        *,
        debounce_ms: int = 30,
        long_press_ms: int = 600,
    ):
        """
        Args:
            id: Pin identifier, as accepted by `machine.Pin`.
            pull: Pull resistor configuration (e.g. `Pin.PULL_UP`,
                `Pin.PULL_DOWN`, or `None`). The button is always
                initialised as an input (`Pin.IN`), active low
                (pressed == 0).
            debounce_ms: Minimum time, in milliseconds, that the pin
                must remain electrically stable (no further edges)
                before a level change is trusted and acted on.
            long_press_ms: Minimum hold duration, in milliseconds,
                required for a press to be classified as a long press.
        """
        super().__init__(id, Pin.IN, pull)
        self.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self._on_irq)
        self._debounce_ms = debounce_ms
        self._long_press_ms = long_press_ms

        self._state = _State.IDLE
        self._last_edge = time.ticks_ms()   # restarts on every edge (debounce timer)
        self._press_start = 0               # for long-press timing
        self._pending_event = ButtonEvent.NONE

    def _on_irq(self, pin):
        """Interrupt handler invoked on rising/falling edges of the pin.

        Deliberately does nothing but restart the debounce timer. It
        makes no assumption about whether this edge is real or bounce;
        `consume` is the only place that commits a state transition,
        and only once the pin has settled.
        """
        self._last_edge = time.ticks_ms()

    def is_pressed(self) -> bool:
        """Return whether the button is currently held down.

        Returns:
            True if the pin reads low (button pressed), False otherwise.
        """
        return self.value() == 0

    def consume(self) -> ButtonEvent:
        """Check for and consume the pending button event.

        Should be polled periodically. A level change is only trusted
        once the pin has been stable for `debounce_ms` since the last
        edge activity; at that point the current `is_pressed()` value
        is used as ground truth to (re)synchronise the state machine,
        which prevents the button from ever getting stuck out of sync
        with reality, even if a fast genuine press/release was
        initially mistaken for bounce.

        A press yields `ButtonEvent.PRESSED`. Being held past the
        configured long-press duration yields `ButtonEvent.LONG_PRESS`.
        Otherwise, releasing before that threshold yields
        `ButtonEvent.SHORT_PRESS`. The event is cleared once read; if
        it wasn't polled before a new event occurred, the older event
        is simply overwritten and lost. If nothing is pending, returns
        `ButtonEvent.NONE`.

        Returns:
            The detected `ButtonEvent` (NONE, PRESSED, SHORT_PRESS, or
            LONG_PRESS).
        """
        now = time.ticks_ms()

        if time.ticks_diff(now, self._last_edge) >= self._debounce_ms:
            pressed = self.is_pressed()

            if pressed and self._state == _State.IDLE:
                self._state = _State.PRESSED
                self._press_start = now
                self._pending_event = ButtonEvent.PRESSED

            elif not pressed and self._state != _State.IDLE:
                if self._state == _State.PRESSED:
                    self._pending_event = ButtonEvent.SHORT_PRESS
                self._state = _State.IDLE

            elif pressed and self._state == _State.PRESSED:
                if time.ticks_diff(now, self._press_start) > self._long_press_ms:
                    self._state = _State.HELD
                    self._pending_event = ButtonEvent.LONG_PRESS

        event = self._pending_event
        self._pending_event = ButtonEvent.NONE
        return event
