# games/kettlepaint.py
# Kettle Paint (updated UI & editor behavior)
# - 3 resolutions (128x64, 64x32, 32x16)
# - up to 25 save slots saved as RLE under /images/kettlepaint/
# - shoulder L draw (hold to draw), shoulder R erase (hold), confirm held SAVE_HOLD_MS to save
# - New menu flow: Main -> (CONF to slot-select) or RIGHT to Gallery (with 2s arrows hint)
#
# Relies on modules:
#   modules/display.py
#   modules/input.py
#   modules/img_loader.py
#
import time
import os

from modules import img_loader

GAME = {"name": "Kettle Paint"}

# ------------- CONFIG -------------
SAVE_FOLDER = "/images/kettlepaint"
MAX_SLOTS = 25

# Resolutions available (w,h)
RESOLUTIONS = [(128, 64), (64, 32), (32, 16)]

# UI timings (ms)
GALLERY_FILENAME_SHOW_MS = 2000    # now 2 seconds per new requirement
SAVE_HOLD_MS = 3000
SAVE_FEEDBACK_MS = 1000            # show "SAVED" screen for 1 second
CURSOR_BLINK_MS = 200             # blink at 1s intervals as requested

# ----------------- HELPERS -----------------

def _ensure_save_folder():
    try:
        os.stat(SAVE_FOLDER)
    except Exception:
        try:
            # ensure parent images folder exists
            try:
                os.stat("/images")
            except Exception:
                os.mkdir("/images")
            os.mkdir(SAVE_FOLDER)
        except Exception as e:
            print("Failed", e)


def _rle_encode_and_write(path, data_bytes):
    """RLE-encode the bytearray (list of ints 0..255) into (count,byte) pairs and write binary."""
    try:
        with open(path, "wb") as f:
            n = len(data_bytes)
            i = 0
            while i < n:
                v = data_bytes[i]
                cnt = 1
                i += 1
                while i < n and data_bytes[i] == v and cnt < 255:
                    cnt += 1
                    i += 1
                f.write(bytes((cnt, v)))
        return True
    except Exception as e:
        print("RLE write error:", e)
        return False


def _framebuf_from_canvas(canvas, w, h):
    """
    canvas: list of lists canvas[y][x] = 0/1
    returns: bytearray of length w * (h//8) in MONO_VLSB format
    """
    pages = h // 8
    out = bytearray(w * pages)
    idx = 0
    for x in range(w):
        for p in range(pages):
            byte = 0
            basey = p * 8
            for bit in range(8):
                y = basey + bit
                if y >= h:
                    continue
                if canvas[y][x]:
                    byte |= (1 << bit)
            out[idx] = byte
            idx += 1
    return out


def _framebuf_to_canvas(fb_bytes, w, h):
    """Inverse of _framebuf_from_canvas. fb_bytes length must be w*(h//8)."""
    pages = h // 8
    canvas = [[0 for _ in range(w)] for __ in range(h)]
    idx = 0
    for x in range(w):
        for p in range(pages):
            byte = fb_bytes[idx]
            idx += 1
            basey = p * 8
            for bit in range(8):
                y = basey + bit
                if y >= h:
                    continue
                canvas[y][x] = 1 if (byte >> bit) & 1 else 0
    return canvas


def _slot_path(slot):
    return SAVE_FOLDER + "/" + str(slot) + ".rle"


def _exists_slot(slot):
    try:
        os.stat(_slot_path(slot))
        return True
    except Exception:
        return False


# ----------------- UI / RENDER -----------------

def _draw_main_menu(display, res_index):
    """
    Main menu layout:
      Title
      up arrow
      selected resolution
      down arrow
    Left and right arrows on sides indicate enterable Gallery submenu.
    """
    display.clear()
    display.text("Kettle Paint", 2, 2)
    # up arrow
    display.text("^", display.width // 2 - 4, 16)
    # resolution
    w, h = RESOLUTIONS[res_index]
    res_text = "%dx%d" % (w, h)
    display.text(res_text, display.width // 2 - (len(res_text) * 4), 28)
    # down arrow
    display.text("v", display.width // 2 - 4, 40)
    # side arrows indicating submenu
    display.text("<", 0, display.height // 2 - 4)
    display.text(">", display.width - 8, display.height // 2 - 4)
    # hint
    display.text("L/R=Gallery ", 0, display.height - 10)
    display.show()


def _draw_slot_selector(display, res_index, slot_index):
    """After selecting resolution, user picks slot to overwrite (LEFT/RIGHT)."""
    display.clear()
    display.text("Pick Slot", 8, 8)
    s = "Slot: %d" % slot_index
    display.text(s, (display.width - len(s)*8)//2, 28)
    display.text("< >", 4, display.height - 8)
    display.text("L=back", 0, display.height - 18)
    display.show()


def _draw_gallery_preview(display, fb_bytes, w_img, h_img, show_filename=False, show_arrows=False):
    """
    fb_bytes: raw framebuffer bytes (length w*(h//8)) in MONO_VLSB ready to blit.
    show_filename: if string or True -> show filename/number on top (string allowed)
    show_arrows: if True, draw left/right arrows on sides to hint cycling
    """
    display.clear()
    # blit using framebuf in-memory
    try:
        import framebuf
        fbobj = framebuf.FrameBuffer(fb_bytes, w_img, h_img, framebuf.MONO_VLSB)
        x = (display.width - w_img) // 2
        y = (display.height - h_img) // 2
        # use display.blit_image if exists
        try:
            if hasattr(display, "blit_image"):
                display.blit_image(fb_bytes, w_img, h_img, x, y)
            else:
                oled = getattr(display, "oled", None)
                if oled is not None:
                    oled.blit(fbobj, x, y)
        except Exception:
            # fallback pixel draw
            for yy in range(h_img):
                for xx in range(w_img):
                    if fbobj.pixel(xx, yy):
                        try:
                            display.oled.pixel(x + xx, y + yy, 1)
                        except Exception:
                            pass
    except Exception as e:
        print("Gallery blit in-memory failed:", e)
        display.clear()
        display.text("Preview error", 10, 30)

    if show_filename:
        # show number or string; center top
        txt = str(show_filename)
        display.text(txt, 2, 0)

    if show_arrows:
        display.text("<", 0, display.height // 2 - 4)
        display.text(">", display.width - 8, display.height // 2 - 4)

    display.show()


# ----------------- EDITOR -----------------

def _editor_loop(display, buttons, res_index, slot_index):
    """
    Editor main loop. Returns True if saved (and file written), False if canceled/back to menu.
    """
    w, h = RESOLUTIONS[res_index]
    # create canvas
    canvas = [[0 for _ in range(w)] for __ in range(h)]

    # load file if exists
    path = _slot_path(slot_index)
    if _exists_slot(slot_index):
        expected_len = w * (h // 8)
        fb = img_loader.rle_decode_file_to_bytearray(path, expected_len, invert=True)
        canvas = _framebuf_to_canvas(fb, w, h)

    # cursor
    cx = 0
    cy = 0
    last_blink = time.ticks_ms()
    cursor_visible = True

    # pins for hold detection
    pins = getattr(buttons, "_pins", {})
    pin_draw = pins.get("SHOULDER_L")
    pin_erase = pins.get("SHOULDER_R")
    pin_confirm = pins.get("CONFIRM")

    confirm_start = None

    # Editor loop
    while True:
        # handle blinking timer
        now = time.ticks_ms()
        if time.ticks_diff(now, last_blink) >= CURSOR_BLINK_MS:
            cursor_visible = not cursor_visible
            last_blink = now

        # input (non-blocking)
        evt = buttons.get_event()
        if evt == "LEFT":
            cx = max(0, cx - 1)
        elif evt == "RIGHT":
            cx = min(w - 1, cx + 1)
        elif evt == "UP":
            cy = max(0, cy - 1)
        elif evt == "DOWN":
            cy = min(h - 1, cy + 1)
        elif evt == "SHOULDER_L":
            canvas[cy][cx] = 1
        elif evt == "SHOULDER_R":
            canvas[cy][cx] = 0
        elif evt == "CONFIRM":
            # begin hold timer if not started
            if confirm_start is None:
                confirm_start = time.ticks_ms()
        else:
            # other events: no action
            pass

        # HOLD drawing/erasing via raw pin reads (so hold works)
        try:
            if pin_draw and pin_draw.value() == 0:
                canvas[cy][cx] = 1
            if pin_erase and pin_erase.value() == 0:
                canvas[cy][cx] = 0
        except Exception:
            pass

        # Confirm hold logic
        if confirm_start is not None:
            # ensure confirm still held and no other buttons are down
            held = False
            try:
                if pin_confirm and pin_confirm.value() == 0:
                    held = True
            except Exception:
                held = False

            other_down = False
            try:
                for name, p in pins.items():
                    if name == "CONFIRM":
                        continue
                    if p.value() == 0:
                        other_down = True
                        break
            except Exception:
                other_down = False

            if not held or other_down:
                confirm_start = None  # cancel
            else:
                if time.ticks_diff(time.ticks_ms(), confirm_start) >= SAVE_HOLD_MS:
                    # Save
                    ok = _save_canvas_to_slot(canvas, w, h, slot_index)
                    # Show "SAVED" screen for SAVE_FEEDBACK_MS (1s) to let user release confirm
                    display.clear()
                    msg = "SAVED"
                    display.text(msg, (display.width - len(msg) * 8) // 2, display.height // 2 - 4)
                    display.show()
                    time.sleep_ms(SAVE_FEEDBACK_MS)
                    return ok  # return to menu after the brief "SAVED" screen

        # render canvas only with cursor blink state
        _render_canvas_only(display, canvas, w, h, cx, cy, cursor_visible)

        time.sleep_ms(20)


def _render_canvas_only(display, canvas, w, h, cx, cy, cursor_visible):
    """
    Render scaled canvas to full screen, draw cursor by inverting pixel under it when cursor_visible==True.
    No extra HUD (as requested).
    """
    display.clear()
    sx = display.width // w
    sy = display.height // h
    scale = sx if sx == sy else min(sx, sy)

    for y in range(h):
        for x in range(w):
            v = canvas[y][x]
            # cursor invert if visible
            if x == cx and y == cy and cursor_visible:
                v = 0 if v else 1
            if v:
                display.fill_rect(x * scale, y * scale, scale, scale, 1)
            else:
                # background left clear
                pass
    display.show()


def _save_canvas_to_slot(canvas, w, h, slot):
    # pack to framebuf bytes
    fb = _framebuf_from_canvas(canvas, w, h)
    # invert bytes to match img_loader.DEFAULT_INVERT
    inv = bytearray(len(fb))
    for i, b in enumerate(fb):
        inv[i] = b ^ 0xFF
    _ensure_save_folder()
    path = _slot_path(slot)
    ok = _rle_encode_and_write(path, inv)
    return ok


# ----------------- GALLERY -----------------

def _gallery_loop(display, buttons, res_index, start_slot):
    """
    Gallery behavior:
      - on enter, show file start_slot preview. Show file number and side arrows for 2s.
      - LEFT/RIGHT cycle slot (wrap). Each change resets the 2s number/arrows display.
      - CONFIRM opens editor for that slot.
      - SHOULDER_L returns to main menu.
    """
    w, h = RESOLUTIONS[res_index]
    slot = start_slot
    show_until = time.ticks_add(time.ticks_ms(), GALLERY_FILENAME_SHOW_MS)

    while True:
        evt = buttons.get_event()
        if evt == "LEFT":
            slot = (slot - 1) % MAX_SLOTS
            show_until = time.ticks_add(time.ticks_ms(), GALLERY_FILENAME_SHOW_MS)
        elif evt == "RIGHT":
            slot = (slot + 1) % MAX_SLOTS
            show_until = time.ticks_add(time.ticks_ms(), GALLERY_FILENAME_SHOW_MS)
        elif evt == "SHOULDER_L":
            return False  # back to main menu
        elif evt == "CONFIRM":
            # open editor (loads existing or blank)
            saved = _editor_loop(display, buttons, res_index, slot)
            return saved

        # draw preview / no-data
        if _exists_slot(slot):
            expected_len = w * (h // 8)
            fb = img_loader.rle_decode_file_to_bytearray(_slot_path(slot), expected_len, invert=True)
            # show filename/arrows only if within show_until window
            show_flag = time.ticks_diff(show_until, time.ticks_ms()) > 0
            fname = str(slot) if show_flag else None
            _draw_gallery_preview(display, fb, w, h, show_filename=fname, show_arrows=show_flag)
        else:
            # no data
            # if show_flag, show number on top even if no-data
            show_flag = time.ticks_diff(show_until, time.ticks_ms()) > 0
            display.clear()
            if show_flag:
                display.text(str(slot), 2, 0)
            display.text("No data", 10, 28)
            if show_flag:
                display.text("< >", 4, display.height // 2 + 8)
            display.text("L=back", 0, display.height - 8)
            display.show()

        time.sleep_ms(40)


# ----------------- TOP-LEVEL RUN -----------------

def run(display, buttons):
    """
    New menu flow:
      - Main screen: choose resolution (UP/DOWN). RIGHT enters Gallery. CONF goes to slot-select for saving.
      - Slot-select: LEFT/RIGHT choose slot; CONF -> open editor for that slot. SHOULDER_L -> back to main menu.
      - Gallery: see _gallery_loop above.
      - SHOULDER_L from main -> exit Kettle Paint (return to overall menu)
    """
    _ensure_save_folder()

    res_index = 0
    slot_index = 0

    while True:
        # MAIN MENU
        _draw_main_menu(display, res_index)

        evt = buttons.get_event()
        if evt == "UP":
            res_index = (res_index - 1) % len(RESOLUTIONS)
        elif evt == "DOWN":
            res_index = (res_index + 1) % len(RESOLUTIONS)
        elif evt == "RIGHT" or evt == "LEFT":
            # enter gallery with current resolution and current slot; gallery shows arrows for 2s on entry
            saved = _gallery_loop(display, buttons, res_index, slot_index)
            # if saved True, we might want to show a short message but editor handles the "SAVED" screen
            # continue to main menu after gallery returns
        elif evt == "CONFIRM":
            # go to slot selector for chosen resolution
            while True:
                _draw_slot_selector(display, res_index, slot_index)
                evt2 = buttons.get_event()
                if evt2 == "LEFT":
                    slot_index = (slot_index - 1) % MAX_SLOTS
                elif evt2 == "RIGHT":
                    slot_index = (slot_index + 1) % MAX_SLOTS
                elif evt2 == "SHOULDER_L":
                    break  # back to main menu
                elif evt2 == "CONFIRM":
                    # open editor for selected resolution & slot
                    saved = _editor_loop(display, buttons, res_index, slot_index)
                    # after editor returns (save screen shown there), return to main menu
                    break
                time.sleep_ms(60)
        elif evt == "SHOULDER_L":
            # exit Kettle Paint entirely (back to main game menu)
            return
        time.sleep_ms(60)

