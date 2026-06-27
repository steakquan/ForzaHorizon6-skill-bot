import win32gui
import win32con

def find_game_window(selected_hwnd=None, game_window_title="Forza Horizon"):
    """Finds the window handle and rect for the game.
    Returns (hwnd, (left, top, right, bottom)) or (None, None).
    """
    if selected_hwnd and win32gui.IsWindow(selected_hwnd):
        if not win32gui.IsIconic(selected_hwnd):
            return selected_hwnd, win32gui.GetWindowRect(selected_hwnd)
            
    # Fallback to search by exact title
    hwnd = win32gui.FindWindow(None, game_window_title)
    if hwnd and win32gui.IsWindow(hwnd) and not win32gui.IsIconic(hwnd):
        return hwnd, win32gui.GetWindowRect(hwnd)
        
    # Fallback: search window titles containing substring
    def enum_callback(h, extra):
        if win32gui.IsWindowVisible(h):
            title = win32gui.GetWindowText(h)
            if game_window_title.lower() in title.lower():
                extra.append((h, win32gui.GetWindowRect(h)))
    found = []
    win32gui.EnumWindows(enum_callback, found)
    if found:
        return found[0]
    return None, None

def get_visible_windows(ignored_hwnd=None):
    """Enumerates visible windows on the system and returns list of (title, hwnd)."""
    window_list = []
    
    def enum_windows_callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and title != "Program Manager" and hwnd != ignored_hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                if w > 100 and h > 100:
                    window_list.append((title, hwnd))
                    
    win32gui.EnumWindows(enum_windows_callback, None)
    window_list.sort(key=lambda x: x[0].lower())
    return window_list

def set_window_topmost(hwnd, enable=True):
    """Sets or clears the HWND_TOPMOST flag of a window."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
        
    try:
        flag = win32con.HWND_TOPMOST if enable else win32con.HWND_NOTOPMOST
        win32gui.SetWindowPos(hwnd, flag, 0, 0, 0, 0,
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
        return True
    except Exception:
        return False
