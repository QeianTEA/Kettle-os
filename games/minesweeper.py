# games/minesweeper/minesweeper.py (optimized)
# Minesweeper adapted for Pico 128x64 OLED (optimized rendering & input)
# Controls:
#   D-PAD: move selection
#   SHOULDER_L: reveal / "click"
#   SHOULDER_R: flag (in-game) OR cycle difficulty (on press-to-play screen)
#   CONFIRM: back to menu (or start)

import time
import random

GAME = {'name': 'Mike sweeper'}

# -----------------------
# CONFIG (tweak these)
# -----------------------
SCREEN_W = 128
SCREEN_H = 64
HUD_H = 8                 # reserved pixels for HUD at top (never obstructed)
TILE = 6                  # 6x6 pixel tile
PLAY_H_PIX = SCREEN_H - HUD_H

DIFFICULTIES = [
    ('EASY',   9, 6, 10),
    ('NORMAL', 13, 8, 24),
    ('HARD',   17, 9, 40),
]
DEFAULT_DIFF = 1  # NORMAL

# 3x5 font bitmaps precomputed as list of (dx,dy) pixels for each digit char
_FONT_3x5_BITS = {
    '0': [ (0,0),(1,0),(2,0),
           (0,1),(2,1),
           (0,2),(2,2),
           (0,3),(2,3),
           (0,4),(1,4),(2,4) ],
    '1': [ (1,0),
           (1,1),
           (1,2),
           (1,3),
           (1,4),(0,4),(2,4) ],
    '2': [ (0,0),(1,0),(2,0),
           (2,1),
           (0,2),(1,2),(2,2),
           (0,3),
           (0,4),(1,4),(2,4) ],
    '3': [ (0,0),(1,0),(2,0),
           (2,1),
           (1,2),(2,2),
           (2,3),
           (0,4),(1,4),(2,4) ],
    '4': [ (0,0),(2,0),
           (0,1),(2,1),
           (0,2),(1,2),(2,2),
           (2,3),
           (2,4) ],
    '5': [ (0,0),(1,0),(2,0),
           (0,1),
           (0,2),(1,2),(2,2),
           (2,3),
           (0,4),(1,4),(2,4) ],
    '6': [ (0,0),(1,0),(2,0),
           (0,1),
           (0,2),(1,2),(2,2),
           (0,3),(2,3),
           (0,4),(1,4),(2,4) ],
    '7': [ (0,0),(1,0),(2,0),
           (2,1),
           (1,2),
           (1,3),
           (1,4) ],
    '8': [ (0,0),(1,0),(2,0),
           (0,1),(2,1),
           (0,2),(1,2),(2,2),
           (0,3),(2,3),
           (0,4),(1,4),(2,4) ],
}

# -----------------------
# Small helpers
# -----------------------
def _randint(a, b):
    try:
        return random.randint(a, b)
    except Exception:
        try:
            return random.randrange(a, b+1)
        except Exception:
            width = b - a + 1
            r = random.getrandbits(16) % width
            return a + r

# -----------------------
# MAIN
# -----------------------
def run(display, buttons):
    diff_index = DEFAULT_DIFF

    # selection screen
    while True:
        display.clear()
        title = "Minesweeper"
        display.text(title, (SCREEN_W - len(title)*8)//2, 12)
        dname = DIFFICULTIES[diff_index][0]
        display.text("Diff: %s" % dname, 12, 28)
        display.text("R change", 12, 44)
        display.text("L start", 12, 52)
        display.show()

        ev = buttons.get_event()
        if ev == 'SHOULDER_R':
            diff_index = (diff_index + 1) % len(DIFFICULTIES)
            time.sleep_ms(150)
            continue
        if ev == 'SHOULDER_L' or ev == 'CONFIRM':
            break
        time.sleep_ms(30)

    # get params
    _, COLS, ROWS, MCOUNT = DIFFICULTIES[diff_index]

    # compute offsets once
    play_w = COLS * TILE
    play_h = ROWS * TILE
    offset_x = max(0, (SCREEN_W - play_w)//2)
    offset_y = HUD_H + max(0, ((PLAY_H_PIX - play_h)//2))

    # allocate arrays
    has_mine = [[False]*COLS for _ in range(ROWS)]
    revealed = [[False]*COLS for _ in range(ROWS)]
    flagged = [[False]*COLS for _ in range(ROWS)]
    numbers = [[0]*COLS for _ in range(ROWS)]

    # fast-updated counters & flags
    flags_left = MCOUNT
    first_click = True
    cursor_x = COLS//2
    cursor_y = ROWS-1
    game_over = False
    boom_time = None

    # local refs to reduce attribute lookup cost
    fill_rect = display.fill_rect
    rect = display.rect
    text = display.text
    show = display.show
    clear = display.clear

    # detect whether display.fill_rect accepts 'color' arg (test once)
    supports_color = True
    try:
        # draw 1px then clear it
        display.fill_rect(0, 0, 1, 1, 1)
        display.fill_rect(0, 0, 1, 1, 0)
    except TypeError:
        supports_color = False

    # helper functions optimized and local-closure bound
    def _in_bounds(x,y):
        return 0 <= x < COLS and 0 <= y < ROWS

    # neighbors inline as a list (avoids generator overhead)
    neighbor_offsets = [(-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)]

    def _place_mines_safe(sx, sy):
        nonlocal numbers
        coords = [(x,y) for x in range(COLS) for y in range(ROWS)]
        forbidden = {(sx,sy)}
        for dx,dy in neighbor_offsets:
            nx, ny = sx + dx, sy + dy
            if 0 <= nx < COLS and 0 <= ny < ROWS:
                forbidden.add((nx,ny))
        avail = [c for c in coords if c not in forbidden]
        # pick MCOUNT random unique
        for i in range(MCOUNT):
            if not avail:
                break
            idx = _randint(0, len(avail)-1)
            x,y = avail.pop(idx)
            has_mine[y][x] = True
        # compute numbers (neighbor counts)
        for y in range(ROWS):
            rowm = has_mine[y]
            for x in range(COLS):
                if rowm[x]:
                    numbers[y][x] = -1
                else:
                    cnt = 0
                    for dx,dy in neighbor_offsets:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < COLS and 0 <= ny < ROWS and has_mine[ny][nx]:
                            cnt += 1
                    numbers[y][x] = cnt

    # optimized reveal (list queue)
    def _reveal_cell(rx, ry):
        nonlocal first_click, game_over, flags_left
        if revealed[ry][rx] or flagged[ry][rx]:
            return
        if first_click:
            first_click = False
            _place_mines_safe(rx, ry)
        revealed[ry][rx] = True
        if has_mine[ry][rx]:
            game_over = True
            _reveal_all_bombs(rx, ry)
            return
        if numbers[ry][rx] == 0:
            q = [(rx,ry)]
            qi = 0
            while qi < len(q):
                cx, cy = q[qi]; qi += 1
                for dx,dy in neighbor_offsets:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < COLS and 0 <= ny < ROWS:
                        if not revealed[ny][nx] and not flagged[ny][nx]:
                            revealed[ny][nx] = True
                            if numbers[ny][nx] == 0:
                                q.append((nx, ny))

    def _toggle_flag(tx, ty):
        nonlocal flags_left
        if revealed[ty][tx]:
            return
        if flagged[ty][tx]:
            flagged[ty][tx] = False
            flags_left += 1
        else:
            if flags_left <= 0:
                return
            flagged[ty][tx] = True
            flags_left -= 1

    # optimized bomb reveal + blink (uses fewer renders)
    def _reveal_all_bombs(expl_x=None, expl_y=None):
        nonlocal boom_time
        # reveal mines logically
        for y in range(ROWS):
            mr = has_mine[y]
            rv = revealed[y]
            for x in range(COLS):
                if mr[x]:
                    rv[x] = True
        # start blink period (we'll let main loop handle drawing/bomb timing)
        boom_time = time.ticks_ms()

    def _check_win():
        for y in range(ROWS):
            for x in range(COLS):
                if not has_mine[y][x] and not revealed[y][x]:
                    return False
        return True

    # fast drawing helpers using precomputed font bit pixels
    def _draw_digit_at(disp, ch, sx, sy, color=1):
        pixs = _FONT_3x5_BITS.get(ch)
        if not pixs: 
            return
        if supports_color:
            for dx,dy in pixs:
                disp.fill_rect(sx + dx, sy + dy, 1, 1, color)
        else:
            for dx,dy in pixs:
                disp.fill_rect(sx + dx, sy + dy, 1, 1)

    # Enabled dirty rendering: only draw when something changed
    dirty = True  # initial draw
    last_cursor = (cursor_x, cursor_y)
    last_flags_left = flags_left

    # main loop: faster polling but render only when dirty
    while True:
        # poll inputs frequently
        ev = buttons.get_event()
        state_changed = False

        if ev == 'UP':
            if cursor_y > 0:
                cursor_y -= 1; state_changed = True
        elif ev == 'DOWN':
            if cursor_y < ROWS-1:
                cursor_y += 1; state_changed = True
        elif ev == 'LEFT':
            if cursor_x > 0:
                cursor_x -= 1; state_changed = True
        elif ev == 'RIGHT':
            if cursor_x < COLS-1:
                cursor_x += 1; state_changed = True
        elif ev == 'SHOULDER_L':
            if not revealed[cursor_y][cursor_x] and not flagged[cursor_y][cursor_x]:
                _reveal_cell(cursor_x, cursor_y)
                state_changed = True
        elif ev == 'SHOULDER_R':
            _toggle_flag(cursor_x, cursor_y)
            state_changed = True
        #elif ev == 'CONFIRM':
            #return

        # if game over and boom_time set, after 3 seconds return to menu automatically
        if game_over and boom_time is not None:
            if time.ticks_diff(time.ticks_ms(), boom_time) > 3000:
                return

        # win check
        if not game_over and _check_win():
            # show small win and return after short pause
            clear()
            text("YOU WIN", (SCREEN_W - 8*7)//2, 20)
            show()
            time.sleep(0.8)
            return

        # determine if we should redraw
        if state_changed:
            dirty = True

        # Also redraw periodically to allow bomb blink animation frames (if game_over)
        if game_over and boom_time is not None:
            # determine blink phase (toggle every 200ms)
            phase = (time.ticks_diff(time.ticks_ms(), boom_time) // 200) % 2
            # Force redraw every blink
            dirty = True
        else:
            phase = 0

        if dirty:
            # render whole screen (fast path: inline loops, local refs)
            clear()
            # HUD (clear top)
            if supports_color:
                fill_rect(0, 0, SCREEN_W, HUD_H, 0)
            else:
                fill_rect(0, 0, SCREEN_W, HUD_H)
            text("F:%d" % flags_left, 0, 0)
            text(DIFFICULTIES[diff_index][0][:3], SCREEN_W - 28, 0)

            # board draw
            for y in range(ROWS):
                hr = has_mine[y]
                rv = revealed[y]
                fg = flagged[y]
                nr = numbers[y]
                for x in range(COLS):
                    px = offset_x + x * TILE
                    py = offset_y + y * TILE
                    sel = (x == cursor_x and y == cursor_y and not game_over)
                    if sel:
                        # invert tile background: fill full tile
                        if supports_color:
                            fill_rect(px, py, TILE, TILE, 1)
                        else:
                            fill_rect(px, py, TILE, TILE)
                        draw_color = 0
                    else:
                        # unrevealed border
                        draw_color = 1

                    if not rv[x]:
                        # unrevealed tile
                        if not sel:
                            rect(px, py, TILE, TILE)
                            if fg[x]:
                                _draw_flag_at(display=display, sx=px+1, sy=py+1, color=draw_color)
                        else:
                            if fg[x]:
                                _draw_flag_at(display=display, sx=px+1, sy=py+1, color=draw_color)
                        # hide mines when unrevealed
                    else:
                        # revealed tile: clear interior (color 0)
                        if supports_color:
                            fill_rect(px+1, py+1, TILE-2, TILE-2, 0)
                        else:
                            fill_rect(px+1, py+1, TILE-2, TILE-2)
                        if hr[x]:
                            # mine - draw filled square
                            if supports_color:
                                fill_rect(px+1, py+1, TILE-2, TILE-2, 1)
                            else:
                                fill_rect(px+1, py+1, TILE-2, TILE-2)
                        else:
                            n = nr[x]
                            if n > 0:
                                sx = px + (TILE - 3)//2
                                sy = py + (TILE - 5)//2
                                # when selected use draw_color=0 already handled by sel
                                _draw_digit_at(display, str(n), sx, sy, color= (0 if sel else 1))

            # special: if game_over and boom_time set, ensure bombs blink:
            if game_over and boom_time is not None:
                # blink phase: if phase==0 draw bombs; if phase==1 hide bombs (we already reveal logically)
                # we simply redraw bombs as filled squares when phase==0 (already done by revealed==True)
                # draw BOOM message a bit higher
                text("BOOM!", (SCREEN_W - 8*4)//2, 0)

            show()
            dirty = False

        # small sleep to allow other operations; keep small for responsiveness
        time.sleep_ms(20)

# helper used above for drawing flags (kept separate to avoid heavy inlines)
def _draw_flag_at(display, sx, sy, color=1):
    # draw 3x5-ish flag faster with fill_rect single pixels
    try:
        display.fill_rect(sx+1, sy+0, 1, 1, color)
        display.fill_rect(sx+1, sy+1, 1, 1, color)
        display.fill_rect(sx+1, sy+2, 1, 1, color)
        display.fill_rect(sx+2, sy+0, 1, 1, color)
        display.fill_rect(sx+2, sy+1, 1, 1, color)
    except TypeError:
        # fallback
        display.fill_rect(sx+1, sy+0, 1, 1)
        display.fill_rect(sx+1, sy+1, 1, 1)
        display.fill_rect(sx+1, sy+2, 1, 1)
        display.fill_rect(sx+2, sy+0, 1, 1)
        display.fill_rect(sx+2, sy+1, 1, 1)

def _draw_digit_at(display, ch, sx, sy, color=1):
    pixs = _FONT_3x5_BITS.get(ch)
    if not pixs:
        return
    try:
        for dx,dy in pixs:
            display.fill_rect(sx + dx, sy + dy, 1, 1, color)
    except TypeError:
        for dx,dy in pixs:
            display.fill_rect(sx + dx, sy + dy, 1, 1)
