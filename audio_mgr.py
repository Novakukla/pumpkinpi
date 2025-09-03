"""
audio_mgr.py — dual backend:
- "mixer": pygame.mixer plays assets/hiss.mp3 on the Pi
- "dfplayer": write DFPlayer command frames over UART (/dev/serial0), TX-only

Public API:
  init(backend: str, df_uart_port: str | None = "/dev/serial0", volume: int = 20, hiss_track: int = 1, hiss_file: str = "assets/hiss.mp3") -> None
  play_hiss() -> None
"""
from __future__ import annotations
import os, sys, time

# Runtime state
_BACKEND = "mixer"
_HISS = None  # pygame.mixer.Sound | None
_UART_FD = None
_HISS_TRACK = 1
_VOLUME = 20  # 0..30

# -------- DFPlayer framing --------
# Protocol: 0x7E, 0xFF, 0x06, CMD, FEEDBACK(0/1), PARAM_H, PARAM_L, CHKSUM_H, CHKSUM_L, 0xEF
def _df_checksum(cmd: int, fb: int, p1: int, p2: int) -> int:
    total = 0xFF + 0x06 + cmd + fb + p1 + p2
    return (0xFFFF - total + 1) & 0xFFFF

def _df_frame(cmd: int, param: int, feedback: int = 0) -> bytes:
    p1 = (param >> 8) & 0xFF
    p2 = param & 0xFF
    cs = _df_checksum(cmd, feedback, p1, p2)
    return bytes([
        0x7E, 0xFF, 0x06, cmd & 0xFF, feedback & 0xFF, p1, p2,
        (cs >> 8) & 0xFF, cs & 0xFF, 0xEF
    ])

def _df_write_frame(fd: int, frame: bytes):
    if fd is None: return
    try:
        os.write(fd, frame)
        # tiny settle; DFPlayer is forgiving but avoid spamming
        time.sleep(0.005)
    except Exception:
        pass

def _df_cmd_set_volume(fd: int, vol: int):
    v = max(0, min(30, int(vol)))
    _df_write_frame(fd, _df_frame(0x06, v))

def _df_cmd_play_track(fd: int, track_no: int):
    # plays by track index (01..299) if files named 0001.mp3 etc. in /mp3 or root
    t = max(1, min(299, int(track_no)))
    _df_write_frame(fd, _df_frame(0x03, t))

# -------- UART open (no pyserial) --------
def _open_uart(path: str, baud: int = 9600):
    """
    Open a UART device (TX-only is fine) without pyserial, using termios.
    Returns a file descriptor (int) or None on failure.
    """
    try:
        import termios
        import fcntl
        fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(fd)
        # iflag, oflag, cflag, lflag, ispeed, ospeed, cc
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
        # 8N1, no flow control
        cflag &= ~termios.PARENB
        cflag &= ~termios.CSTOPB
        cflag &= ~termios.CSIZE
        cflag |= termios.CS8
        cflag &= ~termios.CRTSCTS
        lflag = 0
        oflag = 0
        iflag = 0
        # Baud
        # Map common baud
        BAUDS = {
            9600: termios.B9600,
            19200: termios.B19200,
            38400: termios.B38400,
            57600: termios.B57600,
            115200: termios.B115200
        }
        b = BAUDS.get(baud, termios.B9600)
        ispeed = b
        ospeed = b
        termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
        # make it blocking for short writes
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
        return fd
    except Exception as e:
        print(f"[warn] UART open failed on {path}: {e}")
        try:
            if 'fd' in locals(): os.close(fd)
        except Exception:
            pass
        return None

# -------- Public API --------
def init(backend: str, df_uart_port: str | None = "/dev/serial0", volume: int = 20, hiss_track: int = 1, hiss_file: str = "assets/hiss.mp3"):
    """
    backend: "mixer" | "dfplayer"
    df_uart_port: path to serial device when using dfplayer (default /dev/serial0)
    volume: 0..30 (dfplayer), 0..1.0 mapped to pygame volume if mixer
    hiss_track: DFPlayer track number to play (e.g., 1 for 0001.mp3 on its SD card)
    hiss_file: local MP3 for mixer backend
    """
    global _BACKEND, _HISS, _UART_FD, _HISS_TRACK, _VOLUME
    _BACKEND = backend or "mixer"
    _HISS_TRACK = hiss_track
    _VOLUME = volume

    if _BACKEND == "mixer":
        try:
            import pygame
            pygame.mixer.init()
            _HISS = pygame.mixer.Sound(hiss_file)
            # Map DF volume 0..30 -> mixer 0..1
            pygame.mixer.Sound.set_volume(_HISS, max(0.0, min(1.0, volume/30.0)))
            print("[audio] mixer ready")
        except Exception as e:
            print(f"[warn] mixer init failed: {e}")
            _HISS = None
            _BACKEND = "none"
    elif _BACKEND == "dfplayer":
        path = df_uart_port or "/dev/serial0"
        _UART_FD = _open_uart(path, 9600)
        if _UART_FD is None:
            print("[warn] dfplayer UART not available; audio disabled")
            _BACKEND = "none"
            return
        # prime: set volume
        _df_cmd_set_volume(_UART_FD, _VOLUME)
        print(f"[audio] dfplayer ready on {path}, volume={_VOLUME}, hiss_track={_HISS_TRACK}")
    else:
        _BACKEND = "none"
        print("[audio] disabled")

def play_hiss():
    if _BACKEND == "mixer":
        if _HISS:
            try:
                _HISS.play()
            except Exception:
                pass
    elif _BACKEND == "dfplayer":
        if _UART_FD is not None:
            _df_cmd_play_track(_UART_FD, _HISS_TRACK)
