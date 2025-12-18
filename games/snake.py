# games/snake/test_snake.py
import time
import random

# Must expose a GAME dict with name, optional icon, and run(display, buttons)
GAME = {
    'name': 'Snake (test)',
    # 'icon_bytes': None, 'icon_w': 32, 'icon_h': 32,  # optional
}

# Grid settings
CELL = 4   # pixels per cell
GRID_W = 128 // CELL  # 16
GRID_H = 64 // CELL   # 8

def run(display, buttons):
    # simple snake
    display.clear()
    display.text("Snake", 10, 24)
    display.show()
    time.sleep(0.6)

    # initial snake in middle
    sx = GRID_W // 2
    sy = GRID_H // 2
    snake = [(sx, sy), (sx-1, sy), (sx-2, sy)]
    dirx, diry = 1, 0
    food = _place_food(snake)

    speed_ms = 130
    last_move = time.ticks_ms()
    alive = True

    while True:
        evt = buttons.get_event()
        if evt == 'UP' and not (diry == 1 and dirx == 0):
            dirx, diry = 0, -1
        elif evt == 'DOWN' and not (diry == -1 and dirx == 0):
            dirx, diry = 0, 1
        elif evt == 'LEFT' and not (dirx == 1 and diry == 0):
            dirx, diry = -1, 0
        elif evt == 'RIGHT' and not (dirx == -1 and diry == 0):
            dirx, diry = 1, 0
        elif evt == 'SHOULDER_L':
            # exit to menu
            return

        if time.ticks_diff(time.ticks_ms(), last_move) > speed_ms:
            last_move = time.ticks_ms()
            # move snake
            head = (snake[0][0] + dirx, snake[0][1] + diry)
            # wrap around
            head = (head[0] % GRID_W, head[1] % GRID_H)
            if head in snake:
                alive = False
            snake.insert(0, head)
            if head == food:
                food = _place_food(snake)
            else:
                snake.pop()

        # render
        display.clear()
        # draw food
        fx = food[0] * CELL
        fy = food[1] * CELL
        display.fill_rect(fx, fy, CELL, CELL)
        # draw snake
        for seg in snake:
            x = seg[0] * CELL
            y = seg[1] * CELL
            display.rect(x, y, CELL, CELL)
        # HUD
        display.text("Score:%d" % (len(snake)-3), 0, 0)
        display.show()

        if not alive:
            display.clear()
            display.text("Game Over", 30, 20)
            display.text("Score:%d" % (len(snake)-3), 30, 34)
            display.text("Press to exit", 8, 50)
            display.show()
            # wait for confirm
            while True:
                if buttons.get_event() == 'CONFIRM':
                    return
                time.sleep_ms(50)

        time.sleep_ms(20)

def _place_food(snake):
    while True:
        x = random.getrandbits(4) % GRID_W
        y = random.getrandbits(3) % GRID_H
        if (x,y) not in snake:
            return (x,y)

