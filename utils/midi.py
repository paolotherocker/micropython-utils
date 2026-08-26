"""
midi.py
=======

A MIDI message library for a MicroPython instance.

This module defines a `Message` class hierarchy for standard MIDI channel
and system realtime messages, a separate `SysEx` type for System
Exclusive data, and two output classes sharing an identical
`send_message()`/`send_sysex()` API:

- `MidiUsb`: extends `usb.device.midi.MIDIInterface` and initialises the
  USB MIDI device automatically.
- `MidiUart`: sends the same messages as a raw byte stream over a
  `machine.UART`, using the standard MIDI serial protocol (31250 baud,
  8 data bits, no parity, 1 stop bit -- no USB involved at all).

Because both classes expose the same two methods, application code that
builds `Message`/`SysEx` instances and calls `send_message()`/
`send_sysex()` on an interface object works unchanged whether that object
is a `MidiUsb`, a `MidiUart`, or -- since both accept the same calls --
looped over a list containing both, to transmit out of two ports at once.

Each `Message` subclass exposes `to_bytes()` (the raw MIDI bytes as a list
of integers) and `cin()` (the USB-MIDI Code Index Number, used only by
`MidiUsb`).

Dependencies
------------

`MidiUsb` requires MicroPython's USB MIDI device package:

    mpremote mip install usb-device-midi

and firmware with `usb.device` support. If `usb.device` or
`usb.device.midi` are not importable, `MidiUsb` falls back to subclassing
`object` and raises a clear `RuntimeError` if instantiated.

`MidiUart` requires only the built-in `machine` module (`machine.UART`
and `machine.Pin`); no additional package is needed. If `machine` is not
importable (for example, when this module is loaded outside MicroPython),
`MidiUart` raises a clear `RuntimeError` if instantiated.

Either class can be used independently -- this module still imports (and
`Message`/`SysEx` remain fully usable) even if one or both of these
dependencies are unavailable.

Why SysEx is not a Message
--------------------------

Every `Message` subclass maps to exactly one fixed-size USB-MIDI Event
Packet, so `cin()` always returns a single, well-defined Code Index
Number for it. SysEx does not fit that contract: it is variable length
and, over USB, must be split into multiple 3-byte packets, each with a
*different* CIN depending on its position in the stream (0x4 for
start/continue packets, 0x5/0x6/0x7 for the final packet depending on
whether it ends with 1, 2, or 3 bytes). There is no single correct
`cin()` value for a SysEx message as a whole. Over UART there is no
packet framing at all, so this distinction does not apply there, but
`SysEx` is still kept separate from `Message` for a consistent interface
across both transports.

Making `SysEx` its own type, rather than a `Message` subclass with a
`cin()` that returns `None` or raises, means code written against the
`Message` interface simply cannot call `.cin()` on a `SysEx` instance by
accident -- the method does not exist on it, so doing so raises a
standard `AttributeError` immediately. `MidiUsb.send_sysex()` handles USB
SysEx chunking and per-packet CIN selection internally; `MidiUart.send_sysex()`
just writes the raw bytes.

Examples
--------

USB MIDI via `MidiUsb` (device initialisation happens in the constructor)::

    from midi import MidiUsb, NoteOn, ControlChange, SysEx

    usb_midi = MidiUsb(product_str="My MIDI Controller")

    usb_midi.send_message(NoteOn(0, note=60, velocity=100))
    usb_midi.send_message(ControlChange(0, controller=20, value=127))
    usb_midi.send_sysex(SysEx([0x7E, 0x00, 0x09, 0x01]))

Serial MIDI via `MidiUart` (UART is configured automatically too)::

    from midi import MidiUart, NoteOn

    serial_midi = MidiUart(uart_id=1, tx_pin=4, rx_pin=5)
    serial_midi.send_message(NoteOn(0, note=60, velocity=100))

Sending the same message out of both transports::

    for interface in (usb_midi, serial_midi):
        interface.send_message(NoteOn(0, note=60, velocity=100))
"""

try:
    import usb.device
    from usb.device.midi import MIDIInterface
except ImportError:
    usb = None
    MIDIInterface = object

try:
    from machine import UART, Pin
except ImportError:
    UART = None
    Pin = None

# ===========================================================================
# MIDI message classes
# ===========================================================================

_NOTE_OFF = 0x8
_NOTE_ON = 0x9
_POLY_AFTERTOUCH = 0xA
_CONTROL_CHANGE = 0xB
_PROGRAM_CHANGE = 0xC
_CHANNEL_AFTERTOUCH = 0xD
_PITCH_BEND = 0xE

_SYSEX_START = 0xF0
_SYSEX_END = 0xF7
_CLOCK = 0xF8
_START = 0xFA
_CONTINUE = 0xFB
_STOP = 0xFC
_ACTIVE_SENSING = 0xFE
_SYSTEM_RESET = 0xFF

_MIDI_UART_BAUDRATE = 31250


def _clamp7(value: int, name: str = "value") -> int:
    """Validate and return a 7-bit MIDI data-byte value."""
    if not 0 <= value <= 127:
        raise ValueError("%s must be 0-127, got %r" % (name, value))
    return value


def _clamp_channel(channel: int) -> int:
    """Validate and return a zero-based MIDI channel number."""
    if not 0 <= channel <= 15:
        raise ValueError("channel must be 0-15, got %r" % channel)
    return channel


class Message:
    """
    Abstract base class for fixed-size MIDI messages.

    Concrete subclasses implement `to_bytes()` and `cin()`, the latter
    returning the USB-MIDI Code Index Number. Channels are zero-based:
    channel=0 is MIDI channel 1, and channel=15 is MIDI channel 16.

    SysEx is deliberately not part of this hierarchy; see `SysEx` below.
    """

    def __init__(self, channel: int) -> None:
        self.channel: int = _clamp_channel(channel)

    def to_bytes(self) -> list:
        """Return the raw MIDI bytes as a list of integers."""
        raise NotImplementedError

    def cin(self) -> int:
        """Return the USB-MIDI Code Index Number for this message."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return "<%s bytes=%s>" % (self.__class__.__name__, list(self.to_bytes()))


class NoteOn(Message):
    """MIDI Note On message."""

    def __init__(self, channel: int, note: int, velocity: int) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_ON << 4) | self.channel, self.note, self.velocity]

    def cin(self) -> int:
        return _NOTE_ON


class NoteOff(Message):
    """MIDI Note Off message."""

    def __init__(self, channel: int, note: int, velocity: int) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_OFF << 4) | self.channel, self.note, self.velocity]

    def cin(self) -> int:
        return _NOTE_OFF


class ControlChange(Message):
    """MIDI Control Change message."""

    def __init__(self, channel: int, controller: int, value: int) -> None:
        super().__init__(channel)
        self.controller: int = _clamp7(controller, "controller")
        self.value: int = _clamp7(value, "value")

    def to_bytes(self) -> list:
        return [(_CONTROL_CHANGE << 4) | self.channel, self.controller, self.value]

    def cin(self) -> int:
        return _CONTROL_CHANGE


class ProgramChange(Message):
    """MIDI Program Change message."""

    def __init__(self, channel: int, program: int) -> None:
        super().__init__(channel)
        self.program: int = _clamp7(program, "program")

    def to_bytes(self) -> list:
        return [(_PROGRAM_CHANGE << 4) | self.channel, self.program]

    def cin(self) -> int:
        return _PROGRAM_CHANGE


class ChannelAftertouch(Message):
    """MIDI channel pressure (monophonic aftertouch) message."""

    def __init__(self, channel: int, pressure: int) -> None:
        super().__init__(channel)
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_CHANNEL_AFTERTOUCH << 4) | self.channel, self.pressure]

    def cin(self) -> int:
        return _CHANNEL_AFTERTOUCH


class PolyAftertouch(Message):
    """MIDI polyphonic key-pressure message."""

    def __init__(self, channel: int, note: int, pressure: int) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_POLY_AFTERTOUCH << 4) | self.channel, self.note, self.pressure]

    def cin(self) -> int:
        return _POLY_AFTERTOUCH


class PitchBend(Message):
    """
    MIDI 14-bit pitch bend.

    `value` ranges from -8192 to 8191. Zero is centre/no bend.
    """

    def __init__(self, channel: int, value: int) -> None:
        super().__init__(channel)
        if not -8192 <= value <= 8191:
            raise ValueError("pitch bend value must be -8192..8191")
        self.value: int = value

    def to_bytes(self) -> list:
        raw: int = self.value + 8192
        return [
            (_PITCH_BEND << 4) | self.channel,
            raw & 0x7F,
            (raw >> 7) & 0x7F,
        ]

    def cin(self) -> int:
        return _PITCH_BEND


class SystemRealtime(Message):
    """Base class for single-byte MIDI system realtime messages."""

    _STATUS = None

    def __init__(self, channel: int) -> None:
        super().__init__(channel)

    def to_bytes(self) -> list:
        return [self._STATUS]

    def cin(self) -> int:
        return 0xF


class Clock(SystemRealtime):
    """MIDI Timing Clock (0xF8)."""
    _STATUS: int = _CLOCK


class Start(SystemRealtime):
    """MIDI Start (0xFA)."""
    _STATUS: int = _START


class Continue(SystemRealtime):
    """MIDI Continue (0xFB)."""
    _STATUS: int = _CONTINUE


class Stop(SystemRealtime):
    """MIDI Stop (0xFC)."""
    _STATUS: int = _STOP


class ActiveSensing(SystemRealtime):
    """MIDI Active Sensing (0xFE)."""
    _STATUS: int = _ACTIVE_SENSING


class SystemReset(SystemRealtime):
    """MIDI System Reset (0xFF)."""
    _STATUS: int = _SYSTEM_RESET


# ===========================================================================
# System Exclusive -- deliberately not a Message subclass; see module
# docstring for why.
# ===========================================================================

class SysEx:
    """
    MIDI System Exclusive message.

    `data` is the payload only. Do not include 0xF0 and 0xF7; this class
    adds them when rendering the complete wire-format message via
    `to_bytes()`.

    SysEx has no MIDI channel and no single fixed USB-MIDI Code Index
    Number, so it intentionally does not implement the `Message`
    interface (`cin()`) and is not a subclass of `Message`. Send it with
    `MidiUsb.send_sysex()` (which handles the required 3-byte chunking
    and per-chunk CIN selection) or `MidiUart.send_sysex()` (which writes
    the raw bytes directly, since UART has no packet framing).
    """

    def __init__(self, data: list) -> None:
        self.data: list = list(data)
        for byte in self.data:
            if not 0 <= byte <= 127:
                raise ValueError("SysEx payload bytes must be 0-127")

    def to_bytes(self) -> list:
        return [_SYSEX_START] + self.data + [_SYSEX_END]

    def __repr__(self) -> str:
        return "<SysEx bytes=%s>" % (self.to_bytes(),)


# ===========================================================================
# USB MIDI interface
# ===========================================================================

class MidiUsb(MIDIInterface):
    """
    Self-initialising USB MIDI interface with `Message`/`SysEx`-aware send
    helpers.

    Extends `usb.device.midi.MIDIInterface`, which already provides the
    low-level `send_event(cin, midi0, midi1=0, midi2=0)` primitive used to
    transmit a single USB-MIDI Event Packet. The constructor registers
    itself with the USB device stack automatically, using the singleton
    from `usb.device.get()` -- there is no need to call
    `usb.device.get().init(...)` separately. This class also adds:

    - `send_message(msg)`: send any `Message` instance (`NoteOn`,
      `ControlChange`, `ProgramChange`, etc.) in a single call.
    - `send_sysex(msg)`: send a `SysEx` instance, automatically split
      into correctly CIN-tagged 3-byte USB-MIDI packets.

    Example::

        usb_midi = MidiUsb(product_str="My MIDI Controller")
        usb_midi.send_message(NoteOn(0, note=60, velocity=100))
        usb_midi.send_sysex(SysEx([0x7E, 0x00, 0x09, 0x01]))
    """

    def __init__(
        self,
        product_str: str = None,
        manufacturer_str: str = None,
        rxlen: int = 16,
        txlen: int = 16,
        builtin_driver: bool = True,
    ) -> None:
        """
        Arguments:
            product_str: Optional USB product string descriptor, shown by
                the host as the device name (for example, in a DAW's MIDI
                port list).
            manufacturer_str: Optional USB manufacturer string descriptor.
            rxlen: Receive buffer size in bytes, passed to
                `usb.device.midi.MIDIInterface`.
            txlen: Transmit buffer size in bytes, passed to
                `usb.device.midi.MIDIInterface`.
            builtin_driver: Passed to `usb.device.get().init()`. Keep this
                `True` unless you are also registering other custom USB
                interfaces that require it disabled.
        """
        if MIDIInterface is object:
            raise RuntimeError(
                "usb.device.midi.MIDIInterface is not available. Install "
                "it with `mpremote mip install usb-device-midi` on "
                "firmware with usb.device support."
            )

        super().__init__(rxlen=rxlen, txlen=txlen)

        init_kwargs = {"builtin_driver": builtin_driver}
        if product_str is not None:
            init_kwargs["product_str"] = product_str
        if manufacturer_str is not None:
            init_kwargs["manufacturer_str"] = manufacturer_str

        usb.device.get().init(self, **init_kwargs)

    def send_message(self, msg: Message) -> None:
        """Send a fixed-size `Message` as a single USB-MIDI Event Packet."""
        if not isinstance(msg, Message):
            raise TypeError(
                "send_message() expects a Message instance, got %r" % (msg,)
            )
        self.send_event(msg.cin(), *msg.to_bytes())

    def send_sysex(self, msg: SysEx) -> None:
        """Send a `SysEx` message, split into 3-byte USB-MIDI packets."""
        if not isinstance(msg, SysEx):
            raise TypeError(
                "send_sysex() expects a SysEx instance, got %r" % (msg,)
            )

        data: list = msg.to_bytes()
        chunk_count: int = (len(data) + 2) // 3

        for index in range(chunk_count):
            chunk: list = data[index * 3 : index * 3 + 3]
            is_last: bool = index == chunk_count - 1

            if is_last:
                cin: int = {1: 0x5, 2: 0x6, 3: 0x7}[len(chunk)]
            else:
                cin = 0x4

            b0, b1, b2 = (chunk + [0, 0, 0])[:3]
            self.send_event(cin, b0, b1, b2)


# ===========================================================================
# UART MIDI interface
# ===========================================================================

class MidiUart:
    """
    Self-initialising serial MIDI interface with `Message`/`SysEx`-aware
    send helpers, matching the `MidiUsb` API.

    Configures a `machine.UART` at the standard MIDI serial settings
    (31250 baud, 8 data bits, no parity, 1 stop bit) and writes messages
    to it as a plain byte stream -- there is no packet framing or Code
    Index Number involved, since that is a USB-MIDI concept only. This
    class exposes the same two methods as `MidiUsb`:

    - `send_message(msg)`: send any `Message` instance (`NoteOn`,
      `ControlChange`, `ProgramChange`, etc.) as its raw MIDI bytes.
    - `send_sysex(msg)`: send a `SysEx` instance as its raw MIDI bytes,
      including the 0xF0/0xF7 start/end bytes.

    Example::

        serial_midi = MidiUart(uart_id=1, tx_pin=4, rx_pin=5)
        serial_midi.send_message(NoteOn(0, note=60, velocity=100))
        serial_midi.send_sysex(SysEx([0x7E, 0x00, 0x09, 0x01]))
    """

    def __init__(
        self,
        uart_id: int,
        tx_pin: int,
        rx_pin: int,
        baudrate: int = _MIDI_UART_BAUDRATE,
    ) -> None:
        """
        Arguments:
            uart_id: The `machine.UART` peripheral number to use.
            tx_pin: GPIO pin number connected to the MIDI output circuit.
            rx_pin: GPIO pin number connected to the MIDI input circuit.
            baudrate: Serial baud rate. Defaults to the standard MIDI
                rate of 31250; only change this for non-standard links.
        """
        if UART is None or Pin is None:
            raise RuntimeError(
                "machine.UART/machine.Pin are not available. MidiUart "
                "requires MicroPython's machine module."
            )

        self._uart = UART(
            uart_id,
            baudrate=baudrate,
            tx=Pin(tx_pin),
            rx=Pin(rx_pin),
            bits=8,
            parity=None,
            stop=1,
        )

    def send_message(self, msg: Message) -> None:
        """Write a fixed-size `Message` as raw MIDI bytes."""
        if not isinstance(msg, Message):
            raise TypeError(
                "send_message() expects a Message instance, got %r" % (msg,)
            )
        self._uart.write(bytes(msg.to_bytes()))

    def send_sysex(self, msg: SysEx) -> None:
        """Write a `SysEx` message as raw MIDI bytes."""
        if not isinstance(msg, SysEx):
            raise TypeError(
                "send_sysex() expects a SysEx instance, got %r" % (msg,)
            )
        self._uart.write(bytes(msg.to_bytes()))
