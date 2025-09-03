# main.py
# Pumpkin Python Snake — 1024x600, chunky tiles, joystick + keyboard fallback
# Run: pip install pygame  ;  python main.py

import os, random
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

# --- Joystick settings ---
USE_JOYSTICK  = True
JOY_DEADZONE  = 0.5     # analog stick deadzone (if any)
JOY_START_BTN = 9       # Start button index (adjust to your encoder if needed)

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
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Pumpkin Python Snake")
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
        # toast shows “Keyboard mode” briefly if no joystick
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
        self._load_assets()           # pumpkin food
        self._load_snake_endcaps()    # head/tail

        self.reset()

    # ---- Asset loading ----
    def _load_assets(self):
        """Load food sprite; safe fallback."""
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
        self.dir = (1, 0)     # moving right
        self.next_dir = self.dir
        self.grow = 0
        self.score = 0
        blocked = set(self.snake)
        self.food = random_empty_cell(blocked)
        audio_mgr.play_hiss()  # fun startup hiss
        self.accum = 0
        self.state = "menu"   # menu -> playing -> paused/gameover

    # ---- Joystick helpers ----
    def _joy_dir(self):
        """Return 4-way dir from joystick/hat with diagonals resolved; None if idle."""
        if not self.joy:
            return None

        # Prefer HAT (typical for Zero-Delay encoders)
        if self.joy.get_numhats() > 0:
            hx, hy = self.joy.get_hat(0)  # hy: up=+1, down=-1
            if hy != 0:
                return (0, -1) if hy > 0 else (0, 1)
            if hx != 0:
                return (1, 0) if hx > 0 else (-1, 0)

        # Fallback: analog axes → 4-way with deadzone
        ax = self.joy.get_axis(0) if self.joy.get_numaxes() > 0 else 0.0
        ay = self.joy.get_axis(1) if self.joy.get_numaxes() > 1 else 0.0
        if abs(ax) < JOY_DEADZONE and abs(ay) < JOY_DEADZONE:
            return None
        if abs(ax) > abs(ay):
            return (1, 0) if ax > 0 else (-1, 0)
        else:
            return (0, 1) if ay > 0 else (0, -1)

    @staticmethod
    def _is_reverse(want, cur):
        return want[0] == -cur[0] and want[1] == -cur[1]

    def handle_input(self):
        want = self.next_dir

        # 1) Joystick first (last input wins if moved)
        jdir = self._joy_dir()
        if jdir is not None:
            want = jdir
        else:
            # 2) Keyboard fallback (arrows or WASD)
            keys = pygame.key.get_pressed()
            if keys[pygame.K_UP] or keys[pygame.K_w]:
                want = (0, -1)
            elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
                want = (0, 1)
            elif keys[pygame.K_LEFT] or keys[pygame.K_a]:
                want = (-1, 0)
            elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                want = (1, 0)

        # Disallow reversing directly
        if not self._is_reverse(want, self.dir):
            self.next_dir = want

    # ---- Math helpers for segments ----
    @staticmethod
    def _dir_from(a, b):
        """Direction from b -> a (grid step), one of {(1,0),(-1,0),(0,1),(0,-1)}."""
        dx, dy = a[0]-b[0], a[1]-b[1]
        if dx > 0: return (1, 0)
        if dx < 0: return (-1, 0)
        if dy > 0: return (0, 1)
        if dy < 0: return (0, -1)
        return (0, 0)

    @staticmethod
    def _dir_to_angle(d):
        # base images face RIGHT; rotate CCW in degrees
        if d == (1, 0):  return 0
        if d == (0, 1):  return 90
        if d == (-1,0):  return 180
        if d == (0,-1):  return 270
        return 0

    def _orient_sprite(self, base_img: pygame.Surface, d, kind: str) -> pygame.Surface:
        """Rotate from right-facing base + apply corrective flips per direction."""
        img = pygame.transform.rotate(base_img, self._dir_to_angle(d))
        if kind == "head":
            flip_x, flip_y = {
                (1, 0): (False, False),
                (0, 1): (False, True),
                (-1,0): (False, False),
                (0,-1): (False, True),
            }.get(d, (False, False))
        else:  # tail
            flip_x, flip_y = {
                (1, 0): (True,  False),
                (0, 1): (False, False),
                (-1,0): (True,  False),
                (0,-1): (False, False),
            }.get(d, (False, False))
        if flip_x or flip_y:
            img = pygame.transform.flip(img, flip_x, flip_y)
        return img

    # ---- Game step ----
    def step(self):
        self.dir = self.next_dir
        head_x, head_y = self.snake[0]
        nx, ny = head_x + self.dir[0], head_y + self.dir[1]

        # Wall collision
        if nx < 0 or nx >= GRID_W or ny < 0 or ny >= GRID_H:
            self.state = "gameover"; return

        new_head = (nx, ny)

        # Self collision
        if new_head in self.snake:
            self.state = "gameover"; return

        self.snake.insert(0, new_head)

        # Food
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
    def _draw_body_block(self, dst: pygame.Rect, index: int, horizontal: bool, is_turn: bool):
        base = PY_BODY_A if (index % 2 == 0) else PY_BODY_B
        pygame.draw.rect(self.screen, base, dst, border_radius=6)
        pygame.draw.rect(self.screen, PY_EDGE, dst, width=1, border_radius=6)

        # subtle blotches
        blotches = 1 if is_turn else 2
        for i in range(blotches):
            if horizontal:
                w = max(6, dst.w//3); h = max(6, dst.h//2)
                x = dst.left + (i+1)*(dst.w//(blotches+1)) - w//2
                y = dst.centery - h//2
            else:
                w = max(6, dst.w//2); h = max(6, dst.h//3)
                x = dst.centerx - w//2
                y = dst.top + (i+1)*(dst.h//(blotches+1)) - h//2
            pygame.draw.ellipse(self.screen, PY_BLOTCH, pygame.Rect(x, y, w, h))

    def draw_playfield(self):
        # Background
        self.screen.fill(BG_COLOR)

        # Grid
        for y in range(GRID_H):
            ypx = MARGIN_TOP + y * TILE
            pygame.draw.line(self.screen, GRID_COLOR, (MARGIN_LEFT, ypx), (MARGIN_LEFT + GRID_W*TILE, ypx), 1)
        for x in range(GRID_W+1):
            xpx = MARGIN_LEFT + x * TILE
            pygame.draw.line(self.screen, GRID_COLOR, (xpx, MARGIN_TOP), (xpx, MARGIN_TOP + GRID_H*TILE), 1)

        # Food
        fx, fy = grid_to_px(self.food)
        if self.food_img:
            self.screen.blit(self.food_img, (fx + 1, fy + 1))
        else:
            pygame.draw.rect(self.screen, FOOD_COLOR, (fx + 2, fy + 2, TILE - 4, TILE - 4), border_radius=3)

        # Snake — head/tail sprites + procedural body
        n = len(self.snake)
        for i, cell in enumerate(self.snake):
            px, py = grid_to_px(cell)
            dst = pygame.Rect(px+1, py+1, TILE-2, TILE-2)

            if i == 0:
                # HEAD
                head_img = self.snake_imgs.get("head")
                if head_img:
                    img = self._orient_sprite(head_img, self.dir, "head")
                    rect = img.get_rect(center=dst.center)   # center align
                    self.screen.blit(img, rect.topleft)
                else:
                    pygame.draw.rect(self.screen, (40, 255, 170), dst, border_radius=6)
                    pygame.draw.rect(self.screen, PY_EDGE, dst, width=1, border_radius=6)
                continue

            if i == n - 1:
                # TAIL
                tail_img = self.snake_imgs.get("tail")
                tail_dir = self._dir_from(cell, self.snake[i-1])  # direction from prev -> tail
                if tail_img:
                    img = self._orient_sprite(tail_img, tail_dir, "tail")
                    rect = img.get_rect(center=dst.center)   # center align
                    self.screen.blit(img, rect.topleft)
                else:
                    pygame.draw.rect(self.screen, PY_BODY_B, dst, border_radius=6)
                    pygame.draw.rect(self.screen, PY_EDGE, dst, width=1, border_radius=6)
                continue

            # BODY segment: straight or turn?
            prev = self.snake[i-1]
            nxt  = self.snake[i+1]
            d_in  = self._dir_from(cell, prev)  # from prev -> cell
            d_out = self._dir_from(nxt,  cell)  # from cell -> next

            horizontal = (d_in[1] == 0 and d_out[1] == 0)
            vertical   = (d_in[0] == 0 and d_out[0] == 0)
            is_turn    = not (horizontal or vertical)

            self._draw_body_block(dst, index=i, horizontal=horizontal, is_turn=is_turn)

        # HUD
        hud = self.font.render(f"Score: {self.score}", True, TEXT_COLOR)
        self.screen.blit(hud, (8, 6))

        # Mode toast (shows briefly if joystick missing/removed)
        if self._toast_ms > 0:
            label = "Keyboard mode" if self.joy is None else "Gamepad mode"
            toast = self.font.render(label, True, (200, 200, 200))
            self.screen.blit(toast, (SCREEN_W - toast.get_width() - 8, 6))

    def draw_menu(self, title, subtitle="Press ENTER/Start to play"):
        self.draw_playfield()
        t = self.bigfont.render(title, True, TEXT_COLOR)
        s = self.font.render(subtitle, True, TEXT_COLOR)
        self.screen.blit(t, t.get_rect(center=(SCREEN_W//2, SCREEN_H//2 - 30)))
        self.screen.blit(s, s.get_rect(center=(SCREEN_W//2, SCREEN_H//2 + 20)))

    # ---------- Main loop ----------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60)  # render at ~60 FPS
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                        continue

                    if self.state in ("menu", "gameover"):
                        if event.key == pygame.K_RETURN:
                            self.reset()
                            self.state = "playing"
                            continue

                    if self.state == "playing":
                        if event.key == pygame.K_SPACE:
                            self.state = "paused"
                    elif self.state == "paused":
                        if event.key == pygame.K_SPACE:
                            self.state = "playing"

                # Joystick buttons (Start toggles state)
                elif event.type == pygame.JOYBUTTONDOWN:
                    if event.button == JOY_START_BTN:
                        if self.state in ("menu", "gameover"):
                            self.reset()
                            self.state = "playing"
                        elif self.state == "playing":
                            self.state = "paused"
                        elif self.state == "paused":
                            self.state = "playing"

                # Hotplug support (optional)
                elif event.type == pygame.JOYDEVICEADDED:
                    if self.joy is None and pygame.joystick.get_count() > 0:
                        self.joy = pygame.joystick.Joystick(0)
                        self.joy.init()
                        self._toast_ms = 0
                        print(f"[input] joystick connected: {self.joy.get_name()}")
                elif event.type == pygame.JOYDEVICEREMOVED:
                    if self.joy and event.instance_id == self.joy.get_instance_id():
                        print("[input] joystick removed; keyboard fallback")
                        self.joy = None
                        self._toast_ms = 3000

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
                self.draw_menu("Pumpkin Python Snake")
            elif self.state == "paused":
                self.draw_playfield()
                self.draw_menu("Paused", "Press SPACE/Start to resume")
            elif self.state == "gameover":
                self.draw_playfield()
                self.draw_menu(f"Game Over — Score {self.score}", "ENTER/Start to restart")
            else:
                self.draw_playfield()

            pygame.display.flip()

        pygame.quit()

if __name__ == "__main__":
    SnakeGame().run()
