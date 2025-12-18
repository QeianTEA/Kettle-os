# modules/img_loader.py
# Robust RLE image loader for Pico with optional bit-inversion fix.
# Exposes:
#   rle_decode_file_to_bytearray(path, expected_len, invert=False)
#   blit_rle_file(display, filepath, w, h, x=0, y=0, invert=False)
#   play_gif_from_index(display, index_dict, folder, center=True, loops=1, hold_last=True, invert=True)

import framebuf
import time
import os

# Default: invert decoded bytes to match display driver expectations.
# Set to False if your converter already produced images in the correct polarity.
DEFAULT_INVERT = True

def rle_decode_file_to_bytearray(path, expected_len, invert=False):
    """
    Read RLE file (pairs count,value) and expand into a bytearray of expected length.
    If invert=True, every decoded byte is XORed with 0xFF to flip pixel polarity.
    Returns bytearray(expected_len) padded with zeros if truncated/missing.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        print("rle_decode: failed to open", path, "err:", e)
        return bytearray(expected_len)  # return blank buffer (safe)

    out = bytearray(expected_len)
    i = 0
    j = 0
    n = len(data)
    # simple pairs (count, byte)
    while i + 1 < n and j < expected_len:
        cnt = data[i]
        val = data[i+1]
        i += 2
        # optionally invert value on the fly if that's slightly faster memory-wise
        if invert:
            val = val ^ 0xFF
        for k in range(cnt):
            if j >= expected_len:
                break
            out[j] = val
            j += 1

    # if j < expected_len we leave remainder as 0 (already padded)
    return out

def blit_rle_file(display, filepath, w, h, x=0, y=0, invert=None):
    """
    Decode RLE file and blit to display at (x,y).
    invert: bool or None. If None, uses DEFAULT_INVERT.
    Returns True on success, False on failure (e.g., file missing).
    """
    if invert is None:
        invert = DEFAULT_INVERT

    bytes_len = w * (h // 8)
    buf = rle_decode_file_to_bytearray(filepath, bytes_len, invert=invert)

    # create framebuffer
    try:
        fb = framebuf.FrameBuffer(buf, w, h, framebuf.MONO_VLSB)
    except Exception as e:
        print("blit_rle_file: FrameBuffer creation failed:", e)
        return False

    # Prefer display.blit_image if implemented (keeps abstraction)
    try:
        if hasattr(display, "blit_image"):
            display.blit_image(buf, w, h, x, y)
            display.show()
            return True
    except Exception as ex:
        print("blit_rle_file: display.blit_image failed:", ex)

    # fallback: call driver object if exposed
    try:
        oled = getattr(display, "oled", None)
        if oled is not None:
            oled.blit(fb, x, y)
            try:
                oled.show()
            except Exception:
                display.show()
            return True
    except Exception as e:
        print("blit_rle_file: direct oled.blit failed:", e)

    # final fallback: pixel-by-pixel drawing (slow)
    try:
        for yy in range(h):
            for xx in range(w):
                if fb.pixel(xx, yy):
                    display.oled.pixel(x + xx, y + yy, 1)
        display.show()
        return True
    except Exception as e:
        print("blit_rle_file: final fallback failed:", e)
        return False


def play_gif_from_index(display, index, folder, center=True, loops=1, hold_last=True, invert=None):
    """
    Play frames described in index (a dict like {'frames':[{'file':..., 'w':..., 'h':..., 'ms':...}, ...]})
    folder = path on device where .rle files are stored (e.g. "/images/splash")
    loops: number of times to play the sequence. If <=0, play forever.
    hold_last: if True, leave the last frame visible after playing; if False, clear on return.
    invert: override default inversion for playback (None uses DEFAULT_INVERT).
    Returns True if playback completed successfully, False if a file error occurred.
    """
    if invert is None:
        invert = DEFAULT_INVERT

    if not index or "frames" not in index:
        print("play_gif_from_index: invalid index")
        return False

    frames = index["frames"]
    if not frames:
        print("play_gif_from_index: no frames")
        return False

    play_count = 0
    infinite = (loops <= 0)

    try:
        while infinite or play_count < loops:
            for fr in frames:
                fname = fr.get("file")
                w = int(fr.get("w", 128))
                h = int(fr.get("h", 64))
                ms = int(fr.get("ms", 100))
                if not fname:
                    print("play_gif_from_index: skipping frame with no file")
                    continue

                path = folder.rstrip("/") + "/" + fname

                # check file exists
                try:
                    os.stat(path)
                except Exception as e:
                    print("play_gif_from_index: missing file:", path, "err:", e)
                    return False

                ok = blit_rle_file(display, path, w, h, 0, 0, invert=invert)
                if not ok:
                    print("play_gif_from_index: failed to blit", path)
                    return False

                if ms <= 0:
                    ms = 100
                time.sleep_ms(ms)

            play_count += 1

        # finished requested loops
        if not hold_last:
            display.clear()
            display.show()
        return True
    except Exception as e:
        print("play_gif_from_index: exception during playback:", e)
        return False
