# games/heatseekers/heatseekers.py
# HeatSeekers - Pico (128x64)
# Extended/fixed: miniboss, passerby jets (dive), bullets, powerup storage/use, restart on L_shoulder
# Performance: fixed-point math kept; death handling/sync fixed; passerby modified to dive.
# Adjustments: boss spawn at 45s & visible; missiles/passerby spawn higher; reliable missile-vs-missile explosions.

import time
import random
import math
from machine import Pin

GAME = {'name': 'HeatSeekers'}

# ---------- CONFIG ----------
W = 128
H = 64

PX = W // 2
PY = 56
PLANE_W = 4
PLANE_H = 3

# Fixed-point scale
FP = 16

# Player fixed-point world and velocity
player_world_x = 0
player_lat_vel = 0

LAT_ACCEL = int(1.2 * FP)
LAT_MAX = int(7.2 * FP)
LAT_FRICTION_FP = 0.88

MISSILE_BASE_SPAWN_MS = 700
MIN_SPAWN_MS = 180
last_spawn_ms = 0

last_powerup_ms = 0
next_powerup_ms = 0

invuln_until = 0
start_ms = 0

MISSILE_TYPES = [
    ('standard',   2, 2, 2.5, 0.048, False, 1.0),
    ('blinky_fast',1, 1, 4.2, 0.02, True,  0.6),
    ('man',        1, 1, 2.5, 0.10, False, 0.6),
    ('slowblink',  2, 2, 1.5, 0.15, True,  0.1),
]

PASSERBY_CONFIG = {
    'spawn_ms_min': 4000,
    'spawn_ms_max': 9000,
    'speed': 4.5,
    'missile_delay': 0,
    'size': (8,3),
    'last_spawn_ms': 0
}

BOSS_CONFIG = {
    'appear_after_s': 45.0,         # changed: spawn earlier at 45s
    'start_world_y': -40.0,         # changed: spawn near top of screen (visible)
    'follow_speed': 0.9,
    'dodge_dist': 16.0,
    'hp': 18,
    'rocket_speed': 6.0,
    'rocket_size': (3,3),
    'pattern_delay_ms': 1200,
    'last_pattern_ms': 0,
}

BULLET_SPEED = 6
BULLET_SIZE = (2,2)
bullets = []

missiles = []
powerups = []
explosions = []
passerby = []
boss = None
boss_active = False

stored_powerup = None
shoot_until = 0
maneuver_until = 0

PIN_LEFT = 8
PIN_RIGHT = 9
PIN_SH_L = 11
PIN_SH_R = 12

# ---------- helpers ----------
def now_ms():
    return time.ticks_ms()

def clamp(v, a, b):
    if v < a: return a
    if v > b: return b
    return v

def rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)

def fp_from_float(f):
    return int(f * FP)

def fp_to_int(fp_val):
    if fp_val >= 0:
        return fp_val // FP
    return -((-fp_val) // FP)

def spawn_interval_ms(elapsed_s):
    t = min(elapsed_s, 120.0)
    frac = t / 120.0
    return int(MISSILE_BASE_SPAWN_MS - frac * (MISSILE_BASE_SPAWN_MS - MIN_SPAWN_MS))

def world_to_screen_x(world_x_fp, world_x_offset_fp):
    dx_fp = world_x_fp - world_x_offset_fp
    return PX + fp_to_int(dx_fp)

def world_to_screen_y(world_y_fp):
    return PY + fp_to_int(world_y_fp)

def plane_rect():
    left = PX - (PLANE_W // 2)
    top = PY - (PLANE_H // 2)
    return left, top, PLANE_W, PLANE_H

def draw_plane(display, angle_deg, invuln):
    cx = PX; cy = PY
    shift = int(clamp(angle_deg / 20.0, -3, 3))
    try:
        display.fill_rect(cx + shift, cy - 3, 1, 1, 1)
        display.fill_rect(cx - 1 + shift, cy - 2, 3, 1, 1)
        display.fill_rect(cx + shift, cy - 1, 1, 1, 1)
        display.fill_rect(cx - 3 + shift, cy - 1, 2, 1, 1)
        display.fill_rect(cx + 2 + shift, cy - 1, 2, 1, 1)
    except TypeError:
        display.fill_rect(cx + shift, cy - 3, 1, 1)
        display.fill_rect(cx - 1 + shift, cy - 2, 3, 1)
        display.fill_rect(cx + shift, cy - 1, 1, 1)
        display.fill_rect(cx - 3 + shift, cy - 1, 2, 1)
        display.fill_rect(cx + 2 + shift, cy - 1, 2, 1)
    if invuln:
        try:
            display.rect(cx - 4, cy - 4, 9, 9, 1)
        except TypeError:
            display.rect(cx - 4, cy - 4, 9, 9)

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

# ---------- spawners (fixed point conversions) ----------
def spawn_missile(elapsed_s):
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
    # spawn higher above so they come into frame
    wx_fp = fp_from_float(player_world_x / FP + random.uniform(-W * 0.6, W * 0.6))
    wy_fp = fp_from_float(-random.uniform(80.0, 160.0))   # raised spawn height
    vx_fp = fp_from_float(random.uniform(-0.6, 0.6))
    vy_fp = fp_from_float(speed)
    missiles.append({
        'type': name, 'world_x': wx_fp, 'world_y': wy_fp,
        'vx': vx_fp, 'vy': vy_fp,
        'pw': pw, 'ph': ph, 'maneuver': maneuver, 'blink': blink,
        'born_ms': now_ms(), 'owner': 'missile'
    })

def spawn_powerup():
    ptype = random.choice(['shoot', 'maneuver', 'invuln'])
    wx_fp = fp_from_float(player_world_x / FP + random.uniform(-W * 0.5, W * 0.5))
    wy_fp = fp_from_float(-random.uniform(60.0, 140.0))
    powerups.append({'world_x': wx_fp, 'world_y': wy_fp, 'type': ptype, 'born_ms': now_ms()})

def spawn_passerby():
    # spawn in front of player (±30 px) and noticeably higher so they dive into view
    player_px = player_world_x / FP
    offset = random.uniform(-30.0, 30.0)
    wx_fp = fp_from_float(player_px + offset)
    wy_fp = fp_from_float(-random.uniform(220.0, 140.0))  # spawn higher than before

    # stronger initial horizontal velocity toward player's current position (more aggressive tracking)
    # compute delta in fixed-point and apply a larger factor so jets start heading directly at player
    delta_fp = int(player_world_x - wx_fp)
    vx_fp = int(delta_fp * 0.12)   # <-- change factor here to tune "closeness" at spawn (0.12 is fairly strong)
    vy_fp = fp_from_float(PASSERBY_CONFIG['speed'])
    pw, ph = PASSERBY_CONFIG['size']
    passerby.append({
        'world_x': wx_fp, 'world_y': wy_fp,
        'vx': vx_fp, 'vy': vy_fp, 'pw': pw, 'ph': ph,
        'born_ms': now_ms(), 'fired': False
    })
    PASSERBY_CONFIG['last_spawn_ms'] = now_ms()


def spawn_boss():
    global boss, boss_active, shoot_until
    boss = {
        'world_x': fp_from_float(player_world_x / FP),
        'world_y': fp_from_float(BOSS_CONFIG['start_world_y']),
        'vx': 0, 'vy': 0,
        'hp': BOSS_CONFIG['hp'],
        'born_ms': now_ms(), 'last_dodge_ms': 0
    }
    boss_active = True
    shoot_until = now_ms() + 10000
    BOSS_CONFIG['last_pattern_ms'] = now_ms()

def spawn_boss_rocket(bx_fp, by_fp, target_x_fp):
    dx_fp = target_x_fp - bx_fp
    vx_fp = int((dx_fp * int(BOSS_CONFIG['rocket_speed'] * FP)) / (8 * FP))
    vy_fp = fp_from_float(BOSS_CONFIG['rocket_speed'])
    missiles.append({
        'type': 'boss_rocket', 'world_x': bx_fp, 'world_y': by_fp,
        'vx': vx_fp, 'vy': vy_fp,
        'pw': BOSS_CONFIG['rocket_size'][0], 'ph': BOSS_CONFIG['rocket_size'][1],
        'maneuver': 0.0, 'blink': False, 'born_ms': now_ms(), 'owner': 'boss'
    })

def create_explosion_at_world(wx_fp_or_f, wy_fp_or_f, now_ts, size=5, vy=None):
    if isinstance(wx_fp_or_f, int):
        wx_fp = wx_fp_or_f
    else:
        wx_fp = fp_from_float(wx_fp_or_f)
    if isinstance(wy_fp_or_f, int):
        wy_fp = wy_fp_or_f
    else:
        wy_fp = fp_from_float(wy_fp_or_f)
    if vy is None:
        vy_fp = fp_from_float(1.5)
    else:
        vy_fp = fp_from_float(vy)
    explosions.append({'wx': float(wx_fp), 'wy': float(wy_fp), 'vy': float(vy_fp), 'born': now_ts, 'size': int(size)})
    ex_left_px = world_to_screen_x(int(wx_fp), player_world_x) - (size // 2)
    ex_top_px  = world_to_screen_y(int(wy_fp)) - (size // 2)
    ex_w = size; ex_h = size
    rm = []
    for m in list(missiles):
        mx_px = world_to_screen_x(int(m['world_x']), player_world_x)
        my_px = world_to_screen_y(int(m['world_y']))
        if rects_overlap(ex_left_px, ex_top_px, ex_w, ex_h, mx_px, my_px, m['pw'], m['ph']):
            rm.append(m)
    for m in rm:
        if m in missiles: missiles.remove(m)

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

    display.clear()
    display.text("HEATSEEKERS", 12, 18)
    display.text("L/R to steer", 8, 34)
    display.text("Press to play", 8, 46)
    display.show()
    while True:
        if buttons.get_event() == 'CONFIRM':
            return
        time.sleep_ms(40)

def draw_powerup_icon(display, ptype):
    sx = 2
    sy = H - 10
    try:
        display.fill_rect(sx, sy, 8, 8, 0)
    except TypeError:
        display.fill_rect(sx, sy, 8, 8)
    if ptype is None:
        display.rect(sx, sy, 8, 8)
        return
    if ptype == 'shoot':
        display.fill_rect(sx + 1, sy + 3, 5, 2, 1)
        display.fill_rect(sx + 6, sy + 2, 2, 2, 1)
    elif ptype == 'maneuver':
        display.fill_rect(sx + 1, sy + 1, 6, 1, 1)
        display.fill_rect(sx + 4, sy + 1, 1, 3, 1)
    elif ptype == 'invuln':
        display.rect(sx + 1, sy + 1, 6, 6)
        display.fill_rect(sx + 3, sy + 3, 2, 2, 1)
    else:
        display.rect(sx, sy, 8, 8)

# ---------- MAIN ----------
def run(display, buttons):
    """
    Outer session loop allows immediate restart without re-showing splash.
    """
    global player_world_x, player_lat_vel, last_spawn_ms, start_ms, last_powerup_ms, next_powerup_ms, invuln_until
    global missiles, powerups, explosions, passerby, boss, boss_active, bullets
    global stored_powerup, shoot_until, maneuver_until

    pin_left = Pin(PIN_LEFT, Pin.IN, Pin.PULL_UP)
    pin_right = Pin(PIN_RIGHT, Pin.IN, Pin.PULL_UP)
    pin_sh_l = Pin(PIN_SH_L, Pin.IN, Pin.PULL_UP)
    pin_sh_r = Pin(PIN_SH_R, Pin.IN, Pin.PULL_UP)

    # session loop
    skip_splash = False
    while True:
        if not skip_splash:
            _show_splash_image_or_text(display, buttons)
        skip_splash = False

        missiles.clear(); powerups.clear(); explosions.clear(); passerby.clear(); bullets.clear()
        player_world_x = fp_from_float(0.0)
        player_lat_vel = 0
        last_spawn_ms = now_ms()
        last_powerup_ms = now_ms()
        next_powerup_ms = last_powerup_ms + _randint(3000, 5000)
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

        while True:
            now = now_ms()
            elapsed_s = (now - start_ms) / 1000.0
            
                        # ----- missile spawn window -----
            # Disallow missile & passerby spawning in the final 5 seconds before boss appears.
            # This variable is used later when deciding to spawn missiles / passerby and when
            # passerby decide to drop their missile.
            missiles_allowed = (elapsed_s < (BOSS_CONFIG['appear_after_s'] - 5.0)) and (not boss_active)


            # spawn boss when time reached
            if (not boss_active) and elapsed_s >= BOSS_CONFIG['appear_after_s']:
                spawn_boss()

            if exploding:
                pass
            else:
                steering_left = (pin_left.value() == 0) or (pin_sh_l.value() == 0)
                steering_right = (pin_right.value() == 0) or (pin_sh_r.value() == 0)

                accel_mult = 2 if now < maneuver_until else 1
                lat_accel_fp = LAT_ACCEL * accel_mult
                lat_max_fp = int(LAT_MAX * (1.4 if now < maneuver_until else 1.0))

                if steering_left and not steering_right:
                    player_lat_vel -= lat_accel_fp
                    angle = clamp(angle - 6.0, -45.0, 45.0)
                elif steering_right and not steering_left:
                    player_lat_vel += lat_accel_fp
                    angle = clamp(angle + 6.0, -45.0, 45.0)
                else:
                    angle *= 0.9

                player_lat_vel = int(player_lat_vel * LAT_FRICTION_FP)
                player_lat_vel = clamp(player_lat_vel, -lat_max_fp, lat_max_fp)
                player_world_x += player_lat_vel
                max_world_fp = fp_from_float(W * 2.0)
                player_world_x = clamp(player_world_x, -max_world_fp, max_world_fp)

                si = spawn_interval_ms(elapsed_s)
                if time.ticks_diff(now, last_spawn_ms) >= si:
                    spawn_missile(elapsed_s)
                    last_spawn_ms = now

                if now >= next_powerup_ms:
                    spawn_powerup()
                    last_powerup_ms = now
                    next_powerup_ms = now + _randint(3000, 5000)

                if time.ticks_diff(now, PASSERBY_CONFIG['last_spawn_ms']) > _randint(PASSERBY_CONFIG['spawn_ms_min'], PASSERBY_CONFIG['spawn_ms_max']):
                    spawn_passerby()

                # update missiles (fixed-point)
                to_remove = []
                for m in list(missiles):
                    vy_px = fp_to_int(m['vy'])
                    world_y_px = fp_to_int(m['world_y'])
                    if vy_px == 0:
                        t_frames = 10
                    else:
                        t_frames = max(1, int(-world_y_px / vy_px))
                    predicted_target_x_fp = player_world_x + int(player_lat_vel * t_frames / 4)
                    desired_vx_fp = int((predicted_target_x_fp - m['world_x']) / max(1, t_frames))
                    max_delta_fp = int(m['maneuver'] * 6.0 * FP)
                    dv = clamp(desired_vx_fp - m['vx'], -max_delta_fp, max_delta_fp)
                    m['vx'] += dv
                    m['world_x'] += m['vx']
                    m['world_y'] += m['vy']
                    sy = world_to_screen_y(int(m['world_y']))
                    if sy > H + 32 or int(m['world_y']) > fp_from_float(5000.0):
                        to_remove.append(m)
                for m in to_remove:
                    if m in missiles: missiles.remove(m)

                # update passerby: dive downward (vy); apply light homing so they follow player closely
                for p in list(passerby):
                    # homing: compute desired vx toward player and gently approach it
                    # homing_strength: how aggressively they adjust toward player's x (fixed-point multiplier)
                    homing_strength = 0.5   # tune this: larger -> tighter following (0.06 good for "very close")
                    max_delta_per_frame_px = 1.5  # in pixels: max change in vx per frame (keeps jet feel)
                    # compute desired vx in fixed-point
                    desired_vx_fp = int((player_world_x - p['world_x']) * homing_strength)
                    # compute max delta in fixed-point
                    max_delta_fp = fp_from_float(max_delta_per_frame_px)
                    # clamp change so they can't instantly teleport their vx
                    dv = clamp(desired_vx_fp - p['vx'], -max_delta_fp, max_delta_fp)
                    p['vx'] += dv

                    # apply motion
                    p['world_x'] += int(p['vx'])
                    p['world_y'] += int(p['vy'])

                    p_sy = world_to_screen_y(int(p['world_y']))
                    # drop missile earlier: threshold moved up, and only if missiles_allowed
                    if missiles_allowed and (not p['fired']) and p_sy >= PY - 50:
                        mx_fp = int(p['world_x'])
                        my_fp = int(p['world_y']) + fp_from_float(4.0)
                        target_x_fp = int(player_world_x)
                        # compute horizontal velocity in fixed-point so missile aims toward player's X
                        dx_fp = (target_x_fp - mx_fp)   # fixed-point delta
                        # approximate frames-to-impact (t). Larger t -> gentler horizontal velocity.
                        # Tune this: 60 = gentle lead, 30 = stronger lead, float division used then cast to int
                        t_frames = 20.0
                        vx_fp = int(dx_fp / t_frames)
                        missiles.append({
                            'type': 'p_missile', 'world_x': mx_fp, 'world_y': my_fp,
                            'vx': vx_fp, 'vy': fp_from_float(3.8),
                            'pw': 2, 'ph': 2, 'maneuver': 0.02, 'blink': False,
                            'born_ms': now, 'owner': 'passerby'
                        })

                        p['fired'] = True

                    # remove only after they pass far below play area (so they pass near player)
                    if world_to_screen_y(int(p['world_y'])) > H + 40:
                        if p in passerby: passerby.remove(p)


                # update boss
                if boss_active and boss:
                    dx_fp = player_world_x - boss['world_x']
                    boss['vx'] = int(dx_fp * 0.02 * BOSS_CONFIG['follow_speed'])
                    boss['world_x'] += boss['vx']
                    boss['world_y'] = fp_from_float(BOSS_CONFIG['start_world_y'] + math.sin((now - boss['born_ms'])/400.0) * 4.0)
                    for b in list(bullets):
                        if abs(b['world_x'] - boss['world_x']) < fp_from_float(BOSS_CONFIG['dodge_dist']):
                            dodge = -int(math.copysign(fp_from_float(8.0), (b['world_x'] - boss['world_x'])))
                            boss['world_x'] += int(dodge * 0.6)
                            boss['last_dodge_ms'] = now
                            break
                    if time.ticks_diff(now, BOSS_CONFIG['last_pattern_ms']) >= BOSS_CONFIG['pattern_delay_ms']:
                        BOSS_CONFIG['last_pattern_ms'] = now
                        pat = random.choice([0,1,2])
                        if pat == 0:
                            for ang in (-0.35, -0.1, 0.1, 0.35):
                                missiles.append({
                                    'type': 'boss_rocket', 'world_x': int(boss['world_x']), 'world_y': int(boss['world_y'] + fp_from_float(8.0)),
                                    'vx': int(ang * BOSS_CONFIG['rocket_speed'] * FP), 'vy': fp_from_float(BOSS_CONFIG['rocket_speed']),
                                    'pw': BOSS_CONFIG['rocket_size'][0], 'ph': BOSS_CONFIG['rocket_size'][1],
                                    'maneuver': 0.0, 'blink': False, 'born_ms': now, 'owner': 'boss'
                                })
                        elif pat == 1:
                            spawn_boss_rocket(int(boss['world_x']), int(boss['world_y'] + fp_from_float(6.0)), int(player_world_x))
                            spawn_boss_rocket(int(boss['world_x']) - fp_from_float(12.0), int(boss['world_y'] + fp_from_float(6.0)), int(player_world_x))
                            spawn_boss_rocket(int(boss['world_x']) + fp_from_float(12.0), int(boss['world_y'] + fp_from_float(6.0)), int(player_world_x))
                        else:
                            for sx in (-10, -5, 0, 5, 10):
                                missiles.append({
                                    'type': 'boss_bullet', 'world_x': int(boss['world_x']) + fp_from_float(sx), 'world_y': int(boss['world_y'] + fp_from_float(6.0)),
                                    'vx': 0, 'vy': fp_from_float(BOSS_CONFIG['rocket_speed'] * 1.2),
                                    'pw': 2, 'ph': 2, 'maneuver': 0.0, 'blink': False, 'born_ms': now, 'owner': 'boss'
                                })

                # bullets update
                for b in list(bullets):
                    b['world_y'] -= fp_from_float(b['vy'])
                    if world_to_screen_y(int(b['world_y'])) < -48:
                        if b in bullets: bullets.remove(b)

                # bullets collisions (missiles/passerby/boss)
                for b in list(bullets):
                    bx_px = world_to_screen_x(int(b['world_x']), player_world_x)
                    by_px = world_to_screen_y(int(b['world_y']))
                    removed_b = False
                    for m in list(missiles):
                        mx_px = world_to_screen_x(int(m['world_x']), player_world_x)
                        my_px = world_to_screen_y(int(m['world_y']))
                        if rects_overlap(bx_px, by_px, b['pw'], b['ph'], mx_px, my_px, m['pw'], m['ph']):
                            if m in missiles: missiles.remove(m)
                            if b in bullets: bullets.remove(b)
                            removed_b = True
                            # explosion at missile world coords
                            create_explosion_at_world(int(m['world_x']), int(m['world_y']), now, size=5, vy=None)
                            break
                    if removed_b: continue
                    for p in list(passerby):
                        px_px = world_to_screen_x(int(p['world_x']), player_world_x)
                        py_px = world_to_screen_y(int(p['world_y']))
                        if rects_overlap(bx_px, by_px, b['pw'], b['ph'], px_px, py_px, p['pw'], p['ph']):
                            if p in passerby: passerby.remove(p)
                            if b in bullets: bullets.remove(b)
                            removed_b = True
                            create_explosion_at_world(int(p['world_x']), int(p['world_y']), now, size=6, vy=None)
                            break
                    if removed_b: continue
                    if boss_active and boss:
                        bx_center = world_to_screen_x(int(boss['world_x']), player_world_x)
                        by_center = world_to_screen_y(int(boss['world_y']))
                        if rects_overlap(bx_px, by_px, b['pw'], b['ph'], bx_center-9, by_center-6, 18, 12):
                            boss['hp'] -= 1
                            if b in bullets: bullets.remove(b)
                            create_explosion_at_world(int(boss['world_x']), int(boss['world_y']), now, size=6, vy=None)
                            if boss['hp'] <= 0:
                                create_explosion_at_world(int(boss['world_x']), int(boss['world_y']), now, size=18, vy=fp_from_float(1.0))
                                missiles[:] = []; passerby[:] = []
                                boss_active = False; boss = None
                                display.clear(); display.text("VICTORY", 36, 20); display.show(); time.sleep(2.0);
                                skip_splash = False
                                break

                # missile vs missile collisions (now use world coords to place explosion reliably)
                msnap = list(missiles)
                for i, a in enumerate(msnap):
                    if a not in missiles: continue
                    for b2 in msnap[i+1:]:
                        if b2 not in missiles: continue
                        ax_fp = int(a['world_x']); ay_fp = int(a['world_y'])
                        bx_fp = int(b2['world_x']); by_fp = int(b2['world_y'])
                        # compute screen pixels for overlap check (same as before)
                        ax_px = world_to_screen_x(ax_fp, player_world_x); ay_px = world_to_screen_y(ay_fp)
                        bx_px = world_to_screen_x(bx_fp, player_world_x); by_px = world_to_screen_y(by_fp)
                        if rects_overlap(ax_px, ay_px, a['pw'], a['ph'], bx_px, by_px, b2['pw'], b2['ph']):
                            # center in world fixed-point (integer)
                            center_wx = (ax_fp + bx_fp) // 2
                            center_wy = (ay_fp + by_fp) // 2
                            # create explosion at world center (guaranteed correct position)
                            create_explosion_at_world(center_wx, center_wy, now, size=5, vy=None)
                            if a in missiles: missiles.remove(a)
                            if b2 in missiles: missiles.remove(b2)

                # update powerups
                pu_remove = []
                for pu in list(powerups):
                    pu['world_y'] += fp_from_float(1.2)
                    sx = world_to_screen_x(int(pu['world_x']), player_world_x)
                    sy = world_to_screen_y(int(pu['world_y']))
                    plx, ply, pw, ph = plane_rect()
                    if rects_overlap(sx, sy, 4, 4, plx, ply, pw, ph):
                        stored_powerup = pu['type']
                        pu_remove.append(pu)
                    if sy > H + 32: pu_remove.append(pu)
                for pu in pu_remove:
                    if pu in powerups: powerups.remove(pu)

                # missile vs player collisions
                invuln = (now < invuln_until)
                if not invuln:
                    plx, ply, pw, ph = plane_rect()
                    hit = False; hit_missile = None
                    for m in list(missiles):
                        mx_px = world_to_screen_x(int(m['world_x']), player_world_x)
                        my_px = world_to_screen_y(int(m['world_y']))
                        if rects_overlap(mx_px, my_px, m['pw'], m['ph'], plx, ply, pw, ph):
                            hit = True; hit_missile = m; break
                    if hit:
                        create_explosion_at_world(int(player_world_x), fp_from_float(0.0), now, size=5, vy=None)
                        if hit_missile and hit_missile in missiles: missiles.remove(hit_missile)
                        exploding = True
                        explosion_end_ms = now + 1000
                        game_over = True

                # explosions damage missiles while moving
                if not exploding:
                    for ex in list(explosions):
                        try:
                            ex['wy'] += ex.get('vy', 1.5)
                        except Exception:
                            pass
                        ex_left = world_to_screen_x(int(ex['wx']), player_world_x) - (ex['size'] // 2)
                        ex_top  = world_to_screen_y(int(ex['wy'])) - (ex['size'] // 2)
                        rm = []
                        for m in list(missiles):
                            mx_px = world_to_screen_x(int(m['world_x']), player_world_x)
                            my_px = world_to_screen_y(int(m['world_y']))
                            if rects_overlap(ex_left, ex_top, ex['size'], ex['size'], mx_px, my_px, m['pw'], m['ph']):
                                rm.append(m)
                        for m in rm:
                            if m in missiles: missiles.remove(m)

            # If we just entered exploding state, handle death sequence now (freeze simulation and show crash after timer)
            if exploding:
                while now_ms() < explosion_end_ms:
                    display.clear()
                    ex_blink_phase = ((now_ms() // 300) & 1)
                    for ex in list(explosions):
                        age = now_ms() - ex['born']
                        if age <= 2000:
                            sx = world_to_screen_x(int(ex['wx']), player_world_x) - (ex['size'] // 2)
                            sy = world_to_screen_y(int(ex['wy'])) - (ex['size'] // 2)
                            if ex_blink_phase:
                                display.fill_rect(int(sx), int(sy), ex['size'], ex['size'], 1)
                    display.show()
                    _ = buttons.get_event()
                    time.sleep_ms(30)
                total_s = int((explosion_end_ms - start_ms) / 1000.0)
                display.clear()
                display.text("CRASHED", 28, 12)
                display.text("T:%03d s" % (total_s), 40, 28)
                display.text("L and R for res", 4, 46)
                display.show()
                while True:
                    ev_local = None
                    if pin_sh_l.value() == 0:
                        ev_local = 'RESTART'
                    else:
                        ev_local = buttons.get_event()
                    if ev_local == 'RESTART' or (ev_local == 'SHOULDER_L' and ev_local == 'SHOULDER_R'):
                        skip_splash = True
                        break
                    if ev_local == 'CONFIRM':
                        return
                    time.sleep_ms(60)
                break

            # ---------- RENDER ----------
            display.clear()

            blink_phase = ((now // 75) & 1)
            for m in list(missiles):
                sx = world_to_screen_x(int(m['world_x']), player_world_x)
                sy = world_to_screen_y(int(m['world_y']))
                w_px = int(m['pw']); h_px = int(m['ph'])
                if sy < -32 or sy > H + 32 or sx < -64 or sx > W + 64: continue
                if m['type'].startswith('boss_'):
                    display.fill_rect(int(sx), int(sy), w_px, h_px, 1)
                elif m['blink']:
                    if blink_phase: display.fill_rect(int(sx), int(sy), w_px, h_px, 1)
                else:
                    display.fill_rect(int(sx), int(sy), w_px, h_px, 1)

            # passerby draw as downward triangle (long triangle)
            for p in list(passerby):
                sx = world_to_screen_x(int(p['world_x']), player_world_x)
                sy = world_to_screen_y(int(p['world_y']))
                if -20 <= sy <= H + 20:
                    try:
                        # top middle
                        display.fill_rect(int(sx) + 1, int(sy) + 0, 1, 1, 1)
                        # middle row
                        display.fill_rect(int(sx) + 0, int(sy) + 1, 1, 1, 1)
                        display.fill_rect(int(sx) + 1, int(sy) + 1, 1, 1, 1)
                        display.fill_rect(int(sx) + 2, int(sy) + 1, 1, 1, 1)
                        # bottom middle
                        display.fill_rect(int(sx) + 1, int(sy) + 2, 1, 1, 1)
                    except TypeError:
                        display.fill_rect(int(sx), int(sy), 1, 1)
                        display.fill_rect(int(sx)-1, int(sy)+1, 3, 1)
                        display.fill_rect(int(sx)-2, int(sy)+2, 5, 1)

            # powerups
            for pu in list(powerups):
                sx = world_to_screen_x(int(pu['world_x']), player_world_x)
                sy = world_to_screen_y(int(pu['world_y']))
                if -16 <= sy <= H + 16:
                    display.rect(int(sx), int(sy), 4, 4, 1)

            # explosions
            ex_blink_phase = ((now // 300) & 1)
            new_explosions = []
            for ex in list(explosions):
                age = now - ex['born']
                if age <= 2000:
                    sx = world_to_screen_x(int(ex['wx']), player_world_x) - (ex['size'] // 2)
                    sy = world_to_screen_y(int(ex['wy'])) - (ex['size'] // 2)
                    if ex_blink_phase:
                        display.fill_rect(int(sx), int(sy), ex['size'], ex['size'], 1)
                    new_explosions.append(ex)
            explosions[:] = new_explosions

            # bullets
            for b in list(bullets):
                sx = world_to_screen_x(int(b['world_x']), player_world_x)
                sy = world_to_screen_y(int(b['world_y']))
                if -40 <= sy <= H + 40:
                    display.fill_rect(int(sx), int(sy), b['pw'], b['ph'], 1)

            # boss
            if boss_active and boss:
                bx = world_to_screen_x(int(boss['world_x']), player_world_x)
                by = world_to_screen_y(int(boss['world_y']))
                display.fill_rect(int(bx)-9, int(by)-6, 18, 12, 1)
                hpboxes = max(0, min(8, boss['hp']))
                for i in range(hpboxes):
                    display.fill_rect(int(bx) - 8 + i*2, int(by) - 10, 2, 2, 1)

            # player
            if not exploding:
                invuln = (now < invuln_until)
                draw_plane(display, angle, invuln)

            # HUD: hide timer when boss is active
            try:
                display.fill_rect(0, 0, 56, 8, 0)
            except TypeError:
                display.fill_rect(0, 0, 56, 8)
            if not boss_active:
                elapsed_display = int(elapsed_s)
                display.text("T:%03d" % (elapsed_display), 0, 0)
            if now < invuln_until:
                display.text("I", 56, 0)

            draw_powerup_icon(display, stored_powerup)

            display.show()

            # CONFIRM usage
            ev = buttons.get_event()
            if ev == 'CONFIRM' and not exploding:
                if now < shoot_until:
                    bullets.append({
                        'world_x': int(player_world_x), 'world_y': fp_from_float(-2.0), 'pw': BULLET_SIZE[0], 'ph': BULLET_SIZE[1], 'vy': BULLET_SPEED
                    })
                else:
                    if stored_powerup is not None:
                        if stored_powerup == 'shoot':
                            shoot_until = now + _randint(5000, 10000)
                        elif stored_powerup == 'maneuver':
                            maneuver_until = now + _randint(5000, 10000)
                        elif stored_powerup == 'invuln':
                            invuln_until = now + _randint(3000, 8000)
                        stored_powerup = None

            time.sleep_ms(28)

        # outer session continues; if skip_splash True next session starts immediately




