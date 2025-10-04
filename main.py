# main.py
# Python vs. Pumpkins — fullscreen, joystick-first, persistent highscores
# Requires: pygame (or pygame-ce)
# Run on Pi: python3 main.py

import os, json, random, time, tempfile, shutil, subprocess, colorsys
import pygame
import shutil as _shutil  # for which()

# ---------- Config ----------
SCREEN_W, SCREEN_H = 1024, 600
TILE = 48
GRID_W, GRID_H = SCREEN_W // TILE, SCREEN_H // TILE
MARGIN_TOP = (SCREEN_H - GRID_H * TILE) // 2
MARGIN_LEFT = (SCREEN_W - GRID_W * TILE) // 2

# Fullscreen on Pi; windowed on desktop by commenting this block if you prefer
FULLSCREEN = True

# Joystick axis mapping you settled on:
# axis 1: -1 = LEFT, +1 = RIGHT
# axis 0: -1 = UP,   +1 = DOWN
AXIS_H = 1
AXIS_V = 0
AXIS_THRESH = 0.6      # stick threshold to count as a press
UI_REPEAT_MS = 220     # cooldown for UI navigation (name entry)

# Highscore persistence
SAVE_PATH = os.path.expanduser("~/.pumpkin_snake/highscores.json")
MAX_SCORES = 10

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

STEP_MS   = 150   # ≈6.7 updates/sec
START_LEN = 4

HEAD_SCALE = 2
TAIL_SCALE = 2

# Screen lock duration (ms) before returning to menu
GAMEOVER_LOCK_MS = 5000
TOPCELEB_MS = 5000   # how long to show the rainbow neon celebration

ASSETS_DIR = "assets"
ARCADE_TTF = os.path.join(ASSETS_DIR, "PressStart2P-Regular.ttf")
VIDEO_DIED = os.path.join(ASSETS_DIR, "youdied.mp4")
# (Top score video removed per your request)

# ---------- Helpers ----------
def grid_to_px(cell):
    x, y = cell
    return (MARGIN_LEFT + x * TILE, MARGIN_TOP + y * TILE)

def random_empty_cell(blocked):
    while True:
        c = (random.randrange(0, GRID_W), random.randrange(0, GRID_H))
        if c not in blocked:
            return c

def ensure_save_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def load_scores(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            out = []
            for it in data:
                name = str(it.get("name", ""))[:4]
                score = int(it.get("score", 0))
                out.append({"name": name, "score": score})
            out.sort(key=lambda x: x["score"], reverse=True)
            return out[:MAX_SCORES]
    except Exception:
        pass
    return []

def save_scores(path: str, scores):
    ensure_save_dir(path)
    tmpfd, tmppath = tempfile.mkstemp(prefix="scores_", suffix=".json",
                                      dir=os.path.dirname(path) or None)
    os.close(tmpfd)
    try:
        with open(tmppath, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)
        shutil.move(tmppath, path)
    finally:
        if os.path.exists(tmppath):
            os.remove(tmppath)

# ---------- Game ----------
class SnakeGame:
    def __init__(self):
        pygame.init()
        pygame.mouse.set_visible(False)   # hide cursor
        pygame.event.set_grab(True)       # lock pointer to the window

        flags = 0
        if FULLSCREEN:
            flags |= pygame.FULLSCREEN
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        pygame.display.set_caption("Python vs. Pumpkins")
        self.clock = pygame.time.Clock()

        # Fonts (retro arcade if available)
        self._init_fonts()

        # Joystick
        pygame.joystick.init()
        self.js = None
        if pygame.joystick.get_count() > 0:
            self.js = pygame.joystick.Joystick(0)
            self.js.init()
        self.last_ui_nav = 0  # for name-entry cooldown

        # Assets
        self.food_img = None
        self.snake_imgs = {"head": None, "tail": None}
        self._load_assets()
        self._load_snake_endcaps()

        # Highscores
        self.scores = load_scores(SAVE_PATH)

        # Timing for screens
        self.gameover_until = 0  # when gameover can auto-leave
        self.post_until = 0      # when post-submit can auto-leave
        self.topcelebrate_until = 0


        self.reset()

    # ---- Fonts ----
    def _init_fonts(self):
        def _sys(size): return pygame.font.SysFont("Courier New", size, bold=True)
        if os.path.exists(ARCADE_TTF):
            try:
                self.title_font   = pygame.font.Font(ARCADE_TTF, 42)  # big title
                self.bigfont      = pygame.font.Font(ARCADE_TTF, 24)
                self.hiscore_font = pygame.font.Font(ARCADE_TTF, 17)
                self.font         = pygame.font.Font(ARCADE_TTF, 17)
                self.top_font     = pygame.font.Font(ARCADE_TTF, 96) 
                return
            except Exception as e:
                print(f"[warn] arcade font load failed: {e}")
        # Fallback mono look if font missing
        self.title_font   = _sys(72)
        self.bigfont      = _sys(42)
        self.hiscore_font = _sys(24)
        self.font         = _sys(20)
        self.top_font     = _sys(96)

    # ---- Joystick helpers ----
    def _stick_axes(self):
        if not self.js:
            return 0.0, 0.0
        ax_h = self.js.get_axis(AXIS_H)
        ax_v = self.js.get_axis(AXIS_V)
        return ax_h, ax_v

    def _stick_neutral(self, deadzone=0.2):
        ax_h, ax_v = self._stick_axes()
        return abs(ax_h) < deadzone and abs(ax_v) < deadzone

    def _stick_moved(self, thresh=AXIS_THRESH):
        ax_h, ax_v = self._stick_axes()
        return (abs(ax_h) > thresh) or (abs(ax_v) > thresh)

    # ---- Assets ----
    def _load_assets(self):
        try:
            img_path = os.path.join(ASSETS_DIR, "pumpkin.png")
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
        base = ASSETS_DIR
        self.snake_imgs["head"] = load(os.path.join(base, "snake_head.png"), HEAD_SCALE)
        self.snake_imgs["tail"] = load(os.path.join(base, "snake_tail.png"), TAIL_SCALE)

    # ---- Video ----
    def _play_video(self, path):
        """Try to play a video fullscreen with an available player; blocks until done."""
        if not os.path.exists(path):
            return
        for player in ("mpv", "ffplay", "omxplayer"):
            if _shutil.which(player):
                try:
                    if player == "mpv":
                        subprocess.run([player, "--fs", "--no-osd-bar", "--quiet", path])
                    elif player == "ffplay":
                        subprocess.run([player, "-autoexit", "-hide_banner", "-loglevel", "quiet", path])
                    else:  # omxplayer
                        subprocess.run([player, "--no-osd", path])
                except Exception as e:
                    print(f"[warn] video player failed: {e}")
                break

    # ---- State ----
    def reset(self):
        cx, cy = GRID_W // 2, GRID_H // 2
        self.snake = [(cx - i, cy) for i in range(START_LEN)]
        self.dir = (1, 0)
        self.next_dir = self.dir
        self.grow = 0
        self.score = 0
        blocked = set(self.snake)
        self.food = random_empty_cell(blocked)
        self.accum = 0
        # States: menu -> playing -> paused -> gameover (panel) -> menu
        # or menu -> playing -> enter_score -> post_submit (no panel) -> menu
        self.state = "menu"

        # Name entry model
        self.entry_name = ["A", "A", "A", "A"]
        self.entry_idx = 0    # 0..3 (4 = ENTER)
        self.start_need_neutral = True

    # ---- Input helpers ----
    def _dir_from(self, a, b):
        dx, dy = a[0]-b[0], a[1]-b[1]
        if dx > 0: return (1, 0)
        if dx < 0: return (-1, 0)
        if dy > 0: return (0, 1)
        if dy < 0: return (0, -1)
        return (0, 0)

    def _dir_to_angle(self, d):
        if d == (1, 0):  return 0
        if d == (0, 1):  return 90
        if d == (-1,0):  return 180
        if d == (0,-1):  return 270
        return 0

    def _orient_sprite(self, base_img: pygame.Surface, d: tuple[int,int], kind: str) -> pygame.Surface:
        angle = self._dir_to_angle(d)
        img = pygame.transform.rotate(base_img, angle)
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
    def handle_input_game(self):
        # Keyboard fallback
        want = self.next_dir
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            want = (0, -1)
        elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
            want = (0, 1)
        elif keys[pygame.K_LEFT] or keys[pygame.K_a]:
            want = (-1, 0)
        elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            want = (1, 0)

        # Joystick axes
        if self.js:
            ax_h = self.js.get_axis(AXIS_H)
            ax_v = -self.js.get_axis(AXIS_V)  # your chosen invert on V
            if abs(ax_h) > abs(ax_v):
                if ax_h <= -AXIS_THRESH: want = (-1, 0)
                elif ax_h >=  AXIS_THRESH: want = ( 1, 0)
            else:
                if ax_v <= -AXIS_THRESH: want = (0, -1)
                elif ax_v >=  AXIS_THRESH: want = (0,  1)

        if (want[0] != -self.dir[0]) or (want[1] != -self.dir[1]):
            self.next_dir = want

    def step(self):
        self.dir = self.next_dir
        head_x, head_y = self.snake[0]
        nx, ny = head_x + self.dir[0], head_y + self.dir[1]

        if nx < 0 or nx >= GRID_W or ny < 0 or ny >= GRID_H:
            self._to_gameover(); return
        new_head = (nx, ny)
        if new_head in self.snake:
            self._to_gameover(); return

        self.snake.insert(0, new_head)
        if new_head == self.food:
            self.score += 1
            self.grow += 1
            blocked = set(self.snake)
            self.food = random_empty_cell(blocked)
        else:
            if self.grow > 0:
                self.grow -= 1
            else:
                self.snake.pop()

    def _to_gameover(self):
        # If score qualifies for table -> enter name
        if self._qualifies(self.score):
            if self._is_top_score(self.score):
                # Show neon celebration first, THEN enter name
                self.state = "topcelebrate"
                self.topcelebrate_until = pygame.time.get_ticks() + TOPCELEB_MS
            else:
                self.state = "enter_score"
                self.entry_name = ["A", "A", "A", "A"]
                self.entry_idx = 0
                self.last_ui_nav = 0
        else:
            # Straight to gameover panel with lockout timer
            self.state = "gameover"
            self.gameover_until = pygame.time.get_ticks() + GAMEOVER_LOCK_MS
            self.start_need_neutral = True

    # ---- Highscore logic ----
    def _qualifies(self, score: int) -> bool:
        if score <= 0:
            return False
        if not self.scores or len(self.scores) < MAX_SCORES:
            return True
        return score > self.scores[-1]["score"]

    def _is_top_score(self, score: int) -> bool:
        """True if this score is #1 (tie or beat)."""
        if not self.scores:
            return score > 0
        return score >= self.scores[0]["score"]

    def _commit_score(self):
        name = "".join(self.entry_name).strip() or "AAAA"
        self.scores.append({"name": name, "score": self.score})
        self.scores.sort(key=lambda x: x["score"], reverse=True)
        self.scores = self.scores[:MAX_SCORES]
        save_scores(SAVE_PATH, self.scores)

        # After submitting a leaderboard entry:
        # DO NOT show the high-scores panel. Show a simple "saved" panel for 5s, then go to menu.
        self.state = "post_submit"
        self.post_until = pygame.time.get_ticks() + GAMEOVER_LOCK_MS
        self.start_need_neutral = True

    # ---- UI name entry helpers ----
    def _ui_can_nav(self):
        now = pygame.time.get_ticks()
        if now - self.last_ui_nav >= UI_REPEAT_MS:
            self.last_ui_nav = now
            return True
        return False

    def _ui_move_cursor(self, delta):
        self.entry_idx = max(0, min(4, self.entry_idx + delta))

    def _ui_change_letter(self, delta):
        if self.entry_idx >= 4:
            return
        charset = [*(chr(ord('A')+i) for i in range(26)),
                   *[str(i) for i in range(10)],
                   ' ']
        cur = self.entry_name[self.entry_idx]
        try:
            idx = charset.index(cur)
        except ValueError:
            idx = 0
        idx = (idx + delta) % len(charset)
        self.entry_name[self.entry_idx] = charset[idx]

    def handle_input_entry(self, events):
        # Keyboard edges
        for e in events:
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_LEFT, pygame.K_a):
                    if self._ui_can_nav(): self._ui_move_cursor(-1)
                elif e.key in (pygame.K_RIGHT, pygame.K_d):
                    if self._ui_can_nav(): self._ui_move_cursor(+1)
                elif e.key in (pygame.K_UP, pygame.K_w):
                    if self._ui_can_nav():
                        if self.entry_idx == 4:
                            self._commit_score()
                        else:
                            self._ui_change_letter(+1)
                elif e.key in (pygame.K_DOWN, pygame.K_s):
                    if self._ui_can_nav() and self.entry_idx < 4:
                        self._ui_change_letter(-1)
                elif e.key == pygame.K_ESCAPE:
                    # cancel name entry, still go to gameover lock screen
                    self.state = "gameover"
                    self.gameover_until = pygame.time.get_ticks() + GAMEOVER_LOCK_MS

        # Joystick axes (edge-ish via cooldown)
        if self.js and self._ui_can_nav():
            ax_h = self.js.get_axis(AXIS_H)
            ax_v = self.js.get_axis(AXIS_V)
            if abs(ax_h) > abs(ax_v):
                if ax_h <= -AXIS_THRESH: self._ui_move_cursor(-1)
                elif ax_h >=  AXIS_THRESH: self._ui_move_cursor(+1)
            else:
                if ax_v <= -AXIS_THRESH:
                    if self.entry_idx == 4: self._commit_score()
                    else: self._ui_change_letter(+1)
                elif ax_v >= AXIS_THRESH:
                    if self.entry_idx < 4: self._ui_change_letter(-1)

    # ---- Drawing ----
    def _draw_body_block(self, dst: pygame.Rect, index: int, horizontal: bool, is_turn: bool):
        base = PY_BODY_A if (index % 2 == 0) else PY_BODY_B

        # Adjust rect shape depending on orientation
        if horizontal:
            body_rect = dst.inflate(10, 0)  # wider, flatter
        else:
            body_rect = dst.inflate(0, 10)  # taller, thinner

        pygame.draw.ellipse(self.screen, base, body_rect)
        pygame.draw.ellipse(self.screen, PY_EDGE, body_rect, width=1)

        # Blotches
        blotches = 1 if is_turn else 2
        for i in range(blotches):
            if horizontal:
                w = max(6, body_rect.w//3); h = max(4, body_rect.h//2)
                x = body_rect.left + (i+1)*(body_rect.w//(blotches+1)) - w//2
                y = body_rect.centery - h//2
            else:
                w = max(4, body_rect.w//2); h = max(6, body_rect.h//3)
                x = body_rect.centerx - w//2
                y = body_rect.top + (i+1)*(body_rect.h//(blotches+1)) - h//2
            blotch_rect = pygame.Rect(x, y, w, h)
            pygame.draw.ellipse(self.screen, PY_BLOTCH, blotch_rect)

    def draw_playfield(self):
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

        # Snake
        n = len(self.snake)
        for i, cell in enumerate(self.snake):
            px, py = grid_to_px(cell)
            dst = pygame.Rect(px+1, py+1, TILE-2, TILE-2)
            if i == 0:
                head_img = self.snake_imgs.get("head")
                if head_img:
                    img = self._orient_sprite(head_img, self.dir, "head")
                    rect = img.get_rect(center=dst.center)
                    self.screen.blit(img, rect.topleft)
                else:
                    pygame.draw.rect(self.screen, (40, 255, 170), dst, border_radius=6)
                    pygame.draw.rect(self.screen, PY_EDGE, dst, width=1, border_radius=6)
                continue
            if i == n - 1:
                tail_img = self.snake_imgs.get("tail")
                tail_dir = self._dir_from(cell, self.snake[i-1])
                if tail_img:
                    img = self._orient_sprite(tail_img, tail_dir, "tail")
                    rect = img.get_rect(center=dst.center)
                    self.screen.blit(img, rect.topleft)
                else:
                    pygame.draw.rect(self.screen, PY_BODY_B, dst, border_radius=6)
                    pygame.draw.rect(self.screen, PY_EDGE, dst, width=1, border_radius=6)
                continue

            prev = self.snake[i-1]
            nxt  = self.snake[i+1]
            d_in  = self._dir_from(cell, prev)
            d_out = self._dir_from(nxt,  cell)
            horizontal = (d_in[1] == 0 and d_out[1] == 0)
            vertical   = (d_in[0] == 0 and d_out[0] == 0)
            is_turn    = not (horizontal or vertical)
            self._draw_body_block(dst, index=i, horizontal=horizontal, is_turn=is_turn)

        # HUD
        hud = self.font.render(f"Score: {self.score}", True, TEXT_COLOR)
        self.screen.blit(hud, (8, 6))

    def draw_menu(self):
        self.draw_playfield()
        # Big retro title, no scoreboard here per your request
        title = self.title_font.render("PYTHON vs PUMPKINS", True, TEXT_COLOR)
        self.screen.blit(title, title.get_rect(center=(SCREEN_W//2, SCREEN_H//2 - 40)))
        s = self.hiscore_font.render("Move the joystick or press ENTER to start", True, TEXT_COLOR)
        self.screen.blit(s, s.get_rect(center=(SCREEN_W//2, SCREEN_H//2 + 40)))
        # Footer credit
		credit = self.hiscore_font.render("made by nova kukla", True, (150, 150, 150))
		self.screen.blit(credit, credit.get_rect(midbottom=(SCREEN_W//2, SCREEN_H - 10)))


    def _draw_gameover_scores_panel(self):
        # Panel geometry: centered
        panel_w, panel_h = 560, 320
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = (SCREEN_W // 2, SCREEN_H // 2 - 10)

        # Panel background
        pygame.draw.rect(self.screen, (16, 16, 16), panel, border_radius=12)
        pygame.draw.rect(self.screen, (64, 64, 64), panel, width=2, border_radius=12)

        # Title
        title = self.bigfont.render("High Scores", True, TEXT_COLOR)
        self.screen.blit(title, title.get_rect(midtop=(panel.centerx, panel.top + 14)))

        # Split into 2 columns
        left_x  = panel.left + panel_w // 4
        right_x = panel.left + 3 * panel_w // 4
        start_y = panel.top + 80
        line_gap = 6

        # Left column (1–5)
        yy = start_y
        for i, row in enumerate(self.scores[:5], start=1):
            line = self.hiscore_font.render(f"{i:2d}. {row['name']:<4} — {row['score']}", True, TEXT_COLOR)
            self.screen.blit(line, line.get_rect(midtop=(left_x, yy)))
            yy += line.get_height() + line_gap

        # Right column (6–10)
        yy = start_y
        for i, row in enumerate(self.scores[5:10], start=6):
            line = self.hiscore_font.render(f"{i:2d}. {row['name']:<4} — {row['score']}", True, TEXT_COLOR)
            self.screen.blit(line, line.get_rect(midtop=(right_x, yy)))
            yy += line.get_height() + line_gap

    def _draw_name_entry(self):
        self.draw_playfield()

        # Panel
        panel_w, panel_h = 900, 500
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = (SCREEN_W//2, SCREEN_H//2)
        pygame.draw.rect(self.screen, (16,16,16), panel, border_radius=12)
        pygame.draw.rect(self.screen, (64,64,64), panel, width=2, border_radius=12)

        # Title
        t = self.bigfont.render("You Made The Leaderboard!", True, TEXT_COLOR)
        self.screen.blit(t, t.get_rect(midtop=(panel.centerx, panel.top + 12)))

        subt = self.hiscore_font.render(f"Score: {self.score}", True, TEXT_COLOR)
        self.screen.blit(subt, subt.get_rect(midtop=(panel.centerx, panel.top + 60)))

        # Entry slots (4 letters + ENTER)
        slots_y = panel.top + 350
        slot_w, slot_h = 150, 72
        gap = 22

        labels = [self.entry_name[0], self.entry_name[1], self.entry_name[2], self.entry_name[3], "ENTER"]
        rects = []
        total_w = 5*slot_w + 4*gap
        start_x = panel.centerx - (total_w // 2) + slot_w//2

        for i in range(5):
            cx = start_x + i*(slot_w + gap)
            r = pygame.Rect(0, 0, slot_w, slot_h)
            r.center = (cx, slots_y)
            rects.append(r)
            col = (50,50,50) if i != self.entry_idx else (90,90,90)
            pygame.draw.rect(self.screen, col, r, border_radius=8)
            pygame.draw.rect(self.screen, (150,150,150), r, width=2, border_radius=8)

            label = labels[i]
            txt = self.bigfont.render(label, True, TEXT_COLOR)
            self.screen.blit(txt, txt.get_rect(center=r.center))

        hint1 = self.hiscore_font.render("LEFT/RIGHT: Select   UP/DOWN: Change", True, TEXT_COLOR)
        hint2 = self.hiscore_font.render("Hover ENTER and press DOWN to submit", True, TEXT_COLOR)
        self.screen.blit(hint1, hint1.get_rect(midtop=(panel.centerx, panel.bottom - 90)))
        self.screen.blit(hint2, hint2.get_rect(midtop=(panel.centerx, panel.bottom - 60)))

    def _draw_rainbow_text(self, text: str, center: tuple[int, int], t_ms: int,
                           font=None, outline_px=2, glow_rings=(6, 3), glow_alpha=80):
        """
        Rainbow *inside* the glyphs (not boxes), with a dark outline and soft glow.
        - font: defaults to self.title_font, falls back to self.bigfont.
        - outline_px: thickness of the black stroke.
        - glow_rings: list of pixel offsets for additive glow.
        """
        if font is None:
            font = getattr(self, "title_font", None) or self.bigfont

        # measure + center
        text_w, text_h = font.size(text)
        x0 = center[0] - text_w // 2
        y0 = center[1] - text_h // 2

        # 1) build a rainbow gradient surface the size of the text
        grad = pygame.Surface((text_w, text_h), pygame.SRCALPHA)
        # animate hue over time; sweep across X
        period_ms = 4000.0
        phase = (t_ms % period_ms) / period_ms
        for x in range(text_w):
            hue = (phase + x / max(1, text_w)) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            pygame.draw.line(grad, (int(r*255), int(g*255), int(b*255), 255), (x, 0), (x, text_h))

        # 2) render the text once (white = full mask, nice antialias alpha)
        mask_text = font.render(text, True, (255, 255, 255))    # has per-pixel alpha
        black_text = font.render(text, True, (0, 0, 0))

        # 3) make the gradient respect the text alpha (RGBA_MULT multiplies both color and alpha)
        grad.blit(mask_text, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        # 4) soft colored glow *under* the text
        if glow_rings:
            glow = grad.copy()
            glow.set_alpha(glow_alpha)
            # 8 directions around the glyph for a halo
            def ring_offsets(r):
                return [(-r, 0), (r, 0), (0, -r), (0, r), (-r, -r), (-r, r), (r, -r), (r, r)]
            for r in glow_rings:
                for dx, dy in ring_offsets(r):
                    self.screen.blit(glow, (x0 + dx, y0 + dy), special_flags=pygame.BLEND_ADD)

        # 5) crisp black outline for readability
        if outline_px > 0:
            for dx in range(-outline_px, outline_px + 1):
                for dy in range(-outline_px, outline_px + 1):
                    if dx == 0 and dy == 0:
                        continue
                    self.screen.blit(black_text, (x0 + dx, y0 + dy))

        # 6) final gradient-filled text on top
        self.screen.blit(grad, (x0, y0))


    def _draw_topcelebrate_screen(self):
        # dim the background playfield a bit
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        self.screen.blit(overlay, (0, 0))

        now = pygame.time.get_ticks()
        # Main neon headline
        # in your “new #1 score” celebration state draw:
        self._draw_rainbow_text(
            "NEW TOP HIGH SCORE!",
            (SCREEN_W//2, SCREEN_H//2 - 120),
            pygame.time.get_ticks(),
            font=self.title_font,      # or a bigger dedicated font if you made one
            outline_px=3,
            glow_rings=(10, 6, 3),
            glow_alpha=70
        )


        # Score under it (steady, not neon)
        score_txt = self.bigfont.render(f"SCORE: {self.score}", True, TEXT_COLOR)
        self.screen.blit(score_txt, score_txt.get_rect(center=(SCREEN_W//2, SCREEN_H//2 + 40)))

        # (No input hint here—this screen auto-advances)



    # ---------- Main loop ----------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60)
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False

            if self.state == "menu":
                # Start on any joystick movement (after neutral) or Enter (key edge)
                started = False

                for e in events:
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_RETURN:
                        started = True

                if self.js:
                    if self.start_need_neutral:
                        if self._stick_neutral():
                            self.start_need_neutral = False
                    else:
                        if self._stick_moved():
                            started = True

                if started:
                    self.reset()
                    self.state = "playing"

                self.draw_menu()

            elif self.state == "playing":
                self.handle_input_game()
                self.accum += dt
                while self.accum >= STEP_MS:
                    self.step()
                    self.accum -= STEP_MS
                self.draw_playfield()

                for e in events:
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                        self.state = "paused"

            elif self.state == "paused":
                self.draw_playfield()
                t = self.bigfont.render("Paused", True, TEXT_COLOR)
                s = self.hiscore_font.render("Press SPACE to resume", True, TEXT_COLOR)
                self.screen.blit(t, t.get_rect(center=(SCREEN_W//2, SCREEN_H//2 - 20)))
                self.screen.blit(s, s.get_rect(center=(SCREEN_W//2, SCREEN_H//2 + 30)))
                for e in events:
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                        self.state = "playing"

            elif self.state == "topcelebrate":
                # Draw the field behind it for a nice backdrop
                self.draw_playfield()
                self._draw_topcelebrate_screen()
                # Ignore input; auto-advance after timer
                if pygame.time.get_ticks() >= self.topcelebrate_until:
                    # Now transition to name entry
                    self.state = "enter_score"
                    self.entry_name = ["A", "A", "A", "A"]
                    self.entry_idx = 0
                    self.last_ui_nav = 0

            elif self.state == "enter_score":
                self._draw_name_entry()
                self.handle_input_entry(events)

            elif self.state == "post_submit":
                # Show a simple confirmation for 5 seconds; ignore input
                self._draw_gameover_scores_panel()
                if pygame.time.get_ticks() >= self.post_until:
                    self.state = "menu"
                    self.start_need_neutral = True

            elif self.state == "gameover":
                # Death without leaderboard: show highscores panel (locked)
                self.draw_playfield()
                self._draw_gameover_scores_panel()
                if pygame.time.get_ticks() >= self.gameover_until:
                    self.state = "menu"
                    self.start_need_neutral = True

            pygame.display.flip()

        pygame.quit()

if __name__ == "__main__":
    SnakeGame().run()
