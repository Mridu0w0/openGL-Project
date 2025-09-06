# --------------------------------------------------
# 1) 3D board (10x10) with perspective camera (gluPerspective).
# 2) Two player tokens (spheres) with turn-based logic.
# 3) Dice roll (SPACE) — random 1..6.
# 4) Smooth animated movement square-by-square using transforms.
# 5) Snakes (head->tail) and ladders (base->top) rules + animations.
# 6) Enemy-free, logic-only “teleport” via animated slide/climb.
# 7) Win condition (exact 100 not required here; stops at 100).
# 8) Camera controls: orbit, tilt, zoom (gluLookAt).
# 9) Restart (R) resets positions/turn/animations.
# 10) Optional top-down view toggle (Tab).
# Adds:
#  - D: toggle double dice (1 or 2 dice)
#  - T: toggle board theme
#  - Bonus tiles (extra roll, forward 3, skip turn)
#  - Snake slide & ladder climb animations (curved / rung-based)
#  - Winner celebration (spin + bounce)
# --------------------------------------------------

from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
import sys, random, time, math


# -------- Window / Scene ----------
W_WIDTH, W_HEIGHT = 1200, 1000
BOARD_N = 10              # 10x10
SQ = 1.0                  # square size (world units)
BOARD_SIZE = BOARD_N * SQ
BOARD_MIN = -BOARD_SIZE/2
BOARD_MAX =  BOARD_SIZE/2
BOARD_Y  = 0.0

# -------- Camera ---------------
cam_angle = 45.0          # orbit around Y (degrees)
cam_tilt  = 30.0          # tilt (degrees)
cam_dist  = 16.0          # radius
top_down  = False

# -------- Game State ----------
players = [
    {"pos": 1, "color": (0.9, 0.2, 0.2), "skip": False},  # P1
    {"pos": 1, "color": (0.2, 0.5, 0.9), "skip": False},  # P2
]
current_player = 0
game_over = False
winner = None
two_players = True


# Animation state
animating = False
anim_mode = None      # None, 'steps', 'snake', 'ladder'
anim_path = []        # for 'steps': list of (from,to); for snake/ladder: list of world points
anim_t = 0.0          # 0..1 within current animation segment
anim_speed = 2.5      # base speed (units per second for squares); adjusted per mode

# Dice
last_rolls = []
double_dice = False   # feature (D) toggle

# Bonus tiles (extra features)
# Format: cell: ("type", value)
# types: "extra_roll", "skip"
BONUS_TILES = {
    5: ("extra_roll", None),
    12: ("skip", 1),
    27: ("extra_roll", None),
    44: ("skip", 1),
    58: ("skip", 1),
    82: ("extra_roll", None)
}
# Board themes: list of (light_color, dark_color, border_color)
THEMES = [
    ((0.95,0.90,0.80),(0.75,0.70,0.60),(0.2,0.2,0.2)),  # classic
    ((0.98,0.94,0.86),(0.85,0.72,0.55),(0.35,0.22,0.05)),  # desert
    ((0.12,0.12,0.18),(0.18,0.18,0.26),(0.05,0.05,0.12)),  # night
]
theme_idx = 0

# Time
last_time = time.time()

# GLU quadric for fallback cylinder
quadric = None
have_glut_cylinder = hasattr(glutSolidCylinder, "__call__")

# ---------- Snakes & Ladders Layout ----------
LADDERS = {
    2: 38,
    7: 14,
    8: 31,
    15: 26,
    21: 42,
    28: 84,
    36: 44,
    51: 67,
    71: 91,
    78: 98
}
SNAKES = {
    16: 6,
    46: 25,
    49: 11,
    62: 19,
    64: 60,
    74: 53,
    89: 68,
    92: 88,
    95: 75,
    99: 80
}

# ---------- Utilities ----------
def clamp(v, a, b): 
    return max(a, min(b, v))

def cell_to_ij(n):
    n = clamp(n, 1, BOARD_N*BOARD_N)
    n0 = n - 1
    i = n0 // BOARD_N
    j = n0 % BOARD_N
    if i % 2 == 1:
        j = BOARD_N - 1 - j
    return i, j

def ij_to_world(i, j):
    x = BOARD_MIN + (j + 0.5) * SQ
    z = BOARD_MIN + (i + 0.5) * SQ
    return x, z

def cell_to_world(n):
    i, j = cell_to_ij(n)
    return ij_to_world(i, j)

def make_step_path(start_cell, end_cell):
    path = []
    c = start_cell
    step = 1 if end_cell >= start_cell else -1
    while c != end_cell:
        path.append((c, c + step))
        c += step
    return path

def schedule_move(player_index, roll):
    global animating, anim_path, anim_t, last_roll, anim_mode
    if game_over: return
    last_roll = roll
    p = players[player_index]
    start = p["pos"]
    target = start + roll
    if target > 100:
        target = 100
    # schedule step-by-step movement (we animate square-by-square)
    anim_path = make_step_path(start, target)
    animating = len(anim_path) > 0
    anim_t = 0.0
    anim_mode = 'steps'

# ---------- Drawing ----------
def draw_square():
    glBegin(GL_QUADS)
    glVertex3f(-0.5, 0.0, -0.5)
    glVertex3f( 0.5, 0.0, -0.5)
    glVertex3f( 0.5, 0.0,  0.5)
    glVertex3f(-0.5, 0.0,  0.5)
    glEnd()

def draw_cuboid(wx, wy, wz):
    glPushMatrix()
    glScalef(wx, wy, wz)
    glutSolidCube(1.0)
    glPopMatrix()

def draw_cylinder(radius, height, slices=20, stacks=4):
    glPushMatrix()
    glRotatef(-90, 1,0,0)
    if have_glut_cylinder:
        glutSolidCylinder(radius, height, slices, stacks)
    else:
        gluCylinder(quadric, radius, radius, height, slices, stacks)
        gluDisk(quadric, 0.0, radius, slices, 1)
        glTranslatef(0,0,height)
        gluDisk(quadric, 0.0, radius, slices, 1)
    glPopMatrix()

def draw_board():
    global theme_idx
    light, dark, border = THEMES[theme_idx]
    glPushMatrix()
    glTranslatef(0, BOARD_Y, 0)
    for i in range(BOARD_N):
        for j in range(BOARD_N):
            x, z = ij_to_world(i, j)
            glPushMatrix()
            glTranslatef(x, 0.0, z)
            glScalef(SQ, 1.0, SQ)
            c = (i + j) % 2
            
            # if bonus tile, tint it
            cell_num = i*BOARD_N + (j if (i%2==0) else (BOARD_N-1-j)) + 1
            if cell_num in BONUS_TILES:
                # brighter highlight
                bc = (0.9, 0.9, 0.5)
                glColor3f(*bc)
            else:
                glColor3f(*(light if c==0 else dark))
            draw_square()
            cell_num = i*BOARD_N + (j if (i%2==0) else (BOARD_N-1-j)) + 1
            # Check if player is on this cell
            color = (0,0,0)
            for idx, p in enumerate(players):
                if p["pos"] == cell_num:
                    color = p["color"]
            # Draw number
            glColor3f(*color)
            glRasterPos3f(0, 0.01, 0)  # small offset above the square
            for ch in str(cell_num):
                glutBitmapCharacter(GLUT_BITMAP_HELVETICA_12, ord(ch))
            
            glPopMatrix()
    # Border walls
    wall_h = 0.2
    wall_t = 0.05
    glColor3f(*border)
    glPushMatrix(); glTranslatef(0, wall_h/2, BOARD_MAX); draw_cuboid(BOARD_SIZE+0.1, wall_h, wall_t); glPopMatrix()
    glPushMatrix(); glTranslatef(0, wall_h/2, BOARD_MIN); draw_cuboid(BOARD_SIZE+0.1, wall_h, wall_t); glPopMatrix()
    glPushMatrix(); glTranslatef(BOARD_MAX, wall_h/2, 0); draw_cuboid(wall_t, wall_h, BOARD_SIZE+0.1); glPopMatrix()
    glPushMatrix(); glTranslatef(BOARD_MIN, wall_h/2, 0); draw_cuboid(wall_t, wall_h, BOARD_SIZE+0.1); glPopMatrix()
    glPopMatrix()

def draw_token_at(world_x, world_z, color, scale=0.18, y_offset=0.25):
    glPushMatrix()
    glTranslatef(world_x, BOARD_Y + y_offset, world_z)
    glColor3f(*color)
    glutSolidSphere(scale, 24, 16)
    glColor3f(0.15,0.15,0.15)
    draw_cuboid(scale+0.08, 0.05, scale+0.08)
    glPopMatrix()

def draw_token(cell, color):
    x, z = cell_to_world(cell)
    draw_token_at(x, z, color)

def draw_snake_line(from_cell, to_cell, col=(0.2, 0.8, 0.2)):
    x1, z1 = cell_to_world(from_cell)
    x2, z2 = cell_to_world(to_cell)
    dx, dz = x2 - x1, z2 - z1
    segs = 14
    glColor3f(*col)
    for k in range(segs+1):
        t = k / float(segs)
        ox = -dz * 0.07 * math.sin(t*math.pi*2)
        oz =  dx * 0.07 * math.sin(t*math.pi*2)
        x = x1 + dx*t + ox
        z = z1 + dz*t + oz
        glPushMatrix()
        glTranslatef(x, BOARD_Y + 0.12 + 0.03*math.sin(t*math.pi*2), z)
        r = 0.10 + 0.03*math.sin(t*math.pi)
        glutSolidSphere(r, 16, 10)
        glPopMatrix()
    glPushMatrix()
    glTranslatef(x1, BOARD_Y + 0.25, z1)
    glColor3f(0.1,0.6,0.1)
    glutSolidSphere(0.22, 16, 12)
    glPopMatrix()


def draw_ladder(from_cell, to_cell, col=(0.7,0.5,0.2)):
    x1, z1 = cell_to_world(from_cell)
    x2, z2 = cell_to_world(to_cell)
    y = BOARD_Y + 0.05
    glColor3f(*col)
    def rail(px, pz, qx, qz, spacing):
        dx, dz = qx - px, qz - pz
        L = math.hypot(dx, dz) + 1e-6
        ux, uz = dx/L, dz/L
        pxn, pzn = -uz, ux
        rx1, rz1 = px + pxn*spacing, pz + pzn*spacing
        rx2, rz2 = qx + pxn*spacing, qz + pzn*spacing
        segs = 10
        for k in range(segs):
            t0 = k/segs; t1 = (k+1)/segs
            sx = rx1 + (rx2-rx1)*t0; sz = rz1 + (rz2-rz1)*t0
            ex = rx1 + (rx2-rx1)*t1; ez = rz1 + (rz2-rz1)*t1
            glPushMatrix()
            glTranslatef(sx, y, sz)
            ang = math.degrees(math.atan2(ez - sz, ex - sx))
            glRotatef(-ang, 0,1,0)
            draw_cylinder(0.04, math.hypot(ex - sx, ez - sz))
            glPopMatrix()
        rung_count = 6
        for r in range(rung_count+1):
            t = r / float(rung_count)
            cx = px + dx*t; cz = pz + dz*t
            glPushMatrix()
            glTranslatef(cx, y+0.03, cz)
            ang = math.degrees(math.atan2(dz, dx))
            glRotatef(-ang, 0,1,0)
            draw_cuboid(0.7, 0.05, 0.08)
            glPopMatrix()
    rail(x1, z1, x2, z2, spacing=0.12)
    rail(x1, z1, x2, z2, spacing=-0.12)

def draw_all_snakes_ladders():
    for head, tail in SNAKES.items():
        draw_snake_line(head, tail)
    for base, top in LADDERS.items():
        draw_ladder(base, top)


def draw_dice_preview():
    if not last_rolls:
        return

    # Dice position (middle right side of the board)
    dx0 = BOARD_MAX + 1.5
    dz  = (BOARD_MIN + BOARD_MAX) / 2.0
    dy  = 0.8
    size = 0.6
    spacing = 1.3  # space between dice

    for idx, val in enumerate(last_rolls):
        glPushMatrix()
        glTranslatef(dx0, dy, dz + idx * spacing)  # stack along Z axis

        # Draw cube (the dice body)
        glColor3f(0.95, 0.95, 0.95)
        draw_cuboid(size*2, size*2, size*2)

        # Draw pips on top face
        glColor3f(0.1, 0.1, 0.1)
        s = 0.3
        layouts = {
            1:[(0,0)],
            2:[(-s,-s),(s,s)],
            3:[(-s,-s),(0,0),(s,s)],
            4:[(-s,-s),(-s,s),(s,-s),(s,s)],
            5:[(-s,-s),(-s,s),(0,0),(s,-s),(s,s)],
            6:[(-s,-s),(-s,0),(-s,s),(s,-s),(s,0),(s,s)],
        }
        for px, pz in layouts[val]:
            glPushMatrix()
            glTranslatef(px, size + 0.01, pz)
            glutSolidSphere(0.1, 12, 10)
            glPopMatrix()

        glPopMatrix()

# ---------- Advanced Animation Helpers ----------
def make_snake_curve(from_cell, to_cell, segs=60):
    # returns list of (x,y,z) world points along a wavy curve from head->tail
    x1, z1 = cell_to_world(from_cell)
    x2, z2 = cell_to_world(to_cell)
    dx, dz = x2 - x1, z2 - z1
    pts = []
    for k in range(segs+1):
        t = k / float(segs)
        # base linear
        x = x1 + dx * t
        z = z1 + dz * t
        # curve offset orthogonal
        ox = -dz * 0.12 * math.sin(t * math.pi * 2)
        oz =  dx * 0.12 * math.sin(t * math.pi * 2)
        y = 0.12 + 0.08 * math.sin(t * math.pi)
        pts.append((x + ox, BOARD_Y + y, z + oz))
    return pts

def make_ladder_path(from_cell, to_cell, rung_count=6):
    # returns path points going up rung by rung along ladder center
    x1, z1 = cell_to_world(from_cell)
    x2, z2 = cell_to_world(to_cell)
    pts = []
    for r in range(rung_count+1):
        t = r / float(rung_count)
        x = x1 + (x2 - x1) * t
        z = z1 + (z2 - z1) * t
        y = BOARD_Y + 0.05 + 0.04 * r  # climb height per rung
        pts.append((x, y, z))
    return pts

# ---------- Game / Animation ----------
def apply_snake_or_ladder(cell):
    if cell in SNAKES: return SNAKES[cell], 'snake'
    if cell in LADDERS: return LADDERS[cell], 'ladder'
    return cell, None

def on_step_finished():
    global animating, anim_path, anim_t, anim_mode, current_player
    p = players[current_player]
    final_cell = p["pos"]
    # apply bonus tiles first? We'll apply snakes/ladders then bonus tiles
    new_cell, mode = apply_snake_or_ladder(final_cell)
    if mode == 'snake':
        # prepare snake curve animation from head(final_cell) to tail(new_cell)
        anim_mode = 'snake'
        anim_path = make_snake_curve(final_cell, new_cell, segs=80)
        animating = True
        anim_t = 0.0
    elif mode == 'ladder':
        anim_mode = 'ladder'
        anim_path = make_ladder_path(final_cell, new_cell, rung_count=6)
        animating = True
        anim_t = 0.0
    else:
        # check bonus tiles
        if final_cell in BONUS_TILES:
            btype, val = BONUS_TILES[final_cell]
            handle_bonus_tile(btype, val)
            # if extra_roll we leave turn unchanged (player will roll again)
            if btype == 'extra_roll':
                return
        end_turn_or_win()

      
def preview_dice():
    global last_rolls
    if double_dice:
        last_rolls = [random.randint(1,6), random.randint(1,6)]
    else:
        last_rolls = [random.randint(1,6)]

def handle_bonus_tile(btype, val):
    global last_roll, animating, anim_path, anim_t
    if btype == 'extra_roll':
        # immediately allow another roll (no movement scheduled)
        pass
    elif btype == 'forward':
        p = players[current_player]
        start = p["pos"]
        target = clamp(start + val, 1, 100)
        anim_path = make_step_path(start, target)
        animating = len(anim_path) > 0
        anim_mode = 'steps'
        anim_t = 0.0
    elif btype == 'skip':
        players[current_player]['skip'] = True


def end_turn_or_win():
    global current_player, game_over, winner, two_players
    p = players[current_player]
    if p["pos"] >= 100:
        p["pos"] = 100
        game_over = True
        winner = current_player
    else:
        if two_players:
            # normal turn switch
            current_player = (current_player + 1) % len(players)
            if players[current_player].get('skip', False):
                players[current_player]['skip'] = False
                current_player = (current_player + 1) % len(players)
        else:
            # single-player mode: always stay Player 1
            current_player = 0


def update_animation(dt):
    global anim_t, animating, anim_path, anim_mode, last_roll
    if not animating: return
    if anim_mode == 'steps':
        if not anim_path:
            animating = False
            on_step_finished()
            return
        frm, to = anim_path[0]
        anim_t += anim_speed * dt
        while anim_t >= 1.0 and anim_path:
            players[current_player]["pos"] = to
            anim_t -= 1.0
            anim_path.pop(0)
            if not anim_path:
                animating = False
                on_step_finished()
                return
    elif anim_mode == 'snake':
        # anim_path is list of world points; we move along them
        seg_len = 1.0 / max(1, len(anim_path)-1)
        anim_t += 1.4 * dt  # snake slower
        posf = anim_t
        idxf = posf / seg_len
        idx_int = int(idxf)
        if idx_int >= len(anim_path)-1:
            # finish: set player pos to tail cell
            # find tail cell from last world point -> map to nearest cell
            tail_world = anim_path[-1]
            # nearest cell number
            # naive: find cell whose world coords match tail approx
            # compute all cell centers and pick closest
            best = None; bestd = 1e9; bestcell = players[current_player]["pos"]
            for c in range(1, 101):
                wx, wz = cell_to_world(c)
                d = (wx - tail_world[0])**2 + (wz - tail_world[2])**2
                if d < bestd:
                    bestd = d; bestcell = c
            players[current_player]["pos"] = bestcell
            animating = False
            anim_mode = None
            on_step_finished()
            return
    elif anim_mode == 'ladder':
        # climb rung-by-rung
        seg_len = 1.0 / max(1, len(anim_path)-1)
        anim_t += 2.2 * dt  # ladder quicker
        posf = anim_t
        idxf = posf / seg_len
        idx_int = int(idxf)
        if idx_int >= len(anim_path)-1:
            # finish: set pos to top cell
            top_world = anim_path[-1]
            best = None; bestd = 1e9; bestcell = players[current_player]["pos"]
            for c in range(1, 101):
                wx, wz = cell_to_world(c)
                d = (wx - top_world[0])**2 + (wz - top_world[2])**2
                if d < bestd:
                    bestd = d; bestcell = c
            players[current_player]["pos"] = bestcell
            animating = False
            anim_mode = None
            on_step_finished()
            return


def display():
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    aspect = max(1e-6, W_WIDTH / float(W_HEIGHT))
    gluPerspective(60.0, aspect, 0.1, 200.0)

    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    cx, cy, cz = 0.0, 0.0, 0.0
    if top_down:
        eye = (0, 30, 0.001)
        at  = (0, 0, 0)
        up  = (0, 1, 0)
        gluLookAt(eye[0],eye[1],eye[2], at[0],at[1],at[2], up[0],up[1],up[2])
    else:
        ang = math.radians(cam_angle)
        tilt = math.radians(cam_tilt)
        ex = math.cos(ang) * math.cos(tilt) * cam_dist
        ez = math.sin(ang) * math.cos(tilt) * cam_dist
        ey = math.sin(tilt) * cam_dist
        gluLookAt(ex, ey, ez, cx, 0.0, cz, 0,1,0)

    draw_board()
    draw_all_snakes_ladders()
    
    if game_over:
        msg = f"Winner: Player {winner+1}!"
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        gluOrtho2D(0, W_WIDTH, 0, W_HEIGHT)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        draw_text(W_WIDTH//2 - 60, W_HEIGHT - 40, msg, players[winner]["color"])
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)


    # Draw static tokens
    for idx, p in enumerate(players):
        # if current player and animating in 'steps', token drawn static at last confirmed pos
        if game_over and winner == idx:
            # winner celebration: spin + bounce
            t = time.time()
            bounce = 0.15 * abs(math.sin(t * 6.0))
            spin = (t * 360.0) % 360.0
            x, z = cell_to_world(p["pos"])
            glPushMatrix()
            glTranslatef(x, BOARD_Y + 0.25 + bounce, z)
            glRotatef(spin, 0,1,0)
            glColor3f(*p["color"])
            glutSolidSphere(0.20, 24, 16)
            glPopMatrix()
        else:
            draw_token(p["pos"], p["color"])

    # draw moving token ghost depending on anim mode
    if animating:
        if anim_mode == 'steps' and anim_path:
            frm, to = anim_path[0]
            x0, z0 = cell_to_world(frm)
            x1, z1 = cell_to_world(to)
            x = x0 + (x1 - x0) * anim_t
            z = z0 + (z1 - z0) * anim_t
            draw_token_at(x, z, players[current_player]["color"])
        elif anim_mode == 'snake' and anim_path:
            # move along anim_path points using anim_t
            total = len(anim_path)
            if total >= 2:
                idxf = anim_t * (total - 1)
                i0 = int(clamp(math.floor(idxf), 0, total-1))
                i1 = min(i0 + 1, total-1)
                ft = idxf - i0
                x0,y0,z0 = anim_path[i0]; x1,y1,z1 = anim_path[i1]
                x = x0 + (x1-x0)*ft; y = y0 + (y1-y0)*ft; z = z0 + (z1-z0)*ft
                draw_token_at(x, z, players[current_player]["color"], y_offset=0.0, scale=0.16)
        elif anim_mode == 'ladder' and anim_path:
            total = len(anim_path)
            if total >= 2:
                idxf = anim_t * (total - 1)
                i0 = int(clamp(math.floor(idxf), 0, total-1))
                i1 = min(i0 + 1, total-1)
                ft = idxf - i0
                x0,y0,z0 = anim_path[i0]; x1,y1,z1 = anim_path[i1]
                x = x0 + (x1-x0)*ft; y = y0 + (y1-y0)*ft; z = z0 + (z1-z0)*ft
                draw_token_at(x, z, players[current_player]["color"], y_offset=0.0, scale=0.16)

    draw_dice_preview()
    draw_status_plates()
    draw_status_corner() 
    glutSwapBuffers()

def draw_status_plates():
    glPushMatrix()
    glTranslatef(BOARD_MIN - 1.2, 0.2, BOARD_MIN + 1.0)
    glRotatef(90, 0,1,0)
    glColor3f(*players[current_player]["color"])
    draw_cuboid(0.6, 0.05, 0.4)
    glPopMatrix()
    glPushMatrix()
    glTranslatef(BOARD_MAX + 1.2, 0.2, BOARD_MIN + 1.0)
    glRotatef(90, 0,1,0)
    if game_over: glColor3f(0.1,0.8,0.2)
    else:         glColor3f(0.3,0.3,0.3)
    draw_cuboid(0.6, 0.05, 0.4)
    glPopMatrix()

def idle():
    global last_time, anim_t
    now = time.time()
    dt = now - last_time
    last_time = now
    if dt > 0.1: dt = 0.1
    # update anim_t differently per mode
    if animating:
        if anim_mode == 'steps':
            update_animation(dt)
        elif anim_mode == 'snake':
            # snake progress along path using anim_t
            anim_t += 1.4 * dt
            update_animation(0)  # let update_animation finish when needed
        elif anim_mode == 'ladder':
            anim_t += 2.2 * dt
            update_animation(0)
    glutPostRedisplay()

def keyboard(key, x, y):
    global last_roll, game_over, winner, animating, anim_path, anim_t, current_player, top_down, double_dice, theme_idx
    k = key.decode("utf-8") if isinstance(key, bytes) else key
    if k in ('\x1b', 'q', 'Q'):
        sys.exit(0)
    if k in ('r','R'):
        restart_game()
        
    if k in ('p','P'):
        global two_players
        two_players = not two_players
        if not two_players:
            current_player = 0

    if k == ' ':
        if not game_over and not animating:
            # if player has skip flag, consume and end turn
            if players[current_player].get('skip', False):
                players[current_player]['skip'] = False
                end_turn_or_win()
                return
            perform_roll_and_schedule()
    if k in ('\t',):
        # top down toggle
        global top_down
        top_down = not top_down
    if k in ('+', '='):
        zoom(-1)
    if k in ('-', '_'):
        zoom(1)
    if k in ('d','D'):
        double_dice = not double_dice
        preview_dice()
    if k in ('t','T'):
        theme_idx = (theme_idx + 1) % len(THEMES)

def draw_text(x, y, text, color=(1,1,1)):
    glColor3f(*color)
    glRasterPos2f(x, y)
    for ch in text:
        glutBitmapCharacter(GLUT_BITMAP_HELVETICA_18, ord(ch))


def draw_status_corner():
    global two_players

    # Switch to 2D overlay
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, W_WIDTH, 0, W_HEIGHT)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()

    y = W_HEIGHT - 20

    # Always show Player 1
    msg1 = f"Red (P1): {players[0]['pos']}"
    draw_text(10, y, msg1, players[0]["color"])

    # Only show Player 2 if two_players is enabled
    if two_players and len(players) > 1:
        msg2 = f"Blue (P2): {players[1]['pos']}"
        draw_text(10, y - 20, msg2, players[1]["color"])

    # Restore matrices
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)


def reshape(w, h):
    global W_WIDTH, W_HEIGHT
    W_WIDTH, W_HEIGHT = max(1, w), max(1, h)
    glViewport(0, 0, W_WIDTH, W_HEIGHT)

def perform_roll_and_schedule():
    global last_rolls
    last_rolls = []
    if double_dice:
        a = random.randint(1,6)
        b = random.randint(1,6)
        last_rolls = [a, b]
        roll = a + b
    else:
        roll = random.randint(1,6)
        last_rolls = [roll]
    schedule_move(current_player, roll)

def special(key, x, y):
    global cam_angle, cam_tilt
    if key == GLUT_KEY_LEFT: cam_angle += 4.0
    elif key == GLUT_KEY_RIGHT: cam_angle -= 4.0
    elif key == GLUT_KEY_UP: cam_tilt = clamp(cam_tilt + 3.0, -85.0, 85.0)
    elif key == GLUT_KEY_DOWN: cam_tilt = clamp(cam_tilt - 3.0, -85.0, 85.0)

def zoom(direction):
    global cam_dist
    cam_dist = clamp(cam_dist + direction*0.8, 6.0, 40.0)

def restart_game():
    global players, current_player, game_over, winner, animating, anim_path, anim_t, last_roll, anim_mode, double_dice
    for p in players:
        p["pos"] = 1
        p["skip"] = False
    current_player = 0
    game_over = False
    winner = None
    animating = False
    anim_path = []
    anim_t = 0.0
    anim_mode = None
    last_roll = None
    double_dice = False

def init_gl():
    global quadric
    glClearColor(0.08, 0.10, 0.12, 1.0)
    glEnable(GL_DEPTH_TEST)
    glShadeModel(GL_SMOOTH)
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
    glEnable(GL_COLOR_MATERIAL)
    quadric = gluNewQuadric()
    gluQuadricNormals(quadric, GLU_SMOOTH)

def main():
    glutInit(sys.argv)
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB | GLUT_DEPTH)
    glutInitWindowSize(W_WIDTH, W_HEIGHT)
    glutCreateWindow(b"3D Snake & Ladder - Extended")
    init_gl()
    restart_game()
    glutDisplayFunc(display)
    glutIdleFunc(idle)
    glutReshapeFunc(reshape) 
    glutKeyboardFunc(keyboard)
    glutSpecialFunc(special)
    glutMainLoop()

if __name__ == "__main__":
    main()
