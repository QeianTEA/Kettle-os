# games/heatseekers/heatseekers.py
# HeatSeekers - Pico (128x64)
# Extended: miniboss, passerby jets, bullets, powerup storage/use, restart on L_shoulder
# Preserves existing behavior and integrates new features.

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
PY = 56
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

# Powerups spawn timing
last_powerup_ms = 0
next_powerup_ms = 0

# Invulnerability
invuln_until = 0

# Game timing
start_ms = 0

# Missile types: (name, px_w, px_h, base_speed_px_frame, maneuver, blink, spawn_weight)
MISSILE_TYPES = [
    ('standard',   2, 2, 2.5, 0.062, False, 1.0),
    ('blinky_fast',1, 1, 4.2, 0.052, True,  0.6),
    ('man',        1, 1, 2.5, 0.100, False, 0.6),
    ('slowblink',  2, 2, 1.5, 0.055, True,  0.1),
]

# Passerby jets config (new enemy)
PASSERBY_CONFIG = {
    'spawn_ms_min': 4000,    # min interval
    'spawn_ms_max': 9000,    # max interval
    'speed': 6.5,            # px/frame horizontal
    'missile_delay': 700,    # ms after spawn they drop a missile
    'size': (6, 2),          # px (w,h)
    'last_spawn_ms': 0,
}

# Boss config (miniboss)
BOSS_CONFIG = {
    'appear_after_s': 100.0,   # seconds until miniboss appears
    'start_world_y': -160.0,   # spawn high above
    'follow_speed': 0.9,       # how quickly the boss follows player horizontally
    'dodge_dist': 16.0,        # how close a bullet must be before boss dodges
    'hp': 12,                  # boss health (adjustable)
    'rocket_speed': 6.0,       # rocket projectile speed (fast)
    'rocket_size': (3,3),
    'pattern_delay_ms': 1200,  # delay between attack patterns
    'last_pattern_ms': 0,
}

# Player bullets config
BULLET_SPEED = 8.5   # px per frame upward (fast)
BULLET_SIZE = (2,2)
bullets = []

# State
missiles = []
powerups = []
explosions = []
passerby = []   # list of passerby jets
boss = None     # boss dict or None
boss_active = False

# stored powerup (single slot)
stored_powerup = None  # string like 'shoot', 'maneuver', 'invuln'

# active powerups on player (timed)
shoot_until = 0
maneuver_until = 0

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
        try:
            display.rect(cx - 4, cy - 4, 9, 9, 1)
        except TypeError:
            display.rect(cx - 4, cy - 4, 9, 9)

def spawn_missile(elapsed_s):
    """
    Spawn a missile type using weights:
      weight_for_type = spawn_weight * (1.0 + time_bias)
    where time_bias increases over time so later-game favors stronger types.
    """
    weights = []
    for i, t in enumerate(MISSILE_TYPES):
        spawn_weight = t[6]
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
        'born_ms': now_ms(), 'owner': 'missile'
    })

def spawn_powerup():
    # randomly choose type
    ptype = random.choice(['shoot', 'maneuver', 'invuln'])
    wx = player_world_x + random.uniform(-W * 0.5, W * 0.5)
    wy = -random.uniform(60.0, 140.0)
    powerups.append({'world_x': wx, 'world_y': wy, 'type': ptype, 'born_ms': now_ms()})

def spawn_passerby():
    # spawn a passerby coming either left-to-right or right-to-left across top area
    dir = random.choice([-1, 1])
    # world_x spawn well off-screen depending on direction
    if dir == -1:
        wx = player_world_x + W + 40.0
    else:
        wx = player_world_x - W - 40.0
    wy = -random.uniform(90.0, 40.0)
    pw, ph = PASSERBY_CONFIG['size']
    passerby.append({
        'world_x': wx, 'world_y': wy,
        'vx': dir * PASSERBY_CONFIG['speed'], 'vy': 0.0,
        'pw': pw, 'ph': ph,
        'born_ms': now_ms(), 'fired': False
    })
    PASSERBY_CONFIG['last_spawn_ms'] = now_ms()

def spawn_boss():
    global boss, boss_active, shoot_until
    boss = {
        'world_x': player_world_x,
        'world_y': BOSS_CONFIG['start_world_y'],
        'vx': 0.0, 'vy': 0.0,
        'hp': BOSS_CONFIG['hp'],
        'born_ms': now_ms(),
        'last_dodge_ms': 0
    }
    boss_active = True
    # grant player shooting power instantly for a reasonable fight window
    shoot_until = now_ms() + 10000  # 10 seconds of shooting active immediately
    # mark pattern timer so boss starts attacking
    BOSS_CONFIG['last_pattern_ms'] = now_ms()

def spawn_boss_rocket(bx, by, target_x):
    # spawn a boss rocket aimed at target_x with high speed
    vx = (target_x - bx) * 0.02
    vy = BOSS_CONFIG['rocket_speed']
    missiles.append({
        'type': 'boss_rocket', 'world_x': bx, 'world_y': by,
        'vx': vx, 'vy': vy,
        'pw': BOSS_CONFIG['rocket_size'][0], 'ph': BOSS_CONFIG['rocket_size'][1],
        'maneuver': 0.0, 'blink': False, 'born_ms': now_ms(), 'owner': 'boss'
    })

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

# Splash helper: try graphic or fallback to text (unchanged)
def _show_splash_image_or_text(display, buttons):
    try:
        from modules.img_loader import play_gif_from_index, blit_rle_file
    except Exception:
        play_gif_from_index = None
        blit_rle_file = None

    try:
        import images.heatseekers.heatseekers_index as hk_idx
        if play_gif_from_index:
            try:
                ok = play_gif_from_index(display, hk_idx.IMAGES, "/images/heatseekers",
                                         center=False, loops=1, hold_last=True)
                if ok:
                    while True:
                        if buttons.get_event() == 'CONFIRM':
                            return
                        time.sleep_ms(40)
            except Exception:
                pass
    except Exception:
        pass

    # fallback text
    display.clear()
    display.text("HEATSEEKERS", 12, 18)
    display.text("L/R to steer", 8, 34)
    display.text("Press to play", 8, 46)
    display.show()
    while True:
        if buttons.get_event() == 'CONFIRM':
            return
        time.sleep_ms(40)


# Draw stored powerup icon (8x8) bottom-left
def draw_powerup_icon(display, ptype):
    # icon area bottom-left: x=2,y=H-10 (fits 8x8)
    sx = 2
    sy = H - 10
    # clear 8x8
    try:
        display.fill_rect(sx, sy, 8, 8, 0)
    except TypeError:
        display.fill_rect(sx, sy, 8, 8)
    if ptype is None:
        # draw empty outline
        display.rect(sx, sy, 8, 8)
        return
    # draw type shapes
    if ptype == 'shoot':
        # small cannon icon: a rectangle and a muzzle
        display.fill_rect(sx + 1, sy + 3, 5, 2, 1)
        display.fill_rect(sx + 6, sy + 2, 2, 2, 1)
    elif ptype == 'maneuver':
        # draw zigzag arrow
        display.fill_rect(sx + 1, sy + 1, 6, 1, 1)
        display.fill_rect(sx + 4, sy + 1, 1, 3, 1)
    elif ptype == 'invuln':
        # shield shape
        display.rect(sx + 1, sy + 1, 6, 6)
        display.fill_rect(sx + 3, sy + 3, 2, 2, 1)
    else:
        display.rect(sx, sy, 8, 8)

# MAIN
def run(display, buttons):
    global player_world_x, player_lat_vel, last_spawn_ms, start_ms, last_powerup_ms, next_powerup_ms, invuln_until
    global missiles, powerups, explosions, passerby, boss, boss_active, bullets
    global stored_powerup, shoot_until, maneuver_until

    # raw pins
    pin_left = Pin(PIN_LEFT, Pin.IN, Pin.PULL_UP)
    pin_right = Pin(PIN_RIGHT, Pin.IN, Pin.PULL_UP)
    pin_sh_l = Pin(PIN_SH_L, Pin.IN, Pin.PULL_UP)
    pin_sh_r = Pin(PIN_SH_R, Pin.IN, Pin.PULL_UP)

    # initial reset
    missiles.clear(); powerups.clear(); explosions.clear(); passerby.clear(); bullets.clear()
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

    stored_powerup = None
    shoot_until = 0
    maneuver_until = 0
    boss = None
    boss_active = False
    PASSERBY_CONFIG['last_spawn_ms'] = now_ms()

    # Try graphical splash first; fallback to text if not available
    _show_splash_image_or_text(display, buttons)

    # <<< CLEAN RESET HERE >>>
    missiles.clear()
    powerups.clear()
    explosions.clear()
    passerby.clear()
    bullets.clear()
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

        # spawn boss when time reached
        if (not boss_active) and elapsed_s >= BOSS_CONFIG['appear_after_s']:
            spawn_boss()

        if exploding:
            # while exploding freeze movement for player; explosions still drawn below
            pass
        else:
            # continuous input
            steering_left = (pin_left.value() == 0) or (pin_sh_l.value() == 0)
            steering_right = (pin_right.value() == 0) or (pin_sh_r.value() == 0)

            # apply maneuver powerup modifier
            lat_accel = LAT_ACCEL * (2.0 if now < maneuver_until else 1.0)
            lat_max = LAT_MAX * (1.4 if now < maneuver_until else 1.0)

            if steering_left and not steering_right:
                player_lat_vel -= lat_accel
                angle = clamp(angle - 6.0, -45.0, 45.0)
            elif steering_right and not steering_left:
                player_lat_vel += lat_accel
                angle = clamp(angle + 6.0, -45.0, 45.0)
            else:
                angle *= 0.9

            player_lat_vel = clamp(player_lat_vel, -lat_max, lat_max)
            player_lat_vel *= LAT_FRICTION
            player_world_x += player_lat_vel
            max_world = W * 2.0
            player_world_x = clamp(player_world_x, -max_world, max_world)

            # spawn missiles (existing logic)
            si = spawn_interval_ms(elapsed_s)
            if time.ticks_diff(now, last_spawn_ms) >= si:
                spawn_missile(elapsed_s)
                last_spawn_ms = now

            # spawn powerups
            if now >= next_powerup_ms:
                spawn_powerup()
                last_powerup_ms = now
                next_powerup_ms = now + random.randint(15000, 30000)

            # spawn passerby occasionally
            if time.ticks_diff(now, PASSERBY_CONFIG['last_spawn_ms']) > _randint(PASSERBY_CONFIG['spawn_ms_min'], PASSERBY_CONFIG['spawn_ms_max']):
                spawn_passerby()

            # update missiles (seek player)
            to_remove = []
            for m in list(missiles):
                if m['vy'] > 0:
                    t = -m['world_y'] / m['vy'] if m['vy'] != 0 else 10.0
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

            # update passerby jets
            for p in list(passerby):
                p['world_x'] += p['vx']
                # check if it's time to fire missile
                if not p['fired'] and time.ticks_diff(now, p['born_ms']) > PASSERBY_CONFIG['missile_delay']:
                    # spawn a missile under the jet aimed at player approximate x
                    mx = p['world_x']; my = p['world_y'] + 6.0
                    target_x = player_world_x
                    # make a standard missile object
                    missiles.append({
                        'type': 'p_missile', 'world_x': mx, 'world_y': my,
                        'vx': (target_x - mx) * 0.02, 'vy': 3.6,
                        'pw': 2, 'ph': 2, 'maneuver': 0.02, 'blink': False,
                        'born_ms': now, 'owner': 'passerby'
                    })
                    p['fired'] = True
                # remove if far off-screen
                if abs(p['world_x'] - player_world_x) > W * 2.0:
                    if p in passerby:
                        passerby.remove(p)

            # update boss if active
            if boss_active and boss:
                # simple follow: move boss.world_x towards player_world_x
                dx = player_world_x - boss['world_x']
                boss['vx'] = dx * 0.02 * BOSS_CONFIG['follow_speed']
                boss['world_x'] += boss['vx']
                # boss stays at fixed world_y near top but can slightly bob
                boss['world_y'] = BOSS_CONFIG['start_world_y'] + math.sin((now - boss['born_ms'])/400.0) * 4.0
                # dodging logic: if any bullet is within dodge_dist horizontally, shift away
                for b in list(bullets):
                    if abs(b['world_x'] - boss['world_x']) < BOSS_CONFIG['dodge_dist']:
                        # dodge away horizontally
                        dodge = -math.copysign(8.0, (b['world_x'] - boss['world_x']))
                        boss['world_x'] += dodge * 0.6
                        boss['last_dodge_ms'] = now
                        break
                # attack patterns
                if time.ticks_diff(now, BOSS_CONFIG['last_pattern_ms']) >= BOSS_CONFIG['pattern_delay_ms']:
                    BOSS_CONFIG['last_pattern_ms'] = now
                    # choose one pattern: spread rockets, tracking rockets, burst
                    pat = random.choice([0,1,2])
                    if pat == 0:
                        # spread rockets aimed in fan
                        for ang in (-0.35, -0.1, 0.1, 0.35):
                            missiles.append({
                                'type': 'boss_rocket', 'world_x': boss['world_x'], 'world_y': boss['world_y'] + 8.0,
                                'vx': ang * BOSS_CONFIG['rocket_speed'], 'vy': BOSS_CONFIG['rocket_speed'],
                                'pw': BOSS_CONFIG['rocket_size'][0], 'ph': BOSS_CONFIG['rocket_size'][1],
                                'maneuver': 0.0, 'blink': False, 'born_ms': now, 'owner': 'boss'
                            })
                    elif pat == 1:
                        # aimed rockets directly at player X
                        spawn_boss_rocket(boss['world_x'], boss['world_y'] + 6.0, player_world_x)
                        spawn_boss_rocket(boss['world_x'] - 12.0, boss['world_y'] + 6.0, player_world_x)
                        spawn_boss_rocket(boss['world_x'] + 12.0, boss['world_y'] + 6.0, player_world_x)
                    else:
                        # fast bullet barrage straight down near player
                        for sx in (-10, -5, 0, 5, 10):
                            missiles.append({
                                'type': 'boss_bullet', 'world_x': boss['world_x'] + sx, 'world_y': boss['world_y'] + 6.0,
                                'vx': 0.0, 'vy': BOSS_CONFIG['rocket_speed'] * 1.2,
                                'pw': 2, 'ph': 2, 'maneuver': 0.0, 'blink': False, 'born_ms': now, 'owner': 'boss'
                            })

            # bullets update (player fired)
            for b in list(bullets):
                b['world_y'] -= b['vy']
                # screen cull
                if world_to_screen_y(b['world_y']) < -48:
                    if b in bullets: bullets.remove(b)

            # collisions: bullets vs missiles, passerby, boss
            # bullets are very fast; do simple overlap checks
            for b in list(bullets):
                # check missiles
                for m in list(missiles):
                    if rects_overlap(b['world_x'], b['world_y'], b['pw'], b['ph'],
                                     m['world_x'], m['world_y'], m['pw'], m['ph']):
                        # if missile belongs to boss, still destroy, but boss unaffected unless it's a special rocket - only boss death via HP
                        if m in missiles:
                            missiles.remove(m)
                        if b in bullets:
                            bullets.remove(b)
                        # create explosion
                        create_explosion_at_world(m['world_x'], m['world_y'], now, size=5, vy=None)
                        break
                # passerby collision
                for p in list(passerby):
                    if rects_overlap(b['world_x'], b['world_y'], b['pw'], b['ph'],
                                     p['world_x'], p['world_y'], p['pw'], p['ph']):
                        # kill passerby
                        if p in passerby:
                            passerby.remove(p)
                        if b in bullets:
                            bullets.remove(b)
                        create_explosion_at_world(p['world_x'], p['world_y'], now, size=6, vy=None)
                        break
                # boss collision
                if boss_active and boss and rects_overlap(b['world_x'], b['world_y'], b['pw'], b['ph'],
                                                          boss['world_x'], boss['world_y'], 18, 12):
                    # direct hit reduces boss HP
                    boss['hp'] -= 1
                    if b in bullets: bullets.remove(b)
                    create_explosion_at_world(b['world_x'], b['world_y'], now, size=6, vy=None)
                    if boss['hp'] <= 0:
                        # boss dies: show victory sequence then return to menu
                        create_explosion_at_world(boss['world_x'], boss['world_y'], now, size=18, vy=1.0)
                        # clean-up
                        missiles[:] = []
                        passerby[:] = []
                        boss_active = False
                        boss = None
                        # victory screen
                        display.clear()
                        display.text("VICTORY", 36, 20)
                        display.show()
                        time.sleep(2.0)
                        return
                    break

            # missile vs missile collisions (existing)
            msnap = list(missiles)
            for i, a in enumerate(msnap):
                if a not in missiles:
                    continue
                ax = a['world_x']; ay = a['world_y']; aw = a['pw']; ah = a['ph']
                for b2 in msnap[i+1:]:
                    if b2 not in missiles:
                        continue
                    bx = b2['world_x']; by = b2['world_y']; bw = b2['pw']; bh = b2['ph']
                    if rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
                        center_x = (ax + aw/2.0 + bx + bw/2.0) / 2.0
                        center_y = (ay + ah/2.0 + by + bh/2.0) / 2.0
                        create_explosion_at_world(center_x, center_y, now, size=5, vy=None)
                        if a in missiles: missiles.remove(a)
                        if b2 in missiles: missiles.remove(b2)

            # update powerups falling and pickup
            pu_remove = []
            for pu in list(powerups):
                pu['world_y'] += 1.2
                sx = world_to_screen_x(pu['world_x'], player_world_x)
                sy = world_to_screen_y(pu['world_y'])
                plx, ply, pw, ph = plane_rect()
                if rects_overlap(sx, sy, 4, 4, plx, ply, pw, ph):
                    # pick up: store powerup (replace existing stored)
                    stored_powerup = pu['type']
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
                    create_explosion_at_world(player_world_x, 0.0, now, size=5, vy=None)
                    if hit_missile and hit_missile in missiles:
                        missiles.remove(hit_missile)
                    exploding = True
                    explosion_end_ms = now + 1000
                    game_over = True

            # explosions destroying missiles (when explosions move)
            if not exploding:
                for ex in list(explosions):
                    ex['wy'] += ex.get('vy', 1.5)
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
                # while exploding, keep checking but do not advance explosion wy
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

        # ----- RENDER -----
        display.clear()

        # missiles
        blink_phase = ((now // 75) & 1)
        for m in list(missiles):
            sx = world_to_screen_x(m['world_x'], player_world_x)
            sy = world_to_screen_y(m['world_y'])
            w_px = int(m['pw']); h_px = int(m['ph'])
            if sy < -32 or sy > H + 32 or sx < -64 or sx > W + 64:
                continue
            if m['type'].startswith('boss_'):
                # boss rockets always drawn (big and visible)
                display.fill_rect(int(sx), int(sy), w_px, h_px, 1)
            elif m['blink']:
                if blink_phase:
                    display.fill_rect(int(sx), int(sy), w_px, h_px, 1)
            else:
                display.fill_rect(int(sx), int(sy), w_px, h_px, 1)

        # passerby jets
        for p in list(passerby):
            sx = world_to_screen_x(p['world_x'], player_world_x)
            sy = world_to_screen_y(p['world_y'])
            if -20 <= sy <= H + 20:
                # small rectangle for jet
                display.fill_rect(int(sx), int(sy), int(p['pw']), int(p['ph']), 1)

        # powerups (icons falling)
        for pu in list(powerups):
            sx = world_to_screen_x(pu['world_x'], player_world_x)
            sy = world_to_screen_y(pu['world_y'])
            if -16 <= sy <= H + 16:
                display.rect(int(sx), int(sy), 4, 4, 1)

        # explosions drawing
        ex_blink_phase = ((now // 300) & 1)
        new_explosions = []
        for ex in list(explosions):
            age = now - ex['born']
            if age <= 2000:
                sx = world_to_screen_x(ex['wx'], player_world_x) - (ex['size'] // 2)
                sy = world_to_screen_y(ex['wy']) - (ex['size'] // 2)
                if ex_blink_phase:
                    display.fill_rect(int(sx), int(sy), ex['size'], ex['size'], 1)
                new_explosions.append(ex)
        explosions[:] = new_explosions

        # bullets
        for b in list(bullets):
            sx = world_to_screen_x(b['world_x'], player_world_x)
            sy = world_to_screen_y(b['world_y'])
            if -40 <= sy <= H + 40:
                display.fill_rect(int(sx), int(sy), b['pw'], b['ph'], 1)

        # boss draw (big) if active
        if boss_active and boss:
            bx = world_to_screen_x(boss['world_x'], player_world_x)
            by = world_to_screen_y(boss['world_y'])
            # boss body
            display.fill_rect(int(bx)-9, int(by)-6, 18, 12, 1)
            # show boss HP as boxes above
            hpboxes = max(0, min(8, boss['hp']))
            for i in range(hpboxes):
                display.fill_rect(int(bx) - 8 + i*2, int(by) - 10, 2, 2, 1)

        # player (don't draw while exploding)
        if not exploding:
            invuln = (now < invuln_until)
            draw_plane(display, angle, invuln)
        else:
            # explosion finished -> crashed screen
            if 'explosion_end_ms' in locals() and now >= explosion_end_ms:
                total_s = int((explosion_end_ms - start_ms) / 1000.0)
                display.show()
                display.clear()
                display.text("CRASHED", 28, 12)
                display.text("T:%03d s" % (total_s), 40, 28)
                display.text("Press L to restart", 4, 46)
                display.show()
                # Wait for either L_SH to restart or CONFIRM to exit to menu
                while True:
                    ev = None
                    # poll raw pins too for left-shoulder quick restart
                    if pin_sh_l.value() == 0:
                        ev = 'RESTART'
                    else:
                        ev = buttons.get_event()
                    if ev == 'RESTART' or ev == 'SHOULDER_L':
                        # restart in-place (break to outer loop which reinitializes)
                        return run(display, buttons)
                    if ev == 'CONFIRM':
                        return
                    time.sleep_ms(60)

        # HUD: time, invuln indicator, stored powerup icon bottom-left
        try:
            display.fill_rect(0, 0, 56, 8, 0)
        except TypeError:
            display.fill_rect(0, 0, 56, 8)
        elapsed_display = int(elapsed_s)
        display.text("T:%03d" % (elapsed_display), 0, 0)
        if now < invuln_until:
            display.text("I", 56, 0)

        # draw stored powerup icon bottom-left
        draw_powerup_icon(display, stored_powerup)

        display.show()

        # ---- Player input: CONFIRM usage: fire bullet if shoot active, else use stored powerup
        # CONFIRM interpreted via buttons.get_event() occasionally; poll a few times for responsiveness
        ev = buttons.get_event()
        if ev == 'CONFIRM':
            if now < shoot_until:
                # fire bullet
                bullets.append({
                    'world_x': player_world_x, 'world_y': -2.0, 'pw': BULLET_SIZE[0], 'ph': BULLET_SIZE[1], 'vy': BULLET_SPEED
                })
            else:
                # use stored powerup if any
                if stored_powerup is not None:
                    if stored_powerup == 'shoot':
                        shoot_until = now + random.randint(5000, 10000)  # random 5-10s per your request
                    elif stored_powerup == 'maneuver':
                        maneuver_until = now + random.randint(5000, 10000)
                    elif stored_powerup == 'invuln':
                        invuln_until = now + random.randint(3000, 8000)
                    stored_powerup = None

        # Small step sleep
        time.sleep_ms(28)


# small helper: robust randint used earlier
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
