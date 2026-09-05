"""Minimal MidiUsb smoke test.

Sends a Note On/Off pair on a loop over USB MIDI.
See ../../midi.py for the MidiUsb API.
"""

import time
from utils.midi import MidiUsb, NoteOn, NoteOff

CHANNEL = 0
NOTE = 60
VELOCITY = 100

midi_out = MidiUsb(product_str="Pico MIDI Controller", manufacturer_str="Paolo")

while True:
    midi_out.send_message(NoteOn(CHANNEL, note=NOTE, velocity=VELOCITY))
    print("note on")
    time.sleep(0.5)

    midi_out.send_message(NoteOff(CHANNEL, note=NOTE, velocity=0))
    print("note off")
    time.sleep(0.5)
