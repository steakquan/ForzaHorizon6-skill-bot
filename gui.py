import os
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageGrab
import threading
import ctypes
from ctypes import wintypes
import win32con
import win32gui

# Import modules from our project
import direct_input
from bot import ForzaBot, HAS_WINSDK

# Try to import cv2
try:
    import cv2
except ImportError:
    cv2 = None

# Global WinAPI details for Hotkeys
user32 = ctypes.windll.user32
HOTKEY_START_ID = 100
HOTKEY_STOP_ID = 101
VK_F10 = 0x79  # F10 key
VK_F11 = 0x7A  # F11 key

FONT_FAMILY = "Microsoft JhengHei"

LOG_TOKEN_PATTERN = re.compile(
    r"("
    r"\[[^\]]+\]|"
    r"【[^】]+】|"
    r"[🔍💡]|"
    r"\b[a-zA-Z0-9_\-]+\.png\b|"
    r"\b[A-Z_]{4,30}\b|"
    r"'[^']+'|"
    r"\b\d+(?:\.\d+)?\b|"
    r"偵測到|比對成功|置信度|成功|"
    r"錯誤|失敗|異常|error|fail|"
    r"警告|warning|"
    r"模擬滑鼠點擊|滑鼠點選|發送鍵盤|自動按下|按鍵|點擊|按下|釋放|鍵盤|滑鼠|點選|更換"
    r")"
)

def get_tag_for_token(token):
    if token in ("💡", "🔍"):
        return "badge"
    if token.startswith('[') and token.endswith(']'):
        content = token[1:-1]
        if '/' in content and all(c.isdigit() or c == '/' for c in content):
            return "number"
        return "badge"
    if token.startswith('【') and token.endswith('】'):
        return "bracket"
    if token.endswith('.png'):
        return "template"
    if token.startswith("'") and token.endswith("'"):
        return "key"
    if token[0].isdigit():
        return "number"
    if token.isupper() and len(token) >= 4:
        return "state"
    if token in ("偵測到", "比對成功", "置信度", "成功"):
        return "detect"
    if token in ("錯誤", "失敗", "異常", "error", "fail"):
        return "error"
    if token in ("警告", "warning"):
        return "warn"
    if token in ("模擬滑鼠點擊", "滑鼠點選", "發送鍵盤", "自動按下", "按鍵", "點擊", "按下", "釋放", "鍵盤", "滑鼠", "點選", "更換"):
        return "action"
    return "info"


class BotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Forza Horizon 6 刷技能點小助手")
        self.root.geometry("640x580")
        self.root.configure(bg="#1a1a22")
        self.root.resizable(True, True)
        self.root.minsize(640, 580)
        
        # Initialize the bot
        self.bot = ForzaBot()
        self.bot.log_callback = self.log_message
        self.bot.state_callback = self.on_state_change
        
        # Keep references to thumbnail images to prevent garbage collection
        self.thumbnails = {}
        
        # Track visible windows
        self.windows_map = {}
        
        # Track auto stop timer
        self.auto_stop_target_time = None
        
        # Thread safety control for hotkeys
        self.hotkey_stop_event = threading.Event()
        self.hotkey_thread = None
        
        # Custom styling
        self.setup_styles()
        # Build UI layout
        self.build_ui()
        # Start hotkey listener
        self.start_hotkey_listener()
        
        # Periodically refresh bot status in GUI
        self.refresh_timer()
        
        # Log init status
        self.log_message("系統初始化完成。")
        self.check_opencv_status()
        self.update_all_thumbnails()
        self.refresh_windows_list()

    def check_opencv_status(self):
        global cv2
        try:
            import cv2
            self.bot.log("OpenCV 載入成功！圖像比對功能已啟用。")
        except ImportError:
            self.log_message("警告: OpenCV (cv2) 尚未成功安裝。圖像辨識將無法運作！")
            self.log_message("正在等候背景安裝程序完成...")

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        
        # Configure frames and layouts
        style.configure("TFrame", background="#1a1a22")
        style.configure("Card.TFrame", background="#252533", relief="flat")
        
        # Notebook styling
        style.configure("TNotebook", background="#1a1a22", borderwidth=0)
        style.configure("TNotebook.Tab", background="#252533", foreground="#a0a0b0", font=(FONT_FAMILY, 10, "bold"), padding=[18, 6])
        style.map("TNotebook.Tab",
                  background=[("selected", "#00e5ff"), ("active", "#2e2e3d")],
                  foreground=[("selected", "#1a1a22"), ("active", "#ffffff")])
        
        # Scrollbar styling
        style.configure("Vertical.TScrollbar", background="#2a2a38", troughcolor="#15151d", bordercolor="#1a1a22", arrowcolor="#ffffff")

    def build_ui(self):
        # Header (Minimalist title + indicator)
        header_frame = tk.Frame(self.root, bg="#111116", height=50)
        header_frame.pack(fill="x", side="top")
        
        title_label = tk.Label(header_frame, text="FORZA HORIZON 6 SKILL BOT", font=(FONT_FAMILY, 14, "bold"), fg="#00e5ff", bg="#111116")
        title_label.pack(side="left", padx=15, pady=10)
        
        # Status indicator dot
        self.status_dot = tk.Canvas(header_frame, width=12, height=12, bg="#111116", highlightthickness=0)
        self.status_dot.pack(side="right", padx=(0, 15), pady=18)
        self.draw_status_dot("#ef4444") # Red for stopped
        
        self.status_text = tk.Label(header_frame, text="已停止 (IDLE)", font=(FONT_FAMILY, 9, "bold"), fg="#ef4444", bg="#111116")
        self.status_text.pack(side="right", padx=8, pady=15)
        
        # Main Tab Container
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=12)
        
        # Create Tab Frames
        self.tab_dash = ttk.Frame(self.notebook, style="TFrame")
        self.tab_settings = ttk.Frame(self.notebook, style="TFrame")
        self.tab_calib = ttk.Frame(self.notebook, style="TFrame")
        
        self.notebook.add(self.tab_dash, text=" 運行儀表板 ")
        self.notebook.add(self.tab_settings, text=" 參數設定 ")
        self.notebook.add(self.tab_calib, text=" 圖像校準 ")
        
        # Build contents for each tab
        self.build_dash_tab()
        self.build_settings_tab()
        self.build_calib_tab()

    def build_dash_tab(self):
        # 1. State card
        state_card = ttk.Frame(self.tab_dash, style="Card.TFrame")
        state_card.pack(fill="x", padx=10, pady=(10, 5))
        
        state_title = tk.Label(state_card, text="當前執行狀態", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533")
        state_title.pack(anchor="w", padx=15, pady=(8, 2))
        
        self.state_desc = tk.Label(state_card, text="未啟動 - 請按 F10 鍵或點擊下方啟動按鈕", font=(FONT_FAMILY, 12, "bold"), fg="#ffffff", bg="#252533")
        self.state_desc.pack(anchor="w", padx=15, pady=(0, 8))
        
        # Mode Selection Card
        mode_card = ttk.Frame(self.tab_dash, style="Card.TFrame")
        mode_card.pack(fill="x", padx=10, pady=(5, 5))
        
        mode_title = tk.Label(mode_card, text="選擇掛機模式項目", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533")
        mode_title.pack(anchor="w", padx=15, pady=(6, 2))
        
        radio_frame = tk.Frame(mode_card, bg="#252533")
        radio_frame.pack(anchor="w", padx=15, pady=(0, 8))
        
        self.bot_mode_var = tk.StringVar(value="RACE_FARM")
        
        self.rad_race = tk.Radiobutton(radio_frame, text="自動刷賽事", variable=self.bot_mode_var, value="RACE_FARM", fg="#ffffff", bg="#252533", selectcolor="#15151c", activebackground="#252533", activeforeground="#ffffff", font=(FONT_FAMILY, 9), command=self.on_mode_changed)
        self.rad_race.pack(side="left", padx=(0, 15))
        
        self.rad_mastery = tk.Radiobutton(radio_frame, text="自動點熟練度", variable=self.bot_mode_var, value="CAR_MASTERY", fg="#ffffff", bg="#252533", selectcolor="#15151c", activebackground="#252533", activeforeground="#ffffff", font=(FONT_FAMILY, 9), command=self.on_mode_changed)
        self.rad_mastery.pack(side="left")
        
        # 2. Control Buttons
        btn_frame = tk.Frame(self.tab_dash, bg="#1a1a22")
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        self.btn_start = tk.Button(btn_frame, text="啟動腳本 (F10)", font=(FONT_FAMILY, 10, "bold"), bg="#10b981", fg="#ffffff", activebackground="#059669", activeforeground="#ffffff", relief="flat", padx=15, pady=6, command=self.start_bot)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.btn_stop = tk.Button(btn_frame, text="停止腳本 (F11)", font=(FONT_FAMILY, 10, "bold"), bg="#ef4444", fg="#ffffff", activebackground="#dc2626", activeforeground="#ffffff", relief="flat", padx=15, pady=6, command=self.stop_bot)
        self.btn_stop.pack(side="right", fill="x", expand=True, padx=(5, 0))
        
        # 3. Terminal Log
        log_frame = ttk.Frame(self.tab_dash, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        
        log_title = tk.Label(log_frame, text="實時運行日誌", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533")
        log_title.pack(anchor="w", padx=15, pady=(6, 4))
        
        log_container = tk.Frame(log_frame, bg="#15151c")
        log_container.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        self.log_text = tk.Text(log_container, bg="#15151c", fg="#e2e8f0", insertbackground="#ffffff", relief="flat", font=("Consolas", 9), wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(log_container, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # Setup Verilog-like log coloring tags
        self.log_text.tag_config("time", foreground="#5f7181")        # Cool steel gray for timestamp
        self.log_text.tag_config("state", foreground="#00e5ff", font=("Consolas", 9, "bold"))  # Bright Cyan for state changes
        self.log_text.tag_config("detect", foreground="#10b981")      # Emerald Green for template detection
        self.log_text.tag_config("action", foreground="#fbbf24")      # Amber Yellow for keyboard/mouse emulation
        self.log_text.tag_config("warn", foreground="#f97316", font=("Consolas", 9, "bold"))   # Orange for warnings
        self.log_text.tag_config("error", foreground="#ef4444", font=("Consolas", 9, "bold"))  # Bright Red for errors
        self.log_text.tag_config("info", foreground="#94a3b8")        # Slate Gray for general text
        self.log_text.tag_config("number", foreground="#ec4899")      # Bright Pink/Magenta for numbers
        self.log_text.tag_config("key", foreground="#a855f7", font=("Consolas", 9, "bold"))     # Purple for keys
        self.log_text.tag_config("template", foreground="#34d399")   # Mint Green for filenames
        self.log_text.tag_config("badge", foreground="#3b82f6", font=("Consolas", 9, "bold"))  # Blue bold for brackets/badges
        self.log_text.tag_config("bracket", foreground="#22d3ee", font=("Consolas", 9, "bold")) # Cyan/teal bold for UI names

    def build_settings_tab(self):
        settings_card = ttk.Frame(self.tab_settings, style="Card.TFrame")
        settings_card.pack(fill="both", expand=True, padx=10, pady=10)
        
        settings_title = tk.Label(settings_card, text="自動化參數配置", font=(FONT_FAMILY, 11, "bold"), fg="#00e5ff", bg="#252533")
        settings_title.pack(anchor="w", padx=15, pady=(12, 10))
        
        grid_frame = tk.Frame(settings_card, bg="#252533")
        grid_frame.pack(fill="both", expand=True, padx=15, pady=5)
        
        # Row 0: Window selection
        tk.Label(grid_frame, text="選擇遊戲視窗:", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533", anchor="w").grid(row=0, column=0, sticky="w", pady=8)
        
        win_select_frame = tk.Frame(grid_frame, bg="#252533")
        win_select_frame.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=8)
        
        self.combo_windows = ttk.Combobox(win_select_frame, width=24, state="readonly", font=(FONT_FAMILY, 9))
        self.combo_windows.pack(side="left")
        self.combo_windows.bind("<<ComboboxSelected>>", self.on_window_selected)
        
        self.btn_refresh_windows = tk.Button(win_select_frame, text="🔄 重新整理", font=(FONT_FAMILY, 8), bg="#4b5563", fg="#ffffff", activebackground="#374151", relief="flat", padx=6, pady=1, command=self.refresh_windows_list)
        self.btn_refresh_windows.pack(side="left", padx=(6, 0))
        
        self.is_topmost_var = tk.BooleanVar(value=False)
        self.chk_topmost = tk.Checkbutton(grid_frame, text="視窗強制置頂", variable=self.is_topmost_var, fg="#a0a0b0", bg="#252533", selectcolor="#15151c", activebackground="#252533", activeforeground="#a0a0b0", font=(FONT_FAMILY, 9), command=self.toggle_topmost)
        self.chk_topmost.grid(row=0, column=2, sticky="w", padx=(15, 0), pady=8)
        
        # Row 1: Duration & Background Mode
        tk.Label(grid_frame, text="單局賽事秒數:", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533", anchor="w").grid(row=1, column=0, sticky="w", pady=8)
        self.entry_duration = tk.Entry(grid_frame, bg="#15151c", fg="#ffffff", insertbackground="#ffffff", relief="flat", width=12, font=(FONT_FAMILY, 9))
        self.entry_duration.insert(0, str(int(self.bot.race_duration)))
        self.entry_duration.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=8)
        
        self.btn_bg_guide = tk.Button(grid_frame, text="❓ 背景掛機指引 (推薦 DisplayFusion)", font=(FONT_FAMILY, 9), bg="#4b5563", fg="#ffffff", activebackground="#374151", activeforeground="#ffffff", relief="flat", padx=8, pady=2, command=self.show_deactivate_help)
        self.btn_bg_guide.grid(row=1, column=2, sticky="w", padx=(15, 0), pady=8)
        
        # Row 2: Threshold
        tk.Label(grid_frame, text="辨識相似門檻:", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533", anchor="w").grid(row=2, column=0, sticky="w", pady=8)
        self.entry_threshold = tk.Entry(grid_frame, bg="#15151c", fg="#ffffff", insertbackground="#ffffff", relief="flat", width=12, font=(FONT_FAMILY, 9))
        self.entry_threshold.insert(0, str(self.bot.threshold))
        self.entry_threshold.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=8)
        
        self.btn_help_threshold = tk.Button(grid_frame, text="❓", font=(FONT_FAMILY, 8), bg="#3b82f6", fg="#ffffff", activebackground="#2563eb", activeforeground="#ffffff", relief="flat", padx=4, pady=1, command=self.show_threshold_help)
        self.btn_help_threshold.grid(row=2, column=2, sticky="w", padx=(15, 0), pady=8)
        
        # Row 3: Auto stop timer
        tk.Label(grid_frame, text="自動停止定時:", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533", anchor="w").grid(row=3, column=0, sticky="w", pady=8)
        self.combo_timer = ttk.Combobox(grid_frame, width=10, state="readonly", values=["不限時", "1 小時", "1.5 小時", "2 小時", "3 小時"], font=(FONT_FAMILY, 9))
        self.combo_timer.set("不限時")
        self.combo_timer.grid(row=3, column=1, sticky="w", padx=(10, 0), pady=8)
        
        self.lbl_countdown = tk.Label(grid_frame, text="", fg="#ff007f", bg="#252533", font=(FONT_FAMILY, 9, "bold"))
        self.lbl_countdown.grid(row=3, column=2, sticky="w", padx=(15, 0), pady=8)
        
        # Row 4: Mastery car index
        tk.Label(grid_frame, text="熟練度已處理車數:", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533", anchor="w").grid(row=4, column=0, sticky="w", pady=8)
        
        self.entry_mastery_index = tk.Spinbox(grid_frame, from_=0, to=999, width=10, bg="#15151c", fg="#ffffff", insertbackground="#ffffff", relief="flat", font=(FONT_FAMILY, 9))
        self.entry_mastery_index.delete(0, "end")
        self.entry_mastery_index.insert(0, str(self.bot.mastery_car_index))
        self.entry_mastery_index.grid(row=4, column=1, sticky="w", padx=(10, 0), pady=8)
        
        self.btn_reset_mastery_index = tk.Button(grid_frame, text="🗑️ 重置為 0", font=(FONT_FAMILY, 8), bg="#ef4444", fg="#ffffff", activebackground="#dc2626", activeforeground="#ffffff", relief="flat", padx=8, pady=1, command=self.reset_mastery_index)
        self.btn_reset_mastery_index.grid(row=4, column=2, sticky="w", padx=(15, 0), pady=8)
        
        # Save Button
        self.btn_save_settings = tk.Button(grid_frame, text="儲存並套用設定", font=(FONT_FAMILY, 9, "bold"), bg="#3b82f6", fg="#ffffff", activebackground="#2563eb", activeforeground="#ffffff", relief="flat", padx=15, pady=4, command=self.save_settings)
        self.btn_save_settings.grid(row=5, column=1, sticky="e", pady=(20, 0))

    def build_calib_tab(self):
        # Create a scrollable container for templates
        canvas = tk.Canvas(self.tab_calib, bg="#1a1a22", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_calib, orient="vertical", command=canvas.yview)
        
        template_card = ttk.Frame(canvas, style="Card.TFrame")
        
        # Configure scrollbar and canvas binding
        canvas_window = canvas.create_window((0, 0), window=template_card, anchor="nw")
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            
        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            
        canvas.bind("<Configure>", on_canvas_configure)
        template_card.bind("<Configure>", on_frame_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Enable mousewheel scrolling on Calib tab canvas
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", lambda e: _on_mousewheel(e) if self.notebook.select() == self.notebook.tabs()[2] else None)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        temp_title = tk.Label(template_card, text="圖像匹配模板校準與設定", font=(FONT_FAMILY, 11, "bold"), fg="#00e5ff", bg="#252533")
        temp_title.pack(anchor="w", padx=15, pady=(12, 5))
        
        inst_text = tk.Label(template_card, text="如果辨識不準，請在遊戲執行至對應畫面時點擊「擷取」，然後在跳出的截圖中框選目標文字區域。", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533", justify="left", wraplength=500)
        inst_text.pack(anchor="w", padx=15, pady=(0, 10))
        
        self.temp_items = [
            ("restart.png", "重新開始字樣", "等待結算畫面出現此字樣以重新開始"),
            ("yes.png", "確認選單「是」", "確認重新開始對話框的「是」按鈕（偵測後模擬 Enter）"),
            ("start.png", "開始賽事字樣", "即將開始賽事時，按下 Enter 的字樣"),
            ("lambo_brand.png", "蘭博基尼商標", "車廠選單中的「LAMBORGHINI」廠牌圖示"),
            ("revuelto.png", "Revuelto卡片", "車輛選單中的「REVUELTO」車型卡片按鈕"),
            ("my_cars_tile.png", "「我的車輛」入口", "車庫首頁進入我的車輛的按鈕區域（辨識後按 Enter 進入）"),
            ("select_action.png", "選擇動作標題", "選中車輛後跳出的「選擇動作」對話框標題（以此為基準點擊下方的乘駕車輛）"),
            ("upgrades_tuning.png", "「升級套件與調校」", "車庫主選單的「升級套件與調校」按鈕（辨識後滑鼠點擊）"),
            ("car_mastery_button.png", "「車輛熟練度」入口", "升級選單中的「車輛熟練度」按鈕（辨識後滑鼠點擊）")
        ]
        
        self.temp_frames = {}
        for filename, title, desc in self.temp_items:
            item_frame = tk.Frame(template_card, bg="#1e1e28", bd=1, relief="solid", highlightthickness=0)
            item_frame.pack(fill="x", padx=15, pady=5)
            
            # Title
            lbl_title = tk.Label(item_frame, text=title, font=(FONT_FAMILY, 9, "bold"), fg="#ffffff", bg="#1e1e28")
            lbl_title.pack(anchor="w", padx=8, pady=(4, 0))
            
            # Subframe for contents
            detail_frame = tk.Frame(item_frame, bg="#1e1e28")
            detail_frame.pack(fill="x", padx=8, pady=4)
            
            # Thumbnail
            thumb_canvas = tk.Canvas(detail_frame, width=50, height=35, bg="#15151c", highlightthickness=1, highlightbackground="#3e3e4f")
            thumb_canvas.pack(side="left", padx=(0, 10))
            
            # Text information & button
            info_btn_frame = tk.Frame(detail_frame, bg="#1e1e28")
            info_btn_frame.pack(side="left", fill="both", expand=True)
            
            lbl_desc = tk.Label(info_btn_frame, text=desc, font=(FONT_FAMILY, 8), fg="#808090", bg="#1e1e28", justify="left")
            lbl_desc.pack(anchor="w", pady=(0, 2))
            
            btn_cap = tk.Button(info_btn_frame, text=" 重新擷取模板 ", font=(FONT_FAMILY, 8), bg="#00e5ff", fg="#1a1a22", activebackground="#00b8cc", activeforeground="#1a1a22", relief="flat", padx=8, pady=1, command=lambda fn=filename: self.capture_template(fn))
            btn_cap.pack(anchor="w")
            
            self.temp_frames[filename] = {
                "canvas": thumb_canvas,
                "label": lbl_title
            }
            
        # Divider line
        div = tk.Frame(template_card, height=1, bg="#3e3e4f")
        div.pack(fill="x", padx=15, pady=15)
        
        grid_calib_title = tk.Label(template_card, text="4x4 技能樹網格校準", font=(FONT_FAMILY, 11, "bold"), fg="#00e5ff", bg="#252533")
        grid_calib_title.pack(anchor="w", padx=15, pady=(0, 5))
        
        grid_calib_desc = tk.Label(template_card, text="為實現自動點選熟練度技能，請在進入車輛熟練度畫面時，點選下方按鈕分別校準技能樹的最左上角與最右下角按鈕的中心位置。", font=(FONT_FAMILY, 9), fg="#a0a0b0", bg="#252533", justify="left", wraplength=500)
        grid_calib_desc.pack(anchor="w", padx=15, pady=(0, 10))
        
        # Grid frame for calibration buttons
        grid_calib_frame = tk.Frame(template_card, bg="#252533")
        grid_calib_frame.pack(fill="x", padx=15, pady=5)
        
        # Top-left Calib
        tl_frame = tk.Frame(grid_calib_frame, bg="#1e1e28", bd=1, relief="solid", highlightthickness=0)
        tl_frame.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=5)
        
        lbl_tl_title = tk.Label(tl_frame, text="1. 技能樹左上角按鈕中心", font=(FONT_FAMILY, 9, "bold"), fg="#ffffff", bg="#1e1e28")
        lbl_tl_title.pack(anchor="w", padx=8, pady=(4, 2))
        
        tl_val = f"已設定: {self.bot.mastery_grid_topleft}" if self.bot.mastery_grid_topleft else "未設定"
        tl_color = "#2efb57" if self.bot.mastery_grid_topleft else "#ef4444"
        self.lbl_mastery_topleft = tk.Label(tl_frame, text=tl_val, font=(FONT_FAMILY, 9), fg=tl_color, bg="#1e1e28")
        self.lbl_mastery_topleft.pack(anchor="w", padx=8, pady=(0, 4))
        
        btn_tl_calib = tk.Button(tl_frame, text=" 校準左上角 ", font=(FONT_FAMILY, 8), bg="#00e5ff", fg="#1a1a22", activebackground="#00b8cc", activeforeground="#1a1a22", relief="flat", padx=8, pady=1, command=lambda: self.calibrate_grid_point("左上角"))
        btn_tl_calib.pack(anchor="w", padx=8, pady=(0, 8))
        
        # Bottom-right Calib
        br_frame = tk.Frame(grid_calib_frame, bg="#1e1e28", bd=1, relief="solid", highlightthickness=0)
        br_frame.pack(side="right", fill="both", expand=True, padx=(10, 0), pady=5)
        
        lbl_br_title = tk.Label(br_frame, text="2. 技能樹右下角按鈕中心", font=(FONT_FAMILY, 9, "bold"), fg="#ffffff", bg="#1e1e28")
        lbl_br_title.pack(anchor="w", padx=8, pady=(4, 2))
        
        br_val = f"已設定: {self.bot.mastery_grid_bottomright}" if self.bot.mastery_grid_bottomright else "未設定"
        br_color = "#2efb57" if self.bot.mastery_grid_bottomright else "#ef4444"
        self.lbl_mastery_bottomright = tk.Label(br_frame, text=br_val, font=(FONT_FAMILY, 9), fg=br_color, bg="#1e1e28")
        self.lbl_mastery_bottomright.pack(anchor="w", padx=8, pady=(0, 4))
        
        btn_br_calib = tk.Button(br_frame, text=" 校準右下角 ", font=(FONT_FAMILY, 8), bg="#00e5ff", fg="#1a1a22", activebackground="#00b8cc", activeforeground="#1a1a22", relief="flat", padx=8, pady=1, command=lambda: self.calibrate_grid_point("右下角"))
        btn_br_calib.pack(anchor="w", padx=8, pady=(0, 8))

    def draw_status_dot(self, color):
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 10, 10, fill=color, outline="")

    def log_message(self, message):
        """Thread-safe logging to the text widget with Verilog-like multi-coloring."""
        def action():
            # Insert timestamp in gray
            self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - ", "time")
            
            # Parse message into segments and insert with appropriate tags
            parts = LOG_TOKEN_PATTERN.split(message)
            for i, part in enumerate(parts):
                if not part:
                    continue
                if i % 2 == 1:
                    # Matched token
                    tag = get_tag_for_token(part)
                    self.log_text.insert(tk.END, part, tag)
                else:
                    # Unmatched text
                    self.log_text.insert(tk.END, part, "info")
                    
            self.log_text.insert(tk.END, "\n")
            self.log_text.see(tk.END)
        self.root.after(0, action)


    def on_state_change(self, state):
        """Callback for bot state transitions."""
        def action():
            if state == "IDLE":
                self.draw_status_dot("#ef4444") # Red
                self.status_text.config(text="已停止 (IDLE)", fg="#ef4444")
                self.state_desc.config(text="未啟動 - 請按 F10 鍵或點擊下方啟動按鈕", fg="#ffffff")
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
            elif state == "WAIT_FOR_SETTLEMENT":
                self.draw_status_dot("#00e5ff") # Cyan
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#00e5ff")
                self.state_desc.config(text="偵測結算畫面中... (尋找：重新開始)", fg="#00e5ff")
            elif state == "WAIT_FOR_CONFIRM":
                self.draw_status_dot("#3b82f6") # Blue
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#3b82f6")
                self.state_desc.config(text="偵測對話框中... (尋找：確認-是)", fg="#3b82f6")
            elif state == "WAIT_FOR_START_EVENT":
                self.draw_status_dot("#ff007f") # Pink
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#ff007f")
                self.state_desc.config(text="偵測賽事起跑中... (尋找：開始賽事)", fg="#ff007f")
            elif state == "RACING":
                self.draw_status_dot("#10b981") # Green
                self.status_text.config(text="執行中 (RACING)", fg="#10b981")
                self.state_desc.config(text="自動賽事計時等待中...", fg="#10b981")
            elif state == "MASTERY_START":
                self.draw_status_dot("#00e5ff") # Cyan
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#00e5ff")
                self.state_desc.config(text="搜尋「我的車輛」按鈕... (尋找：my_cars_tile.png)", fg="#00e5ff")
            elif state == "MASTERY_OPEN_MANUFACTURER":
                self.draw_status_dot("#3b82f6") # Blue
                self.status_text.config(text="執行中 (ACTIVE)", fg="#3b82f6")
                self.state_desc.config(text="已進入車庫，發送 Backspace 以開啟車廠篩選...", fg="#3b82f6")
            elif state == "MASTERY_SELECT_MANUFACTURER":
                self.draw_status_dot("#00e5ff") # Cyan
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#00e5ff")
                self.state_desc.config(text="搜尋 LAMBORGHINI 車廠標誌... (尋找：lambo_brand.png)", fg="#00e5ff")
            elif state == "MASTERY_SELECT_CAR":
                self.draw_status_dot("#00e5ff") # Cyan
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#00e5ff")
                self.state_desc.config(text=f"選取第 {self.bot.mastery_car_index + 1} 輛 REVUELTO 車輛中... (尋找：revuelto.png)", fg="#00e5ff")
            elif state == "MASTERY_DRIVE_PROMPT":
                self.draw_status_dot("#00e5ff") # Cyan
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#00e5ff")
                self.state_desc.config(text="確認「選擇動作」提示... (尋找：select_action.png)", fg="#00e5ff")
            elif state == "MASTERY_ENTER_UPGRADES":
                self.draw_status_dot("#00e5ff") # Cyan
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#00e5ff")
                self.state_desc.config(text="搜尋「升級套件與調校」入口... (尋找：upgrades_tuning.png)", fg="#00e5ff")
            elif state == "MASTERY_ENTER_MASTERY":
                self.draw_status_dot("#00e5ff") # Cyan
                self.status_text.config(text="偵測中 (ACTIVE)", fg="#00e5ff")
                self.state_desc.config(text="搜尋「車輛熟練度」按鈕... (尋找：car_mastery_button.png)", fg="#00e5ff")
            elif state == "MASTERY_UNLOCK_SKILLS":
                self.draw_status_dot("#10b981") # Green
                self.status_text.config(text="執行中 (ACTIVE)", fg="#10b981")
                self.state_desc.config(text="正在解鎖技能點 (4x4 網格)...", fg="#10b981")
        self.root.after(0, action)

    def save_settings(self):
        try:
            duration = float(self.entry_duration.get())
            threshold = float(self.entry_threshold.get())
            window_title = self.combo_windows.get()
            
            if duration <= 0:
                raise ValueError("秒數必須大於 0")
            if not (0.1 <= threshold <= 1.0):
                raise ValueError("相似度門檻必須在 0.1 到 1.0 之間")
            if not window_title:
                raise ValueError("未選擇遊戲視窗")
                
            mastery_index = int(self.entry_mastery_index.get())
            if mastery_index < 0:
                raise ValueError("已處理車數不能為負數")
                
            self.bot.race_duration = duration
            self.bot.threshold = threshold
            self.bot.game_window_title = window_title
            self.bot.selected_hwnd = self.windows_map.get(window_title)
            self.bot.mastery_car_index = mastery_index
            
            self.bot.save_config()
            self.log_message(f"設定已儲存：賽事時間 {duration} 秒，相似門檻 {threshold}，已處理車數 {mastery_index}，視窗標題「{window_title}」")
            messagebox.showinfo("成功", "設定參數已儲存！")
        except ValueError as e:
            messagebox.showerror("錯誤", f"輸入值無效：{e}")

    def reset_mastery_index(self):
        self.entry_mastery_index.delete(0, "end")
        self.entry_mastery_index.insert(0, "0")
        self.bot.mastery_car_index = 0
        self.bot.save_config()
        self.log_message("已重置車輛熟練度處理索引為 0")

    def start_bot(self):
        # Apply current inputs first
        try:
            self.bot.race_duration = float(self.entry_duration.get())
            self.bot.threshold = float(self.entry_threshold.get())
            window_title = self.combo_windows.get()
            self.bot.game_window_title = window_title
            self.bot.selected_hwnd = self.windows_map.get(window_title)
            self.bot.mode = self.bot_mode_var.get()
        except ValueError:
            pass
            
        if not self.bot.is_running:
            # Check OpenCV again in case it finished installing
            self.check_opencv_status()
            
            # Check if templates exist for the selected mode
            missing = []
            mode = self.bot_mode_var.get()
            required_templates = []
            if mode == "RACE_FARM":
                required_templates = ["restart.png", "yes.png", "start.png"]
            elif mode == "CAR_MASTERY":
                required_templates = ["my_cars_tile.png", "lambo_brand.png", "revuelto.png", "upgrades_tuning.png", "car_mastery_button.png"]
                if not HAS_WINSDK:
                    required_templates.append("select_action.png")
                if not self.bot.mastery_grid_topleft or not self.bot.mastery_grid_bottomright:
                    self.log_message("錯誤: 尚未校準技能樹網格座標！請在「圖像校準」中設定。")
                    messagebox.showwarning("警告", "請先完成技能樹「左上角」與「右下角」座標校準再啟動腳本！")
                    return
                
            for filename in required_templates:
                path = os.path.join(self.bot.templates_dir, filename)
                if not os.path.exists(path):
                    # Find the title for the filename
                    title = filename
                    for fn, t, _ in self.temp_items:
                        if fn == filename:
                            title = t
                            break
                    missing.append(title)
            if missing:
                self.log_message(f"錯誤: 缺少此模式所需的模板檔案 {missing}，請先完成擷取。")
                messagebox.showwarning("警告", f"請先截圖設定當前模式所需的模板：{missing} 再啟動腳本！")
                return
                
            self.bot.start()
            
            # Start timer if selected
            timer_val = self.combo_timer.get()
            if timer_val != "不限時":
                seconds = 0
                if timer_val == "1 小時":
                    seconds = 3600
                elif timer_val == "1.5 小時":
                    seconds = 5400
                elif timer_val == "2 小時":
                    seconds = 7200
                elif timer_val == "3 小時":
                    seconds = 10800
                    
                if seconds > 0:
                    self.auto_stop_target_time = time.time() + seconds
                    self.log_message(f"已啟動定時關閉：將於 {timer_val} 後自動停止掛機。")
            else:
                self.auto_stop_target_time = None
                
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            
    def stop_bot(self):
        if self.bot.is_running:
            self.bot.stop()
            self.auto_stop_target_time = None
            self.lbl_countdown.config(text="")
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")

    def refresh_windows_list(self):
        """Refreshes the dropdown list with visible windows."""
        self.windows_map = {}
        window_list = []
        
        def enum_windows_callback(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and title != "Program Manager" and title != self.root.title():
                    rect = win32gui.GetWindowRect(hwnd)
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    if w > 100 and h > 100:
                        window_list.append((title, hwnd))
                        
        win32gui.EnumWindows(enum_windows_callback, None)
        window_list.sort(key=lambda x: x[0].lower())
        
        titles = []
        for title, hwnd in window_list:
            display_title = title
            if display_title in self.windows_map:
                display_title = f"{title} (HWND: {hwnd})"
            self.windows_map[display_title] = hwnd
            titles.append(display_title)
            
        self.combo_windows["values"] = titles
        
        # Auto-select Forza
        for title in titles:
            if "forza" in title.lower():
                self.combo_windows.set(title)
                self.bot.game_window_title = title
                self.bot.selected_hwnd = self.windows_map[title]
                break
        else:
            if titles:
                self.combo_windows.set(titles[0])
                self.bot.game_window_title = titles[0]
                self.bot.selected_hwnd = self.windows_map[titles[0]]
                
        self.log_message(f"已整理目前電腦上的視窗列表（共 {len(titles)} 個）")

    def on_window_selected(self, event):
        selected_title = self.combo_windows.get()
        if selected_title:
            self.bot.game_window_title = selected_title
            self.bot.selected_hwnd = self.windows_map.get(selected_title)
            # Reset topmost when switching windows
            self.is_topmost_var.set(False)
            self.log_message(f"已選擇遊戲視窗：{selected_title}")

    def on_mode_changed(self):
        mode = self.bot_mode_var.get()
        self.bot.mode = mode
        if mode == "RACE_FARM":
            self.log_message("已切換運行模式：【自動刷賽事技能點】")
        elif mode == "CAR_MASTERY":
            self.log_message("已切換運行模式：【自動點選車輛熟練度】")

    def toggle_topmost(self):
        """Toggles the topmost status of the selected window."""
        selected_title = self.combo_windows.get()
        if not selected_title:
            messagebox.showwarning("警告", "請先選擇一個視窗！")
            self.is_topmost_var.set(False)
            return
            
        hwnd = self.windows_map.get(selected_title)
        if not hwnd or not win32gui.IsWindow(hwnd):
            messagebox.showerror("錯誤", "找不到該視窗的有效控制代碼 (HWND)，請重新整理列表。")
            self.is_topmost_var.set(False)
            return
            
        enable = self.is_topmost_var.get()
        try:
            if enable:
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                     win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
                self.log_message(f"已將視窗「{selected_title}」強制置頂顯示。")
            else:
                win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                     win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
                self.log_message(f"已取消視窗「{selected_title}」的置頂顯示。")
        except Exception as e:
            self.log_message(f"置頂控制失敗: {e}")
            messagebox.showerror("錯誤", f"無法設定置頂狀態: {e}")
            self.is_topmost_var.set(False)



    def show_deactivate_help(self):
        """Shows the guide window explaining background deactivation and how to use DisplayFusion / VM."""
        help_win = tk.Toplevel(self.root)
        help_win.title("背景掛機與焦點設定指引")
        help_win.geometry("540x480")
        help_win.configure(bg="#1a1a22")
        help_win.resizable(True, True)
        help_win.minsize(450, 400)
        help_win.transient(self.root)
        help_win.grab_set()
        
        # Center the window relative to root
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        help_win.geometry(f"+{root_x + 50}+{root_y + 50}")
        
        title_label = tk.Label(help_win, text="背景掛機重要指引與技術限制", font=(FONT_FAMILY, 12, "bold"), fg="#00e5ff", bg="#1a1a22")
        title_label.pack(anchor="w", padx=20, pady=(15, 10))
        
        text_frame = tk.Frame(help_win, bg="#252533", bd=1, relief="solid", highlightthickness=0)
        text_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        # Use a Text widget to render formatted information with scrollbar
        text_widget = tk.Text(text_frame, bg="#252533", fg="#ffffff", font=(FONT_FAMILY, 9), wrap="word", relief="flat", padx=10, pady=10)
        text_widget.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.config(yscrollcommand=scrollbar.set)
        
        guide_text = (
            "【💡 為什麼背景維持聚焦功能無法自動運作？】\n"
            "現代 Windows 3D 遊戲（如《極限競速：地平線》系列）使用 DirectX 12 與原始輸入（Raw Input）系統。當玩家點擊其他視窗或進行 Alt-Tab 切換時，遊戲會在底層主動偵測焦點喪失，並強制將遊戲暫停或降低幀率以防浪費硬體資源。\n\n"
            "程式碼級別的「欺騙」（如傳送 WM_ACTIVATE 訊息）無法越過 DirectX 底層偵測。要實現強行防凍結，必須將自訂程式碼（DLL）注入遊戲程序。然而，由於地平線系列受反作弊系統嚴密監控，DLL 注入將會面臨極高的帳號封禁（Ban）風險！為了使用者的帳號安全，本腳本堅決不包含任何危險的注入行為。\n\n"
            "─────────────────────────────────\n\n"
            "【⚠️ 鍵盤模擬洩漏限制】\n"
            "本腳本使用 SendInput API 進行硬體級鍵盤模擬（這是繞過遊戲反按鍵阻擋的唯一手段）。SendInput 發出的所有按鍵只會送到「當前系統焦點視窗」（即您滑鼠選中或正在打字的視窗）。\n"
            "因此，即使我們成功使遊戲在背景運行不凍結，只要您在其他視窗（如 Chrome 瀏覽器）打字，腳本發送的「W」、「X」、「Enter」鍵就會直接輸入到您的 Chrome 中，導致您無法使用鍵盤，且遊戲也會因收不到按鍵而中斷！\n\n"
            "─────────────────────────────────\n\n"
            "【🛠️ 社群驗證的最佳掛機方案】\n\n"
            "方案 1：搭配 DisplayFusion（雙螢幕玩家推薦）\n"
            "對於擁有第二螢幕的玩家，您可以使用 DisplayFusion 軟體來達成背景不凍結：\n"
            "  1. 將遊戲改為「無邊框視窗化 (Borderless Windowed)」。\n"
            "  2. 下載並安裝 DisplayFusion（免費版即可）。\n"
            "  3. 開啟 DisplayFusion 設定 -> 點選「Functions」分頁 -> 搜尋「Prevent Window Deactivation (防止視窗停用)」。\n"
            "  4. 為此功能指定一組自訂快捷鍵（例如 Ctrl + Alt + P）。\n"
            "  5. 點入遊戲視窗使其成為活動視窗，接著按下該快捷鍵。\n"
            "  6. 此時您可將滑鼠移到第二螢幕進行滑鼠操作或觀看影片，遊戲不會再因失去焦點而凍結。\n"
            "  *(注意：因 SendInput 限制，掛機期間仍不可使用鍵盤打字，否則按鍵會輸入到您打字的視窗中)*\n\n"
            "方案 2：使用 Windows 虛擬機 (VM)\n"
            "若想在掛機時完全不受干擾地使用鍵盤和滑鼠：\n"
            "  1. 在本機安裝 Windows 虛擬機（如 VMware Workstation 或 Hyper-V）。\n"
            "  2. 確保虛擬機分配了足夠的顯示卡效能（GPU 直通）以流暢執行遊戲。\n"
            "  3. 在虛擬機內執行遊戲與本腳本。\n"
            "  4. 如此一來，您可以隨時將虛擬機視窗縮小或置於背景，主機的日常鍵盤打字將完全不受影響！\n\n"
            "方案 3：利用內建定時器離線掛機（最推薦）\n"
            "  - 在設定中選擇「1 小時」或「1.5 小時」後啟動。\n"
            "  - 讓遊戲保持在最上層，人離開電腦，時間到後腳本將自動安全停止並倒數，最適合短時間離開或睡前掛機。\n"
        )
        
        text_widget.insert("1.0", guide_text)
        text_widget.config(state="disabled") # Make it read-only
        
        btn_close = tk.Button(help_win, text="我知道了", font=(FONT_FAMILY, 9, "bold"), bg="#3b82f6", fg="#ffffff", activebackground="#2563eb", activeforeground="#ffffff", relief="flat", padx=20, pady=5, command=help_win.destroy)
        btn_close.pack(pady=(0, 15))

    def show_threshold_help(self):
        """Shows the guide window explaining the similarity threshold setting."""
        help_win = tk.Toplevel(self.root)
        help_win.title("辨識相似門檻說明")
        help_win.geometry("460x340")
        help_win.configure(bg="#1a1a22")
        help_win.resizable(False, False)
        help_win.transient(self.root)
        help_win.grab_set()
        
        # Center relative to root
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        help_win.geometry(f"+{root_x + 80}+{root_y + 100}")
        
        title_label = tk.Label(help_win, text="什麼是「辨識相似門檻」？", font=(FONT_FAMILY, 12, "bold"), fg="#00e5ff", bg="#1a1a22")
        title_label.pack(anchor="w", padx=20, pady=(15, 10))
        
        text_frame = tk.Frame(help_win, bg="#252533", bd=1, relief="solid", highlightthickness=0)
        text_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        text_widget = tk.Text(text_frame, bg="#252533", fg="#ffffff", font=(FONT_FAMILY, 9), wrap="word", relief="flat", padx=10, pady=10)
        text_widget.pack(side="left", fill="both", expand=True)
        
        guide_text = (
            "【📊 數值的作用與設定指南】\n"
            "「辨識相似門檻」代表腳本在進行圖像匹配時，對目標特徵相似度的嚴格程度。其範圍介於 0.1 到 1.0 之間：\n\n"
            "• 預設值為 0.8：這是最平衡的設定。相似度達到 80% 即判定為匹配成功。\n\n"
            "• 當數值調高（如 0.9 ~ 0.95）：\n"
            "  - 判定會變得極為嚴格。只有畫面與您的模板幾乎完全一模一樣時才會觸發。\n"
            "  - 💡 優點：能有效避免誤判（例如將其它文字誤認成按鈕）。\n"
            "  - ⚠️ 缺點：若遊戲畫質稍微波動、出現鋸齒或光影微變，可能會導致完全偵測不到按鈕。\n\n"
            "• 當數值調低（如 0.6 ~ 0.7）：\n"
            "  - 判定會變得寬鬆。即使畫面上的字體有輕微模糊或解析度有些許色差，也能順利辨識。\n"
            "  - ⚠️ 缺點：太低容易產生誤判，導致腳本在無關畫面中誤觸按鍵。\n\n"
            "💡 【調整建議】\n"
            "如果出現「畫面有按鈕但腳本沒反應」，請先重新擷取清晰的模板。若仍無法辨識，可嘗試將此門檻微調降至 0.7 或 0.75。"
        )
        
        text_widget.insert("1.0", guide_text)
        text_widget.config(state="disabled")
        
        btn_close = tk.Button(help_win, text="我知道了", font=(FONT_FAMILY, 9, "bold"), bg="#3b82f6", fg="#ffffff", activebackground="#2563eb", activeforeground="#ffffff", relief="flat", padx=20, pady=5, command=help_win.destroy)
        btn_close.pack(pady=(0, 15))

    # Template Capture System
    def capture_template(self, filename):
        """Handles screenshot capturing and overlay for selection."""
        # Check if bot is running
        if self.bot.is_running:
            messagebox.showwarning("提示", "請先停止腳本後再擷取模板。")
            return
            
        self.log_message(f"開始擷取模板 {filename}... 視窗即將隱藏...")
        self.root.withdraw()
        self.root.update()
        
        time.sleep(0.6)
        
        hwnd, rect = self.bot.find_game_window()
        offset = (0, 0)
        
        if hwnd and rect:
            left, top, right, bottom = rect
            if left < 0: left = 0
            if top < 0: top = 0
            if right > left and bottom > top:
                screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
                offset = (left, top)
            else:
                screenshot = ImageGrab.grab()
        else:
            screenshot = ImageGrab.grab()
            self.log_message("找不到遊戲視窗，擷取全螢幕畫面。")
            
        def on_crop_finished(success, result):
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.root.update()
            
            if success:
                self.log_message(f"模板 {filename} 擷取儲存成功！")
                self.update_thumbnail(filename)
            else:
                self.log_message(f"模板擷取失敗或取消：{result}")
                
        save_path = os.path.join(self.bot.templates_dir, filename)
        CropOverlay(self.root, screenshot, save_path, on_crop_finished)

    def calibrate_grid_point(self, point_name):
        """Handles single coordinate selection for grid points."""
        if self.bot.is_running:
            messagebox.showwarning("提示", "請先停止腳本後再進行校準。")
            return
            
        self.log_message(f"開始校準技能樹{point_name}座標... 視窗即將隱藏...")
        self.root.withdraw()
        self.root.update()
        
        time.sleep(0.6)
        
        hwnd, rect = self.bot.find_game_window()
        
        if hwnd and rect:
            left, top, right, bottom = rect
            if left < 0: left = 0
            if top < 0: top = 0
            if right > left and bottom > top:
                screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
            else:
                screenshot = ImageGrab.grab()
        else:
            screenshot = ImageGrab.grab()
            self.log_message("找不到遊戲視窗，擷取全螢幕畫面。")
            
        def on_select_finished(success, result):
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.root.update()
            
            if success:
                x, y = result
                if point_name == "左上角":
                    self.bot.mastery_grid_topleft = (x, y)
                    self.lbl_mastery_topleft.config(text=f"已設定: ({x}, {y})", fg="#2efb57")
                else:
                    self.bot.mastery_grid_bottomright = (x, y)
                    self.lbl_mastery_bottomright.config(text=f"已設定: ({x}, {y})", fg="#2efb57")
                self.bot.save_config()
                self.log_message(f"技能樹{point_name}座標校準成功！相對座標: ({x}, {y})")
            else:
                self.log_message(f"技能樹校準取消或失敗: {result}")
                
        CoordinateOverlay(self.root, screenshot, on_select_finished)

    def update_all_thumbnails(self):
        for filename, _, _ in self.temp_items:
            self.update_thumbnail(filename)

    def update_thumbnail(self, filename):
        path = os.path.join(self.bot.templates_dir, filename)
        canvas = self.temp_frames[filename]["canvas"]
        canvas.delete("all")
        
        if os.path.exists(path):
            try:
                img = Image.open(path)
                # Resize to fit 50x35 canvas
                img.thumbnail((50, 35))
                tk_img = ImageTk.PhotoImage(img)
                self.thumbnails[filename] = tk_img
                
                canvas.create_image(25, 17, image=tk_img)
                self.temp_frames[filename]["label"].config(fg="#2efb57")
            except Exception as e:
                self.log_message(f"無法載入模板預覽 {filename}: {e}")
        else:
            canvas.create_line(12, 17, 38, 17, fill="#ef4444", width=2)
            canvas.create_text(25, 17, text="未設定", fill="#ef4444", font=(FONT_FAMILY, 7))
            self.temp_frames[filename]["label"].config(fg="#ffffff")

    # Global Hotkey Listener System
    def start_hotkey_listener(self):
        self.hotkey_stop_event.clear()
        self.hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self.hotkey_thread.start()

    def _hotkey_loop(self):
        if not user32.RegisterHotKey(0, HOTKEY_START_ID, 0, VK_F10):
            self.log_message("警告: 無法註冊全域啟動快捷鍵 F10 (可能被佔用)")
        if not user32.RegisterHotKey(0, HOTKEY_STOP_ID, 0, VK_F11):
            self.log_message("警告: 無法註冊全域停止快捷鍵 F11 (可能被佔用)")
            
        msg = wintypes.MSG()
        while not self.hotkey_stop_event.is_set():
            r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if r != 0:
                if msg.message == win32con.WM_HOTKEY:
                    if msg.wParam == HOTKEY_START_ID:
                        self.log_message("全域快捷鍵 F10 觸發 -> 啟動腳本")
                        self.root.after(0, self.start_bot)
                    elif msg.wParam == HOTKEY_STOP_ID:
                        self.log_message("全域快捷鍵 F11 觸發 -> 停止腳本")
                        self.root.after(0, self.stop_bot)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
                
        user32.UnregisterHotKey(0, HOTKEY_START_ID)
        user32.UnregisterHotKey(0, HOTKEY_STOP_ID)

    def refresh_timer(self):
        """Periodic UI updates."""
        # Check auto stop countdown
        if self.bot.is_running and self.auto_stop_target_time:
            remaining = self.auto_stop_target_time - time.time()
            if remaining <= 0:
                self.auto_stop_target_time = None
                self.lbl_countdown.config(text="")
                self.log_message("定時掛機時間已到，自動停止腳本！")
                self.stop_bot()
                messagebox.showinfo("定時停止", "設定的自動掛機時間已到，腳本已安全停止。")
            else:
                hrs = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                secs = int(remaining % 60)
                self.lbl_countdown.config(text=f"⏱️ 倒數停止: {hrs:02d}:{mins:02d}:{secs:02d}")
        else:
            if not self.bot.is_running:
                self.auto_stop_target_time = None
                self.lbl_countdown.config(text="")

        # Update mastery index in UI if it changed in bot
        try:
            current_ui_val = int(self.entry_mastery_index.get())
            if current_ui_val != self.bot.mastery_car_index:
                self.entry_mastery_index.delete(0, "end")
                self.entry_mastery_index.insert(0, str(self.bot.mastery_car_index))
        except Exception:
            pass

        # Schedule next tick every 500ms
        self.root.after(500, self.refresh_timer)

    def on_closing(self):
        if self.bot.is_running:
            self.bot.stop()
        self.hotkey_stop_event.set()
        if self.hotkey_thread and self.hotkey_thread.ident:
            try:
                user32.PostThreadMessageW(self.hotkey_thread.ident, win32con.WM_QUIT, 0, 0)
            except Exception:
                pass
        self.root.destroy()


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

if __name__ == "__main__":
    root = tk.Tk()
    app = BotGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
