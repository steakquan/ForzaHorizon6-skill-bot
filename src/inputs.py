import ctypes
import time
from ctypes import wintypes

# Input Types
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

# Keyboard flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# Mouse flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

# DirectInput Scan Codes
KEY_X = 0x2D       # 'X' key
KEY_ENTER = 0x1C   # 'Enter' key
KEY_ESC = 0x01     # 'ESC' key
KEY_W = 0x11       # 'W' key (Forward)
KEY_BACKSPACE = 0x0E # 'Backspace' key
KEY_SPACE = 0x39   # 'Space' key
KEY_DOWN = 0x50    # 'Arrow Down' key


# C Structs
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ii", INPUT_UNION),
    ]

# Keyboard Actions
def press_key(scan_code):
    """Presses a key using DirectInput scan code."""
    extra = ctypes.c_void_p(0)
    ii_ = INPUT_UNION()
    flags = KEYEVENTF_SCANCODE
    if scan_code in [0x48, 0x50, 0x4B, 0x4D]:  # Arrow Up, Down, Left, Right
        flags |= KEYEVENTF_EXTENDEDKEY
    ii_.ki = KEYBDINPUT(0, scan_code, flags, 0, extra)
    x = INPUT(INPUT_KEYBOARD, ii_)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def release_key(scan_code):
    """Releases a key using DirectInput scan code."""
    extra = ctypes.c_void_p(0)
    ii_ = INPUT_UNION()
    flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    if scan_code in [0x48, 0x50, 0x4B, 0x4D]:  # Arrow Up, Down, Left, Right
        flags |= KEYEVENTF_EXTENDEDKEY
    ii_.ki = KEYBDINPUT(0, scan_code, flags, 0, extra)
    x = INPUT(INPUT_KEYBOARD, ii_)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def press_and_release(scan_code, duration=0.5):
    """Simulates a key press down, waits for duration, releases it, and adds a 0.5s delay."""
    press_key(scan_code)
    time.sleep(duration)
    release_key(scan_code)
    time.sleep(0.5)  # 0.5s delay between keys

# Mouse Actions
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_cursor_pos():
    """Gets the current cursor position using Windows API."""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def set_cursor_pos(x, y):
    """Moves the cursor to absolute screen coordinates (x, y)."""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))

def smooth_move_mouse(target_x, target_y, duration=0.3):
    """Smoothly moves the mouse from current position to target position using a quadratic ease-out curve."""
    start_x, start_y = get_cursor_pos()
    
    # Calculate steps (aim for approx 15ms per step for smooth 60fps)
    steps = int(duration / 0.015)
    if steps < 5:
        steps = 5
        
    for i in range(1, steps + 1):
        t = i / steps
        # Quadratic ease-out curve: t_eased = 1 - (1 - t)^2
        t_eased = 1 - (1 - t) * (1 - t)
        curr_x = int(start_x + (target_x - start_x) * t_eased)
        curr_y = int(start_y + (target_y - start_y) * t_eased)
        set_cursor_pos(curr_x, curr_y)
        time.sleep(0.015)
        
    # Ensure final position is exact target
    set_cursor_pos(target_x, target_y)

def mouse_click(x, y, click_duration=0.1, settle_delay=0.1):
    """Moves the mouse to (x, y) and performs a left-click."""
    # Move mouse cursor
    set_cursor_pos(x, y)
    time.sleep(settle_delay)
    
    # Left click down
    extra = ctypes.c_void_p(0)
    ii_ = INPUT_UNION()
    ii_.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, extra)
    input_down = INPUT(INPUT_MOUSE, ii_)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(input_down), ctypes.sizeof(input_down))
    
    time.sleep(click_duration)
    
    # Left click up
    ii_up = INPUT_UNION()
    ii_up.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, extra)
    input_up = INPUT(INPUT_MOUSE, ii_up)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(input_up), ctypes.sizeof(input_up))

def mouse_scroll(clicks):
    """Scrolls the mouse wheel. Positive for up, negative for down."""
    extra = ctypes.c_void_p(0)
    ii_ = INPUT_UNION()
    delta = clicks * 120
    unsigned_delta = delta & 0xFFFFFFFF
    ii_.mi = MOUSEINPUT(0, 0, unsigned_delta, 0x0800, 0, extra)
    input_wheel = INPUT(INPUT_MOUSE, ii_)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(input_wheel), ctypes.sizeof(input_wheel))
