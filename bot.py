import os
import time
import logging
import threading
from PIL import Image, ImageGrab
import numpy as np
import win32gui
import win32con

# Import our DirectInput module
import direct_input

# Try to import cv2, we will handle ImportError gracefully if it's not installed yet
try:
    import cv2
except ImportError:
    cv2 = None

# Try to import winsdk and asyncio for Windows Native OCR support
try:
    import asyncio
    import io
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
    HAS_WINSDK = True
except ImportError:
    HAS_WINSDK = False

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ForzaBot:
    def __init__(self, templates_dir="templates"):
        self.templates_dir = templates_dir
        self.race_duration = 62.0  # seconds
        self.threshold = 0.8       # similarity threshold
        self.check_interval = 1.0  # check screen every X seconds
        self.game_window_title = "Forza Horizon" # Substring to find window
        self.selected_hwnd = None                # Explicit HWND from GUI
        
        self.state = "IDLE"
        self.mode = "RACE_FARM"  # RACE_FARM, CAR_MASTERY
        self.is_running = False
        self.thread = None
        self.log_callback = print # Can be replaced by GUI log function
        self.state_callback = None # Can be replaced by GUI state update function
        
        self.mastery_grid_topleft = None
        self.mastery_grid_bottomright = None
        self.mastery_car_index = 0
        
        # Ensure templates directory exists
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir)
            
        self.load_config()
        
        # Initialize OCR engines for multiple languages (with broader tag fallbacks)
        self.ocr_engines = []
        if HAS_WINSDK:
            for lang_tag in ["zh-TW", "zh-Hant-TW", "zh-Hant", "zh-CN", "zh-Hans-CN", "zh-Hans", "en-US"]:
                try:
                    lang = Language(lang_tag)
                    engine = OcrEngine.try_create_from_language(lang)
                    if engine:
                        self.ocr_engines.append((lang_tag, engine))
                        self.log(f"成功載入 OCR 引擎: {lang_tag}")
                except Exception as e:
                    pass
            # Fallback to current system language if none could be loaded
            if not self.ocr_engines:
                try:
                    engine = OcrEngine.try_create_from_current_language()
                    if engine:
                        self.ocr_engines.append(("system", engine))
                        self.log("成功載入系統預設 OCR 引擎")
                except Exception as e:
                    pass

    def load_config(self):
        import json
        config_path = os.path.join(self.templates_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.race_duration = data.get("race_duration", self.race_duration)
                    self.threshold = data.get("threshold", self.threshold)
                    self.game_window_title = data.get("game_window_title", self.game_window_title)
                    self.mastery_grid_topleft = data.get("mastery_grid_topleft", self.mastery_grid_topleft)
                    if self.mastery_grid_topleft:
                        self.mastery_grid_topleft = tuple(self.mastery_grid_topleft)
                    self.mastery_grid_bottomright = data.get("mastery_grid_bottomright", self.mastery_grid_bottomright)
                    if self.mastery_grid_bottomright:
                        self.mastery_grid_bottomright = tuple(self.mastery_grid_bottomright)
                    self.mastery_car_index = data.get("mastery_car_index", self.mastery_car_index)
            except Exception as e:
                self.log(f"讀取設定檔 config.json 發生錯誤: {e}")

    def save_config(self):
        import json
        config_path = os.path.join(self.templates_dir, "config.json")
        try:
            data = {
                "race_duration": self.race_duration,
                "threshold": self.threshold,
                "game_window_title": self.game_window_title,
                "mastery_grid_topleft": self.mastery_grid_topleft,
                "mastery_grid_bottomright": self.mastery_grid_bottomright,
                "mastery_car_index": self.mastery_car_index
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.log(f"儲存設定檔 config.json 發生錯誤: {e}")

    def log(self, message):
        # Prevent crash if logging/printing fails due to encoding limitations
        try:
            logging.info(message)
        except Exception:
            pass
            
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                try:
                    import sys
                    safe_msg = message.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')
                    print(safe_msg)
                except Exception:
                    pass

    def update_state(self, new_state):
        self.state = new_state
        self.log(f"狀態轉移至: {new_state}")
        if self.state_callback:
            self.state_callback(new_state)

    def find_game_window(self):
        """Finds the window handle and rect for the game."""
        # If we have an explicit hwnd selected and it is valid, use it directly
        if self.selected_hwnd and win32gui.IsWindow(self.selected_hwnd):
            if not win32gui.IsIconic(self.selected_hwnd):
                return self.selected_hwnd, win32gui.GetWindowRect(self.selected_hwnd)

        hwnd_list = []
        def win_enum_handler(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if self.game_window_title.lower() in title.lower():
                    hwnd_list.append((hwnd, title))
        win32gui.EnumWindows(win_enum_handler, None)
        
        if not hwnd_list:
            return None, None
            
        # Prioritize windows that are not minimized and have actual size
        for hwnd, title in hwnd_list:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width > 100 and height > 100:
                # Check if minimized
                if not win32gui.IsIconic(hwnd):
                    return hwnd, rect
        
        # Fallback to the first found
        hwnd, title = hwnd_list[0]
        return hwnd, win32gui.GetWindowRect(hwnd)

    def capture_game_screen(self):
        """Captures the game screen, or full screen if game window not found."""
        hwnd, rect = self.find_game_window()
        if hwnd and rect:
            # rect is (left, top, right, bottom)
            # Ensure coordinates are within valid range
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

    def find_template_on_screen(self, template_filename, threshold=None, region=None):
        """Searches for a template image on the game screen, optionally within a relative region and threshold."""
        if cv2 is None:
            self.log("錯誤: OpenCV (cv2) 尚未載入，請確認安裝完成。")
            return None
            
        template_path = os.path.join(self.templates_dir, template_filename)
        if not os.path.exists(template_path):
            self.log(f"警告: 找不到模板檔案 {template_path}，請先截圖設定。")
            return None
            
        screenshot, offset = self.capture_game_screen()
        img_rgb = np.array(screenshot)
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            self.log(f"錯誤: 無法讀取模板檔案 {template_path}")
            return None
            
        w, h = template.shape[1], template.shape[0]
        
        # Determine threshold
        search_threshold = threshold if threshold is not None else self.threshold
        
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
            # Ensure crop bounds are valid
            py_min = max(0, min(py_min, sh - 1))
            py_max = max(0, min(py_max, sh))
            px_min = max(0, min(px_min, sw - 1))
            px_max = max(0, min(px_max, sw))
            
            if py_max > py_min and px_max > px_min:
                img_gray = img_gray[py_min:py_max, px_min:px_max]
                crop_offset_x = px_min
                crop_offset_y = py_min
        
        # Ensure template is smaller than screen
        if w > img_gray.shape[1] or h > img_gray.shape[0]:
            return None
            
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        
        if max_val >= search_threshold:
            # relative center of match in the (cropped) image
            rel_x = max_loc[0] + w // 2
            rel_y = max_loc[1] + h // 2
            # absolute center of match on screen
            abs_x = offset[0] + crop_offset_x + rel_x
            abs_y = offset[1] + crop_offset_y + rel_y
            return abs_x, abs_y, max_val
            
        return None

    def find_all_templates_on_screen(self, template_filename, min_distance=30):
        """Searches for all occurrences of a template image on the game screen.
        Returns a list of (abs_x, abs_y, confidence) sorted from left to right.
        """
        if cv2 is None:
            self.log("錯誤: OpenCV (cv2) 尚未載入，請確認安裝完成。")
            return []
            
        template_path = os.path.join(self.templates_dir, template_filename)
        if not os.path.exists(template_path):
            self.log(f"警告: 找不到模板檔案 {template_path}，請先截圖設定。")
            return []
            
        screenshot, offset = self.capture_game_screen()
        img_rgb = np.array(screenshot)
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            self.log(f"錯誤: 無法讀取模板檔案 {template_path}")
            return []
            
        w, h = template.shape[1], template.shape[0]
        
        # Ensure template is smaller than screen
        if w > img_gray.shape[1] or h > img_gray.shape[0]:
            self.log(f"錯誤: 模板尺寸 {w}x{h} 大於畫面尺寸 {img_gray.shape[1]}x{img_gray.shape[0]}")
            return []
            
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        
        # Find all locations with confidence >= threshold
        loc = np.where(res >= self.threshold)
        
        matches = []
        for pt in zip(*loc[::-1]):  # Switch x and y
            confidence = res[pt[1], pt[0]]
            matches.append((pt[0] + w // 2, pt[1] + h // 2, confidence))
            
        # Group close matches to avoid multiple detections of the same card (basic NMS)
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
                
        # Convert to absolute screen coordinates
        final_matches = []
        for rel_x, rel_y, conf in filtered_matches:
            abs_x = offset[0] + rel_x
            abs_y = offset[1] + rel_y
            final_matches.append((abs_x, abs_y, conf))
            
        # Sort by x coordinate left-to-right
        final_matches.sort(key=lambda item: item[0])
        return final_matches

    def find_text_by_ocr_sync(self, target_texts):
        """Synchronously runs OCR to find the given text list on the game screen.
        Returns (abs_x, abs_y, confidence) of the matched text center, or None.
        """
        if not HAS_WINSDK or not self.ocr_engines:
            return None
        try:
            if isinstance(target_texts, str):
                target_texts = [target_texts]
            return asyncio.run(self._ocr_search_multi_async(target_texts))
        except Exception as e:
            self.log(f"OCR 辨識過程發生異常錯誤: {e}")
            return None

    async def _ocr_search_multi_async(self, target_texts):
        """Asynchronously grabs screen and runs Windows Media OCR using multiple engines to find any of target_texts."""
        if not self.ocr_engines:
            return None
            
        screenshot, offset = self.capture_game_screen()
        
        # 為了大幅提升小字元與孤立按鈕文字的 OCR 識別率，將截圖等比放大 2 倍
        scale_factor = 2
        new_size = (screenshot.size[0] * scale_factor, screenshot.size[1] * scale_factor)
        screenshot_scaled = screenshot.resize(new_size, Image.Resampling.LANCZOS)
        
        # Convert PIL Image to bytes
        img_byte_arr = io.BytesIO()
        screenshot_scaled.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        
        # Write bytes into a Windows Random Access Stream
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(img_bytes)
        await writer.store_async()
        await writer.flush_async()
        
        # Decode the stream into a SoftwareBitmap
        decoder = await BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()
        
        # Convert target_texts to lowercase and remove spaces for space-insensitive comparison
        targets_clean = ["".join(t.lower().split()) for t in target_texts]
        
        # Try engines one by one
        for lang_tag, engine in self.ocr_engines:
            try:
                result = await engine.recognize_async(software_bitmap)
                for line in result.lines:
                    # Remove all spaces from the line text for comparison
                    line_text_clean = "".join(line.text.lower().split())
                    
                    matched_target = None
                    for t_clean in targets_clean:
                        if t_clean in line_text_clean:
                            # 針對短按鈕文字進行長度過濾，避免從「是否要在...」等長句子誤匹配到「是」、「否」等短目標
                            short_button_targets = {"是", "确定", "確定", "yes", "ok", "no", "否", "不", "buy", "購買", "购买", "已新增", "車庫", "车库"}
                            if t_clean in short_button_targets and len(line_text_clean) > len(t_clean) + 4:
                                continue
                            matched_target = t_clean
                            break
                            
                    if matched_target:
                        words = list(line.words)
                        if words:
                            # 尋找匹配目標的最窄單字區間，以實現極致的點擊精準度
                            best_range = None
                            min_len = float('inf')
                            for i in range(len(words)):
                                for j in range(i, len(words)):
                                    subsegment = words[i:j+1]
                                    sub_text_clean = "".join("".join(w.text.lower().split()) for w in subsegment)
                                    if matched_target in sub_text_clean:
                                        length = j - i
                                        if length < min_len:
                                            min_len = length
                                            best_range = (i, j)
                            
                            if best_range:
                                i, j = best_range
                                matched_words = words[i:j+1]
                                left = matched_words[0].bounding_rect.x / scale_factor
                                top = min(w.bounding_rect.y for w in matched_words) / scale_factor
                                right = (matched_words[-1].bounding_rect.x + matched_words[-1].bounding_rect.width) / scale_factor
                                bottom = max(w.bounding_rect.y + w.bounding_rect.height for w in matched_words) / scale_factor
                            else:
                                left = words[0].bounding_rect.x / scale_factor
                                top = min(w.bounding_rect.y for w in words) / scale_factor
                                right = (words[-1].bounding_rect.x + words[-1].bounding_rect.width) / scale_factor
                                bottom = max(w.bounding_rect.y + w.bounding_rect.height for w in words) / scale_factor
                                
                            center_x = int(offset[0] + left + (right - left) / 2)
                            center_y = int(offset[1] + top + (bottom - top) / 2)
                            self.log(f"[OCR] [OCR 匹配成功] 語言: {lang_tag}, 原始文字: '{line.text}', 匹配目標: '{matched_target}', 點擊目標: ({center_x}, {center_y})")
                            return center_x, center_y, 1.0
            except Exception as e:
                self.log(f"OCR 引擎 {lang_tag} 辨識出錯: {e}")
                
        return None

    def start(self):
        """Starts the bot loop in a background thread."""
        if self.is_running:
            return
        
        if cv2 is None:
            self.log("無法啟動：OpenCV 模組未安裝或載入失敗。")
            return
            
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.log("腳本已在背景啟動...")

    def stop(self):
        """Stops the bot loop."""
        if not self.is_running:
            return
        self.is_running = False
        # Safety release of keys
        try:
            direct_input.release_key(direct_input.KEY_W)
        except Exception:
            pass
        self.update_state("IDLE")
        self.log("腳本已停止運作。")

    def _run_loop(self):
        """Main execution loop."""
        # Wait for CV2 to load if needed
        while cv2 is None and self.is_running:
            time.sleep(1.0)
            
        if not self.is_running:
            return

        if self.mode == "CAR_MASTERY":
            self.log("正在啟動自動解鎖車輛熟練度模式...")
            self.update_state("MASTERY_START")
            
            while self.is_running:
                try:
                    if cv2 is None:
                        time.sleep(2.0)
                        continue
                        
                    if self.state == "MASTERY_START":
                        match = self.find_template_on_screen("my_cars_tile.png")
                        if match:
                            x, y, conf = match
                            self.log(f"偵測到【我的車輛】按鈕 (置信度: {conf:.2f})")
                            self.log("模擬滑鼠點擊「我的車輛」...")
                            direct_input.mouse_click(x, y, click_duration=0.15, settle_delay=0.15)
                            self.update_state("MASTERY_OPEN_MANUFACTURER")
                            time.sleep(2.5)
                        else:
                            if self.find_template_on_screen("lambo_brand.png"):
                                self.log("[INFO] [自動狀態修正]：已在車廠選單中，修正狀態至【選擇車廠】")
                                self.update_state("MASTERY_SELECT_MANUFACTURER")
                            elif self.find_template_on_screen("revuelto.png"):
                                self.log("[INFO] [自動狀態修正]：已在車輛選單中，修正狀態至【選擇車輛】")
                                self.update_state("MASTERY_SELECT_CAR")
                            else:
                                time.sleep(self.check_interval)
                                
                    elif self.state == "MASTERY_OPEN_MANUFACTURER":
                        self.log("已進入車庫，發送鍵盤 'Backspace' 開啟車廠選單...")
                        direct_input.press_and_release(direct_input.KEY_BACKSPACE, duration=0.5)
                        self.update_state("MASTERY_SELECT_MANUFACTURER")
                        time.sleep(1.5)
                        
                    elif self.state == "MASTERY_SELECT_MANUFACTURER":
                        match = self.find_template_on_screen("lambo_brand.png")
                        if match:
                            x, y, conf = match
                            self.log(f"偵測到【LAMBORGHINI】車廠標誌 (置信度: {conf:.2f})")
                            self.log("模擬滑鼠點擊進入車廠選單...")
                            direct_input.mouse_click(x, y, click_duration=0.15, settle_delay=0.15)
                            self.update_state("MASTERY_SELECT_CAR")
                            time.sleep(2.0)
                        else:
                            if self.find_template_on_screen("revuelto.png"):
                                self.log("[INFO] [自動狀態修正]：已在車輛選單中，修正狀態至【選擇車輛】")
                                self.update_state("MASTERY_SELECT_CAR")
                            else:
                                time.sleep(self.check_interval)
                                
                    elif self.state == "MASTERY_SELECT_CAR":
                        matches = self.find_all_templates_on_screen("revuelto.png")
                        if matches:
                            self.log(f"畫面中偵測到 {len(matches)} 輛 REVUELTO 車輛卡片")
                            if self.mastery_car_index < len(matches):
                                x, y, conf = matches[self.mastery_car_index]
                                self.log(f"滑鼠先移至第 {self.mastery_car_index + 1} 輛未使用過之車輛位置 (座標: {x}, {y})，等待 0.5 秒以觸發懸停狀態...")
                                direct_input.smooth_move_mouse(x, y, duration=0.3)
                                time.sleep(0.5)
                                self.log(f"模擬滑鼠點擊選中車輛 (置信度: {conf:.2f})...")
                                direct_input.mouse_click(x, y, click_duration=0.15, settle_delay=0.05)
                                # 等待選單位移與動畫完成，發送 Enter 開啟選單
                                time.sleep(1.0)
                                self.log("發送鍵盤 'Enter' 鍵以叫出乘駕選單...")
                                direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                                self.update_state("MASTERY_DRIVE_PROMPT")
                                time.sleep(1.5)
                            else:
                                self.log(f"所有畫面上偵測到的 {len(matches)} 輛車均已點過熟練度，腳本停止。")
                                self.stop()
                                break
                        else:
                            time.sleep(self.check_interval)
                            
                    elif self.state == "MASTERY_DRIVE_PROMPT":
                        # Attempt to find "選擇動作" via Windows Native OCR first
                        match = None
                        if HAS_WINSDK:
                            match = self.find_text_by_ocr_sync("選擇動作")
                            if match:
                                self.log("[INFO] [OCR 偵測] 成功辨識「選擇動作」字樣")
                                
                        if not match:
                            # Fallback to OpenCV template matching
                            match = self.find_template_on_screen("select_action.png")
                            if match:
                                self.log("[INFO] [模板比對] 成功偵測到【選擇動作】標題")
                                
                        if match:
                            x, y, conf = match
                            
                            # Calculate proportional offset from "選擇動作" title to "乘駕車輛" button
                            # ~6.2% of the client height
                            hwnd, rect = self.find_game_window()
                            offset_y = 67  # Default fallback (e.g. for 1080p, 1080 * 0.062 = ~67)
                            if rect:
                                height = rect[3] - rect[1]
                                offset_y = int(height * 0.062)
                                self.log(f"依據視窗高度 {height} 計算偏移量: {offset_y}px")
                            
                            click_x = x
                            click_y = y + offset_y
                            
                            self.log(f"滑鼠先移至乘駕車輛按鈕位置 (座標: {click_x}, {click_y})，等待 0.5 秒以觸發懸停狀態...")
                            direct_input.smooth_move_mouse(click_x, click_y, duration=0.3)
                            time.sleep(0.5)
                            
                            self.log("模擬滑鼠點擊「乘駕車輛」按鈕...")
                            direct_input.mouse_click(click_x, click_y, click_duration=0.15, settle_delay=0.15)
                            
                            self.update_state("MASTERY_ENTER_UPGRADES")
                            self.log("正在進入車庫並更換乘駕車輛，等待 8 秒過場...")
                            time.sleep(8.0)
                        else:
                            if self.find_template_on_screen("upgrades_tuning.png"):
                                self.log("[INFO] [自動狀態修正]：已越過乘駕車輛，直接進入升級選單")
                                self.update_state("MASTERY_ENTER_UPGRADES")
                            else:
                                time.sleep(self.check_interval)
                                
                    elif self.state == "MASTERY_ENTER_UPGRADES":
                        match = self.find_template_on_screen("upgrades_tuning.png")
                        if match:
                            x, y, conf = match
                            self.log(f"偵測到【升級套件與調校】入口 (置信度: {conf:.2f})")
                            self.log("模擬滑鼠點擊「升級套件與調校」...")
                            direct_input.mouse_click(x, y, click_duration=0.15, settle_delay=0.15)
                            self.update_state("MASTERY_ENTER_MASTERY")
                            time.sleep(2.0)
                        else:
                            if self.find_template_on_screen("car_mastery_button.png"):
                                self.log("[INFO] [自動狀態修正]：已越過升級套件，直接進入熟練度選單")
                                self.update_state("MASTERY_ENTER_MASTERY")
                            else:
                                time.sleep(self.check_interval)
                                
                    elif self.state == "MASTERY_ENTER_MASTERY":
                        match = self.find_template_on_screen("car_mastery_button.png")
                        if match:
                            x, y, conf = match
                            self.log(f"偵測到【車輛熟練度】入口 (置信度: {conf:.2f})")
                            self.log("模擬滑鼠點擊「車輛熟練度」...")
                            direct_input.mouse_click(x, y, click_duration=0.15, settle_delay=0.15)
                            self.update_state("MASTERY_UNLOCK_SKILLS")
                            time.sleep(2.5)
                        else:
                            time.sleep(self.check_interval)
                            
                    elif self.state == "MASTERY_UNLOCK_SKILLS":
                        if not self.mastery_grid_topleft or not self.mastery_grid_bottomright:
                            self.log("錯誤：缺少技能樹校準座標，無法點選技能！")
                            self.stop()
                            break
                            
                        # User path: (3, 0) -> (2, 0) -> (1, 0) -> (0, 0) -> (0, 1) -> (0, 2)
                        path = [(3, 0), (2, 0), (1, 0), (0, 0), (0, 1), (0, 2)]
                        
                        hwnd, rect = self.find_game_window()
                        if not rect:
                            self.log("錯誤：找不到遊戲視窗，無法定位技能點。")
                            self.stop()
                            break
                            
                        offset_x, offset_y = rect[0], rect[1]
                        x_tl, y_tl = self.mastery_grid_topleft
                        x_br, y_br = self.mastery_grid_bottomright
                        
                        step_x = (x_br - x_tl) / 3.0
                        step_y = (y_br - y_tl) / 3.0
                        
                        self.log("開始依序解鎖車輛熟練度技能點...")
                        for step_idx, (row, col) in enumerate(path):
                            if not self.is_running:
                                break
                            
                            rel_x = x_tl + col * step_x
                            rel_y = y_tl + row * step_y
                            abs_x = int(offset_x + rel_x)
                            abs_y = int(offset_y + rel_y)
                            
                            self.log(f"滑鼠先移至技能點 [{step_idx + 1}/6]：格點 (row={row}, col={col}) -> 螢幕座標 ({abs_x}, {abs_y})，等待 0.5 秒以觸發懸停狀態...")
                            direct_input.smooth_move_mouse(abs_x, abs_y, duration=0.3)
                            time.sleep(0.5)
                            
                            self.log("模擬滑鼠點擊解鎖技能點...")
                            direct_input.mouse_click(abs_x, abs_y, click_duration=0.15, settle_delay=0.1)
                            time.sleep(0.5)
                            
                            direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.4)
                            time.sleep(0.8)
                            
                        if not self.is_running:
                            break
                            
                        self.log("技能點擊完成！發送 'Esc' 返回升級調校畫面...")
                        direct_input.press_and_release(direct_input.KEY_ESC, duration=0.5)
                        time.sleep(1.5)
                        
                        self.log("發送 'Esc' 返回車庫大廳頁面...")
                        direct_input.press_and_release(direct_input.KEY_ESC, duration=0.5)
                        time.sleep(2.0)
                        
                        self.mastery_car_index += 1
                        self.save_config()
                        self.log(f"該車解鎖完成。切換至下一輛，目前索引：{self.mastery_car_index}")
                        
                        if self.mastery_car_index >= 12:
                            self.log("已成功處理完 12 輛車的車輛熟練度，自動重置已點處理車數為 0，腳本停止。")
                            self.mastery_car_index = 0
                            self.save_config()
                            self.stop()
                            break
                            
                        self.update_state("MASTERY_START")
                        time.sleep(1.0)
                        
                except Exception as e:
                    self.log(f"自動點選熟練度循環中發生異常錯誤: {e}")
                    time.sleep(2.0)
                    
            self.update_state("IDLE")
            return

        self.log("正在分析當前遊戲畫面，嘗試自動判定所處階段...")
        
        detected_state = "WAIT_FOR_SETTLEMENT"
        immediate_action = None
        try:
            # We check yes.png first as a confirmation prompt is distinct in the center
            yes_match = self.find_template_on_screen("yes.png")
            if yes_match:
                detected_state = "WAIT_FOR_CONFIRM"
                self.log("自動判定成功：目前處於【確認重新開始彈窗】")
                immediate_action = "YES"
            else:
                restart_match = self.find_template_on_screen("restart.png")
                if restart_match:
                    detected_state = "WAIT_FOR_SETTLEMENT"
                    self.log("自動判定成功：目前處於【結算畫面】")
                    immediate_action = "RESTART"
                else:
                    start_match = self.find_template_on_screen("start.png")
                    if start_match:
                        detected_state = "WAIT_FOR_START_EVENT"
                        self.log("自動判定成功：目前處於【賽事準備起跑畫面】")
                        immediate_action = "START"
                    else:
                        self.log("未偵測到已知特徵，預設進入【等待結算畫面】偵測狀態。")
        except Exception as e:
            self.log(f"自動判定階段發生異常: {e}，預設進入【等待結算畫面】")
            
        self.update_state(detected_state)
        
        # Execute immediate action if detected to make startup instant
        if self.is_running and immediate_action:
            if immediate_action == "YES":
                self.log("啟動瞬時響應：發送鍵盤 'Enter' 按鍵確認重新開始...")
                direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                self.update_state("WAIT_FOR_START_EVENT")
                time.sleep(3.0)
            elif immediate_action == "RESTART":
                self.log("啟動瞬時響應：發送鍵盤 'X' 按鍵進行重新開始...")
                direct_input.press_and_release(direct_input.KEY_X, duration=0.5)
                self.update_state("WAIT_FOR_CONFIRM")
                time.sleep(1.0)
            elif immediate_action == "START":
                self.log("啟動瞬時響應：發送鍵盤 'Enter' 按鍵開始賽事...")
                direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                self.update_state("RACING")
                
        while self.is_running:
            try:
                # 確保 OpenCV 已經載入
                if cv2 is None:
                    time.sleep(2.0)
                    continue

                if self.state == "WAIT_FOR_SETTLEMENT":
                    # 辨識畫面是否有「重新開始」按鈕 (restart.png)
                    match = self.find_template_on_screen("restart.png")
                    if match:
                        x, y, conf = match
                        self.log(f"偵測到【重新開始】按鈕 (置信度: {conf:.2f})")
                        self.log("發送鍵盤 'X' 按鍵進行重新開始...")
                        direct_input.press_and_release(direct_input.KEY_X, duration=0.5)
                        self.update_state("WAIT_FOR_CONFIRM")
                        time.sleep(1.0)
                    else:
                        # 備用語音/畫面狀態自適應修正：如果已經跳過此階段
                        if self.find_template_on_screen("yes.png"):
                            self.log("[INFO] [自動狀態修正]：等待結算時偵測到【是】確認按鈕，修正狀態至【確認選單】")
                            self.update_state("WAIT_FOR_CONFIRM")
                        elif self.find_template_on_screen("start.png"):
                            self.log("[INFO] [自動狀態修正]：等待結算時偵測到【開始賽事】按鈕，修正狀態至【起跑畫面】")
                            self.update_state("WAIT_FOR_START_EVENT")
                        else:
                            time.sleep(self.check_interval)

                elif self.state == "WAIT_FOR_CONFIRM":
                    # 辨識畫面中央是否有「是」按鈕 (yes.png)
                    match = self.find_template_on_screen("yes.png")
                    if match:
                        x, y, conf = match
                        self.log(f"偵測到【是】確認按鈕 (置信度: {conf:.2f})")
                        self.log("發送鍵盤 'Enter' 按鍵確認重新開始...")
                        direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                        self.update_state("WAIT_FOR_START_EVENT")
                        time.sleep(3.0)
                    else:
                        # 備用語音/畫面狀態自適應修正
                        if self.find_template_on_screen("start.png"):
                            self.log("[INFO] [自動狀態修正]：等待確認時偵測到【開始賽事】按鈕，修正狀態至【起跑畫面】")
                            self.update_state("WAIT_FOR_START_EVENT")
                        elif self.find_template_on_screen("restart.png"):
                            self.log("[INFO] [自動狀態修正]：等待確認時偵測到【重新開始】按鈕，修正狀態至【結算畫面】")
                            self.update_state("WAIT_FOR_SETTLEMENT")
                        else:
                            time.sleep(self.check_interval)

                elif self.state == "WAIT_FOR_START_EVENT":
                    # 辨識畫面是否有「開始賽事」按鈕 (start.png)
                    match = self.find_template_on_screen("start.png")
                    if match:
                        x, y, conf = match
                        self.log(f"偵測到【開始賽事】按鈕 (置信度: {conf:.2f})")
                        self.log("發送鍵盤 'Enter' 按鍵開始賽事...")
                        direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                        self.update_state("RACING")
                    else:
                        # 備用語音/畫面狀態自適應修正
                        if self.find_template_on_screen("restart.png"):
                            self.log("[INFO] [自動狀態修正]：等待起跑時偵測到【重新開始】按鈕，修正狀態至【結算畫面】")
                            self.update_state("WAIT_FOR_SETTLEMENT")
                        elif self.find_template_on_screen("yes.png"):
                            self.log("[INFO] [自動狀態修正]：等待起跑時偵測到【是】確認按鈕，修正狀態至【確認選單】")
                            self.update_state("WAIT_FOR_CONFIRM")
                        else:
                            time.sleep(self.check_interval)

                elif self.state == "RACING":
                    self.log("賽事已開始，自動按下 'W' 鍵加速前進...")
                    direct_input.press_key(direct_input.KEY_W)
                    
                    try:
                        self.log(f"開始賽事計時等待，共 {self.race_duration:.1f} 秒...")
                        start_time = time.time()
                        last_w_press_time = time.time()
                        
                        while time.time() - start_time < self.race_duration:
                            if not self.is_running:
                                break
                            
                            current_time = time.time()
                            
                            # 每 2.0 秒重送一次 W 鍵，確保遊戲在控制權移交或載入完成後能確實接收並維持 W 鍵訊號
                            if current_time - last_w_press_time >= 2.0:
                                last_w_press_time = current_time
                                direct_input.press_key(direct_input.KEY_W)
                            
                            time.sleep(0.1)
                    finally:
                        self.log("釋放 'W' 鍵...")
                        direct_input.release_key(direct_input.KEY_W)
                        
                    if not self.is_running:
                        return
                        
                    self.log("預定賽事等待時間已到，進入結算畫面偵測狀態。")
                    self.update_state("WAIT_FOR_SETTLEMENT")

            except Exception as e:
                self.log(f"執行循環中發生異常錯誤: {e}")
                time.sleep(2.0)
                
        self.update_state("IDLE")

# Test routine
if __name__ == "__main__":
    bot = ForzaBot()
    # Simple check of screen grab
    screenshot, offset = bot.capture_game_screen()
    print(f"Captured screen size: {screenshot.size}, Top-left offset: {offset}")
