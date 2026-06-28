import os
import time
import threading
import logging
import win32gui

try:
    import cv2
except ImportError:
    cv2 = None

# Import our modular packages
from src import inputs as direct_input
from src.config import load_config, save_config
from src.window_utils import find_game_window
from src.screen import capture_game_screen, find_template_on_screen, find_all_templates_on_screen
from src.ocr import OcrEngineManager, HAS_WINSDK

class ForzaBot:
    def __init__(self, templates_dir="templates"):
        self.templates_dir = templates_dir
        self.race_duration = 62.0  # seconds
        self.threshold = 0.8       # similarity threshold
        self.check_interval = 1.0  # check screen every X seconds
        self.game_window_title = "Forza Horizon" # Substring to find window
        self.selected_hwnd = None                # Explicit HWND from GUI
        
        self.mode = "RACE_FARM"    # RACE_FARM, CAR_MASTERY
        self.state = "IDLE"        # Current state
        self._is_running = False
        self.thread = None
        self.log_callback = print  # Can be replaced by GUI log function
        self.state_callback = None # Can be replaced by GUI state update function
        
        self.mastery_grid_topleft = None
        self.mastery_grid_bottomright = None
        self.mastery_car_index = 0
        self.upgrades_enter_start_time = 0
        
        # Ensure templates directory exists
        os.makedirs(self.templates_dir, exist_ok=True)
            
        self.load_bot_config()
        
        # Initialize OCR engine manager
        self.ocr_manager = OcrEngineManager(log_func=self.log)

    @property
    def is_running(self):
        curr = threading.current_thread()
        if curr.name == "ForzaBotThread":
            if curr == self.thread:
                return self._is_running
            return False
        return self._is_running

    @is_running.setter
    def is_running(self, value):
        self._is_running = value

    def load_bot_config(self):
        cfg = load_config(self.templates_dir)
        self.race_duration = cfg.get("race_duration", self.race_duration)
        self.threshold = cfg.get("threshold", self.threshold)
        self.game_window_title = cfg.get("game_window_title", self.game_window_title)
        self.mastery_grid_topleft = cfg.get("mastery_grid_topleft", self.mastery_grid_topleft)
        self.mastery_grid_bottomright = cfg.get("mastery_grid_bottomright", self.mastery_grid_bottomright)
        self.mastery_car_index = cfg.get("mastery_car_index", self.mastery_car_index)

    def save_bot_config(self):
        cfg = {
            "race_duration": self.race_duration,
            "threshold": self.threshold,
            "game_window_title": self.game_window_title,
            "mastery_grid_topleft": self.mastery_grid_topleft,
            "mastery_grid_bottomright": self.mastery_grid_bottomright,
            "mastery_car_index": self.mastery_car_index
        }
        save_config(cfg, self.templates_dir)

    def log(self, message):
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
        if new_state == "MASTERY_ENTER_UPGRADES":
            self.upgrades_enter_start_time = time.time()
        if self.state_callback:
            self.state_callback(new_state)

    def find_game_window(self):
        return find_game_window(self.selected_hwnd, self.game_window_title)

    def capture_game_screen(self):
        return capture_game_screen(self.selected_hwnd, self.game_window_title)

    def find_template_on_screen(self, template_filename, threshold=None, region=None):
        search_threshold = threshold if threshold is not None else self.threshold
        return find_template_on_screen(
            template_filename=template_filename,
            templates_dir=self.templates_dir,
            threshold=search_threshold,
            selected_hwnd=self.selected_hwnd,
            game_window_title=self.game_window_title,
            region=region,
            log_func=self.log
        )

    def find_all_templates_on_screen(self, template_filename, min_distance=30):
        return find_all_templates_on_screen(
            template_filename=template_filename,
            templates_dir=self.templates_dir,
            threshold=self.threshold,
            selected_hwnd=self.selected_hwnd,
            game_window_title=self.game_window_title,
            min_distance=min_distance,
            log_func=self.log
        )

    def find_text_by_ocr_sync(self, target_texts):
        return self.ocr_manager.find_text_by_ocr_sync(target_texts, self.selected_hwnd, self.game_window_title)

    def start(self):
        """Starts the bot loop in a background thread."""
        if self.is_running:
            return
        
        if cv2 is None:
            self.log("無法啟動：OpenCV 模組未安裝或載入失敗。")
            return
            
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, name="ForzaBotThread", daemon=True)
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
                            self.log(f"車輛選單中偵測到 {len(matches)} 輛 REVUELTO 車型")
                            
                            # Limit index to size of matches
                            target_idx = self.mastery_car_index
                            if target_idx >= len(matches):
                                self.log(f"目標車輛索引 {target_idx + 1} 超出當前頁面偵測數量，自動以最後一輛為目標。")
                                target_idx = len(matches) - 1
                                
                            x_car, y_car, conf_car = matches[target_idx]
                            self.log(f"定位目標車輛 [{self.mastery_car_index + 1}/{len(matches)}]：螢幕座標 ({x_car}, {y_car})")
                            
                            # Click car card
                            self.log("模擬滑鼠移動至車輛卡片...")
                            direct_input.smooth_move_mouse(x_car, y_car, duration=0.3)
                            time.sleep(0.5)
                            self.log("模擬滑鼠點擊選擇車輛...")
                            direct_input.mouse_click(x_car, y_car, click_duration=0.15, settle_delay=0.15)
                            time.sleep(1.0)
                            
                            if self.mastery_car_index > 0:
                                self.log("發送 'Enter' 鍵代替第二次點選...")
                                direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                            else:
                                self.log("第一台車輛無須按下 'Enter' 鍵，直接跳過第二次點選...")
                            self.update_state("MASTERY_DRIVE_PROMPT")
                            time.sleep(2.5)
                        else:
                            time.sleep(self.check_interval)
                            
                    elif self.state == "MASTERY_DRIVE_PROMPT":
                        # Detect "select_action" or "ride vehicle" dialog
                        # We use OCR to locate "選擇動作" or "SELECT ACTION"
                        has_ocr = self.ocr_manager.is_available()
                        match_action = None
                        if has_ocr:
                            match_action = self.find_text_by_ocr_sync(["選擇動作", "选择动作", "SELECT ACTION"])
                            
                        if match_action:
                            x_act, y_act, conf_act = match_action
                            self.log(f"OCR 成功定位【選擇動作】標題 (置信度: {conf_act:.2f})")
                            # Get the window rect and calculate the exact offset
                            hwnd, rect = self.find_game_window()
                            if rect:
                                # Offset y by 6.2% of window height down to click the "drive car" button
                                height = rect[3] - rect[1]
                                offset_y = int(height * 0.062)
                                x_drive = x_act
                                y_drive = y_act + offset_y
                                self.log(f"根據視窗比例計算「乘駕車輛」點擊位置：({x_drive}, {y_drive})")
                                direct_input.smooth_move_mouse(x_drive, y_drive, duration=0.3)
                                time.sleep(0.5)
                                direct_input.mouse_click(x_drive, y_drive, click_duration=0.15, settle_delay=0.15)
                            else:
                                self.log("錯誤: 無法取得視窗大小，無法計算相對點擊點。")
                        else:
                            # Fallback to template matching of select_action.png
                            match_temp = self.find_template_on_screen("select_action.png")
                            if match_temp:
                                x_act, y_act, conf_act = match_temp
                                self.log(f"比對到【選擇動作】標題模板 (置信度: {conf_act:.2f})")
                                x_drive = x_act
                                y_drive = y_act + 40
                                self.log(f"點擊下方「乘駕車輛」位置：({x_drive}, {y_drive})")
                                direct_input.smooth_move_mouse(x_drive, y_drive, duration=0.3)
                                time.sleep(0.5)
                                direct_input.mouse_click(x_drive, y_drive, click_duration=0.15, settle_delay=0.15)
                            else:
                                time.sleep(self.check_interval)
                                continue
                                
                        # Wait for transition animation
                        self.log("選擇乘駕車輛，等待約 9 秒過場與載入動畫...")
                        time.sleep(9.0)
                        
                        # Adaptive check to ensure screen has loaded
                        self.log("正在檢查畫面載入狀態...")
                        for _ in range(10): # Max wait 5 seconds (10 * 0.5s)
                            if not self.is_running:
                                break
                            if self.find_template_on_screen("revuelto.png") or self.find_template_on_screen("upgrades_tuning.png"):
                                break
                            time.sleep(0.5)
                            
                        if self.find_template_on_screen("upgrades_tuning.png"):
                            self.log("已進入車庫首頁。")
                        else:
                            self.log("發送 'Esc' 返回車庫首頁...")
                            direct_input.press_and_release(direct_input.KEY_ESC, duration=0.5)
                            time.sleep(1.5)
                            
                        self.update_state("MASTERY_ENTER_UPGRADES")
                        time.sleep(1.0)
                            
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
                                elapsed = time.time() - self.upgrades_enter_start_time
                                if elapsed > 10.0 and HAS_WINSDK:
                                    self.log(f"[RECOVERY] 進入【升級套件與調校】超時 ({elapsed:.1f} 秒)，執行卡死恢復程式...")
                                    
                                    # 1. 按下 esc 打開玩家介面
                                    self.log("[RECOVERY] 步驟 1/5：發送 'Esc' 鍵打開選單...")
                                    direct_input.press_and_release(direct_input.KEY_ESC, duration=0.5)
                                    time.sleep(2.0)
                                    
                                    # 2. 滑鼠點擊「我的 HORIZON」按鈕
                                    self.log("[RECOVERY] 步驟 2/5：尋找『我的 HORIZON』分頁並點擊...")
                                    match_hz = self.find_text_by_ocr_sync(["我的 HORIZON", "我的HORIZON", "MY HORIZON", "HORIZON", "HORZ", "HOR z", "我的 HOR", "我的HOR", "horizon", "horz"])
                                    if match_hz:
                                        x_hz, y_hz, conf_hz = match_hz
                                        self.log(f"[RECOVERY] 尋找到『我的 HORIZON』(座標: {x_hz}, {y_hz})，進行平滑點擊...")
                                        direct_input.smooth_move_mouse(x_hz, y_hz, duration=0.3)
                                        time.sleep(0.5)
                                        direct_input.mouse_click(x_hz, y_hz, click_duration=0.15, settle_delay=0.15)
                                        time.sleep(2.0)
                                    else:
                                        self.log("[RECOVERY] 警告：未找到『我的 HORIZON』分頁，使用預設比例位置 (0.458, 0.237) 進行點擊...")
                                        screenshot, offset = self.capture_game_screen()
                                        fallback_x = offset[0] + int(screenshot.size[0] * 0.458)
                                        fallback_y = offset[1] + int(screenshot.size[1] * 0.237)
                                        direct_input.smooth_move_mouse(fallback_x, fallback_y, duration=0.3)
                                        time.sleep(0.5)
                                        direct_input.mouse_click(fallback_x, fallback_y, click_duration=0.15, settle_delay=0.15)
                                        time.sleep(2.0)
                                        
                                    # 3. 按下「返回住所」的按鈕
                                    self.log("[RECOVERY] 步驟 3/5：尋找『返回住所』按鈕並點擊...")
                                    match_home = self.find_text_by_ocr_sync(["返回住所", "返回", "住所", "GO TO HOME"])
                                    if match_home:
                                        x_hm, y_hm, conf_hm = match_home
                                        self.log(f"[RECOVERY] 尋找到『返回住所』(座標: {x_hm}, {y_hm})，進行平滑點擊...")
                                        direct_input.smooth_move_mouse(x_hm, y_hm, duration=0.3)
                                        time.sleep(0.5)
                                        direct_input.mouse_click(x_hm, y_hm, click_duration=0.15, settle_delay=0.15)
                                        time.sleep(2.0)
                                    else:
                                        self.log("[RECOVERY] 警告：未找到『返回住所』按鈕。")
                                        
                                    # 4. 遊戲詢問是否快速移動到房屋，鍵盤按下 enter 確認
                                    self.log("[RECOVERY] 步驟 4/5：發送 'Enter' 鍵確認快速移動到房屋...")
                                    direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                                    self.log("[RECOVERY] 正在傳送至房屋，等待 9 秒載入...")
                                    time.sleep(9.0)
                                    
                                    # 5. 到了房屋後點擊「車輛」按鈕
                                    self.log("[RECOVERY] 步驟 5/5：尋找頂部『車輛』分頁並點擊...")
                                    while self.is_running:
                                        match_cars = self.find_text_by_ocr_sync(["車輛", "车辆", "CARS"])
                                        if match_cars:
                                            x_cs, y_cs, conf_cs = match_cars
                                            self.log(f"[RECOVERY] 尋找到『車輛』分頁 (座標: {x_cs}, {y_cs})，進行平滑點擊...")
                                            direct_input.smooth_move_mouse(x_cs, y_cs, duration=0.3)
                                            time.sleep(0.5)
                                            direct_input.mouse_click(x_cs, y_cs, click_duration=0.15, settle_delay=0.15)
                                            time.sleep(2.0)
                                            break
                                        else:
                                            self.log("[RECOVERY] 警告：未找到『車輛』分頁按鈕，1秒後重試...")
                                            time.sleep(1.0)
                                        
                                    # 重設計時器
                                    self.upgrades_enter_start_time = time.time()
                                else:
                                    time.sleep(self.check_interval)
                                
                    elif self.state == "MASTERY_ENTER_MASTERY":
                        match = self.find_template_on_screen("car_mastery_button.png")
                        if match:
                            x, y, conf = match
                            self.log(f"偵測到【車輛熟練度】按鈕 (置信度: {conf:.2f})")
                            self.log("模擬滑鼠點擊「車輛熟練度」...")
                            direct_input.mouse_click(x, y, click_duration=0.15, settle_delay=0.15)
                            self.update_state("MASTERY_UNLOCK_SKILLS")
                            time.sleep(2.0)
                        else:
                            time.sleep(self.check_interval)
                            
                    elif self.state == "MASTERY_UNLOCK_SKILLS":
                        self.log("已進入車輛熟練度，偵測可用技能點數...")
                        
                        available_points = None
                        if self.ocr_manager.is_available():
                            for attempt in range(3):
                                if not self.is_running:
                                    break
                                pts = self.ocr_manager.detect_available_points_sync(
                                    self.selected_hwnd, 
                                    self.game_window_title
                                )
                                if pts is not None:
                                    available_points = pts
                                    break
                                self.log(f"未能辨識到可用點數，將於 1 秒後重試第 {attempt + 1}/3 次...")
                                time.sleep(1.0)
                                
                        if available_points is not None:
                            self.log(f"偵測到可用技能點數：{available_points}")
                            if available_points < 39:
                                self.log(f"錯誤：可用點數不足！剩餘 {available_points} 點，不足點滿一台車所需的 39 點。安全停止腳本。")
                                self.stop()
                                break
                        else:
                            self.log("警告：無法辨識可用技能點數，預設繼續解鎖...")
                            
                        self.log("開始依序解鎖 4x4 技能樹...")
                        
                        # Get game window position to convert relative coordinates to absolute screen coordinates
                        hwnd, rect = self.find_game_window()
                        offset_x = 0
                        offset_y = 0
                        if rect:
                            left, top, right, bottom = rect
                            offset_x = max(0, left)
                            offset_y = max(0, top)
                        
                        # 6-step path coordinates based on custom grid top-left and bottom-right calibration
                        x0, y0 = self.mastery_grid_topleft
                        x3, y3 = self.mastery_grid_bottomright
                        
                        # Interpolate other coordinates
                        dx = (x3 - x0) / 3.0
                        dy = (y3 - y0) / 3.0
                        
                        grid_points = {}
                        for r in range(4):
                            for c in range(4):
                                grid_points[(r, c)] = (
                                    int(offset_x + x0 + c * dx), 
                                    int(offset_y + y0 + r * dy)
                                )
                                
                        # 6-step optimal path (row, col)
                        unlock_path = [
                            (3, 0),  # Step 1: 最左下
                            (2, 0),  # Step 2: 左側第二個
                            (1, 0),  # Step 3: 左側第三個
                            (0, 0),  # Step 4: 最左上
                            (0, 1),  # Step 5: 頂部第二個
                            (0, 2)   # Step 6: 頂部第三個
                        ]
                        
                        for step_idx, (row, col) in enumerate(unlock_path):
                            if not self.is_running:
                                break
                                
                            abs_x, abs_y = grid_points[(row, col)]
                            
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
                        self.save_bot_config()
                        self.log(f"該車解鎖完成。切換至下一輛，目前索引：{self.mastery_car_index}")
                        
                        if self.mastery_car_index >= 12:
                            self.log("已成功處理完 12 輛車的車輛熟練度，自動重置已點處理車數為 0，腳本停止。")
                            self.mastery_car_index = 0
                            self.save_bot_config()
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
                if cv2 is None:
                    time.sleep(2.0)
                    continue

                if self.state == "WAIT_FOR_SETTLEMENT":
                    match = self.find_template_on_screen("restart.png")
                    if match:
                        x, y, conf = match
                        self.log(f"偵測到【重新開始】按鈕 (置信度: {conf:.2f})")
                        self.log("發送鍵盤 'X' 按鍵進行重新開始...")
                        direct_input.press_and_release(direct_input.KEY_X, duration=0.5)
                        self.update_state("WAIT_FOR_CONFIRM")
                        time.sleep(1.0)
                    else:
                        if self.find_template_on_screen("yes.png"):
                            self.log("[INFO] [自動狀態修正]：等待結算時偵測到【是】確認按鈕，修正狀態至【確認選單】")
                            self.update_state("WAIT_FOR_CONFIRM")
                        elif self.find_template_on_screen("start.png"):
                            self.log("[INFO] [自動狀態修正]：等待結算時偵測到【開始賽事】按鈕，修正狀態至【起跑畫面】")
                            self.update_state("WAIT_FOR_START_EVENT")
                        else:
                            time.sleep(self.check_interval)

                elif self.state == "WAIT_FOR_CONFIRM":
                    match = self.find_template_on_screen("yes.png")
                    if match:
                        x, y, conf = match
                        self.log(f"偵測到【是】確認按鈕 (置信度: {conf:.2f})")
                        self.log("發送鍵盤 'Enter' 按鍵確認重新開始...")
                        direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                        self.update_state("WAIT_FOR_START_EVENT")
                        time.sleep(3.0)
                    else:
                        if self.find_template_on_screen("start.png"):
                            self.log("[INFO] [自動狀態修正]：等待確認時偵測到【開始賽事】按鈕，修正狀態至【起跑畫面】")
                            self.update_state("WAIT_FOR_START_EVENT")
                        elif self.find_template_on_screen("restart.png"):
                            self.log("[INFO] [自動狀態修正]：等待確認時偵測到【重新開始】按鈕，修正狀態至【結算畫面】")
                            self.update_state("WAIT_FOR_SETTLEMENT")
                        else:
                            time.sleep(self.check_interval)

                elif self.state == "WAIT_FOR_START_EVENT":
                    match = self.find_template_on_screen("start.png")
                    if match:
                        x, y, conf = match
                        self.log(f"偵測到【開始賽事】按鈕 (置信度: {conf:.2f})")
                        self.log("發送鍵盤 'Enter' 按鍵開始賽事...")
                        direct_input.press_and_release(direct_input.KEY_ENTER, duration=0.5)
                        self.update_state("RACING")
                    else:
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
