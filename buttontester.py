import pygame, sys
pygame.init()
pygame.display.set_mode((320, 200))  # ensures event pump on some platforms
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No joystick detected.")
    sys.exit(0)

js = pygame.joystick.Joystick(0); js.init()
print(f"Name: {js.get_name()}")
print(f"axes={js.get_numaxes()} hats={js.get_numhats()} buttons={js.get_numbuttons()}")
print("Move the stick / press buttons; press ESC to quit.")

while True:
    for e in pygame.event.get():
        if e.type == pygame.QUIT: sys.exit(0)
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE: sys.exit(0)

        if e.type == pygame.JOYHATMOTION:
            print(f"HAT {e.hat} -> {e.value}")  # e.value is (hx, hy), up = +1

        elif e.type == pygame.JOYBUTTONDOWN:
            print(f"BUTTON DOWN idx={e.button}")

        elif e.type == pygame.JOYBUTTONUP:
            print(f"BUTTON UP   idx={e.button}")

        elif e.type == pygame.JOYAXISMOTION:
            if abs(e.value) > 0.4:  # ignore tiny noise
                print(f"AXIS {e.axis} -> {e.value:+.2f}")
