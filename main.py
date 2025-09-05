# main.py
# Python vs. Pumpkins — fullscreen, joystick-first, persistent highscores
# Requires: pygame (or pygame-ce)
# Run on Pi: python3 main.py

import os, json, random, time, tempfile, shutil
import pygame

# ---------- Config ----------
SCREEN_W, SCREEN_H = 1024, 600
TILE = 48
GRID_W, GRID_H = SCREEN_W // TILE, SCREEN_H // TILE
MARGIN_TOP = (SCREEN_H - GRID_H * TILE) // 2
MARGIN_LEFT = (SCREEN_W - GRID_W * TILE) // 2

# Fullscreen on Pi; windowed on desktop by commenting this block if you prefer
FULLSCREEN = True

# axis 0: -1 = LEFT, +1 = RIGHT
# axis 1: -1 = UP,   +1 = DOWN
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
            # sanitize
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

        flags = 0
        if FULLSCREEN:
            # Prefer X11/Wayland desktop; if you’re using pure KMS console you can set SDL_VIDEODRIVER in your service
            flags |= pygame.FULLSCREEN
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        pygame.display.set_caption("Python vs. Pumpkins")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 28)
        self.bigfont = pygame.font.SysFont(None, 60)

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

        self.reset()

    # ---- Assets ----
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
        self.state = "menu"   # menu -> playing -> paused -> gameover -> enter_score

        # Name entry model
        self.entry_name = ["A", "A", "A", "A"]
        self.entry_idx = 0    # 0..3 (3 = ENTER)

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
            ax_v = -self.js.get_axis(AXIS_V)
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
            # play hiss here if you wired mixer/DF
            # audio_mgr.play_hiss()
        else:
            if self.grow > 0:
                self.grow -= 1
            else:
                self.snake.pop()

    def _to_gameover(self):
        # If score qualifies for table -> enter name
        if self._qualifies(self.score):
            self.state = "enter_score"
            self.entry_name = ["A", "A", "A", "A"]
            self.entry_idx = 0
            self.last_ui_nav = 0
        else:
            self.state = "gameover"

    # ---- Highscore logic ----
    def _qualifies(self, score: int) -> bool:
        if score <= 0:
            return False
        if not self.scores or len(self.scores) < MAX_SCORES:
            return True
        return score > self.scores[-1]["score"]

    def _commit_score(self):
        name = "".join(self.entry_name).strip() or "AAAA"
        self.scores.append({"name": name, "score": self.score})
        self.scores.sort(key=lambda x: x["score"], reverse=True)
        self.scores = self.scores[:MAX_SCORES]
        save_scores(SAVE_PATH, self.scores)
        self.state = "gameover"

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
        # Allowed charset: A-Z, 0-9, space -> 37 chars
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
                    # cancel name entry
                    self.state = "gameover"

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

    def draw_menu(self, title, subtitle="Move the joystick to start"):
        self.draw_playfield()
        t = self.bigfont.render(title, True, TEXT_COLOR)
        s = self.font.render(subtitle, True, TEXT_COLOR)
        self.screen.blit(t, t.get_rect(center=(SCREEN_W//2, SCREEN_H//2 - 30)))
        self.screen.blit(s, s.get_rect(center=(SCREEN_W//2, SCREEN_H//2 + 20)))
        # Also show top scores
        self._draw_scoreboard(x=SCREEN_W//2, y=SCREEN_H//2 + 90, center=True)

    def _draw_scoreboard(self, x: int, y: int, center=False):
        title = self.font.render("High Scores", True, TEXT_COLOR)
        rect = title.get_rect(midtop=(x, y)) if center else (x, y)
        if center:
            self.screen.blit(title, rect)
            yy = rect.bottom + 6
        else:
            self.screen.blit(title, (x, y))
            yy = y + title.get_height() + 6
        for i, row in enumerate(self.scores[:MAX_SCORES], start=1):
            line = self.font.render(f"{i:2d}. {row['name']:<4} — {row['score']}", True, TEXT_COLOR)
            if center:
                self.screen.blit(line, line.get_rect(midtop=(x, yy)))
            else:
                self.screen.blit(line, (x, yy))
            yy += line.get_height() + 2

    def _draw_name_entry(self):
        self.draw_playfield()

        # Panel
        panel_w, panel_h = 900, 500
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = (SCREEN_W//2, SCREEN_H//2)
        pygame.draw.rect(self.screen, (16,16,16), panel, border_radius=12)
        pygame.draw.rect(self.screen, (64,64,64), panel, width=2, border_radius=12)

        # Title
        t = self.bigfont.render("Game Over", True, TEXT_COLOR)
        self.screen.blit(t, t.get_rect(midtop=(panel.centerx, panel.top + 12)))

        subt = self.font.render(f"Score: {self.score}", True, TEXT_COLOR)
        self.screen.blit(subt, subt.get_rect(midtop=(panel.centerx, panel.top + 72)))

        # Entry slots (4 letters + ENTER)
        slots_y = panel.top + 250
        slot_w, slot_h = 150, 72
        gap = 22

        labels = [self.entry_name[0], self.entry_name[1], self.entry_name[2], self.entry_name[3], "ENTER"]
        rects = []
        total_w = 5*slot_w + 4*gap # 4 slots
        start_x = panel.centerx - (total_w // 2) + slot_w//2

        for i in range(5):
            cx = start_x + i*(slot_w + gap)
            r = pygame.Rect(0, 0, slot_w, slot_h)
            r.center = (cx, slots_y)
            rects.append(r)
            # highlight current index
            col = (50,50,50) if i != self.entry_idx else (90,90,90)
            pygame.draw.rect(self.screen, col, r, border_radius=8)
            pygame.draw.rect(self.screen, (150,150,150), r, width=2, border_radius=8)

            label = labels[i]
            txt = self.bigfont.render(label, True, TEXT_COLOR)
            self.screen.blit(txt, txt.get_rect(center=r.center))

        hint1 = self.font.render("LEFT/RIGHT: Select   UP/DOWN: Change", True, TEXT_COLOR)
        hint2 = self.font.render("Hover ENTER and press DOWN to submit", True, TEXT_COLOR)
        self.screen.blit(hint1, hint1.get_rect(midtop=(panel.centerx, panel.bottom - 70)))
        self.screen.blit(hint2, hint2.get_rect(midtop=(panel.centerx, panel.bottom - 42)))

        # Draw current table on right side of panel
        self._draw_scoreboard(x=panel.right - 160, y=panel.top + 40, center=False)

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

            # State machine
            if self.state == "menu":
                # Start on any joystick movement or Enter (keyboard)
                started = False
                keys = pygame.key.get_pressed()
                if keys[pygame.K_RETURN]:
                    started = True
                if self.js:
                    ax_h = self.js.get_axis(AXIS_H)
                    ax_v = self.js.get_axis(AXIS_V)
                    if abs(ax_h) > AXIS_THRESH or abs(ax_v) > AXIS_THRESH:
                        started = True
                if started:
                    self.reset()
                    self.state = "playing"
                # draw
                self.draw_menu("Python vs. Pumpkins")

            elif self.state == "playing":
                # Input + step
                self.handle_input_game()
                self.accum += dt
                while self.accum >= STEP_MS:
                    self.step()
                    self.accum -= STEP_MS
                self.draw_playfield()

                # Pause (optional) via SPACE
                for e in events:
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                        self.state = "paused"

            elif self.state == "paused":
                self.draw_playfield()
                self.draw_menu("Paused", "Press SPACE to resume")
                for e in events:
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                        self.state = "playing"

            elif self.state == "enter_score":
                self._draw_name_entry()
                self.handle_input_entry(events)

            elif self.state == "gameover":
                self.draw_playfield()
                self._draw_scoreboard(x=SCREEN_W//2, y=SCREEN_H//2 - 20, center=True)
                # Restart hint
                s = self.font.render("Press ENTER or move joystick to play again", True, TEXT_COLOR)
                self.screen.blit(s, s.get_rect(midtop=(SCREEN_W//2, SCREEN_H//2 + 120)))
                # start on input
                started = False
                keys = pygame.key.get_pressed()
                if keys[pygame.K_RETURN]:
                    started = True
                if self.js:
                    ax_h = self.js.get_axis(AXIS_H)
                    ax_v = self.js.get_axis(AXIS_V)
                    if abs(ax_h) > AXIS_THRESH or abs(ax_v) > AXIS_THRESH:
                        started = True
                if started:
                    self.reset()
                    self.state = "playing"

            pygame.display.flip()

        pygame.quit()

if __name__ == "__main__":
    SnakeGame().run()
