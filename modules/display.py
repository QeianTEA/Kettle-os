# modules/display.py
from machine import I2C, Pin
import utime

# Try to import drivers (these files must exist on the Pico)
_has_sh1106 = False
_has_ssd1306 = False
try:
    import sh1106
    _has_sh1106 = True
except Exception:
    _has_sh1106 = False

try:
    import ssd1306
    _has_ssd1306 = True
except Exception:
    _has_ssd1306 = False

class Display:
    def __init__(self, sda_pin=4, scl_pin=5, width=128, height=64, i2c_id=0, freq=400000, addr=None):
        self.width = width
        self.height = height
        # create I2C
        try:
            self.i2c = I2C(i2c_id, scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
        except Exception as e:
            raise Exception("Failed to init I2C on pins SDA={} SCL={}: {}".format(sda_pin, scl_pin, e))

        # scan
        buses = self.i2c.scan()
        print("I2C scan result:", buses)
        if not buses:
            raise OSError("No I2C devices found. Check wiring, power (3.3V) and pins. Scan returned []")

        # choose address
        if addr is None:
            # prefer 0x3C then 0x3D if present
            if 0x3C in buses:
                self.addr = 0x3C
            elif 0x3D in buses:
                self.addr = 0x3D
            else:
                # pick first device found but warn user
                self.addr = buses[0]
                print("Warning: using first I2C address found: 0x{:02x}".format(self.addr))
        else:
            self.addr = addr

        # attempt to instantiate driver (SH1106 preferred for many 1.3" modules)
        self.oled = None
        last_error = None

        if _has_sh1106:
            try:
                print("Attempting SH1106 driver at address 0x{:02x}".format(self.addr))
                # SH1106_I2C signature: (width, height, i2c, res=None, addr=0x3c, rotate=0, external_vcc=False, delay=0)
                self.oled = sh1106.SH1106_I2C(width, height, self.i2c, res=None, addr=self.addr)
                print("Initialized SH1106 driver OK")
            except Exception as e:
                last_error = e
                print("SH1106 init failed:", e)

        if self.oled is None and _has_ssd1306:
            try:
                print("Attempting SSD1306 driver at address 0x{:02x}".format(self.addr))
                # SSD1306_I2C signature varies; common form SSD1306_I2C(width,height,i2c)
                try:
                    self.oled = ssd1306.SSD1306_I2C(width, height, self.i2c, addr=self.addr)
                except TypeError:
                    # older versions might not accept addr param
                    self.oled = ssd1306.SSD1306_I2C(width, height, self.i2c)
                print("Initialized SSD1306 driver OK")
            except Exception as e:
                last_error = e
                print("SSD1306 init failed:", e)

        if self.oled is None:
            raise OSError("Could not initialize display driver. Last error: {}".format(last_error))

        # basic helpers - adapted to match earlier API
        self.clear()
        self.show()

    def clear(self):
        self.oled.fill(0)

    def show(self):
        self.oled.show()
        
    def invert(self, state):
        """
        Safe invert() wrapper. SH1106 often does NOT support invert, so this
        function will simply ignore the call instead of crashing.
        """
        try:
            # SSD1306 supports invert()
            self.oled.invert(state)
        except Exception:
            # SH1106 usually lacks invert(); safe no-op
            pass

    def text(self, s, x=0, y=0):
        self.oled.text(s, x, y)

    def rect(self, x, y, w, h, color=1):
        self.oled.rect(x, y, w, h, color)

    def fill_rect(self, x, y, w, h, color=1):
        self.oled.fill_rect(x, y, w, h, color)

    def blit_image(self, img_bytes, w, h, x=0, y=0):
        import framebuf
        fb = framebuf.FrameBuffer(img_bytes, w, h, framebuf.MONO_VLSB)
        try:
            self.oled.blit(fb, x, y)
        except Exception:
            # Some SH1106 implementations use different framebuffer orientation; catch errors.
            self.oled.blit(fb, x, y)
