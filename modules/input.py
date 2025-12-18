# modules/input.py
from machine import Pin
import time

DEBOUNCE_MS = 50

class Buttons:
    def __init__(self, pins):
        self._pins = {}
        self._last_state = {}
        self._last_time = {}
        for name, gp in pins.items():
            p = Pin(gp, Pin.IN, Pin.PULL_UP)  # active low
            self._pins[name] = p
            self._last_state[name] = p.value()
            self._last_time[name] = time.ticks_ms()

    def _read_raw(self, name):
        return self._pins[name].value()

    def get_event(self):
        now = time.ticks_ms()
        for name in self._pins:
            raw = self._read_raw(name)

            # detect change
            if raw != self._last_state[name]:
                self._last_time[name] = now
                self._last_state[name] = raw
            else:
                # stable, check debounce
                if time.ticks_diff(now, self._last_time[name]) > DEBOUNCE_MS:
                    if raw == 0:  # pressed
                        # print to REPL so you can see activity
                        print("BUTTON:", name)

                        # block repeats until release
                        self._last_time[name] = now + 600
                        return name

        return None
