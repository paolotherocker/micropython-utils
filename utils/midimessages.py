"""
midimessages.py
================

A MIDI message library for a MicroPython instance.

This module defines a `Message` class hierarchy for standard MIDI
messages. Each message exposes a `to_bytes()` method that returns the
raw MIDI bytes as a list of integers, ready to be passed directly to a
transport of your choice (for example, `usb.device.midi.MIDIInterface`
or `machine.UART`).

This module does not send messages itself; it only builds them.

Examples
--------

Build and send a Note On over a `machine.UART` configured for MIDI::

    import machine
    from midimessages import NoteOn

    uart = machine.UART(1, baudrate=31250,
                        tx=machine.Pin(4), rx=machine.Pin(5))
    message = NoteOn(note=60, velocity=100, channel=0)
    uart.write(bytes(message.to_bytes()))

Build and send a Control Change over a USB MIDI interface::

    import usb.device
    from usb.device.midi import MIDIInterface
    from midimessages import ControlChange

    usb_midi = MIDIInterface()
    usb.device.get().init(usb_midi, builtin_driver=True)
    message = ControlChange(controller=20, value=127, channel=0)
    usb_midi.send_event(0, message.cin, *message.to_bytes())

`cin` is the USB-MIDI Code Index Number for the message, exposed on every
concrete `Message` subclass for use with USB-MIDI Event Packet transports.
Consult the API of your installed `usb.device.midi.MIDIInterface` for the
exact send method and argument order it expects, since this has varied
between MicroPython releases.
"""

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
    Abstract base class for MIDI messages.

    Concrete subclasses implement `to_bytes()` and specify `cin`, the
    USB-MIDI Code Index Number. Channels are zero-based: channel=0 is
    MIDI channel 1, and channel=15 is MIDI channel 16.
    """

    cin = None

    def __init__(self, channel: int = 0) -> None:
        self.channel: int = _clamp_channel(channel)

    def to_bytes(self) -> list:
        """Return the raw MIDI bytes as a list of integers."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return "<%s bytes=%s>" % (self.__class__.__name__, list(self.to_bytes()))


class NoteOn(Message):
    """MIDI Note On message."""
    cin: int = _NOTE_ON

    def __init__(self, note: int, velocity: int = 127, channel: int = 0) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_ON << 4) | self.channel, self.note, self.velocity]


class NoteOff(Message):
    """MIDI Note Off message."""
    cin: int = _NOTE_OFF

    def __init__(self, note: int, velocity: int = 0, channel: int = 0) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.velocity: int = _clamp7(velocity, "velocity")

    def to_bytes(self) -> list:
        return [(_NOTE_OFF << 4) | self.channel, self.note, self.velocity]


class ControlChange(Message):
    """MIDI Control Change message."""
    cin: int = _CONTROL_CHANGE

    def __init__(self, controller: int, value: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.controller: int = _clamp7(controller, "controller")
        self.value: int = _clamp7(value, "value")

    def to_bytes(self) -> list:
        return [(_CONTROL_CHANGE << 4) | self.channel, self.controller, self.value]


class ProgramChange(Message):
    """MIDI Program Change message."""
    cin: int = _PROGRAM_CHANGE

    def __init__(self, program: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.program: int = _clamp7(program, "program")

    def to_bytes(self) -> list:
        return [(_PROGRAM_CHANGE << 4) | self.channel, self.program]


class ChannelAftertouch(Message):
    """MIDI channel pressure (monophonic aftertouch) message."""
    cin: int = _CHANNEL_AFTERTOUCH

    def __init__(self, pressure: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_CHANNEL_AFTERTOUCH << 4) | self.channel, self.pressure]


class PolyAftertouch(Message):
    """MIDI polyphonic key-pressure message."""
    cin: int = _POLY_AFTERTOUCH

    def __init__(self, note: int, pressure: int, channel: int = 0) -> None:
        super().__init__(channel)
        self.note: int = _clamp7(note, "note")
        self.pressure: int = _clamp7(pressure, "pressure")

    def to_bytes(self) -> list:
        return [(_POLY_AFTERTOUCH << 4) | self.channel, self.note, self.pressure]


class PitchBend(Message):
    """
    MIDI 14-bit pitch bend.

    `value` ranges from -8192 to 8191. Zero is centre/no bend.
    """
    cin: int = _PITCH_BEND

    def __init__(self, value: int = 0, channel: int = 0) -> None:
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


class SystemRealtime(Message):
    """Base class for single-byte MIDI system realtime messages."""
    cin: int = 0xF
    _STATUS = None

    def __init__(self) -> None:
        super().__init__(channel=0)

    def to_bytes(self) -> list:
        return [self._STATUS]


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


class SysEx(Message):
    """
    MIDI System Exclusive message.

    `data` is the payload only. Do not include 0xF0 and 0xF7; this class
    adds them when rendering the complete wire-format message.
    """
    cin = None

    def __init__(self, data: list) -> None:
        super().__init__(channel=0)
        self.data: list = list(data)
        for byte in self.data:
            if not 0 <= byte <= 127:
                raise ValueError("SysEx payload bytes must be 0-127")

    def to_bytes(self) -> list:
        return [_SYSEX_START] + self.data + [_SYSEX_END]
