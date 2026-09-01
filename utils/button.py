"""Debounced push-button driver with short/long press detection.

Provides a `Button` class for MicroPython that subclasses `machine.Pin`
as a digital input, using an interrupt handler to detect edges, debounce
noisy transitions, and classify presses as short or long.

See ../examples/button/main.py for usage.
"""

from machine import Pin
import time


class ButtonEvent:
    """Enumeration of button events returned by `Button.consume`.

    Attributes:
        NONE: No new event is available.
        PRESSED: The button was just pressed.
        SHORT_PRESS: The button was released before the long-press
            threshold elapsed.
        LONG_PRESS: The button has been held for the configured
            long-press duration.
    """

    NONE = 0
    PRESSED = 1
    SHORT_PRESS = 2
    LONG_PRESS = 3


class _State:
    """Internal button state machine states (not part of the public API)."""

    IDLE = 0  # button released, nothing in progress
    PRESSED = 1  # button down, long-press threshold not yet reached
    HELD = 2  # button down, long-press already fired this cycle


class Button(Pin):
    """Debounced button with press, short-press and long-press detection.

    Always configured as a digital input (`Pin.IN`), active low
    (pressed == 0).
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
            pull: Pull resistor configuration (`Pin.PULL_UP`,
                `Pin.PULL_DOWN`, or `None`).
            debounce_ms: Minimum time, in milliseconds, the pin must
                remain electrically stable before a level change is
                trusted and acted on.
            long_press_ms: Minimum hold duration, in milliseconds,
                required for a press to be classified as a long press.
        """
        super().__init__(id, Pin.IN, pull)
        self.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self._on_irq)
        self._debounce_ms = debounce_ms
        self._long_press_ms = long_press_ms

        self._state = _State.IDLE
        self._last_edge = time.ticks_ms()  # restarts on every edge (debounce timer)
        self._press_start = 0  # for long-press timing
        self._pending_event = ButtonEvent.NONE

    def _on_irq(self, pin):
        """Interrupt handler invoked on rising/falling edges of the pin.

        Args:
            pin: the pin that triggered the interrupt.
        """
        self._last_edge = time.ticks_ms()

    def is_pressed(self) -> bool:
        """Return whether the button is currently held down.

        Returns:
            bool: True if the pin reads low (button pressed).
        """
        return self.value() == 0

    def consume(self) -> ButtonEvent:
        """Check for and consume the pending button event.

        Returns:
            ButtonEvent: NONE, PRESSED, SHORT_PRESS, or LONG_PRESS.
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
