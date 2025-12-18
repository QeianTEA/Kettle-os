# games/volfied.py
# Volfied-like for Pico (flexible CELL size)
# Uses Display methods: clear(), show(), text(), rect(), fill_rect(), invert()
# Buttons: get_event() returning 'UP','DOWN','LEFT','RIGHT','CONFIRM', 'SHOULDER_L'...
#
# Exposes GAME dict and run(display, buttons)

import time
import random
import math

GAME = {'name': 'Volfied'}

# ---------- CONFIG ----------
CELL = 4                # change this to resize cells (4, 6, 8, ...)
W_PIX = 128
H_PIX = 64
GRID_W = W_PIX // CELL
GRID_H = H_PIX // CELL

TARGET_PERCENT = 85
INITIAL_ENEMIES = 1
MAX_LEVEL = 8

# Enemy "base types" - (name, base_radius_px, base_speed_pixels_per_tick)
_ENEMY_TYPES = [
    ('tiny_speedy', 1, 2),
    ('small_fast', 2, 1.5),
    ('medium', 3, 1.0),
    ('big_slow', 5, 0.5),
]

# Trail blink interval (ms) to help visibility at low CELL sizes
TRAIL_BLINK_MS = 500

# Wave animation for captured interior cells (milliseconds per step)
WAVE_MS = 200
WAVE_STEPS = 4   # number of phases in the ripple


# ---------- PUBLIC ENTRY ----------
def run(display, buttons):
    # initialize fresh map with border claimed
    def make_blank_grid():
        g = [[0 for _ in range(GRID_W)] for _ in range(GRID_H)]
        for x in range(GRID_W):
            g[0][x] = 1
            g[GRID_H - 1][x] = 1
        for y in range(GRID_H):
            g[y][0] = 1
            g[y][GRID_W - 1] = 1
        return g

    grid = make_blank_grid()
    level = 1

    # player start cell (top-left-ish on border)
    px, py = 1, 0

    # enemies spawn near center to avoid edge-stuck
    enemies = _make_enemies(level, INITIAL_ENEMIES, grid)

    drawing = False
    trail_cells = set()

    # trail blink state
    last_blink_t = time.ticks_ms()
    trail_visible = True

    # intro
    _show_message(display, "Volfied", "Press to start")
    while True:
        ev = buttons.get_event()
        if ev == 'CONFIRM':
            break
        time.sleep_ms(40)

    game_over = False

    while True:
        now = time.ticks_ms()

        # toggle trail blink periodically (helps visibility on small CELL)
        if time.ticks_diff(now, last_blink_t) >= TRAIL_BLINK_MS:
            last_blink_t = now
            trail_visible = not trail_visible

        # input
        ev = buttons.get_event()
        if ev == 'SHOULDER_L':
            return  # exit to menu

        moved = False
        if ev == 'UP':
            nx, ny = px, py - 1
            moved = True
        elif ev == 'DOWN':
            nx, ny = px, py + 1
            moved = True
        elif ev == 'LEFT':
            nx, ny = px - 1, py
            moved = True
        elif ev == 'RIGHT':
            nx, ny = px + 1, py
            moved = True
        else:
            nx, ny = px, py

        if moved:
            if 0 <= nx < GRID_W and 0 <= ny < GRID_H:
                px_prev, py_prev = px, py
                px, py = nx, ny
                cur = grid[py][px]
                if cur == 0:
                    drawing = True
                    grid[py][px] = 2
                    trail_cells.add((py, px))
                elif cur == 1 and drawing:
                    # finished loop -> capture area (apply immediately and render)
                    _capture_area(grid, trail_cells, enemies)
                    trail_cells.clear()
                    drawing = False
                    # show an immediate full-fill snapshot so capture is clear to the player
                    # duration short so we don't stall gameplay (200 ms)
                    _show_capture_snapshot(display, grid, enemies, px, py, level, duration_ms=200)


        # update enemies (pass player pixel center)
        player_cx = px * CELL + CELL // 2
        player_cy = py * CELL + CELL // 2
        _update_enemies(enemies, grid, player_cx, player_cy, now)

        # collisions
        if _check_enemy_trail_collision(enemies, trail_cells):
            game_over = True
        if grid[py][px] != 1 and _enemy_hits_cell_any(enemies, py, px):
            game_over = True

        # render (trail blink toggles)
        _render(display, grid, enemies, px, py, level, trail_cells, trail_visible, now)

        if game_over:
            _show_message(display, "Game Over", "Press to exit")
            while True:
                if buttons.get_event() == 'CONFIRM':
                    return
                time.sleep_ms(40)

        # level up
        pct = _capture_percent(grid)
        if pct >= TARGET_PERCENT:
            level += 1
            if level > MAX_LEVEL:
                _show_message(display, "You Win!", "Press CONF")
                while True:
                    if buttons.get_event() == 'CONFIRM':
                        return
                    time.sleep_ms(40)
            # reset map and player, then spawn stronger enemies
            grid = make_blank_grid()
            px, py = 1, 0
            trail_cells.clear()
            drawing = False
            enemies = _make_enemies(level, INITIAL_ENEMIES + (level // 2), grid)

            # show Level N on a blank screen (no flashing)
            level_msg = "Level %d" % level
            display.clear()
            lx = max(0, (W_PIX - len(level_msg) * 8) // 2)
            display.text(level_msg, lx, 24)
            display.show()
            time.sleep(1)

        time.sleep_ms(30)


# ---------- HELPERS ----------

def _make_enemies(level, count, grid):
    """Spawn enemies near the center; include base velocities and state machine params."""
    enemies = []

    # center search box (try to place enemies close to center to reduce stuck-on-edge)
    cx_cell = GRID_W // 2
    cy_cell = GRID_H // 2
    radius_cells = max(1, min(GRID_W, GRID_H) // 4)  # quarter-size area

    # candidate cells around center that are unclaimed
    candidates = []
    for ry in range(max(0, cy_cell - radius_cells), min(GRID_H, cy_cell + radius_cells + 1)):
        for rx in range(max(0, cx_cell - radius_cells), min(GRID_W, cx_cell + radius_cells + 1)):
            if grid[ry][rx] == 0:
                candidates.append((ry, rx))

    # fallback to any free cell if no candidate
    if not candidates:
        candidates = [(r, c) for r in range(GRID_H) for c in range(GRID_W) if grid[r][c] == 0]
    if not candidates:
        candidates = [(r, c) for r in range(GRID_H) for c in range(GRID_W)]

    for i in range(count):
        rcell, ccell = random.choice(candidates)

        # choose random type
        tname, base_r, base_speed = random.choice(_ENEMY_TYPES)

        # scale by level
        rad = max(1, int(base_r + (level - 1) * 1))
        # base speed (pixels per tick) scaled moderately by level
        base_speed_scaled = base_speed * (1.0 + (level - 1) * 0.08)

        # center pixel position (slight jitter)
        x = ccell * CELL + CELL/2 + (random.random() - 0.5) * (CELL * 0.5)
        y = rcell * CELL + CELL/2 + (random.random() - 0.5) * (CELL * 0.5)

        # random direction vector normalized
        ang = random.random() * 2 * math.pi
        bvx = math.cos(ang)
        bvy = math.sin(ang)
        # store base (direction unit) and base speed
        enemies.append({
            'x': x, 'y': y,
            'dirx': bvx, 'diry': bvy,
            'base_speed': base_speed_scaled,
            'vx': bvx * base_speed_scaled, 'vy': bvy * base_speed_scaled,
            'r': rad,
            'type': tname,
            # state machine
            'state': 'normal',
            'state_mult': 1.0,
            'next_state_change': time.ticks_add(time.ticks_ms(), _rand_state_duration(base_speed_scaled))
        })
    return enemies


def _rand_state_duration(base_speed):
    """Duration (ms) for a state; faster enemies change state more frequently."""
    # faster base_speed -> shorter durations
    base = int(300 + 800 / (1 + base_speed))
    jitter = int(random.random() * 800)
    return base + jitter


def _choose_state_for_enemy(base_speed):
    """Choose a new state weighted by base_speed (faster enemies more likely aggressive)."""
    # compute aggression weight from speed
    aggr_weight = min(0.2, 0.15 + base_speed * 0.08)  # tuned
    calm_weight = 0.15
    stop_weight = 0.1
    normal_weight = max(0.05, 1.0 - (aggr_weight + calm_weight + stop_weight))
    # build list
    choices = (['aggressive'] * int(100*aggr_weight)
               + ['normal'] * int(100*normal_weight)
               + ['calm'] * int(100*calm_weight)
               + ['stop'] * int(100*stop_weight))
    if not choices:
        return 'normal'
    return random.choice(choices)


def _update_enemies(enemies, grid, player_cx, player_cy, now_ms):
    """Move enemies and bounce on edges and claimed tiles. States influence speed and behavior."""
    for e in enemies:
        # maybe change state
        if time.ticks_diff(now_ms, e['next_state_change']) >= 0:
            new_state = _choose_state_for_enemy(e['base_speed'])
            e['state'] = new_state
            # set multiplier & duration
            if new_state == 'stop':
                e['state_mult'] = 0.0
                dur = 150 + random.randint(0, 450)
            elif new_state == 'calm':
                e['state_mult'] = 0.45
                dur = 400 + random.randint(0, 900)
            elif new_state == 'normal':
                e['state_mult'] = 1.0
                dur = 400 + random.randint(0, 900)
            elif new_state == 'aggressive':
                e['state_mult'] = 1.6
                dur = 150 + random.randint(0, 600)
            else:
                e['state_mult'] = 1.0
                dur = 600
            e['next_state_change'] = time.ticks_add(now_ms, dur)
            # occasionally re-aim direction on state change
            if new_state == 'aggressive':
                # aim roughly toward player (MicroPython-safe)
                dx = player_cx - e['x']
                dy = player_cy - e['y']
                mag = math.sqrt(dx*dx + dy*dy)
                if mag == 0:
                    mag = 1.0
                e['dirx'] = dx / mag
                e['diry'] = dy / mag
            else:
                # slight random perturbation
                ang = random.random() * 2 * math.pi
                e['dirx'] = math.cos(ang)
                e['diry'] = math.sin(ang)

        # compute velocities from direction, base_speed and state mult
        vx = e['dirx'] * e['base_speed'] * e['state_mult']
        vy = e['diry'] * e['base_speed'] * e['state_mult']

        old_x = e['x']
        old_y = e['y']
        nx = old_x + vx
        ny = old_y + vy

        # screen bounce
        if nx - e['r'] < 0:
            nx = e['r']
            e['dirx'] = -e['dirx']
        if nx + e['r'] > W_PIX - 1:
            nx = W_PIX - 1 - e['r']
            e['dirx'] = -e['dirx']
        if ny - e['r'] < 0:
            ny = e['r']
            e['diry'] = -e['diry']
        if ny + e['r'] > H_PIX - 1:
            ny = H_PIX - 1 - e['r']
            e['diry'] = -e['diry']

        # if proposed pos overlaps claimed cells, attempt X-only / Y-only checks
        if _overlaps_claimed(nx, ny, e['r'], grid):
            collide_x = _overlaps_claimed(old_x + vx, old_y, e['r'], grid)
            collide_y = _overlaps_claimed(old_x, old_y + vy, e['r'], grid)

            if collide_x and not collide_y:
                e['dirx'] = -e['dirx']
                nx = old_x + e['dirx'] * e['base_speed'] * e['state_mult']
            elif collide_y and not collide_x:
                e['diry'] = -e['diry']
                ny = old_y + e['diry'] * e['base_speed'] * e['state_mult']
            else:
                # invert both
                e['dirx'] = -e['dirx']
                e['diry'] = -e['diry']
                nx = old_x + e['dirx'] * e['base_speed'] * e['state_mult']
                ny = old_y + e['diry'] * e['base_speed'] * e['state_mult']

            # clamp
            if nx - e['r'] < 0:
                nx = e['r']
            if nx + e['r'] > W_PIX - 1:
                nx = W_PIX - 1 - e['r']
            if ny - e['r'] < 0:
                ny = e['r']
            if ny + e['r'] > H_PIX - 1:
                ny = H_PIX - 1 - e['r']

        # save computed pos & velocity
        e['x'], e['y'] = nx, ny
        e['vx'], e['vy'] = vx, vy


def _overlaps_claimed(cx, cy, r, grid):
    """Circle-vs-rectangle overlap with claimed tiles."""
    min_cx = int(max(0, (cx - r) // CELL))
    max_cx = int(min(GRID_W - 1, (cx + r) // CELL))
    min_cy = int(max(0, (cy - r) // CELL))
    max_cy = int(min(GRID_H - 1, (cy + r) // CELL))

    for gy in range(min_cy, max_cy + 1):
        for gx in range(min_cx, max_cx + 1):
            if grid[gy][gx] == 1:
                rect_x = gx * CELL
                rect_y = gy * CELL
                if _circle_rect_overlap(cx, cy, r, rect_x, rect_y, CELL, CELL):
                    return True
    return False


def _circle_rect_overlap(cx, cy, r, rx, ry, rw, rh):
    nearest_x = cx
    if cx < rx:
        nearest_x = rx
    elif cx > rx + rw:
        nearest_x = rx + rw
    nearest_y = cy
    if cy < ry:
        nearest_y = ry
    elif cy > ry + rh:
        nearest_y = ry + rh
    dx = cx - nearest_x
    dy = cy - nearest_y
    return (dx * dx + dy * dy) <= (r * r)


def _check_enemy_trail_collision(enemies, trail_cells):
    if not trail_cells:
        return False
    for (ry, rx) in list(trail_cells):
        cx = rx * CELL + CELL // 2
        cy = ry * CELL + CELL // 2
        for e in enemies:
            dx = e['x'] - cx
            dy = e['y'] - cy
            if (dx*dx + dy*dy) <= (e['r'] + (CELL//2))**2:
                return True
    return False


def _enemy_hits_cell_any(enemies, py, px):
    cx = px * CELL + CELL // 2
    cy = py * CELL + CELL // 2
    for e in enemies:
        dx = e['x'] - cx
        dy = e['y'] - cy
        if (dx*dx + dy*dy) <= (e['r'] + (CELL//2))**2:
            return True
    return False


def _render(display, grid, enemies, px, py, level, trail_cells, trail_visible=True, now_ms=None):
    # draw with a gentle wave for interior captured cells
    if now_ms is None:
        now_ms = time.ticks_ms()
    # MicroPython doesn't have ticks_div; use integer division on ticks_ms()
    if WAVE_MS > 0:
        phase = (time.ticks_ms() // WAVE_MS) % WAVE_STEPS
    else:
        phase = 0

    display.clear()

    # draw claimed and trail cells
    for r in range(GRID_H):
        for c in range(GRID_W):
            val = grid[r][c]
            x = c * CELL
            y = r * CELL

            is_border = (r == 0 or r == GRID_H - 1 or c == 0 or c == GRID_W - 1)

            if val == 1:
                # claimed: border cells remain solid; interior cells get wave effect
                if is_border:
                    # draw border as solid block (as before)
                    if CELL >= 6:
                        display.fill_rect(x + 1, y + 1, CELL - 2, CELL - 2)
                    else:
                        display.fill_rect(x, y, CELL, CELL)
                else:
                    # interior captured cell -> wave effect
                    idx = (r + c) % WAVE_STEPS
                    if idx == phase:
                        # wave crest: draw larger inset fill
                        if CELL >= 6:
                            display.fill_rect(x + 1, y + 1, CELL - 2, CELL - 2)
                        else:
                            display.fill_rect(x, y, CELL, CELL)
                    else:
                        # wave trough: draw a small center pixel (much cheaper)
                        cx = x + (CELL // 2)
                        cy = y + (CELL // 2)
                        display.fill_rect(cx, cy, 1, 1)
            elif val == 2 and trail_visible:
                # trail: draw a smaller rect or single-pixel depending on CELL
                if CELL >= 6:
                    display.rect(x + 2, y + 2, CELL - 4, CELL - 4)
                elif CELL >= 4:
                    display.rect(x + 1, y + 1, CELL - 2, CELL - 2)
                else:
                    cx = x + CELL // 2
                    cy = y + CELL // 2
                    display.fill_rect(cx, cy, 1, 1)

    # draw enemies as filled boxes (fast)
    for e in enemies:
        ex = int(e['x'] - e['r'])
        ey = int(e['y'] - e['r'])
        size = max(1, int(e['r'] * 2))
        if ex < 0: ex = 0
        if ey < 0: ey = 0
        w = size if (ex + size) <= W_PIX else (W_PIX - ex)
        h = size if (ey + size) <= H_PIX else (H_PIX - ey)
        display.fill_rect(ex, ey, w, h)

    # draw player marker:
    px_pix = px * CELL
    py_pix = py * CELL
    cell_center_x = px_pix + CELL // 2
    cell_center_y = py_pix + CELL // 2

    if 0 <= py < GRID_H and 0 <= px < GRID_W and grid[py][px] == 1:
        # on claimed: create a small "hole" and a center white pixel for encircled dot
        hole = max(1, min(5, CELL - 1))
        hx = cell_center_x - hole // 2
        hy = cell_center_y - hole // 2
        try:
            display.fill_rect(hx, hy, hole, hole, 0)  # clear hole
            display.fill_rect(cell_center_x, cell_center_y, 1, 1)  # center dot
        except TypeError:
            display.rect(cell_center_x - 1, cell_center_y - 1, 3, 3)
    else:
        # not on claimed: draw outline around cell so visible
        if CELL >= 4:
            display.rect(px_pix + 1, py_pix + 1, CELL - 2, CELL - 2)
        else:
            display.fill_rect(cell_center_x, cell_center_y, 1, 1)

    display.show()



def _capture_area(grid, trail_cells, enemies):
    reachable = [[False for _ in range(GRID_W)] for _ in range(GRID_H)]
    stack = []
    for e in enemies:
        gx = int(e['x']) // CELL
        gy = int(e['y']) // CELL
        if 0 <= gy < GRID_H and 0 <= gx < GRID_W and grid[gy][gx] != 1:
            if not reachable[gy][gx]:
                reachable[gy][gx] = True
                stack.append((gy, gx))

    while stack:
        y, x = stack.pop()
        for dy, dx in ((0,1),(0,-1),(1,0),(-1,0)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < GRID_H and 0 <= nx < GRID_W:
                if not reachable[ny][nx] and grid[ny][nx] != 1:
                    reachable[ny][nx] = True
                    stack.append((ny, nx))

    for y in range(GRID_H):
        for x in range(GRID_W):
            if grid[y][x] != 1 and not reachable[y][x]:
                grid[y][x] = 1

    for (ry, rx) in list(trail_cells):
        if 0 <= ry < GRID_H and 0 <= rx < GRID_W:
            grid[ry][rx] = 1


def _capture_percent(grid):
    total = GRID_W * GRID_H
    claimed = 0
    for r in range(GRID_H):
        for c in range(GRID_W):
            if grid[r][c] == 1:
                claimed += 1
    return (claimed * 100) // total


def _show_message(display, line1, line2=None, t=0):
    display.clear()
    if line1:
        x = max(0, (W_PIX - len(line1) * 8)//2)
        display.text(line1, x, 18)
    if line2:
        x2 = max(0, (W_PIX - len(line2) * 8)//2)
        display.text(line2, x2, 34)
    display.show()
    if t > 0:
        time.sleep(t)

def _show_capture_snapshot(display, grid, enemies, px, py, level, duration_ms=200):
    """
    Briefly show the captured area fully filled (no wave) for a short duration.
    This gives immediate, obvious feedback without changing game state.
    """
    # draw a quick full-fill frame
    display.clear()

    # draw claimed and trail cells: drawn solid for snapshot
    for r in range(GRID_H):
        for c in range(GRID_W):
            val = grid[r][c]
            x = c * CELL
            y = r * CELL
            if val == 1:
                # claimed: always draw solid during snapshot
                if CELL >= 6:
                    display.fill_rect(x + 1, y + 1, CELL - 2, CELL - 2)
                else:
                    display.fill_rect(x, y, CELL, CELL)
            elif val == 2:
                # trail - show outline as before
                if CELL >= 6:
                    display.rect(x + 2, y + 2, CELL - 4, CELL - 4)
                elif CELL >= 4:
                    display.rect(x + 1, y + 1, CELL - 2, CELL - 2)
                else:
                    cx = x + CELL // 2
                    cy = y + CELL // 2
                    display.fill_rect(cx, cy, 1, 1)

    # draw enemies
    for e in enemies:
        ex = int(e['x'] - e['r'])
        ey = int(e['y'] - e['r'])
        size = max(1, int(e['r'] * 2))
        if ex < 0: ex = 0
        if ey < 0: ey = 0
        w = size if (ex + size) <= W_PIX else (W_PIX - ex)
        h = size if (ey + size) <= H_PIX else (H_PIX - ey)
        display.fill_rect(ex, ey, w, h)

    # draw player marker (larger than 1px so visible over snapshot)
    px_pix = px * CELL
    py_pix = py * CELL
    center_x = px_pix + CELL // 2
    center_y = py_pix + CELL // 2
    # decide marker size: prefer 3x3 or 2x2 depending on CELL
    if CELL >= 6:
        m = 3
    elif CELL >= 4:
        m = 2
    else:
        m = 1
    ox = center_x - m // 2
    oy = center_y - m // 2
    display.fill_rect(ox, oy, m, m)

    display.show()
    # short pause so player sees the change
    time.sleep_ms(duration_ms)


def _flash_screen(display, times=1):
    for i in range(times):
        display.invert(True)
        display.show()
        time.sleep_ms(120)
        display.invert(False)
        display.show()
        time.sleep_ms(120)
