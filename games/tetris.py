# games/tetris/tetris.py
# ROTATED TETRIS — gravity flows left -> right (for a vertically-mounted display)
# Uses Display: clear(), show(), text(), rect(), fill_rect(), invert()
# Buttons.get_event() returns 'UP','DOWN','LEFT','RIGHT','CONFIRM','SHOULDER_R','SHOULDER_L'
#
# Controls (mapped for vertical play):
#   LEFT  -> move UP (row - 1)
#   RIGHT -> move DOWN (row + 1)
#   DOWN  -> soft drop (advance one column to the right)
#   UP    -> rotate clockwise
#   SHOULDER_R -> hard drop (advance to furthest column)
#   CONFIRM -> exit to menu

import time
import random

GAME = {'name': 'Tetris'}

# ----------------------
# CONFIG (tweakable)
# ----------------------
GRID_W = 20   # columns (pieces move rightwards)
GRID_H = 10   # rows (vertical)
HUD_COLS = 4  # columns reserved to the right for HUD (pixels = HUD_COLS * tile)

BASE_DROP_MS = 700
LEVEL_DROP_DECREASE = 40
MIN_DROP_MS = 60

# scoring
SCORE_SINGLE = 40
SCORE_DOUBLE = 100
SCORE_TRIPLE = 300
SCORE_TETRIS = 1200
SCORE_SOFT_DROP = 1
SCORE_HARD_DROP = 2

# Tetromino shapes (4x4 matrices): I, J, L, O, S, T, Z
TETROMINOES = [
    [[0,0,0,0],[1,1,1,1],[0,0,0,0],[0,0,0,0]],  # I
    [[1,0,0,0],[1,1,1,0],[0,0,0,0],[0,0,0,0]],  # J
    [[0,0,1,0],[1,1,1,0],[0,0,0,0],[0,0,0,0]],  # L
    [[0,1,1,0],[0,1,1,0],[0,0,0,0],[0,0,0,0]],  # O
    [[0,1,1,0],[1,1,0,0],[0,0,0,0],[0,0,0,0]],  # S
    [[0,1,0,0],[1,1,1,0],[0,0,0,0],[0,0,0,0]],  # T
    [[1,1,0,0],[0,1,1,0],[0,0,0,0],[0,0,0,0]],  # Z
]

# ----------------------
# Utilities
# ----------------------

def rotate_clockwise(shape):
    return [[shape[3 - j][i] for j in range(4)] for i in range(4)]

def shape_cells(shape):
    for r in range(4):
        for c in range(4):
            if shape[r][c]:
                yield c, r

def clone_shape(shape):
    return [row[:] for row in shape]

def _fisher_yates_shuffle(lst):
    use_randint = hasattr(random, "randint")
    n = len(lst)
    for i in range(n - 1, 0, -1):
        if use_randint:
            j = random.randint(0, i)
        else:
            j = random.getrandbits(16) % (i + 1)
        lst[i], lst[j] = lst[j], lst[i]

# ----------------------
# Main game
# ----------------------

def run(display, buttons):
    # compute tile size so HUD doesn't overlap
    tile = min(display.width // (GRID_W + HUD_COLS), display.height // GRID_H)
    if tile < 2:
        tile = 2

    play_px_w = GRID_W * tile
    play_px_h = GRID_H * tile
    hud_px_w = HUD_COLS * tile

    total_w = play_px_w + hud_px_w
    ox = max(0, (display.width - total_w) // 2)
    oy = max(0, (display.height - play_px_h) // 2)
    play_x = ox
    play_y = oy
    hud_x = play_x + play_px_w
    hud_y = oy

    # board[row][col]
    board = [[0 for _ in range(GRID_W)] for _ in range(GRID_H)]

    # bag randomizer
    bag = []
    def next_piece():
        nonlocal bag
        if not bag:
            bag = list(range(len(TETROMINOES)))
            _fisher_yates_shuffle(bag)
        return bag.pop()

    curr_id = next_piece()
    curr_shape = clone_shape(TETROMINOES[curr_id])
    next_id = next_piece()
    score = 0
    level = 1
    lines_cleared = 0

    # spawn at left-of-playfield (column -1) centered vertically
    spawn_col = -1
    spawn_row = (GRID_H // 2) - 2  # top-left of 4x4 shape
    piece_col = spawn_col
    piece_row = spawn_row

    drop_timer = time.ticks_ms()
    drop_interval = max(MIN_DROP_MS, BASE_DROP_MS - (level - 1) * LEVEL_DROP_DECREASE)

    def can_place(shape, col, row):
        for sx, sy in shape_cells(shape):
            cx = col + sx
            ry = row + sy
            # allow starting left of playfield (cx < 0)
            if ry < 0 or ry >= GRID_H:
                return False
            if cx >= GRID_W:
                return False
            if cx >= 0 and board[ry][cx]:
                return False
        return True

    def lock_piece(shape, col, row):
        for sx, sy in shape_cells(shape):
            cx = col + sx
            ry = row + sy
            if 0 <= ry < GRID_H and 0 <= cx < GRID_W:
                board[ry][cx] = 1

    def clear_full_columns():
        nonlocal board, score, level, lines_cleared
        removed = 0
        c = 0
        while c < GRID_W:
            full = True
            for r in range(GRID_H):
                if not board[r][c]:
                    full = False
                    break
            if full:
                # remove column c: shift everything left, insert empty column at index 0
                for r in range(GRID_H):
                    del board[r][c]
                    board[r].insert(0, 0)
                removed += 1
                # do not advance c (we must re-check the shifted column at same index)
            else:
                c += 1

        # score
        if removed == 1:
            score += SCORE_SINGLE * level
        elif removed == 2:
            score += SCORE_DOUBLE * level
        elif removed == 3:
            score += SCORE_TRIPLE * level
        elif removed >= 4:
            score += SCORE_TETRIS * level

        if removed:
            lines_cleared += removed
            level = 1 + (lines_cleared // 10)

    def spawn_new():
        nonlocal curr_id, curr_shape, next_id, piece_col, piece_row, drop_timer, drop_interval
        curr_id = next_id
        curr_shape = clone_shape(TETROMINOES[curr_id])
        next_id = next_piece()
        piece_col = spawn_col
        piece_row = spawn_row
        drop_timer = time.ticks_ms()
        drop_interval = max(MIN_DROP_MS, BASE_DROP_MS - (level - 1) * LEVEL_DROP_DECREASE)
        if not can_place(curr_shape, piece_col, piece_row):
            return False
        return True

    if not spawn_new():
        return

    # title
    display.clear()
    display.text("TETRIS", (display.width - len("TETRIS")*8)//2, 12)
    display.text("Press CONF", (display.width - len("Press CONF")*8)//2, 28)
    display.show()
    while True:
        if buttons.get_event() == 'CONFIRM':
            break
        time.sleep_ms(40)

    soft_drop_active = False

    while True:
        now = time.ticks_ms()
        ev = buttons.get_event()

        if ev == 'UP':  # move UP
            if can_place(curr_shape, piece_col, piece_row - 1):
                piece_row -= 1
        elif ev == 'DOWN':  # move DOWN
            if can_place(curr_shape, piece_col, piece_row + 1):
                piece_row += 1
        elif ev == 'RIGHT':  # soft drop (advance column)
            if can_place(curr_shape, piece_col + 1, piece_row):
                piece_col += 1
                score += SCORE_SOFT_DROP
            soft_drop_active = True
            drop_timer = now
        elif ev == 'LEFT':  # rotate clockwise with simple kicks (up/down)
            new_shape = rotate_clockwise(curr_shape)
            if can_place(new_shape, piece_col, piece_row):
                curr_shape = new_shape
            elif can_place(new_shape, piece_col, piece_row - 1):
                piece_row -= 1
                curr_shape = new_shape
            elif can_place(new_shape, piece_col, piece_row + 1):
                piece_row += 1
                curr_shape = new_shape
        elif ev == 'SHOULDER_L':  # hard drop (advance until can't)
            dist = 0
            while can_place(curr_shape, piece_col + 1, piece_row):
                piece_col += 1
                dist += 1
            score += dist * SCORE_HARD_DROP
            lock_piece(curr_shape, piece_col, piece_row)
            clear_full_columns()
            if not spawn_new():
                break
        elif ev == 'SHOULDER_R':
            return
        else:
            soft_drop_active = False

        # gravity (advance columns automatically)
        interval = max(40, drop_interval // (2 if soft_drop_active else 1))
        if time.ticks_diff(now, drop_timer) >= interval:
            drop_timer = now
            if can_place(curr_shape, piece_col + 1, piece_row):
                piece_col += 1
            else:
                # lock
                lock_piece(curr_shape, piece_col, piece_row)
                clear_full_columns()
                if not spawn_new():
                    break

        # render
        display.clear()

        # border rectangle
        bx = play_x - 1
        by = play_y - 1
        display.rect(bx, by, play_px_w + 2, play_px_h + 2)

        # draw board: iterate rows then cols
        for r in range(GRID_H):
            for c in range(GRID_W):
                if board[r][c]:
                    sx = play_x + c * tile
                    sy = play_y + r * tile
                    display.fill_rect(sx + 1, sy + 1, tile - 2, tile - 2)

        # draw current piece at (piece_col, piece_row)
        for sx, sy in shape_cells(curr_shape):
            cx = piece_col + sx
            ry = piece_row + sy
            if 0 <= ry < GRID_H and 0 <= cx < GRID_W:
                sx_px = play_x + cx * tile
                sy_px = play_y + ry * tile
                display.fill_rect(sx_px + 1, sy_px + 1, tile - 2, tile - 2)

        # HUD (clear region first)
        display.fill_rect(hud_x, hud_y, hud_px_w, play_px_h, 0)
        display.text("S:" + str(score), hud_x + 2, hud_y + 2)
        display.text("L:" + str(level), hud_x + 2, hud_y + 12)
        display.text("Nxt:", hud_x + 2, hud_y + 22)
        # preview
        preview = TETROMINOES[next_id]
        pox = hud_x + 2
        poy = hud_y + 30
        for r in range(4):
            for c in range(4):
                if preview[r][c]:
                    display.fill_rect(pox + c * max(1, tile//1), poy + r * max(1, tile//1),
                                      max(1, tile//1), max(1, tile//1))

        display.show()
        time.sleep_ms(18)

    # game over
    display.clear()
    display.text("GAME OVER", (display.width - len("GAME OVER")*8)//2, display.height//2 - 8)
    display.text("Score:" + str(score), (display.width - len("Score:"+str(score))*8)//2, display.height//2 + 4)
    display.show()
    while True:
        if buttons.get_event() == 'CONFIRM':
            return
        time.sleep_ms(40)

