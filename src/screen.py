import os
import numpy as np
from PIL import ImageGrab
import win32gui

try:
    import cv2
except ImportError:
    cv2 = None

from src.window_utils import find_game_window

def capture_game_screen(selected_hwnd=None, game_window_title="Forza Horizon"):
    """Captures the game screen, or full screen if game window not found.
    Returns (PIL.Image, (offset_x, offset_y)).
    """
    hwnd, rect = find_game_window(selected_hwnd, game_window_title)
    if hwnd and rect:
        left, top, right, bottom = rect
        if left < 0: left = 0
        if top < 0: top = 0
        
        # Avoid capturing minimized or zero-size window
        if right > left and bottom > top:
            screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
            return screenshot, (left, top)
            
    # Fallback to full screen
    screenshot = ImageGrab.grab()
    return screenshot, (0, 0)

def find_template_on_screen(template_filename, templates_dir="templates", threshold=0.8, 
                            selected_hwnd=None, game_window_title="Forza Horizon", region=None, log_func=None):
    """Searches for a template image on the game screen, optionally within a relative region and threshold.
    Returns (abs_x, abs_y, max_val) or None.
    """
    if cv2 is None:
        if log_func:
            log_func("錯誤: OpenCV (cv2) 尚未載入，請確認安裝完成。")
        return None
        
    template_path = os.path.join(templates_dir, template_filename)
    if not os.path.exists(template_path):
        if log_func:
            log_func(f"警告: 找不到模板檔案 {template_path}，請先截圖設定。")
        return None
        
    screenshot, offset = capture_game_screen(selected_hwnd, game_window_title)
    img_rgb = np.array(screenshot)
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        if log_func:
            log_func(f"錯誤: 無法讀取模板檔案 {template_path}")
        return None
        
    w, h = template.shape[1], template.shape[0]
    
    # Apply region crop if provided (ymin, ymax, xmin, xmax as fractions of screen size)
    crop_offset_x = 0
    crop_offset_y = 0
    if region is not None:
        sh, sw = img_gray.shape[0], img_gray.shape[1]
        ymin, ymax, xmin, xmax = region
        py_min = int(ymin * sh)
        py_max = int(ymax * sh)
        px_min = int(xmin * sw)
        px_max = int(xmax * sw)
        
        py_min = max(0, min(py_min, sh - 1))
        py_max = max(0, min(py_max, sh))
        px_min = max(0, min(px_min, sw - 1))
        px_max = max(0, min(px_max, sw))
        
        if py_max > py_min and px_max > px_min:
            img_gray = img_gray[py_min:py_max, px_min:px_max]
            crop_offset_x = px_min
            crop_offset_y = py_min
    
    if w > img_gray.shape[1] or h > img_gray.shape[0]:
        return None
        
    res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    
    if max_val >= threshold:
        rel_x = max_loc[0] + w // 2
        rel_y = max_loc[1] + h // 2
        abs_x = offset[0] + crop_offset_x + rel_x
        abs_y = offset[1] + crop_offset_y + rel_y
        return abs_x, abs_y, max_val
        
    return None

def find_all_templates_on_screen(template_filename, templates_dir="templates", threshold=0.8, 
                                 selected_hwnd=None, game_window_title="Forza Horizon", min_distance=30, log_func=None):
    """Searches for all occurrences of a template image on the game screen.
    Returns a list of (abs_x, abs_y, confidence) sorted from left to right.
    """
    if cv2 is None:
        if log_func:
            log_func("錯誤: OpenCV (cv2) 尚未載入，請確認安裝完成。")
        return []
        
    template_path = os.path.join(templates_dir, template_filename)
    if not os.path.exists(template_path):
        if log_func:
            log_func(f"警告: 找不到模板檔案 {template_path}，請先截圖設定。")
        return []
        
    screenshot, offset = capture_game_screen(selected_hwnd, game_window_title)
    img_rgb = np.array(screenshot)
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        if log_func:
            log_func(f"錯誤: 無法讀取模板檔案 {template_path}")
        return []
        
    w, h = template.shape[1], template.shape[0]
    
    if w > img_gray.shape[1] or h > img_gray.shape[0]:
        if log_func:
            log_func(f"錯誤: 模板尺寸 {w}x{h} 大於畫面尺寸 {img_gray.shape[1]}x{img_gray.shape[0]}")
        return []
        
    res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    
    matches = []
    for pt in zip(*loc[::-1]):
        confidence = res[pt[1], pt[0]]
        matches.append((pt[0] + w // 2, pt[1] + h // 2, confidence))
        
    matches.sort(key=lambda item: item[0])
    
    filtered_matches = []
    for pt in matches:
        is_duplicate = False
        for f_pt in filtered_matches:
            dist = np.sqrt((pt[0] - f_pt[0])**2 + (pt[1] - f_pt[1])**2)
            if dist < min_distance:
                if pt[2] > f_pt[2]:
                    filtered_matches.remove(f_pt)
                    filtered_matches.append(pt)
                is_duplicate = True
                break
        if not is_duplicate:
            filtered_matches.append(pt)
            
    final_matches = []
    for rel_x, rel_y, conf in filtered_matches:
        abs_x = offset[0] + rel_x
        abs_y = offset[1] + rel_y
        final_matches.append((abs_x, abs_y, conf))
        
    final_matches.sort(key=lambda item: item[0])
    return final_matches
