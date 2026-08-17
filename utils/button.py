"""Debounced push-button driver with short/long press detection.

This module provides a `Button` class for MicroPython that *is* a
`machine.Pin` (via subclassing) configured as a digital input, using an
interrupt handler to detect edges, debounce noisy transitions, and
classify presses as either short or long based on configurable timing
thresholds.
"""

from machine import Pin
from micropython import const
import time


class ButtonEvent:
    """Enumeration of button events returned by `Button.consume_event`.

    Attributes:
    - NONE: No new event is available.
    - SHORT_PRESS: The button was pressed and released before the
      long-press threshold elapsed.
    - LONG_PRESS: The button has been held down for at least the
      configured long-press duration.
    """

    NONE = const(0)
    SHORT_PRESS = const(1)
    LONG_PRESS = const(2)


class Button(Pin):
    """Debounced button with short-press and long-press detection.

    `Button` is a `machine.Pin` subclass: instead of wrapping a pin
    object, it *is* a pin, always configured as a digital input
    (`Pin.IN`). Only `id` and `pull` need to be supplied; the button
    is active low (pressed == 0).

    The button state is driven by a pin-change interrupt, which
    filters out bounce and flags that a new event is pending. Call
    `consume_event` periodically (e.g. from a main loop) to read and
    clear the pending event as either a short press or long press.
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
            debounce_ms: Minimum time, in milliseconds, that must pass
                between edges for them to be considered distinct (bounce
                shorter than this is ignored).
            long_press_ms: Minimum hold duration, in milliseconds,
                required for a press to be classified as a long press.
        """
        super().__init__(id, Pin.IN, pull)
        self.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self._on_irq)
        self._debounce_ms = debounce_ms
        self._long_press_ms = long_press_ms

        self._last_edge = time.ticks_ms()
        self._flag = False
        self._long_press = False

    def _on_irq(self, pin):
        """Interrupt handler invoked on rising/falling edges of the pin."""

        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_edge) < self._debounce_ms:
            return  # ignore bounce
        self._last_edge = now

        # Set a flag only if the previous event was not a long press
        if self._long_press == True:
            self._long_press = False
        else:
            self._flag = True

    def is_pressed(self) -> bool:
        """Return whether the button is currently held down.

        Returns:
        True if the pin reads low (button pressed), False otherwise.
        """
        return self.value() == 0

    def consume(self) -> ButtonEvent:
        """Check for and consume a pending button event.

        Should be polled periodically. If the button is pressed and quickly
        released before the long press threshold, returns `ButtonEvent.SHORT_PRESS`.
        If button is held down past the long press threshold, returns
        `ButtonEvent.LONG_PRESS`. Only returns each event once, if no new
        event is pending, returns `ButtonEvent.NONE`.

        Returns:
        The detected `ButtonEvent` (NONE, SHORT_PRESS, or LONG_PRESS).
        """
        now = time.ticks_ms()

        if self._flag == False:
            return ButtonEvent.NONE

        # the button is pressed, check if was pressed long enough for long press
        # continue without resetting the flag
        if self.is_pressed():
            if time.ticks_diff(now, self._last_edge) > self._long_press_ms:
                self._long_press = True
                self._flag = False
                return ButtonEvent.LONG_PRESS
        # the button is not pressed, check that we aren't following a long press
        else:
            self._flag = False
            return ButtonEvent.SHORT_PRESS

        return ButtonEvent.NONE
