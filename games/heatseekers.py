# games/heatseekers/heatseekers.py
# HeatSeekers - Pico (128x64)
# Explosions store a vy and advance ex['wy'] += ex['vy'] each frame so they streak down.
# Explosions are 5x5. Missile types now include a spawn_weight parameter for spawn bias.
# CRASHED screen shows how long the player lasted.

import time
import random
import math
from machine import Pin

GAME = {'name': 'HeatSeekers'}

# Screen
W = 128
H = 64

# Player (visual center)
PX = W // 2
PY = 50
PLANE_W = 4
PLANE_H = 3

# Steering / physics (pixel units)
player_world_x = 0.0
player_lat_vel = 0.0
LAT_ACCEL = 1.2
LAT_MAX = 7.2
LAT_FRICTION = 0.88

# Missile spawn tuning
MISSILE_BASE_SPAWN_MS = 700
MIN_SPAWN_MS = 180
last_spawn_ms = 0

# Powerups
last_powerup_ms = 0
next_powerup_ms = 0

# Invulnerability
invuln_until = 0

# Game timing
start_ms = 0

# Missile types: (name, px_w, px_h, base_speed_px_frame, maneuver, blink, spawn_weight)
# spawn_weight: relative baseline probability for selecting that missile (higher -> more likely)
MISSILE_TYPES = [
    ('standard',   2, 2, 2.5, 0.062, False, 1.0),
    ('blinky_fast',1, 1, 4.2, 0.052, True,  0.6),
    ('man',        1, 1, 2.5, 0.100, False, 0.6),
    ('slowblink',  2, 2, 1.5, 0.055, True,  0.1),
]

# State
missiles = []
powerups = []
# explosions in world coords: {'wx':float,'wy':float,'vy':float,'born':ms,'size':int}
explosions = []

# Input pins
PIN_LEFT = 8
PIN_RIGHT = 9
PIN_SH_L = 11
PIN_SH_R = 12

# helpers
def now_ms():
    return time.ticks_ms()

def clamp(v, a, b):
    if v < a: return a
    if v > b: return b
    return v

def rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)

# world->screen conversion
def world_to_screen_x(world_x, world_x_offset):
    return int(PX + (world_x - world_x_offset))

def world_to_screen_y(world_y):
    return int(PY + world_y)

def plane_rect():
    left = PX - (PLANE_W // 2)
    top = PY - (PLANE_H // 2)
    return left, top, PLANE_W, PLANE_H

def draw_plane(display, angle_deg, invuln):
    cx = PX; cy = PY
    shift = int(clamp(angle_deg / 20.0, -3, 3))
    display.fill_rect(cx + shift, cy - 3, 1, 1, 1)
    display.fill_rect(cx - 1 + shift, cy - 2, 3, 1, 1)
    display.fill_rect(cx + shift, cy - 1, 1, 1, 1)
    display.fill_rect(cx - 3 + shift, cy - 1, 2, 1, 1)
    display.fill_rect(cx + 2 + shift, cy - 1, 2, 1, 1)
    if invuln:
        display.rect(cx - 4, cy - 4, 9, 9, 1)

def spawn_missile(elapsed_s):
    """
    Spawn a missile type using weights:
      weight_for_type = spawn_weight * (1.0 + time_bias)
    where time_bias increases over time so later-game favors stronger types.
    """
    weights = []
    for i, t in enumerate(MISSILE_TYPES):
        # t contains spawn_weight at index 6
        spawn_weight = t[6]
        # time bias: increases with elapsed_s and index so higher-index types become more likely later
        time_bias = (elapsed_s / 20.0) * (i * 0.9)
        w = spawn_weight * (1.0 + time_bias)
        weights.append(w)
    total = sum(weights)
    if total <= 0:
        idx = 0
    else:
        r = random.random() * total
        acc = 0.0
        idx = 0
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                idx = i
                break

    name, pw, ph, speed, maneuver, blink, spawn_weight = MISSILE_TYPES[idx]
    wx = player_world_x + random.uniform(-W * 0.6, W * 0.6)
    wy = -random.uniform(40.0, 110.0)
    vx = random.uniform(-0.6, 0.6)
    vy = speed
    missiles.append({
        'type': name, 'world_x': wx, 'world_y': wy,
        'vx': vx, 'vy': vy,
        'pw': pw, 'ph': ph, 'maneuver': maneuver, 'blink': blink,
        'born_ms': now_ms()
    })

def spawn_powerup():
    wx = player_world_x + random.uniform(-W * 0.5, W * 0.5)
    wy = -random.uniform(60.0, 140.0)
    powerups.append({'world_x': wx, 'world_y': wy, 'type': 'invuln', 'born_ms': now_ms()})

def spawn_interval_ms(elapsed_s):
    t = min(elapsed_s, 120.0)
    frac = t / 120.0
    return int(MISSILE_BASE_SPAWN_MS - frac * (MISSILE_BASE_SPAWN_MS - MIN_SPAWN_MS))

# create explosion at world center (wx,wy). size = integer pixel side length (5 => 5x5).
# vy: vertical speed in world units for the explosion (makes it streak). If vy is None, default used.
def create_explosion_at_world(wx, wy, now, size=5, vy=None):
    if vy is None:
        vy = 1.5
    explosions.append({'wx': float(wx), 'wy': float(wy), 'vy': float(vy), 'born': now, 'size': int(size)})
    # immediate missile destruction overlapping explosion (iterate snapshot)
    ex_left = wx - (size // 2)
    ex_top = wy - (size // 2)
    ex_w = size
    ex_h = size
    rm = []
    for m in list(missiles):
        mx = m['world_x']; my = m['world_y']; mw = m['pw']; mh = m['ph']
        if rects_overlap(ex_left, ex_top, ex_w, ex_h, mx, my, mw, mh):
            rm.append(m)
    for m in rm:
        if m in missiles:
            missiles.remove(m)

# --------------------------
# Splash helper: attempt to show an RLE image (or index) in /images/heatseekers.
# Falls back to the original text intro if no image is found or playback fails.
# --------------------------
def _show_splash_image_or_text(display, buttons):
    """
    Try to render a graphical splash (index or single .rle). If successful, hold last frame
    and wait for CONFIRM. Otherwise show the text splash and wait for CONFIRM.
    """
    # first try index-based playback (images.heatseekers.heatseekers_index)
    try:
        from modules.img_loader import play_gif_from_index, blit_rle_file
    except Exception:
        play_gif_from_index = None
        blit_rle_file = None

    # 1) try index module
    try:
        # module path: images.heatseekers.heatseekers_index
        import images.heatseekers.heatseekers_index as hk_idx
        if play_gif_from_index:
            try:
                ok = play_gif_from_index(display, hk_idx.IMAGES, "/images/heatseekers",
                                         center=False, loops=1, hold_last=True)
                if ok:
                    # wait for confirm on last frame (image already shows "Press to play")
                    while True:
                        if buttons.get_event() == 'CONFIRM':
                            return
                        time.sleep_ms(40)
            except Exception:
                # fall through to file checks / text
                pass
    except Exception:
        pass

    # 2) try single-file fallbacks
    candidates = ["/images/heatseekers/heatseekers.rle", "/images/heatseekers/splash.rle"]
    try:
        import os
        for path in candidates:
            try:
                os.stat(path)
                # file exists
                if blit_rle_file:
                    ok = blit_rle_file(display, path, 128, 64, 0, 0)
                else:
                    ok = False
                if ok:
                    while True:
                        if buttons.get_event() == 'CONFIRM':
                            return
                        time.sleep_ms(40)
            except Exception:
                # stat failed or blit failed -> try next candidate
                continue
    except Exception:
        pass

    # fallback: original text splash
    display.clear()
    display.text("HEATSEEKERS", 12, 18)
    display.text("L/R to steer", 8, 34)
    display.text("Press to play", 8, 46)
    display.show()
    while True:
        if buttons.get_event() == 'CONFIRM':
            return
        time.sleep_ms(40)


# MAIN
def run(display, buttons):
    global player_world_x, player_lat_vel, last_spawn_ms, start_ms, last_powerup_ms, next_powerup_ms, invuln_until

    # raw pins
    pin_left = Pin(PIN_LEFT, Pin.IN, Pin.PULL_UP)
    pin_right = Pin(PIN_RIGHT, Pin.IN, Pin.PULL_UP)
    pin_sh_l = Pin(PIN_SH_L, Pin.IN, Pin.PULL_UP)
    pin_sh_r = Pin(PIN_SH_R, Pin.IN, Pin.PULL_UP)

    # initial reset
    missiles.clear(); powerups.clear(); explosions.clear()
    player_world_x = 0.0; player_lat_vel = 0.0
    last_spawn_ms = now_ms()
    last_powerup_ms = now_ms()
    next_powerup_ms = last_powerup_ms + random.randint(20000, 30000)
    invuln_until = 0
    start_ms = now_ms()

    elapsed_s = 0.0
    angle = 0.0
    game_over = False
    exploding = False
    explosion_end_ms = 0

    # Try graphical splash first; fallback to text if not available
    _show_splash_image_or_text(display, buttons)

    # <<< CLEAN RESET HERE >>>
    missiles.clear()
    powerups.clear()
    explosions.clear()

    player_world_x = 0.0
    player_lat_vel = 0.0

    now = now_ms()
    start_ms = now
    last_spawn_ms = now
    last_powerup_ms = now
    next_powerup_ms = now + random.randint(20000, 30000)
    invuln_until = 0
    exploding = False
    game_over = False

    while True:
        now = now_ms()
        elapsed_s = (now - start_ms) / 1000.0

        if exploding:
            # while exploding (player-death) we freeze explosion movement (do not advance wy).
            pass
        else:
            # continuous input
            steering_left = (pin_left.value() == 0) or (pin_sh_l.value() == 0)
            steering_right = (pin_right.value() == 0) or (pin_sh_r.value() == 0)

            if steering_left and not steering_right:
                player_lat_vel -= LAT_ACCEL
                angle = clamp(angle - 6.0, -45.0, 45.0)
            elif steering_right and not steering_left:
                player_lat_vel += LAT_ACCEL
                angle = clamp(angle + 6.0, -45.0, 45.0)
            else:
                angle *= 0.9

            player_lat_vel = clamp(player_lat_vel, -LAT_MAX, LAT_MAX)
            player_lat_vel *= LAT_FRICTION
            player_world_x += player_lat_vel
            max_world = W * 2.0
            player_world_x = clamp(player_world_x, -max_world, max_world)

            # spawn missiles
            si = spawn_interval_ms(elapsed_s)
            if time.ticks_diff(now, last_spawn_ms) >= si:
                spawn_missile(elapsed_s)
                last_spawn_ms = now

            # spawn powerups
            if now >= next_powerup_ms:
                spawn_powerup()
                last_powerup_ms = now
                next_powerup_ms = now + random.randint(20000, 30000)

            # update missiles (snapshot for safety)
            to_remove = []
            for m in list(missiles):
                if m['vy'] > 0:
                    t = -m['world_y'] / m['vy']
                else:
                    t = 10.0
                if t < 1.0: t = 1.0
                predicted_target_x = player_world_x + player_lat_vel * t
                desired_vx = (predicted_target_x - m['world_x']) / t
                desired_vx = clamp(desired_vx, -8.0, 8.0)
                max_delta = m['maneuver'] * 6.0
                dv = clamp(desired_vx - m['vx'], -max_delta, max_delta)
                m['vx'] += dv
                m['world_x'] += m['vx']
                m['world_y'] += m['vy']
                sy = world_to_screen_y(m['world_y'])
                if sy > H + 32 or m['world_y'] > 5000:
                    if m not in to_remove:
                        to_remove.append(m)

            # missile vs missile collisions (snapshot). explosions use default vy and uniform size=5 unless passed explicitly.
            msnap = list(missiles)
            for i, a in enumerate(msnap):
                if a not in missiles:
                    continue
                ax = a['world_x']; ay = a['world_y']; aw = a['pw']; ah = a['ph']
                for b in msnap[i+1:]:
                    if b not in missiles:
                        continue
                    bx = b['world_x']; by = b['world_y']; bw = b['pw']; bh = b['ph']
                    if rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
                        center_x = (ax + aw/2.0 + bx + bw/2.0) / 2.0
                        center_y = (ay + ah/2.0 + by + bh/2.0) / 2.0
                        # use default vy (no per-type vy differences requested)
                        create_explosion_at_world(center_x, center_y, now, size=5, vy=None)
                        if a not in to_remove: to_remove.append(a)
                        if b not in to_remove: to_remove.append(b)

            for m in to_remove:
                if m in missiles:
                    missiles.remove(m)

            # powerups update (snapshot)
            pu_remove = []
            for pu in list(powerups):
                pu['world_y'] += 1.2
                sx = world_to_screen_x(pu['world_x'], player_world_x)
                sy = world_to_screen_y(pu['world_y'])
                plx, ply, pw, ph = plane_rect()
                if rects_overlap(sx, sy, 4, 4, plx, ply, pw, ph):
                    invuln_until = now + 5000
                    pu_remove.append(pu)
                if sy > H + 32:
                    pu_remove.append(pu)
            for pu in pu_remove:
                if pu in powerups:
                    powerups.remove(pu)

            # missile vs player collisions (snapshot)
            invuln = (now < invuln_until)
            if not invuln:
                plx, ply, pw, ph = plane_rect()
                hit = False
                hit_missile = None
                for m in list(missiles):
                    mx = world_to_screen_x(m['world_x'], player_world_x)
                    my = world_to_screen_y(m['world_y'])
                    mw = m['pw']; mh = m['ph']
                    if rects_overlap(mx, my, mw, mh, plx, ply, pw, ph):
                        hit = True
                        hit_missile = m
                        break
                if hit:
                    # player-hit explosion: uniform size 5 and default vy
                    create_explosion_at_world(player_world_x, 0.0, now, size=5, vy=None)
                    if hit_missile and hit_missile in missiles:
                        missiles.remove(hit_missile)
                    exploding = True
                    explosion_end_ms = now + 1000
                    game_over = True

            # explosions created may already overlap player; check them (snapshot)
            if not invuln and not exploding:
                plx, ply, pw, ph = plane_rect()
                for ex in list(explosions):
                    ex_left = ex['wx'] - (ex['size'] // 2)
                    ex_top = ex['wy'] - (ex['size'] // 2)
                    ex_w = ex['size']; ex_h = ex['size']
                    if rects_overlap(ex_left, ex_top, ex_w, ex_h, plx, ply, pw, ph):
                        exploding = True
                        explosion_end_ms = now + 1000
                        game_over = True
                        break

        # ----- Update explosions (move them, kill missiles during their life) -----
        # explosions are in world coords; advance wy by vy only when NOT in exploding (player-death) freeze
        if not exploding:
            for ex in list(explosions):
                ex['wy'] += ex.get('vy', 1.5)  # make them streak down
                # destroying missiles overlapping explosion during life
                ex_left = ex['wx'] - (ex['size'] // 2)
                ex_top = ex['wy'] - (ex['size'] // 2)
                ex_w = ex['size']; ex_h = ex['size']
                rm = []
                for m in list(missiles):
                    mx = m['world_x']; my = m['world_y']; mw = m['pw']; mh = m['ph']
                    if rects_overlap(ex_left, ex_top, ex_w, ex_h, mx, my, mw, mh):
                        rm.append(m)
                for m in rm:
                    if m in missiles:
                        missiles.remove(m)
        else:
            # while exploding (player death) we still check explosion damage to missiles and player (but don't move explosions)
            for ex in list(explosions):
                ex_left = ex['wx'] - (ex['size'] // 2)
                ex_top = ex['wy'] - (ex['size'] // 2)
                ex_w = ex['size']; ex_h = ex['size']
                rm = []
                for m in list(missiles):
                    mx = m['world_x']; my = m['world_y']; mw = m['pw']; mh = m['ph']
                    if rects_overlap(ex_left, ex_top, ex_w, ex_h, mx, my, mw, mh):
                        rm.append(m)
                for m in rm:
                    if m in missiles:
                        missiles.remove(m)

        # RENDER
        display.clear()

        # missiles
        blink_phase = ((now // 75) & 1)
        for m in list(missiles):
            sx = world_to_screen_x(m['world_x'], player_world_x)
            sy = world_to_screen_y(m['world_y'])
            w_px = int(m['pw']); h_px = int(m['ph'])
            if sy < -32 or sy > H + 32 or sx < -64 or sx > W + 64:
                continue
            if m['blink']:
                if blink_phase:
                    display.fill_rect(sx, sy, w_px, h_px, 1)
            else:
                display.fill_rect(sx, sy, w_px, h_px, 1)

        # powerups
        for pu in list(powerups):
            sx = world_to_screen_x(pu['world_x'], player_world_x)
            sy = world_to_screen_y(pu['world_y'])
            if -16 <= sy <= H + 16:
                display.rect(int(sx), int(sy), 4, 4, 1)

        # explosions: blink 300ms, draw as size x size square centered at world coords
        ex_blink_phase = ((now // 300) & 1)
        new_explosions = []
        for ex in list(explosions):
            age = now - ex['born']
            if age <= 1000:
                sx = world_to_screen_x(ex['wx'], player_world_x) - (ex['size'] // 2)
                sy = world_to_screen_y(ex['wy']) - (ex['size'] // 2)
                if ex_blink_phase:
                    display.fill_rect(int(sx), int(sy), ex['size'], ex['size'], 1)
                new_explosions.append(ex)
            # else: expired
        explosions[:] = new_explosions

        # player (don't draw while exploding)
        if not exploding:
            invuln = (now < invuln_until)
            draw_plane(display, angle, invuln)
        else:
            # when explosion_end_ms passes, show CRASHED screen (include how long they lasted)
            if now >= explosion_end_ms:
                # compute elapsed seconds and show on crashed screen
                total_s = int((explosion_end_ms - start_ms) / 1000.0)
                display.show()
                display.clear()
                display.text("CRASHED", 28, 16)
                display.text("T:%03d s" % (total_s), 40, 30)
                display.text("Press to exit", 8, 46)
                display.show()
                while True:
                    if buttons.get_event() == 'CONFIRM':
                        return
                    time.sleep_ms(60)

        # HUD
        try:
            display.fill_rect(0, 0, 48, 8, 0)
        except TypeError:
            display.fill_rect(0, 0, 48, 8)
        elapsed_display = int(elapsed_s)
        display.text("T:%03d" % (elapsed_display), 0, 0)
        if now < invuln_until:
            display.text("I", 52, 0)

        display.show()
        time.sleep_ms(30)
