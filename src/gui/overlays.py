import os
import tkinter as tk
from PIL import ImageTk

FONT_FAMILY = "Microsoft JhengHei"

class CropOverlay:
    """Fullscreen borderless canvas that lets the user crop a region."""
    def __init__(self, parent, screenshot, save_path, callback):
        self.screenshot = screenshot
        self.save_path = save_path
        self.callback = callback
        
        self.top = tk.Toplevel(parent)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-topmost", True)
        self.top.lift()
        self.top.focus_force()
        
        self.width = screenshot.width
        self.height = screenshot.height
        
        self.canvas = tk.Canvas(self.top, width=self.width, height=self.height, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        
        self.tk_img = ImageTk.PhotoImage(screenshot)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        
        self.inst_lbl = self.canvas.create_text(self.width // 2, 30, text="按住滑鼠左鍵並拖曳來框選按鈕文字區域。按 ESC 取消選取。", fill="#ef4444", font=(FONT_FAMILY, 12, "bold"))
        self.canvas.create_rectangle(self.width // 2 - 250, 10, self.width // 2 + 250, 50, fill="#15151c", outline="#00e5ff", width=1)
        self.canvas.tag_raise(self.inst_lbl)
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        
        self.top.bind("<Escape>", lambda e: self.close(False, "User cancelled"))

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="#00e5ff", width=2)

    def on_drag(self, event):
        cur_x = event.x
        cur_y = event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        end_x = event.x
        end_y = event.y
        
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        
        w = x2 - x1
        h = y2 - y1
        
        if w > 5 and h > 5:
            try:
                cropped = self.screenshot.crop((x1, y1, x2, y2))
                os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
                cropped.save(self.save_path)
                self.close(True, self.save_path)
            except Exception as e:
                self.close(False, f"儲存錯誤: {e}")
        else:
            self.close(False, "選取範圍過小")

    def close(self, success, msg):
        self.top.destroy()
        self.callback(success, msg)


class CoordinateOverlay:
    """Fullscreen borderless canvas that lets the user select a single coordinate."""
    def __init__(self, parent, screenshot, callback):
        self.screenshot = screenshot
        self.callback = callback
        
        self.top = tk.Toplevel(parent)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-topmost", True)
        self.top.lift()
        self.top.focus_force()
        
        self.width = screenshot.width
        self.height = screenshot.height
        
        self.canvas = tk.Canvas(self.top, width=self.width, height=self.height, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        
        self.tk_img = ImageTk.PhotoImage(screenshot)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        
        self.inst_lbl = self.canvas.create_text(self.width // 2, 30, text="請在畫面上點擊目標點的中心位置。按 ESC 取消。", fill="#ef4444", font=(FONT_FAMILY, 12, "bold"))
        self.canvas.create_rectangle(self.width // 2 - 250, 10, self.width // 2 + 250, 50, fill="#15151c", outline="#00e5ff", width=1)
        self.canvas.tag_raise(self.inst_lbl)
        
        self.canvas.bind("<ButtonRelease-1>", self.on_click)
        self.top.bind("<Escape>", lambda e: self.close(False, "User cancelled"))

    def on_click(self, event):
        x = event.x
        y = event.y
        self.close(True, (x, y))

    def close(self, success, result):
        self.top.destroy()
        self.callback(success, result)
