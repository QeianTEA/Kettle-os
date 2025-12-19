# games/heatseekers/heatseekers.py
# HeatSeekers - Pico (128x64)
# Restored explosions with collisions, cinematic death pause, improved performance.

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
    ('standard',   2, 2, 3, 0.062, False, 1.0),
    ('blinky_fast',1, 1, 4, 0.032, True,  0.6),
    ('man',        1, 1, 2.5, 0.100, False, 0.6),
    ('slowblink',  2, 2, 2, 0.055, True,  0.1),
]

PASSERBY_CONFIG = {
    'spawn_ms_min': 4000,
    'spawn_ms_max': 9000,
    'speed': 3.5,
    'size': (8,3),
    'last_spawn_ms': 0
}

BOSS_CONFIG = {
    'appear_after_s': 100.0,
    'start_world_y': -220.0,
    'follow_speed': 0.5,
    'dodge_dist': 16.0,
    'hp': 12,
    'rocket_speed': 1.5,
    'rocket_size': (3,3),
    'pattern_delay_ms': 1200,
    'last_pattern_ms': 0,
}

BULLET_SPEED = 5
BULLET_SIZE = (2,2)
bullets = []

missiles = []
powerups = []
# explosions stored in fixed-point (integers)
# explosion: {'wx':int_fp,'wy':int_fp,'vy':int_fp,'born':ms,'size':int,'ttl_ms':int}
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

# small sine table for boss bobbing (values in pixels)
_SIN_TABLE = [0,1,2,3,4,3,2,1,0,-1,-2,-3,-4,-3,-2,-1]
_SIN_LEN = len(_SIN_TABLE)
_bob_idx = 0

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

# ---------- explosions ----------
def create_explosion_at_world(wx_fp_or_f, wy_fp_or_f, now_ts, size=5, vy=None, ttl_ms=1200):
    """
    Creates an explosion in fixed-point coordinates.
    wx_fp_or_f, wy_fp_or_f can be FP ints or floats (world pixels).
    size in pixels (display pixels). ttl_ms explosion lifetime.
    """
    # convert to fixed point ints
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
    explosions.append({'wx': int(wx_fp), 'wy': int(wy_fp), 'vy': int(vy_fp),
                       'born': now_ts, 'size': int(size), 'ttl_ms': int(ttl_ms)})

    # immediate destruction check (remove missiles that overlap on spawn)
    ex_left_px = PX + ((wx_fp - player_world_x) // FP) - (size // 2)
    ex_top_px  = PY + ((wy_fp -  player_world_x) // FP)  # note: WY conversion uses world_to_screen_y normally
    # correct wy pixel using proper conversion:
    ex_top_px = PY + ((wy_fp) // FP) - (size // 2)
    ex_w = size; ex_h = size
    # iterate backward to remove in place
    for i in range(len(missiles)-1, -1, -1):
        m = missiles[i]
        mx_px = PX + ((m['world_x'] - player_world_x)//FP)
        my_px = PY + (m['world_y']//FP)
        if rects_overlap(ex_left_px, ex_top_px, ex_w, ex_h, mx_px, my_px, m['pw'], m['ph']):
            missiles.pop(i)

# ---------- spawners ----------
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
    # spawn farther away above the player so entities approach from a distance
    wx_fp = fp_from_float(player_world_x / FP + random.uniform(-W * 0.6, W * 0.6))
    wy_fp = fp_from_float(-random.uniform(120.0, 300.0))   # increased distance
    vx_fp = fp_from_float(random.uniform(-0.6, 0.6))
    vy_fp = fp_from_float(speed)
    missiles.append({
        'type': name, 'world_x': int(wx_fp), 'world_y': int(wy_fp),
        'vx': int(vx_fp), 'vy': int(vy_fp),
        'pw': pw, 'ph': ph, 'maneuver': maneuver, 'blink': blink,
        'born_ms': now_ms(), 'owner': 'missile'
    })

def spawn_powerup():
    ptype = random.choice(['shoot', 'maneuver', 'invuln'])
    wx_fp = fp_from_float(player_world_x / FP + random.uniform(-W * 0.5, W * 0.5))
    wy_fp = fp_from_float(-random.uniform(120.0, 260.0))   # spawn farther up
    powerups.append({'world_x': int(wx_fp), 'world_y': int(wy_fp), 'type': ptype, 'born_ms': now_ms()})

def spawn_passerby():
    wx_fp = fp_from_float(player_world_x / FP + random.uniform(-W * 0.6, W * 0.6))
    wy_fp = fp_from_float(-random.uniform(260.0, 160.0))   # farther up
    vx_fp = fp_from_float(random.uniform(-0.8, 0.8))
    vy_fp = fp_from_float(PASSERBY_CONFIG['speed'])
    pw, ph = PASSERBY_CONFIG['size']
    passerby.append({
        'world_x': int(wx_fp), 'world_y': int(wy_fp),
        'vx': int(vx_fp), 'vy': int(vy_fp), 'pw': pw, 'ph': ph,
        'born_ms': now_ms(), 'fired': False
    })
    PASSERBY_CONFIG['last_spawn_ms'] = now_ms()

def spawn_boss():
    global boss, boss_active, shoot_until, _bob_idx
    boss = {
        'world_x': int(fp_from_float(player_world_x / FP)),
        'world_y': int(fp_from_float(BOSS_CONFIG['start_world_y'])),
        'vx': 0, 'vy': 0,
        'hp': BOSS_CONFIG['hp'],
        'born_ms': now_ms(), 'last_dodge_ms': 0, 'bob_idx': 0
    }
    boss_active = True
    shoot_until = now_ms() + 10000
    BOSS_CONFIG['last_pattern_ms'] = now_ms()
    _bob_idx = 0

def spawn_boss_rocket(bx_fp, by_fp, target_x_fp):
    dx_fp = target_x_fp - bx_fp
    vx_fp = int((dx_fp * int(BOSS_CONFIG['rocket_speed'] * FP)) / (8 * FP)) if dx_fp != 0 else 0
    vy_fp = int(fp_from_float(BOSS_CONFIG['rocket_speed']))
    missiles.append({
        'type': 'boss_rocket', 'world_x': int(bx_fp), 'world_y': int(by_fp),
        'vx': vx_fp, 'vy': vy_fp,
        'pw': BOSS_CONFIG['rocket_size'][0], 'ph': BOSS_CONFIG['rocket_size'][1],
        'maneuver': 0.0, 'blink': False, 'born_ms': now_ms(), 'owner': 'boss'
    })

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

# Crash handler (requires BOTH shoulders pressed together to restart)
def _player_crash(display, buttons, pin_sh_l, pin_sh_r, start_ts):
    total_s = int((now_ms() - start_ts) / 1000.0)
    display.clear()
    display.text("CRASHED", 28, 12)
    display.text("T:%03d s" % (total_s), 40, 28)
    display.text("Press BOTH shoulders to restart", 2, 46)
    display.show()
    while True:
        if pin_sh_l.value() == 0 and pin_sh_r.value() == 0:
            return 'restart'
        ev = buttons.get_event()
        if ev == 'SHOULDER_L':
            t0 = now_ms()
            while now_ms() - t0 < 300:
                if pin_sh_r.value() == 0:
                    return 'restart'
                time.sleep_ms(20)
        if ev == 'SHOULDER_R':
            t0 = now_ms()
            while now_ms() - t0 < 300:
                if pin_sh_l.value() == 0:
                    return 'restart'
                time.sleep_ms(20)
        if ev == 'CONFIRM':
            return 'exit'
        time.sleep_ms(60)

# play_session runs a single playthrough; returns 'restart' or 'exit'
def play_session(display, buttons):
    global player_world_x, player_lat_vel, last_spawn_ms, start_ms, last_powerup_ms, next_powerup_ms, invuln_until
    global missiles, powerups, explosions, passerby, boss, boss_active, bullets, _bob_idx
    global stored_powerup, shoot_until, maneuver_until

    pin_left = Pin(PIN_LEFT, Pin.IN, Pin.PULL_UP)
    pin_right = Pin(PIN_RIGHT, Pin.IN, Pin.PULL_UP)
    pin_sh_l = Pin(PIN_SH_L, Pin.IN, Pin.PULL_UP)
    pin_sh_r = Pin(PIN_SH_R, Pin.IN, Pin.PULL_UP)

    # reset state
    missiles.clear(); powerups.clear(); explosions.clear(); passerby.clear(); bullets.clear()
    player_world_x = fp_from_float(0.0)
    player_lat_vel = 0
    last_spawn_ms = now_ms()
    last_powerup_ms = now_ms()
    next_powerup_ms = last_powerup_ms + _randint(15000, 30000)
    invuln_until = 0
    start_ms = now_ms()

    elapsed_s = 0.0
    angle = 0.0
    stored_powerup = None
    shoot_until = 0
    maneuver_until = 0
    boss = None
    boss_active = False
    PASSERBY_CONFIG['last_spawn_ms'] = now_ms()

    exploding = False
    explosion_end_ms = 0

    # MAIN session loop
    while True:
        now = now_ms()
        elapsed_s = (now - start_ms) / 1000.0

        # local aliases for speed
        mlist = missiles
        plist = passerby
        blist = bullets
        pulist = powerups
        elist = explosions
        pw = FP
        px = PX
        py = PY
        player_x = player_world_x  # fp int

        # spawn boss?
        if (not boss_active) and elapsed_s >= BOSS_CONFIG['appear_after_s']:
            spawn_boss()

        # read inputs once
        lraw = pin_left.value()
        rraw = pin_right.value()
        lsh = pin_sh_l.value()
        rsh = pin_sh_r.value()
        steering_left = (lraw == 0) or (lsh == 0)
        steering_right = (rraw == 0) or (rsh == 0)

        # If exploding: freeze missiles/passerby/bullets movement but continue explosions updates
        if exploding:
            # advance explosions and remove missiles overlapping them (cinematic clearance)
            for ex_i in range(len(elist)-1, -1, -1):
                ex = elist[ex_i]
                # advance wy (wy stored as fixed-point int)
                ex['wy'] += ex['vy']
                # compute explosion pixel box
                ex_left_px = px + ((ex['wx'] - player_x) // pw) - (ex['size'] // 2)
                ex_top_px = py + (ex['wy'] // pw) - (ex['size'] // 2)
                ex_w = ex['size']; ex_h = ex['size']
                # remove missiles overlapping this explosion
                for mi in range(len(mlist)-1, -1, -1):
                    m = mlist[mi]
                    mx_px = px + ((m['world_x'] - player_x) // pw)
                    my_px = py + (m['world_y'] // pw)
                    if rects_overlap(ex_left_px, ex_top_px, ex_w, ex_h, mx_px, my_px, m['pw'], m['ph']):
                        mlist.pop(mi)
                # expire explosions
                if now - ex['born'] > ex['ttl_ms']:
                    elist.pop(ex_i)

            # cinematic ended?
            if now >= explosion_end_ms:
                res = _player_crash(display, buttons, pin_sh_l, pin_sh_r, start_ms)
                return res

            # render later; skip further simulation
        else:
            # Normal simulation updates (not exploding)
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

            # friction & clamp
            player_lat_vel = int(player_lat_vel * LAT_FRICTION_FP)
            player_lat_vel = clamp(player_lat_vel, -lat_max_fp, lat_max_fp)
            player_world_x += player_lat_vel
            max_world_fp = fp_from_float(W * 2.0)
            player_world_x = clamp(player_world_x, -max_world_fp, max_world_fp)

            # spawn missiles/powerups/passerby
            si = spawn_interval_ms(elapsed_s)
            if time.ticks_diff(now, last_spawn_ms) >= si:
                spawn_missile(elapsed_s)
                last_spawn_ms = now

            if now >= next_powerup_ms:
                spawn_powerup()
                last_powerup_ms = now
                next_powerup_ms = now + _randint(15000, 30000)

            if time.ticks_diff(now, PASSERBY_CONFIG['last_spawn_ms']) > _randint(PASSERBY_CONFIG['spawn_ms_min'], PASSERBY_CONFIG['spawn_ms_max']):
                spawn_passerby()

            # update missiles (in-place, backwards removal)
            for i in range(len(mlist)-1, -1, -1):
                m = mlist[i]
                # integer pixel math
                vy_px = m['vy'] // pw
                world_y_px = m['world_y'] // pw
                if vy_px == 0:
                    t_frames = 10
                else:
                    t_frames = max(1, int(-world_y_px / vy_px))
                predicted_target_x_fp = player_world_x + int(player_lat_vel * t_frames / 4)
                desired_vx_fp = int((predicted_target_x_fp - m['world_x']) / max(1, t_frames))
                max_delta_fp = int(m['maneuver'] * 6.0 * pw)
                dv = clamp(desired_vx_fp - m['vx'], -max_delta_fp, max_delta_fp)
                m['vx'] += dv
                m['world_x'] += m['vx']
                m['world_y'] += m['vy']
                sy = PY + (m['world_y'] // pw)
                if sy > H + 32 or m['world_y'] > fp_from_float(5000.0):
                    mlist.pop(i)

            # update passerby & let them drop missiles once
            for pi in range(len(plist)-1, -1, -1):
                p = plist[pi]
                p['world_x'] += p['vx']
                p['world_y'] += p['vy']
                p_sy = PY + (p['world_y'] // pw)
                if (not p['fired']) and p_sy >= PY - 35:
                    mx_fp = int(p['world_x'])
                    my_fp = int(p['world_y']) + fp_from_float(4.0)
                    target_x_fp = int(player_world_x)
                    mlist.append({
                        'type': 'p_missile', 'world_x': mx_fp, 'world_y': my_fp,
                        'vx': int((target_x_fp - mx_fp) * 0.02), 'vy': fp_from_float(3.8),
                        'pw': 2, 'ph': 2, 'maneuver': 0.02, 'blink': False,
                        'born_ms': now, 'owner': 'passerby'
                    })
                    p['fired'] = True
                if abs(p['world_x'] - player_world_x) > fp_from_float(W * 2.0):
                    plist.pop(pi)

            # update boss (use tiny sin table for bobbing)
            if boss_active and boss:
                dx_fp = player_world_x - boss['world_x']
                boss['vx'] = int(dx_fp * 0.02 * BOSS_CONFIG['follow_speed'])
                boss['world_x'] += boss['vx']
                boss['bob_idx'] = (boss.get('bob_idx', 0) + 1) % _SIN_LEN
                bob_px = _SIN_TABLE[boss['bob_idx']]
                boss['world_y'] = int(fp_from_float(BOSS_CONFIG['start_world_y']) + fp_from_float(bob_px))
                # dodge bullets slightly
                for b in blist:
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
                            mlist.append({
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
                            mlist.append({
                                'type': 'boss_bullet', 'world_x': int(boss['world_x']) + fp_from_float(sx), 'world_y': int(boss['world_y'] + fp_from_float(6.0)),
                                'vx': 0, 'vy': fp_from_float(BOSS_CONFIG['rocket_speed'] * 1.2),
                                'pw': 2, 'ph': 2, 'maneuver': 0.0, 'blink': False, 'born_ms': now, 'owner': 'boss'
                            })

            # bullets update (in-place)
            for bi in range(len(blist)-1, -1, -1):
                b = blist[bi]
                b['world_y'] -= fp_from_float(b['vy'])
                if PY + (b['world_y'] // pw) < -48:
                    blist.pop(bi)

            # bullets collisions (missiles/passerby/boss), in-place removals
            for bi in range(len(blist)-1, -1, -1):
                b = blist[bi]
                bx_px = PX + ((b['world_x'] - player_world_x)//FP)
                by_px = PY + (b['world_y']//FP)
                removed_b = False
                # missile hit (reverse iterate for cache locality)
                for mi in range(len(mlist)-1, -1, -1):
                    m = mlist[mi]
                    mx_px = PX + ((m['world_x'] - player_world_x)//FP)
                    my_px = PY + (m['world_y']//FP)
                    # quick y-prune: if vertical distance > 8 px skip
                    if abs(my_px - by_px) > 8:
                        continue
                    if rects_overlap(bx_px, by_px, b['pw'], b['ph'], mx_px, my_px, m['pw'], m['ph']):
                        mlist.pop(mi)
                        # remove bullet safely if still present
                        if bi < len(blist):
                            blist.pop(bi)
                        removed_b = True
                        create_explosion_at_world(int(m['world_x']), int(m['world_y']), now, size=5, vy=fp_from_float(1.2))
                        break
                if removed_b: continue

                # passerby hit
                for pi in range(len(plist)-1, -1, -1):
                    p = plist[pi]
                    px_px = PX + ((p['world_x'] - player_world_x)//FP)
                    py_px = PY + (p['world_y']//FP)
                    if abs(py_px - by_px) > 8:
                        continue
                    if rects_overlap(bx_px, by_px, b['pw'], b['ph'], px_px, py_px, p['pw'], p['ph']):
                        plist.pop(pi)
                        if bi < len(blist): blist.pop(bi)
                        removed_b = True
                        create_explosion_at_world(int(p['world_x']), int(p['world_y']), now, size=6, vy=fp_from_float(1.5))
                        break
                if removed_b: continue

                # boss hit
                if boss_active and boss:
                    bx_center = PX + ((boss['world_x'] - player_world_x)//FP)
                    by_center = PY + (boss['world_y']//FP)
                    if rects_overlap(bx_px, by_px, b['pw'], b['ph'], bx_center-9, by_center-6, 18, 12):
                        boss['hp'] -= 1
                        if bi < len(blist): blist.pop(bi)
                        create_explosion_at_world(int(boss['world_x']), int(boss['world_y']), now, size=6, vy=fp_from_float(1.0))
                        if boss['hp'] <= 0:
                            create_explosion_at_world(int(boss['world_x']), int(boss['world_y']), now, size=18, vy=fp_from_float(1.0), ttl_ms=1600)
                            mlist[:] = []; plist[:] = []
                            boss_active = False; boss = None
                            display.clear(); display.text("VICTORY", 36, 20); display.show(); time.sleep(2.0); return 'exit'

            # missile vs missile collision - optimized with y-prune
            i = len(mlist) - 1
            while i >= 0:
                a = mlist[i]
                ax_px = PX + ((a['world_x'] - player_world_x)//FP)
                ay_px = PY + (a['world_y']//FP)
                removed_a = False
                j = i - 1
                while j >= 0:
                    b2 = mlist[j]
                    bx_px = PX + ((b2['world_x'] - player_world_x)//FP)
                    by_px = PY + (b2['world_y']//FP)
                    # y prune — missiles far apart vertically won't collide
                    if abs(ay_px - by_px) <= 6:
                        if rects_overlap(ax_px, ay_px, a['pw'], a['ph'], bx_px, by_px, b2['pw'], b2['ph']):
                            cx_px = (ax_px + bx_px) // 2
                            cy_px = (ay_px + by_px) // 2
                            create_explosion_at_world(fp_from_float(cx_px), fp_from_float(cy_px), now, size=5, vy=fp_from_float(1.0))
                            # remove higher index first
                            mlist.pop(i)
                            mlist.pop(j)
                            removed_a = True
                            break
                    j -= 1
                i -= 1
                # continue; indices have changed when removals happened

            # update powerups in-place
            for pi in range(len(pulist)-1, -1, -1):
                pu = pulist[pi]
                pu['world_y'] += fp_from_float(1.2)
                sx = PX + ((pu['world_x'] - player_world_x)//FP)
                sy = PY + (pu['world_y']//FP)
                plx, ply, pwid, pht = plane_rect()
                if rects_overlap(sx, sy, 4, 4, plx, ply, pwid, pht):
                    stored_powerup = pu['type']
                    pulist.pop(pi)
                    continue
                if sy > H + 32:
                    pulist.pop(pi)

            # missile vs player collisions
            invuln = (now < invuln_until)
            if not invuln:
                plx, ply, pwid, pht = plane_rect()
                hit_index = None
                for mi in range(len(mlist)-1, -1, -1):
                    m = mlist[mi]
                    mx_px = PX + ((m['world_x'] - player_world_x)//FP)
                    my_px = PY + (m['world_y']//FP)
                    if rects_overlap(mx_px, my_px, m['pw'], m['ph'], plx, ply, pwid, pht):
                        hit_index = mi
                        break
                if hit_index is not None:
                    # explosion centered at player and larger
                    # explosion at actual collision position
                    create_explosion_at_world(
                        int(m['world_x']),
                        int(m['world_y']),
                        now,
                        size=6,
                        vy=0,            # <- IMPORTANT: death explosion does NOT move
                        ttl_ms=1000
                    )

                    # remove missile that hit if still present
                    if hit_index < len(mlist):
                        mlist.pop(hit_index)
                    exploding = True
                    explosion_end_ms = now + 1000

            # advance explosions (moving streaks and clearing missiles while not exploding)
            for ex_i in range(len(elist)-1, -1, -1):
                ex = elist[ex_i]
                ex['wy'] += ex['vy']
                ex_left_px = PX + ((ex['wx'] - player_world_x)//FP) - (ex['size'] // 2)
                ex_top_px  = PY + (ex['wy']//FP) - (ex['size'] // 2)
                ex_w = ex['size']; ex_h = ex['size']
                for mi in range(len(mlist)-1, -1, -1):
                    m = mlist[mi]
                    mx_px = PX + ((m['world_x'] - player_world_x)//FP)
                    my_px = PY + (m['world_y']//FP)
                    if rects_overlap(ex_left_px, ex_top_px, ex_w, ex_h, mx_px, my_px, m['pw'], m['ph']):
                        mlist.pop(mi)
                if now - ex['born'] > ex['ttl_ms']:
                    elist.pop(ex_i)

        # ---------- RENDER ----------
        display.clear()

        blink_phase = ((now // 75) & 1)
        # draw missiles
        for m in mlist:
            sx = PX + ((m['world_x'] - player_world_x)//FP)
            sy = PY + (m['world_y']//FP)
            w_px = m['pw']; h_px = m['ph']
            if sy < -32 or sy > H + 32 or sx < -64 or sx > W + 64:
                continue
            if m['type'].startswith('boss_'):
                display.fill_rect(int(sx), int(sy), w_px, h_px, 1)
            elif m['blink']:
                if blink_phase:
                    display.fill_rect(int(sx), int(sy), w_px, h_px, 1)
            else:
                display.fill_rect(int(sx), int(sy), w_px, h_px, 1)

        # passerby draw
        for p in plist:
            sx = PX + ((p['world_x'] - player_world_x)//FP)
            sy = PY + (p['world_y']//FP)
            if -32 <= sy <= H + 32:
                try:
                    display.fill_rect(int(sx)-2, int(sy),   5, 1, 1)
                    display.fill_rect(int(sx)-1, int(sy)+1, 3, 1, 1)
                    display.fill_rect(int(sx),   int(sy)+2, 1, 1, 1)
                except TypeError:
                    display.fill_rect(int(sx), int(sy), 1, 1)
                    display.fill_rect(int(sx)-1, int(sy)+1, 3, 1)
                    display.fill_rect(int(sx)-2, int(sy)+2, 5, 1)

        # powerups
        for pu in pulist:
            sx = PX + ((pu['world_x'] - player_world_x)//FP)
            sy = PY + (pu['world_y']//FP)
            if -16 <= sy <= H + 16:
                display.rect(int(sx), int(sy), 4, 4, 1)

        # explosions (draw as square centered on world coords)
        ex_blink_phase = ((now // 200) & 1)
        for ex in elist:
            sx = PX + ((ex['wx'] - player_world_x)//FP) - (ex['size'] // 2)
            sy = PY + (ex['wy']//FP) - (ex['size'] // 2)
            if ex_blink_phase:
                display.fill_rect(int(sx), int(sy), ex['size'], ex['size'], 1)

        # bullets
        for b in blist:
            sx = PX + ((b['world_x'] - player_world_x)//FP)
            sy = PY + (b['world_y']//FP)
            if -40 <= sy <= H + 40:
                display.fill_rect(int(sx), int(sy), b['pw'], b['ph'], 1)

        # boss
        if boss_active and boss:
            bx = PX + ((boss['world_x'] - player_world_x)//FP)
            by = PY + (boss['world_y']//FP)
            display.fill_rect(int(bx)-9, int(by)-6, 18, 12, 1)
            hpboxes = max(0, min(8, boss['hp']))
            for i in range(hpboxes):
                display.fill_rect(int(bx) - 8 + i*2, int(by) - 10, 2, 2, 1)

        # player
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
        if ev == 'CONFIRM':
            if exploding:
                pass  # block powerup usage entirely
            if now < shoot_until:
                blist.append({
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

        # small throttle for CPU & consistent frame pacing
        time.sleep_ms(28)

# run() shows splash once, then enters sessions; restart starts immediately (no splash)
def run(display, buttons):
    # show splash once
    _show_splash_image_or_text(display, buttons)

    # loop over play sessions; restart starts a fresh session immediately (no splash)
    while True:
        res = play_session(display, buttons)
        if res == 'restart':
            continue
        else:
            return

