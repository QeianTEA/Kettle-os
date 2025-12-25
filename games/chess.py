# games/chess/chess.py
# Fixed & optimized chess for Pico (tile=8px). Proper dark-square visibility, cursor clearing, and input flush.
# Controls:
#  - UP/DOWN/LEFT/RIGHT move selector
#  - SHOULDER_RIGHT or CONFIRM to pick/place
#  - SHOULDER_LEFT to cancel selection (or cycle difficulty on pre-play)
# Note: small engine, no castling/en-passant. Pawn -> Queen on promotion.

import time
import random

GAME = {'name': 'Chepp'}

# layout
TILE = 8
BOARD_SIZE = 8
BOARD_PIX = TILE * BOARD_SIZE  # 64
HUD_X = BOARD_PIX
HUD_W = 128 - HUD_X

# piece values for evaluation
VAL = {'P':100, 'N':320, 'B':330, 'R':500, 'Q':900, 'K':20000}

DIFFICULTIES = ['Easy', 'Normal', 'Hard']
DEPTH_FOR = {'Easy': 1, 'Normal': 2, 'Hard': 3}

# ---------------------------
# Engine (unchanged)
# ---------------------------
def initial_board():
    return [
        list("rnbqkbnr"),
        list("pppppppp"),
        list("........"),
        list("........"),
        list("........"),
        list("........"),
        list("PPPPPPPP"),
        list("RNBQKBNR"),
    ]

def in_bounds(x,y):
    return 0 <= x < 8 and 0 <= y < 8
def is_white(piece): return piece.isupper()
def is_black(piece): return piece.islower()
def piece_color(piece):
    if piece == '.': return None
    return 'white' if piece.isupper() else 'black'
def clone_board(b): return [row[:] for row in b]

def find_king(b, color):
    target = 'K' if color=='white' else 'k'
    for y in range(8):
        for x in range(8):
            if b[y][x] == target:
                return x,y
    return None

def gen_moves(b, for_color):
    moves = []
    for y in range(8):
        for x in range(8):
            p = b[y][x]
            if p == '.': continue
            if for_color == 'white' and not is_white(p): continue
            if for_color == 'black' and not is_black(p): continue
            moves.extend(gen_piece_moves(b, x, y, p))
    return moves

def gen_piece_moves(b, x, y, p):
    moves = []
    p_low = p.lower()
    if p_low == 'p':
        dir = -1 if is_white(p) else 1
        start_row = 6 if is_white(p) else 1
        nx, ny = x, y + dir
        if in_bounds(nx, ny) and b[ny][nx] == '.':
            moves.append(((x,y),(nx,ny)))
            nx2, ny2 = x, y + dir*2
            if y == start_row and b[ny2][nx2] == '.':
                moves.append(((x,y),(nx2,ny2)))
        for dx in (-1,1):
            cx, cy = x+dx, y+dir
            if in_bounds(cx, cy) and b[cy][cx] != '.' and piece_color(b[cy][cx]) != piece_color(p):
                moves.append(((x,y),(cx,cy)))
    elif p_low == 'n':
        for dx,dy in ((1,2),(2,1),(2,-1),(1,-2),(-1,-2),(-2,-1),(-2,1),(-1,2)):
            nx, ny = x+dx, y+dy
            if in_bounds(nx, ny) and (b[ny][nx]=='.' or piece_color(b[ny][nx])!=piece_color(p)):
                moves.append(((x,y),(nx,ny)))
    elif p_low in ('b','r','q'):
        directions = []
        if p_low in ('b','q'):
            directions += [(1,1),(1,-1),(-1,1),(-1,-1)]
        if p_low in ('r','q'):
            directions += [(1,0),(-1,0),(0,1),(0,-1)]
        for dx,dy in directions:
            nx, ny = x+dx, y+dy
            while in_bounds(nx,ny):
                if b[ny][nx] == '.':
                    moves.append(((x,y),(nx,ny)))
                else:
                    if piece_color(b[ny][nx]) != piece_color(p):
                        moves.append(((x,y),(nx,ny)))
                    break
                nx += dx; ny += dy
    elif p_low == 'k':
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                if dx==0 and dy==0: continue
                nx, ny = x+dx, y+dy
                if in_bounds(nx,ny) and (b[ny][nx]=='.' or piece_color(b[ny][nx])!=piece_color(p)):
                    moves.append(((x,y),(nx,ny)))
    return moves

def make_move(b, mv):
    (x1,y1),(x2,y2) = mv
    b2 = clone_board(b)
    p = b2[y1][x1]
    b2[y1][x1] = '.'
    if p.lower()=='p' and (y2==0 or y2==7):
        b2[y2][x2] = 'Q' if is_white(p) else 'q'
    else:
        b2[y2][x2] = p
    return b2

def in_check(b, color):
    kpos = find_king(b, color)
    if not kpos:
        return True
    kx, ky = kpos
    enemy = 'black' if color=='white' else 'white'
    for mv in gen_moves(b, enemy):
        (sx,sy),(tx,ty) = mv
        if tx==kx and ty==ky:
            return True
    return False

def legal_moves(b, color):
    moves = gen_moves(b, color)
    leg = []
    for mv in moves:
        b2 = make_move(b, mv)
        if not in_check(b2, color):
            leg.append(mv)
    return leg

def eval_board(b):
    s = 0
    for y in range(8):
        for x in range(8):
            p = b[y][x]
            if p!='.':
                s += VAL.get(p.upper(),0) * (1 if is_white(p) else -1)
    return s

def minimax(b, depth, color, alpha, beta):
    if depth==0:
        return eval_board(b), None
    moves = legal_moves(b, color)
    if not moves:
        if in_check(b, color):
            return (-999999 if color=='white' else 999999), None
        else:
            return 0, None
    best_mv = None
    if color=='white':
        maxv = -10**9
        for mv in moves:
            b2 = make_move(b, mv)
            val,_ = minimax(b2, depth-1, 'black', alpha, beta)
            if val > maxv:
                maxv = val; best_mv = mv
            alpha = max(alpha, val)
            if beta <= alpha:
                break
        return maxv, best_mv
    else:
        minv = 10**9
        for mv in moves:
            b2 = make_move(b, mv)
            val,_ = minimax(b2, depth-1, 'white', alpha, beta)
            if val < minv:
                minv = val; best_mv = mv
            beta = min(beta, val)
            if beta <= alpha:
                break
        return minv, best_mv

# ---------------------------
# Drawing helpers & icons
# ---------------------------
def draw_piece_icon(display, piece, tx, ty, draw_on_dark):
    """
    Draw small icon inside tile. draw_on_dark=True -> draw inverted (clear pixels) so it contrasts.
    tx,ty are top-left pixel coords of tile.
    """
    x = tx + 1
    y = ty + 1
    fr = display.fill_rect
    # color convention: 1=set pixel, 0=clear pixel
    set_color = 1 if not draw_on_dark else 0

    p = piece.lower()
    if p == 'p':
        fr(x+2, y+1, 2, 2, set_color)
        fr(x+2, y+3, 2, 1, set_color)
    elif p == 'r':
        fr(x, y+1, 4, 1, set_color)
        fr(x, y+2, 4, 1, set_color)
        fr(x, y+3, 4, 1, set_color)
        # frame: outline - draw with set_color (works as border)
        try:
            display.rect(x, y, 4, 4, set_color)
        except TypeError:
            pass
    elif p == 'n':
        fr(x+2, y, 2, 1, set_color)
        fr(x+1, y+1, 2, 1, set_color)
        fr(x+1, y+2, 1, 2, set_color)
    elif p == 'b':
        fr(x+1, y, 1, 1, set_color)
        fr(x+2, y+1, 1, 1, set_color)
        fr(x+3, y+2, 1, 1, set_color)
        fr(x+1, y+3, 3, 1, set_color)
    elif p == 'q':
        fr(x, y+1, 1, 1, set_color)
        fr(x+2, y, 1, 1, set_color)
        fr(x+4, y+1, 1, 1, set_color)
        fr(x+1, y+3, 3, 1, set_color)
    elif p == 'k':
        fr(x+2, y, 1, 2, set_color)
        fr(x+1, y+1, 3, 1, set_color)
        fr(x+1, y+3, 3, 1, set_color)
    else:
        fr(x+1, y+1, 2, 2, set_color)

def draw_board_background(display):
    """Draw static board squares once."""
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            x = c * TILE
            y = r * TILE
            if (r + c) % 2 == 1:
                display.fill_rect(x, y, TILE, TILE, 1)
            else:
                display.fill_rect(x, y, TILE, TILE, 0)

# redraw a tile fully (background, piece, move hint, and selection border if needed)
def redraw_tile(display, board, r, c, show_moves_set, sel_now, sel_prev):
    tx = c * TILE
    ty = r * TILE
    dark = ((r + c) % 2 == 1)
    # background
    display.fill_rect(tx, ty, TILE, TILE, 1 if dark else 0)
    # piece
    p = board[r][c]
    if p != '.':
        # draw inverted on dark squares, normal on light
        draw_piece_icon(display, p, tx, ty, draw_on_dark=dark)
    # move hint
    if (c,r) in show_moves_set:
        cx = tx + TILE//2 - 1
        cy = ty + TILE//2 - 1
        display.fill_rect(cx, cy, 2, 2, 1 if not dark else 0)
    # selection border
    now_sel = (sel_now is not None and sel_now[0]==c and sel_now[1]==r)
    prev_sel = (sel_prev is not None and sel_prev[0]==c and sel_prev[1]==r)
    if now_sel:
        # invert-ish border: thicker corners on dark tiles, clear border on dark, drawn border on light
        if dark:
            # clear an inner 4x4 area to create visible "hole" (corners more thick)
            display.fill_rect(tx+1, ty+1, TILE-2, 1, 0)
            display.fill_rect(tx+1, ty+2, 1, TILE-4, 0)
            display.fill_rect(tx+TILE-2, ty+2, 1, TILE-4, 0)
            display.fill_rect(tx+1, ty+TILE-2, TILE-2, 1, 0)
        else:
            # draw border
            try:
                display.rect(tx, ty, TILE, TILE, 1)
                # make corners a bit thicker
                display.fill_rect(tx, ty, 2, 2, 1)
                display.fill_rect(tx+TILE-2, ty, 2, 2, 1)
                display.fill_rect(tx, ty+TILE-2, 2, 2, 1)
                display.fill_rect(tx+TILE-2, ty+TILE-2, 2, 2, 1)
            except Exception:
                pass
    elif prev_sel:
        # previously selected — nothing extra to draw because we already redrew background + piece above
        pass

# simple HUD draw; always cleared before writing
def draw_hud(display, title, diff, turn, hint):
    display.fill_rect(HUD_X, 0, HUD_W, 64, 0)
    display.text(title, HUD_X+2, 2)
    display.text("Diff:" + diff, HUD_X+2, 14)
    display.text("Turn:" + ("W" if turn=='white' else "B"), HUD_X+2, 26)
    if hint:
        display.text(hint, HUD_X+2, 40)

# ---------------------------
# Main loop with fixes
# ---------------------------
def run(display, buttons):
    # pre-play (select difficulty)
    diff_index = 1
    while True:
        display.clear()
        display.text("Chess", 8, 20)
        display.text("Diff: " + DIFFICULTIES[diff_index], 8, 34)
        display.text("Press CONF to play", 8, 48)
        display.show()
        ev = buttons.get_event()
        if ev == 'SHOULDER_RIGHT':
            diff_index = (diff_index + 1) % len(DIFFICULTIES)
        elif ev == 'SHOULDER_LEFT':
            diff_index = (diff_index - 1) % len(DIFFICULTIES)
        elif ev == 'CONFIRM':
            break
        time.sleep_ms(80)

    # Important: flush any residual button events so we don't auto-select from previous presses
    for _ in range(6):
        buttons.get_event()
        time.sleep_ms(30)

    difficulty = DIFFICULTIES[diff_index]

    # init game state
    board = initial_board()
    turn = 'white'
    selx, sely = 0, 7
    selecting = False
    selected_sq = None
    prev_sel = None

    # static draw once
    draw_board_background(display)
    display.show()

    # initial full draw
    show_moves_set = set()
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            redraw_tile(display, board, r, c, show_moves_set, (selx,sely), None)
    draw_hud(display, "Chess", difficulty, turn, "")
    display.show()

    prev_board_snapshot = clone_board(board)

    # main loop - respond only to input changes (dirty redraw)
    while True:
        ev = buttons.get_event()
        dirty_tiles = set()
        hud_hint = ""

        if ev == 'LEFT':
            prev_sel = (selx, sely)
            selx = max(0, selx-1)
            dirty_tiles.add(prev_sel); dirty_tiles.add((selx,sely))
        elif ev == 'RIGHT':
            prev_sel = (selx, sely)
            selx = min(7, selx+1)
            dirty_tiles.add(prev_sel); dirty_tiles.add((selx,sely))
        elif ev == 'UP':
            prev_sel = (selx, sely)
            sely = max(0, sely-1)
            dirty_tiles.add(prev_sel); dirty_tiles.add((selx,sely))
        elif ev == 'DOWN':
            prev_sel = (selx, sely)
            sely = min(7, sely+1)
            dirty_tiles.add(prev_sel); dirty_tiles.add((selx,sely))
        elif ev == 'SHOULDER_LEFT':
            selecting = False
            selected_sq = None
            # redraw current selection tile to remove selection
            dirty_tiles.add((selx,sely))
        elif ev == 'SHOULDER_RIGHT' or ev == 'CONFIRM':
            if not selecting:
                p = board[sely][selx]
                if p != '.' and ((turn=='white' and is_white(p)) or (turn=='black' and is_black(p))):
                    selecting = True
                    selected_sq = (selx, sely)
                    # redraw selected tile to show selection
                    dirty_tiles.add((selx,sely))
                else:
                    hud_hint = "Invalid"
            else:
                mv = (selected_sq, (selx, sely))
                legal = legal_moves(board, turn)
                if mv in legal:
                    # remember source/dest to redraw after move
                    sx, sy = selected_sq
                    dx, dy = selx, sely
                    board = make_move(board, mv)
                    selecting = False
                    selected_sq = None
                    dirty_tiles.add((sx,sy)); dirty_tiles.add((dx,dy))
                    prev_board_snapshot = None  # force snapshot refresh
                    # change turn
                    turn = 'black' if turn=='white' else 'white'
                    # AI move if black
                    if turn == 'black':
                        hud_hint = "Thinking..."
                        draw_hud(display, "Chess", difficulty, turn, hud_hint)
                        display.show()
                        # small think
                        if difficulty == 'Easy':
                            moves = legal_moves(board, turn)
                            if moves:
                                board = make_move(board, random.choice(moves))
                        else:
                            val,mv = minimax(board, DEPTH_FOR[difficulty], turn, -10**9, 10**9)
                            if mv:
                                board = make_move(board, mv)
                        # after AI move
                        turn = 'white'
                        # mark full board dirty (since pieces moved by AI unpredictably)
                        for r in range(BOARD_SIZE):
                            for c in range(BOARD_SIZE):
                                dirty_tiles.add((c,r))
                else:
                    selecting = False
                    selected_sq = None
                    hud_hint = "Bad move"

        # check endgame
        leg = legal_moves(board, turn)
        if not leg:
            if in_check(board, turn):
                display.clear(); display.text("Checkmate", 10, 24); display.show()
            else:
                display.clear(); display.text("Stalemate", 10, 24); display.show()
            while True:
                if buttons.get_event() == 'CONFIRM':
                    return
                time.sleep_ms(80)

        # If nothing happened, small sleep
        if not dirty_tiles and hud_hint == "":
            time.sleep_ms(20)
            continue

        # compute show_moves_set for selected square
        show_moves_set = set()
        if selecting and selected_sq:
            sx, sy = selected_sq
            moves = gen_piece_moves(board, sx, sy, board[sy][sx])
            for mv in moves:
                b2 = make_move(board, mv)
                if not in_check(b2, turn):
                    tx,ty = mv[1]
                    show_moves_set.add((tx,ty))

        # redraw dirty tiles (and ensure neighboring tiles that may have changed are included)
        to_redraw = set(dirty_tiles)
        # also ensure any tiles that changed pieces (compare snapshot) are redrawn
        if prev_board_snapshot is None:
            # full redraw fallback (rare)
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    to_redraw.add((c,r))
        else:
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if board[r][c] != prev_board_snapshot[r][c]:
                        to_redraw.add((c,r))

        # apply redraws
        for (c,r) in to_redraw:
            if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE:
                redraw_tile(display, board, r, c, show_moves_set, (selx,sely) if not selecting else selected_sq, prev_sel)

        # redraw HUD
        draw_hud(display, "Chess", difficulty, turn, hud_hint)
        display.show()

        # snapshot
        prev_board_snapshot = clone_board(board)
        # reset prev_sel so we don't keep redrawing removed selection repeatedly
        prev_sel = None

        # small delay so button repeats aren't too fast
        time.sleep_ms(30)

