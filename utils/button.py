"""Debounced push-button driver with short/long press detection.

Provides a `Button` class for MicroPython that wraps a `machine.Pin`
configured as a digital input, using an interrupt handler to detect
edges, debounce noisy transitions, and classify presses as short or
long.

See ../examples/button/main.py for usage.
"""

from machine import Pin
import time


class ButtonEvent:
    """Events returned by `Button.consume`.

    Attributes:
        NONE: No new event.
        PRESS: The button was just pressed.
        SHORT_RELEASE: Released before the long-press threshold.
        LONG_PRESS: Held for the configured long-press duration.
        LONG_RELEASE: Released after a LONG_PRESS had fired.
    """

    NONE = 0
    PRESS = 1
    SHORT_RELEASE = 2
    LONG_PRESS = 3
    LONG_RELEASE = 4


class _State:
    """Internal button state machine states (not part of the public API)."""

    IDLE = 0     # button released, nothing in progress
    PRESSED = 1  # button down, long-press threshold not yet reached
    HELD = 2     # button down, long-press already fired this cycle


class Button:
    """Debounced button with press, short-press and long-press detection.

    Wraps a `machine.Pin` configured as a digital input (`Pin.IN`).
    `pull=Pin.PULL_DOWN` selects active-high operation; any other
    `pull` value selects active-low operation.
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
            pull: `Pin.PULL_UP`, `Pin.PULL_DOWN`, or `None`.
            debounce_ms: Stable time, in milliseconds, required before
                a level change is acted on. Must be positive.
            long_press_ms: Minimum hold duration, in milliseconds, for
                a press to be classified as a long press. Must be
                positive.

        Raises:
            ValueError: If `pull`, `debounce_ms`, or `long_press_ms`
                is not a valid value.
        """
        if pull not in (Pin.PULL_UP, Pin.PULL_DOWN, None):
            raise ValueError("pull must be Pin.PULL_UP, Pin.PULL_DOWN, or None")
        if debounce_ms <= 0:
            raise ValueError("debounce_ms must be positive")
        if long_press_ms <= 0:
            raise ValueError("long_press_ms must be positive")

        self._pin = Pin(id, Pin.IN, pull)
        self._debounce_ms = debounce_ms
        self._long_press_ms = long_press_ms
        self._active_level = 1 if pull == Pin.PULL_DOWN else 0

        self._state = _State.IDLE
        self._last_edge = time.ticks_ms()  # restarts on every edge (debounce timer)
        self._last_level = self._pin.value()  # pin level captured at last edge
        self._press_start = 0  # for long-press timing
        self._pending_event = ButtonEvent.NONE

        self._pin.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self._on_irq)

    def _on_irq(self, pin):
        """Interrupt handler invoked on rising/falling edges of the pin.

        Captures the edge time and pin level. Each is a single atomic
        attribute write, so `consume` never observes a torn update.

        Args:
            pin: the pin that triggered the interrupt.
        """
        self._last_level = pin.value()
        self._last_edge = time.ticks_ms()

    def is_pressed(self) -> bool:
        """Return whether the button is currently held down (debounced).

        Returns:
            bool: True if the button is currently pressed.
        """
        return self._state != _State.IDLE

    def consume(self) -> ButtonEvent:
        """Check for and consume the pending button event.

        Returns:
            ButtonEvent: NONE, PRESS, SHORT_RELEASE, LONG_PRESS, or
            LONG_RELEASE.
        """
        now = time.ticks_ms()
        last_edge = self._last_edge  # snapshot: avoid a second volatile read

        if time.ticks_diff(now, last_edge) >= self._debounce_ms:
            pressed = self._last_level == self._active_level

            if pressed and self._state == _State.IDLE:
                self._state = _State.PRESSED
                self._press_start = now
                self._pending_event = ButtonEvent.PRESS

            elif not pressed and self._state != _State.IDLE:
                if self._state == _State.PRESSED:
                    self._pending_event = ButtonEvent.SHORT_RELEASE
                elif self._state == _State.HELD:
                    self._pending_event = ButtonEvent.LONG_RELEASE
                self._state = _State.IDLE

            elif pressed and self._state == _State.PRESSED:
                if time.ticks_diff(now, self._press_start) >= self._long_press_ms:
                    self._state = _State.HELD
                    self._pending_event = ButtonEvent.LONG_PRESS

        event = self._pending_event
        self._pending_event = ButtonEvent.NONE
        return event
