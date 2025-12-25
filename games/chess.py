# games/chess/chess.py
# Minimal chess for 128x64 OLED; tile=8px -> board is 64x64; HUD on right
# Controls:
#  - UP/DOWN/LEFT/RIGHT move selector
#  - SHOULDER_RIGHT (or CONFIRM) to pick / place
#  - SHOULDER_LEFT to cancel selection OR (when on menu) cycle difficulty
#  - CONFIRM from menu enters the press-to-play screen
#
# Simple AI: Easy=random, Normal=minimax depth2, Hard=minimax depth3
#
# Note: no castling, no en-passant. Pawn promote -> Queen.

import time
import random
import copy

GAME = {'name': 'Chepp'}

# display layout
TILE = 8
BOARD_SIZE = 8
BOARD_PIX = TILE * BOARD_SIZE  # 64
HUD_X = BOARD_PIX
HUD_W = 128 - HUD_X

# piece values for evaluation
VAL = {'P':100, 'N':320, 'B':330, 'R':500, 'Q':900, 'K':20000}

# difficulties
DIFFICULTIES = ['Easy', 'Normal', 'Hard']
# minimax depths for diffs
DEPTH_FOR = {'Easy': 1, 'Normal': 2, 'Hard': 3}

# helper: initial board (white uppercase, black lowercase)
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

# ---------------------------
# Board utilities & moves
# ---------------------------
def in_bounds(x,y):
    return 0 <= x < 8 and 0 <= y < 8

def is_white(piece):
    return piece.isupper()

def is_black(piece):
    return piece.islower()

def piece_color(piece):
    if piece == '.': return None
    return 'white' if piece.isupper() else 'black'

def clone_board(b):
    return [row[:] for row in b]

# find king pos
def find_king(b, color):
    target = 'K' if color=='white' else 'k'
    for y in range(8):
        for x in range(8):
            if b[y][x] == target:
                return x,y
    return None

# generate pseudo-legal moves (we'll filter for king-safety later)
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
    if p_low == 'p': # pawn
        dir = -1 if is_white(p) else 1
        start_row = 6 if is_white(p) else 1
        # forward
        nx, ny = x, y + dir
        if in_bounds(nx, ny) and b[ny][nx] == '.':
            moves.append(((x,y),(nx,ny)))
            # two-step
            nx2, ny2 = x, y + dir*2
            if y == start_row and b[ny2][nx2] == '.':
                moves.append(((x,y),(nx2,ny2)))
        # captures
        for dx in (-1,1):
            cx, cy = x+dx, y+dir
            if in_bounds(cx, cy) and b[cy][cx] != '.' and piece_color(b[cy][cx]) != piece_color(p):
                moves.append(((x,y),(cx,cy)))
    elif p_low == 'n': # knight
        for dx,dy in ((1,2),(2,1),(2,-1),(1,-2),(-1,-2),(-2,-1),(-2,1),(-1,2)):
            nx, ny = x+dx, y+dy
            if in_bounds(nx, ny) and (b[ny][nx]=='.' or piece_color(b[ny][nx])!=piece_color(p)):
                moves.append(((x,y),(nx,ny)))
    elif p_low == 'b' or p_low == 'r' or p_low == 'q':
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

# apply a move (also handle pawn promotion to Q)
def make_move(b, mv):
    (x1,y1),(x2,y2) = mv
    b2 = clone_board(b)
    p = b2[y1][x1]
    b2[y1][x1] = '.'
    # promotion check: pawn reaches end
    if p.lower()=='p' and (y2==0 or y2==7):
        b2[y2][x2] = 'Q' if is_white(p) else 'q'
    else:
        b2[y2][x2] = p
    return b2

# is king in check?
def in_check(b, color):
    kpos = find_king(b, color)
    if not kpos:
        return True
    kx, ky = kpos
    enemy = 'black' if color=='white' else 'white'
    # generate all enemy moves and see if one captures king
    for mv in gen_moves(b, enemy):
        (sx,sy),(tx,ty) = mv
        if tx==kx and ty==ky:
            return True
    return False

# list legal moves for color
def legal_moves(b, color):
    moves = gen_moves(b, color)
    leg = []
    for mv in moves:
        b2 = make_move(b, mv)
        if not in_check(b2, color):
            leg.append(mv)
    return leg

# basic material evaluation
def eval_board(b):
    s = 0
    for y in range(8):
        for x in range(8):
            p = b[y][x]
            if p!='.':
                s += VAL.get(p.upper(),0) * (1 if is_white(p) else -1)
    return s

# minimax with alpha-beta, returns (score, move)
def minimax(b, depth, color, alpha, beta):
    # terminal or depth
    if depth==0:
        return eval_board(b), None
    moves = legal_moves(b, color)
    if not moves:
        # no legal moves: checkmate or stalemate
        if in_check(b, color):
            # checkmate
            return (-999999 if color=='white' else 999999), None
        else:
            # stalemate
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
# Rendering / UI helpers
# ---------------------------
def draw_board(display, board, selx, sely, show_moves):
    # board origin at (0,0)
    # draw squares
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            x = c*TILE
            y = r*TILE
            # alternate fill for board squares: simple pattern
            if (r + c) % 2 == 0:
                # light: leave empty
                pass
            else:
                # dark: fill small rect
                display.fill_rect(x+0, y+0, TILE, TILE)
            # piece
            p = board[r][c]
            if p != '.':
                # draw piece letter centered-ish
                # font 8px wide -> fits into 8x8 tile
                display.text(p, x+1, y)  # slight offset
    # show selection box
    sx = selx * TILE
    sy = sely * TILE
    display.rect(sx, sy, TILE, TILE)

    # show legal moves hints if provided as list of coords
    if show_moves:
        for (tx,ty) in show_moves:
            px = tx * TILE + (TILE//2)-1
            py = ty * TILE + (TILE//2)-1
            # small dot
            display.fill_rect(px, py, 2, 2)

def draw_hud(display, title, difficulty, turn):
    # clear HUD area (right side)
    display.fill_rect(HUD_X, 0, HUD_W, 64, 0)
    # show title/difficulty/turn
    display.text(title, HUD_X+2, 2)
    display.text("Diff:" + difficulty, HUD_X+2, 14)
    display.text("Turn:" + ("W" if turn=='white' else "B"), HUD_X+2, 26)
    display.text("R=Play", HUD_X+2, 40)
    display.text("L=Cancel", HUD_X+2, 50)

# ---------------------------
# Game flow
# ---------------------------
def run(display, buttons):
    # difficulty state - default medium
    diff_index = 1  # Normal
    # show press-to-play screen where RIGHT cycles difficulty
    # but when the chess tile is selected in hub, LEFT cycles difficulty (this module also supports LEFT cycling)
    # We'll implement both: menu will call run(), so here we present a small pre-play screen.
    chosen = False
    while True:
        display.clear()
        display.text("Chess", 8, 20)
        display.text("Diff: " + DIFFICULTIES[diff_index], 8, 34)
        display.text("Press R to play", 8, 48)
        display.show()
        ev = buttons.get_event()
        if ev == 'SHOULDER_RIGHT':
            # cycle difficulty (explicit request)
            diff_index = (diff_index + 1) % len(DIFFICULTIES)
        if ev == 'SHOULDER_LEFT':
            diff_index = (diff_index - 1) % len(DIFFICULTIES)
        if ev == 'CONFIRM' or ev == 'SHOULDER_RIGHT' and ev is not None:
            # If CONFIRM or shoulder_right pressed as play, but we must ensure we don't interpret diff-change as play
            # Here: pressing CONFIRM will play; pressing SHOULDER_RIGHT cycles diff; pressing CONFIRM after is real play.
            # To reduce ambiguity, require CONFIRM to actually start. But user wanted SHOULDER_RIGHT to cycle difficulty
            # when on press-to-play; we'll require CONFIRM to start.
            if ev == 'CONFIRM':
                break
        time.sleep_ms(80)

    difficulty = DIFFICULTIES[diff_index]
    depth = DEPTH_FOR[difficulty]

    # initialize game
    board = initial_board()
    turn = 'white'
    selx, sely = 0, 7  # selector starts at bottom-left
    selecting = False
    selected_sq = None

    while True:
        # render
        display.clear()
        # compute legal moves for highlighting (if in selecting mode)
        show_moves = []
        if selecting and selected_sq:
            sx, sy = selected_sq
            # get moves from this piece
            moves = gen_piece_moves(board, sx, sy, board[sy][sx])
            # filter legal
            legal = []
            for mv in moves:
                b2 = make_move(board, mv)
                if not in_check(b2, turn):
                    legal.append(mv[1])
            show_moves = legal

        draw_board(display, board, selx, sely, show_moves)
        draw_hud(display, "Chess", difficulty, turn)
        display.show()

        # check for checkmate/stalemate
        leg = legal_moves(board, turn)
        if not leg:
            # terminal
            if in_check(board, turn):
                # checkmate
                display.clear()
                display.text("Checkmate", 10, 24)
                display.text(("White wins" if turn=='black' else "Black wins"), 10, 36)
                display.show()
            else:
                display.clear()
                display.text("Stalemate", 10, 24)
                display.show()
            # wait for CONFIRM to exit to menu
            while True:
                if buttons.get_event() == 'CONFIRM':
                    return
                time.sleep_ms(80)

        # input handling (selector move)
        ev = buttons.get_event()
        if ev == 'LEFT':
            selx = max(0, selx-1)
        elif ev == 'RIGHT':
            selx = min(7, selx+1)
        elif ev == 'UP':
            sely = max(0, sely-1)
        elif ev == 'DOWN':
            sely = min(7, sely+1)
        elif ev == 'SHOULDER_LEFT':
            # cancel selection
            selecting = False
            selected_sq = None
        elif ev == 'SHOULDER_RIGHT' or ev == 'CONFIRM':
            # select / place
            if not selecting:
                # pick a piece if it's player's color
                p = board[sely][selx]
                if p != '.' and ((turn=='white' and is_white(p)) or (turn=='black' and is_black(p))):
                    selecting = True
                    selected_sq = (selx, sely)
                else:
                    # invalid pick -> flash
                    display.clear(); display.text("Invalid", 8, 28); display.show()
                    time.sleep_ms(220)
            else:
                # try to move from selected_sq to current sel
                mv = (selected_sq, (selx, sely))
                # check move is legal
                legal = legal_moves(board, turn)
                if mv in legal:
                    board = make_move(board, mv)
                    selecting = False
                    selected_sq = None
                    # switch turn
                    turn = 'black' if turn=='white' else 'white'
                    # if next turn is AI, compute and apply move
                    if (turn=='black') :
                        # AI move
                        if difficulty == 'Easy':
                            moves = legal_moves(board, turn)
                            if moves:
                                board = make_move(board, random.choice(moves))
                                turn = 'white'
                        else:
                            # use minimax depth per difficulty
                            d = DEPTH_FOR[difficulty]
                            # limited time; choose mov via minimax
                            val,mv = minimax(board, d, turn, -10**9, 10**9)
                            if mv:
                                board = make_move(board, mv)
                            turn = 'white'
                else:
                    # invalid move -> cancel selection
                    selecting = False
                    selected_sq = None
        # allow player to exit to menu with long CONFIRM? We'll use CONFIRM+SHOULDER_LEFT combination
        if ev == 'CONFIRM' and buttons.get_event() == 'SHOULDER_LEFT':
            return

        time.sleep_ms(60)
