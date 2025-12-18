# games/data_hop.py
# DATA HOP — Frog crossing logs with islands every X meters
# Grid uses 4x4 pixel tiles. Full modular configuration.

import time
import random

GAME = {'name': 'Data Hop'}

# -----------------------
# GLOBAL CONFIG
# -----------------------

TILE = 4                       # 4x4 pixels
SCREEN_W = 128
SCREEN_H = 64
GRID_W = SCREEN_W // TILE      # 32 columns
GRID_H = SCREEN_H // TILE      # 16 rows (camera window)

PLAYER_START_X = GRID_W // 2
ISLAND_SPACING = 20            # meters between islands
LEVEL_VIEW_HEIGHT = GRID_H     # after each island, camera scrolls

# bottom safe rows (frog can stand here without logs/islands)
SAFE_BOTTOM_ROWS = 2

# Log types (speed in tiles/frame, length in tiles)
LOG_TYPES = [
    ("SLOW_SHORT",  0.15, 6, False),   # (label, speed, length, breakable)
    ("SLOW_LONG",   0.15, 12, False),
    ("FAST_SHORT",  0.35, 6, False),
    ("FAST_LONG",  0.35, 12, False),
    ("BREAK_SHORT", 0.20, 5, True),
    ("BREAK_LONG",  0.20, 10, True),
]

# Island sizes in tiles
ISLAND_SIZES = [(10, 3), (16, 3), (22, 4)]   # (width, height)


# -----------------------
# CLASSES
# -----------------------

class Log:
    def __init__(self, y, x, length, speed, breakable):
        self.y = y          # grid row (world coordinate)
        self.x = x          # leftmost tile (float)
        self.length = length
        self.speed = speed
        self.breakable = breakable
        # direction random
        self.dir = random.choice([-1, 1])

    def update(self):
        self.x += self.dir * self.speed
        # wrap
        if self.x + self.length < -2:
            self.x = GRID_W + 2
        if self.x > GRID_W + 2:
            self.x = -self.length - 2

    def occupies(self, px):
        # px is integer grid column
        return (self.x <= px) and (px <= self.x + self.length)


class Island:
    def __init__(self, top_y, width, height, x_pos):
        self.top_y = top_y
        self.width = width
        self.height = height
        self.x_pos = x_pos
        # island occupies rows [top_y ... top_y + height-1]

    def contains(self, gy, gx):
        return (self.top_y <= gy < self.top_y + self.height and
                self.x_pos <= gx < self.x_pos + self.width)


# -----------------------
# MAIN GAME LOOP
# -----------------------

def run(display, buttons):
    # camera measures height in grid rows (world coordinate of top visible row)
    camera_y = 0

    # frog position (camera-local)
    px = PLAYER_START_X
    py = GRID_H - 2  # near bottom (camera-local row index)

    # progression
    meters = 0
    next_island_meter = ISLAND_SPACING

    logs = []       # active logs (with world y values)
    islands = []    # islands generated (with world coordinates)

    # Seed logs above frog so they are reachable
    for i in range(6):
        row = (camera_y + py) - (3 + i * 2)
        _spawn_log_row(logs, row)


    # Title screen
    _show_message(display, "DATA HOP", "Press to Start")

    while True:
        if buttons.get_event() == 'CONFIRM':
            break
        time.sleep_ms(40)

    # --------- MAIN GAME -------------
    while True:

        # INPUT
        ev = buttons.get_event()
        if ev == 'LEFT':
            px -= 1
        if ev == 'RIGHT':
            px += 1
        if ev == 'UP':
            py -= 1
            meters += 1
        #if ev == 'DOWN':
            #py += 1
        if ev == 'SHOULDER_L':
            return  # exit to menu

        # CLAMP X
        if px < 0:
            px = 0
        if px >= GRID_W:
            px = GRID_W - 1

        # CAMERA FOLLOW (frog stays near mid/bottom area normally)
        if py < GRID_H // 2:
            shift = (GRID_H // 2) - py
            camera_y -= shift
            py = GRID_H // 2

        # GENERATE new rows ahead
        world_row = camera_y
        
        # CHECK COLLISION WITH LOGS
        frog_world_y = camera_y + py

        # Every new row visible: may spawn logs or islands
        if meters >= next_island_meter:
            next_island_meter += ISLAND_SPACING
            _spawn_island(islands, camera_y)
        else:
            # Spawn logs 3–6 rows above frog
            spawn_y = frog_world_y - random.randint(3, 6)
            _spawn_log_row(logs, spawn_y)


        # UPDATE LOGS
        for log in logs:
            log.update()



        on_log = False
        for log in logs:
            if int(log.y) == int(frog_world_y):
                if log.occupies(px):
                    on_log = True
                    px += log.dir * log.speed
                    # keep px in integer bounds
                    if px < 0:
                        px = 0
                    if px >= GRID_W:
                        px = GRID_W - 1

        # check islands
        on_island = False
        for isl in islands:
            if isl.contains(frog_world_y, px):
                on_island = True

        # RIVER DEATH
        # If frog is not on a log and not on an island, and not in the bottom safe rows -> dead
        # Use camera-local py and SAFE_BOTTOM_ROWS for clarity:
        if not on_log and not on_island:
            if py < (GRID_H - SAFE_BOTTOM_ROWS):
                _show_message(display, "OOPS!", "Press to Exit")
                while buttons.get_event() != 'CONFIRM':
                    time.sleep_ms(40)
                return

        # RENDER
        _render(display, logs, islands, camera_y, px, py, meters)

        time.sleep_ms(30)


# -----------------------
# LOG / ISLAND GENERATION
# -----------------------

def _should_spawn_log_row(world_y):
    # simple spawn probability per tick — world_y currently unused, left for future expansion
    return random.random() < 0.20  # 20% chance per row advance


def _spawn_log_row(logs, row_y):
    # choose a log type
    name, speed, length, breakable = random.choice(LOG_TYPES)
    x = random.randint(-10, GRID_W - 2)
    logs.append(Log(row_y, x, length, speed, breakable))


def _spawn_island(islands, camera_y):
    width, height = random.choice(ISLAND_SIZES)
    x_pos = random.randint(0, GRID_W - width)
    top_y = camera_y  # at top of visible space, then scrolls down as camera shifts
    islands.append(Island(top_y, width, height, x_pos))


# -----------------------
# RENDERING
# -----------------------

def _render(display, logs, islands, camera_y, px, py, meters):
    display.clear()

    # draw logs
    for log in logs:
        vy = int(log.y - camera_y)
        if 0 <= vy < GRID_H:
            sx = int(log.x * TILE)
            display.fill_rect(sx, vy * TILE, int(log.length * TILE), TILE, 1)

    # draw islands
    for isl in islands:
        for ry in range(isl.height):
            draw_y = isl.top_y + ry - camera_y
            if 0 <= draw_y < GRID_H:
                display.fill_rect(isl.x_pos * TILE,
                                  draw_y * TILE,
                                  isl.width * TILE,
                                  TILE,
                                  1)

    # draw frog — 4x4 tile filled so visible
    display.fill_rect(px * TILE + 1, py * TILE + 1, TILE - 2, TILE - 2, 1)

    # HUD (never obstructed)
    # clear HUD region then draw meters
    try:
        display.fill_rect(0, 0, 40, 8, 0)  # clear HUD region (use color=0)
    except TypeError:
        # if driver doesn't support color arg, draw a small black rectangle by filling with 0 via invert trick
        display.fill_rect(0, 0, 40, 8)
    display.text("M:" + str(meters), 0, 0)

    display.show()


# -----------------------
# UI
# -----------------------

def _show_message(display, l1, l2=None):
    display.clear()
    display.text(l1, 20, 20)
    if l2:
        display.text(l2, 10, 36)
    display.show()
    time.sleep_ms(100)
