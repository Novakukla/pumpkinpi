# main.py
# Python vs. Pumpkins — 1024x600, chunky tiles, joystick (Sanwa encoder) + keyboard fallback
# Run: pip install pygame  ;  python main.py         # windowed dev: python main.py --windowed --fps 60

import os, random, argparse
import pygame
import audio_mgr  # DFPlayer / mixer backend

# ---------- Audio Config ----------
AUDIO_BACKEND = "dfplayer"   # "mixer" or "dfplayer"
DF_UART_PORT  = "/dev/serial0"
DF_VOLUME     = 20           # 0..30
DF_HISS_TRACK = 1            # plays 0001.mp3 on DFPlayer SD

# ---------- Display / Game Config ----------
SCREEN_W, SCREEN_H = 1024, 600
TILE = 48
GRID_W, GRID_H = SCREEN_W // TILE, SCREEN_H // TILE
MARGIN_TOP = (SCREEN_H - GRID_H * TILE) // 2
MARGIN_LEFT = (SCREEN_W - GRID_W * TILE) // 2
HEAD_SCALE = 2
TAIL_SCALE = 2

# --- Joystick settings (Sanwa + Zero-Delay encoder: axes only) ---
USE_JOYSTICK       = True
JOY_DEADZONE       = 0.5      # values are ±1 on your encoder; 0.5 is safe
JOY_START_BTN      = 9        # (kept for later; commented in events below)

# Axis mapping: (x_axis_index, y_axis_index)
# Your encoder: axis0 = vertical, axis1 = horizontal -> (x, y) = (1, 0)
JOY_AXIS           = (1, 0)   # x = axis1, y = axis0
JOY_AXIS_INVERT_Y  = True     # makes UP=(0,-1), DOWN=(0,1)

# --- Launch options ---
FULLSCREEN_DEFAULT = True     # Pi fullscreen by default; use --windowed to override

# Colors
SNAKE_COLOR = (220, 153, 0)
FOOD_COLOR  = (255, 120, 0)
BG_COLOR    = (0, 0, 0)
GRID_COLOR  = (28, 28, 40)
TEXT_COLOR  = (240, 240, 240)
PY_BODY_A   = (220, 153, 0)
PY_BODY_B   = (135, 84, 39)
PY_EDGE     = (24, 60, 40)
PY_BLOTCH   = (246, 214, 156)

STEP_MS   = 150   # slower (≈6.7 updates/sec)
START_LEN = 4

# ---------- CLI ----------
_parser = argparse.ArgumentParser()
_parser.add_argument("--windowed", action="store_true", help="run in a resizable window")
_parser.add_argument("--fps", type=int, default=60, help="render cap (default 60)")
_args = _parser.parse_args()

# ---------- Helpers ----------
def grid_to_px(cell):
    x, y = cell
    return (MARGIN_LEFT + x * TILE, MARGIN_TOP + y * TILE)

def random_empty_cell(blocked):
    while True:
        c = (random.randrange(0, GRID_W), random.randrange(0, GRID_H))
        if c not in blocked:
            return c

# ---------- Game ----------
class SnakeGame:
    def __init__(self):
        pygame.init()

        # Fullscreen unless --windowed specified
        want_full = FULLSCREEN_DEFAULT and not _args.windowed
        flags = 0
        if want_full:
            flags |= pygame.FULLSCREEN | pygame.SCALED

        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        pygame.display.set_caption("Python vs. Pumpkins")

        if want_full:
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)

        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 28)
        self.bigfont = pygame.font.SysFont(None, 60)

        # --- Joystick init ---
        self.joy = None
        if USE_JOYSTICK:
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                self.joy = pygame.joystick.Joystick(0)
                self.joy.init()
                print(f"[input] joystick: {self.joy.get_name()} "
                      f"(axes={self.joy.get_numaxes()}, hats={self.joy.get_numhats()}, buttons={self.joy.get_numbuttons()})")
            else:
                print("[input] no joystick found; keyboard fallback")
        self._toast_ms = 3000 if self.joy is None else 0

        # --- Audio init ---
        audio_mgr.init(
            backend=AUDIO_BACKEND,
            df_uart_port=DF_UART_PORT,
            volume=DF_VOLUME,
            hiss_track=DF_HISS_TRACK,
            hiss_file="assets/hiss.mp3"
        )

        # Assets (after display init so convert_alpha works)
        self.food_img = None
        self.snake_imgs = {"head": None, "tail": None}
        self._load_assets()
        self._load_snake_endcaps()

        self.reset()

    # ---- Asset loading ----
    def _load_assets(self):
        try:
            img_path = os.path.join("assets", "pumpkin.png")
            img = pygame.image.load(img_path).convert_alpha()
            self.food_img = pygame.transform.smoothscale(img, (TILE - 2, TILE - 2))
        except Exception as e:
            print(f"[warn] food sprite not loaded: {e}")
            self.food_img = None

    def _load_snake_endcaps(self):
        def load(path, scale=1.0):
            try:
                img = pygame.image.load(path).convert_alpha()
                w = int((TILE - 2) * scale)
                h = int((TILE - 2) * scale)
                return pygame.transform.smoothscale(img, (w, h))
            except Exception as e:
                print(f"[warn] sprite '{path}' not loaded: {e}")
                return None
        base = "assets"
        self.snake_imgs["head"] = load(os.path.join(base, "snake_head.png"), HEAD_SCALE)
        self.snake_imgs["tail"] = load(os.path.join(base, "snake_tail.png"), TAIL_SCALE)

    # ---- State / control ----
    def reset(self):
        cx, cy = GRID_W // 2, GRID_H // 2
        self.snake = [(cx - i, cy) for i in range(START_LEN)]
        self.dir = (1, 0)
        self.next_dir = self.dir
        self.grow = 0
        self.score = 0
        blocked = set(self.snake)
        self.food = random_empty_cell(blocked)
        audio_mgr.play_hiss()  # fun startup hiss
        self.accum = 0
        self.state = "menu"

    # ---- Joystick helpers ----
    def _joy_dir(self, prev_dir=None):
        """Return 4-way dir from joystick (axes only in your case)."""
        if not self.joy:
            return None
        try:
            ax_i, ay_i = JOY_AXIS
            ax = self.joy.get_axis(ax_i) if self.joy.get_numaxes() > ax_i else 0.0
            ay = self.joy.get_axis(ay_i) if self.joy.get_numaxes() > ay_i else 0.0
            if JOY_AXIS_INVERT_Y:
                ay = -ay
            if abs(ax) < JOY_DEADZONE and abs(ay) < JOY_DEADZONE:
                return None
            if abs(ax) > abs(ay):
                return (1, 0) if ax > 0 else (-1, 0)
            else:
                return (0, 1) if ay > 0 else (0, -1)
        except Exception:
            return None

    @staticmethod
    def _is_reverse(want, cur):
        return want[0] == -cur[0] and want[1] == -cur[1]

    def handle_input(self):
        want = self.next_dir
        jdir = self._joy_dir(prev_dir=self.dir)
        if jdir is not None:
            want = jdir
        else:
            keys = pygame.key.get_pressed()
            if keys[pygame.K_UP] or keys[pygame.K_w]:
                want = (0, -1)
            elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
                want = (0, 1)
            elif keys[pygame.K_LEFT] or keys[pygame.K_a]:
                want = (-1, 0)
            elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                want = (1, 0)
        if not self._is_reverse(want, self.dir):
            self.next_dir = want

    # ---- Math helpers for segments ----
    @staticmethod
    def _dir_from(a, b):
        dx, dy = a[0]-b[0], a[1]-b[1]
        if dx > 0: return (1, 0)
        if dx < 0: return (-1, 0)
        if dy > 0: return (0, 1)
        if dy < 0: return (0, -1)
        return (0, 0)

    @staticmethod
    def _dir_to_angle(d):
        if d == (1, 0):  return 0
        if d == (0, 1):  return 90
        if d == (-1,0):  return 180
        if d == (0,-1):  return 270
        return 0

    def _orient_sprite(self, base_img, d, kind):
        img = pygame.transform.rotate(base_img, self._dir_to_angle(d))
        if kind == "head":
            flip_x, flip_y = {
                (1,0):(False,False),(0,1):(False,True),(-1,0):(False,False),(0,-1):(False,True),
            }.get(d,(False,False))
        else:
            flip_x, flip_y = {
                (1,0):(True,False),(0,1):(False,False),(-1,0):(True,False),(0,-1):(False,False),
            }.get(d,(False,False))
        if flip_x or flip_y:
            img = pygame.transform.flip(img, flip_x, flip_y)
        return img

    # ---- Game step ----
    def step(self):
        self.dir = self.next_dir
        head_x, head_y = self.snake[0]
        nx, ny = head_x + self.dir[0], head_y + self.dir[1]
        if nx < 0 or nx >= GRID_W or ny < 0 or ny >= GRID_H:
            self.state = "gameover"; return
        new_head = (nx, ny)
        if new_head in self.snake:
            self.state = "gameover"; return
        self.snake.insert(0, new_head)
        if new_head == self.food:
            self.score += 1
            self.grow += 1
            blocked = set(self.snake)
            self.food = random_empty_cell(blocked)
            audio_mgr.play_hiss()
        else:
            if self.grow > 0:
                self.grow -= 1
            else:
                self.snake.pop()

    # ---- Drawing ----
    def _draw_body_block(self, dst, index, horizontal, is_turn):
        base = PY_BODY_A if (index % 2 == 0) else PY_BODY_B
        pygame.draw.rect(self.screen, base, dst, border_radius=6)
        pygame.draw.rect(self.screen, PY_EDGE, dst, width=1, border_radius=6)
        blotches = 1 if is_turn else 2
        for i in range(blotches):
            if horizontal:
                w = max(6, dst.w//3); h = max(6, dst.h//2)
                x = dst.left+(i+1)*(dst.w//(blotches+1))-w//2
                y = dst.centery-h//2
            else:
                w = max(6, dst.w//2); h = max(6, dst.h//3)
                x = dst.centerx-w//2
                y = dst.top+(i+1)*(dst.h//(blotches+1))-h//2
            pygame.draw.ellipse(self.screen, PY_BLOTCH, pygame.Rect(x,y,w,h))

    def draw_playfield(self):
        self.screen.fill(BG_COLOR)
        for y in range(GRID_H):
            ypx = MARGIN_TOP + y*TILE
            pygame.draw.line(self.screen, GRID_COLOR,(MARGIN_LEFT,ypx),(MARGIN_LEFT+GRID_W*TILE,ypx),1)
        for x in range(GRID_W+1):
            xpx = MARGIN_LEFT + x*TILE
            pygame.draw.line(self.screen, GRID_COLOR,(xpx,MARGIN_TOP),(xpx,MARGIN_TOP+GRID_H*TILE),1)

        fx, fy = grid_to_px(self.food)
        if self.food_img:
            self.screen.blit(self.food_img,(fx+1,fy+1))
        else:
            pygame.draw.rect(self.screen, FOOD_COLOR,(fx+2,fy+2,TILE-4,TILE-4),border_radius=3)

        n = len(self.snake)
        for i, cell in enumerate(self.snake):
            px, py = grid_to_px(cell)
            dst = pygame.Rect(px+1,py+1,TILE-2,TILE-2)
            if i == 0:
                head_img = self.snake_imgs.get("head")
                if head_img:
                    img = self._orient_sprite(head_img, self.dir,"head")
                    rect = img.get_rect(center=dst.center)
                    self.screen.blit(img, rect.topleft)
                else:
                    pygame.draw.rect(self.screen,(40,255,170),dst,border_radius=6)
                    pygame.draw.rect(self.screen,PY_EDGE,dst,width=1,border_radius=6)
                continue
            if i == n-1:
                tail_img = self.snake_imgs.get("tail")
                tail_dir = self._dir_from(cell, self.snake[i-1])
                if tail_img:
                    img = self._orient_sprite(tail_img, tail_dir,"tail")
                    rect = img.get_rect(center=dst.center)
                    self.screen.blit(img, rect.topleft)
                else:
                    pygame.draw.rect(self.screen,PY_BODY_B,dst,border_radius=6)
                    pygame.draw.rect(self.screen,PY_EDGE,dst,width=1,border_radius=6)
                continue
            prev = self.snake[i-1]; nxt = self.snake[i+1]
            d_in = self._dir_from(cell, prev); d_out = self._dir_from(nxt, cell)
            horizontal = (d_in[1]==0 and d_out[1]==0)
            vertical   = (d_in[0]==0 and d_out[0]==0)
            is_turn    = not(horizontal or vertical)
            self._draw_body_block(dst,index=i,horizontal=horizontal,is_turn=is_turn)

        hud = self.font.render(f"Score: {self.score}",True,TEXT_COLOR)
        self.screen.blit(hud,(8,6))
        if self._toast_ms>0:
            label = "Keyboard mode" if self.joy is None else "Gamepad mode"
            toast = self.font.render(label,True,(200,200,200))
            self.screen.blit(toast,(SCREEN_W-toast.get_width()-8,6))

    def draw_menu(self, title, subtitle="Move joystick / press any button to start"):
        self.draw_playfield()
        t = self.bigfont.render(title,True,TEXT_COLOR)
        s = self.font.render(subtitle,True,TEXT_COLOR)
        self.screen.blit(t,t.get_rect(center=(SCREEN_W//2,SCREEN_H//2-30)))
        self.screen.blit(s,s.get_rect(center=(SCREEN_W//2,SCREEN_H//2+20)))

    # ---------- Main loop ----------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(_args.fps)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                # ---------- KEYBOARD ----------
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                        continue

                    # Start/restart from keyboard: Enter, keypad Enter, Space, or arrow/WASD
                    if self.state in ("menu", "gameover"):
                        if event.key in (
                            pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE,
                            pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
                            pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d
                        ):
                            self.reset()
                            self.state = "playing"
                            continue

                    # Pause/resume via keyboard
                    if self.state == "playing":
                        if event.key in (pygame.K_SPACE,):
                            self.state = "paused"
                    elif self.state == "paused":
                        if event.key in (pygame.K_SPACE,):
                            self.state = "playing"

                # ---------- JOYSTICK: START/RESTART ON ANY INPUT ----------
                elif self.state in ("menu", "gameover") and self.joy:
                    # Any button press starts
                    if event.type == pygame.JOYBUTTONDOWN:
                        self.reset()
                        self.state = "playing"
                        continue
                    # Any hat motion (non-zero) starts
                    elif event.type == pygame.JOYHATMOTION:
                        hx, hy = self.joy.get_hat(event.hat)
                        if hx != 0 or hy != 0:
                            self.reset()
                            self.state = "playing"
                            continue
                    # Any axis motion beyond deadzone starts
                    elif event.type == pygame.JOYAXISMOTION:
                        if abs(event.value) > JOY_DEADZONE:
                            self.reset()
                            self.state = "playing"
                            continue

                # ---------- JOYSTICK: PAUSE/RESUME (optional Start button) ----------
                # If you wire a Start button later, uncomment this block:
                """
                elif event.type == pygame.JOYBUTTONDOWN:
                    if event.button == JOY_START_BTN:
                        if self.state in ("menu", "gameover"):
                            self.reset(); self.state = "playing"
                        elif self.state == "playing":
                            self.state = "paused"
                        elif self.state == "paused":
                            self.state = "playing"
                """

            # Movement & ticking
            if self.state == "playing":
                self.handle_input()
                self.accum += dt
                while self.accum >= STEP_MS:
                    self.step()
                    self.accum -= STEP_MS

            # countdown toast timer
            if self._toast_ms > 0:
                self._toast_ms = max(0, self._toast_ms - dt)

            # Draw
            if self.state == "menu":
                self.draw_menu("Python vs. Pumpkins")
            elif self.state == "paused":
                self.draw_playfield()
                self.draw_menu("Paused", "Press SPACE or move joystick to resume")
            elif self.state == "gameover":
                self.draw_playfield()
                self.draw_menu(f"Game Over — Score {self.score}", "Move joystick / any button to restart")
            else:
                self.draw_playfield()

            pygame.display.flip()

        pygame.quit()

if __name__ == "__main__":
    SnakeGame().run()
