"""Minimal MidiUart smoke test.

Sends a Note On/Off pair on a loop over a MIDI UART circuit.
See ../../midi.py for the MidiUart API.
"""

import time
from utils.midi import MidiUart, NoteOn, NoteOff

CHANNEL = 0
NOTE = 60
VELOCITY = 100

midi_out = MidiUart(uart_id=0, tx_pin=0, rx_pin=1)

while True:
    midi_out.send_message(NoteOn(CHANNEL, note=NOTE, velocity=VELOCITY))
    print("note on")
    time.sleep(0.5)

    midi_out.send_message(NoteOff(CHANNEL, note=NOTE, velocity=0))
    print("note off")
    time.sleep(0.5)
