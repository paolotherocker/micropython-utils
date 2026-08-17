from machine import Pin
from micropython import const
from utils.button import Button, ButtonEvent
import time

BUTTON_PIN = const(15)  # GPIO pin the button is connected to

button = Button(BUTTON_PIN, Pin.PULL_UP)
led = Pin(25, Pin.OUT)

button_event = ButtonEvent.NONE
state = False

while True:
    button_event = button.consume()

    if button.is_pressed() == True:
        led.on()
    else:
        led.off()

    if button_event != ButtonEvent.NONE:
        if button_event == ButtonEvent.PRESSED:
            print("pressed")
        elif button_event == ButtonEvent.SHORT_PRESS:
            print("short")
        elif button_event == ButtonEvent.LONG_PRESS:
            print("long")

    time.sleep_ms(10)
