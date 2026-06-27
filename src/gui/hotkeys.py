import ctypes
import threading
from ctypes import wintypes
import win32con

user32 = ctypes.windll.user32

HOTKEY_START_ID = 100
HOTKEY_STOP_ID = 101
VK_F10 = 0x79  # F10 key
VK_F11 = 0x7A  # F11 key

class GlobalHotkeyManager:
    def __init__(self, root, start_callback, stop_callback, log_callback):
        self.root = root
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.log_callback = log_callback
        self.hotkey_stop_event = threading.Event()
        self.hotkey_thread = None

    def start(self):
        self.hotkey_stop_event.clear()
        self.hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self.hotkey_thread.start()

    def stop(self):
        self.hotkey_stop_event.set()
        if self.hotkey_thread and self.hotkey_thread.ident:
            try:
                user32.PostThreadMessageW(self.hotkey_thread.ident, win32con.WM_QUIT, 0, 0)
            except Exception:
                pass

    def _hotkey_loop(self):
        if not user32.RegisterHotKey(0, HOTKEY_START_ID, 0, VK_F10):
            self.log_callback("警告: 無法註冊全域啟動快捷鍵 F10 (可能被佔用)")
        if not user32.RegisterHotKey(0, HOTKEY_STOP_ID, 0, VK_F11):
            self.log_callback("警告: 無法註冊全域停止快捷鍵 F11 (可能被佔用)")
            
        msg = wintypes.MSG()
        while not self.hotkey_stop_event.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if r != 0:
                if msg.message == win32con.WM_HOTKEY:
                    if msg.wParam == HOTKEY_START_ID:
                        self.log_callback("全域快捷鍵 F10 觸發 -> 啟動腳本")
                        self.root.after(0, self.start_callback)
                    elif msg.wParam == HOTKEY_STOP_ID:
                        self.log_callback("全域快捷鍵 F11 觸發 -> 停止腳本")
                        self.root.after(0, self.stop_callback)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
                
        user32.UnregisterHotKey(0, HOTKEY_START_ID)
        user32.UnregisterHotKey(0, HOTKEY_STOP_ID)
