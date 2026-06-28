import os
import io
import asyncio
from PIL import Image

try:
    import winsdk
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
    HAS_WINSDK = True
except ImportError:
    HAS_WINSDK = False

from src.screen import capture_game_screen

class OcrEngineManager:
    def __init__(self, log_func=None):
        self.log_func = log_func
        self.ocr_engines = []
        
        if HAS_WINSDK:
            for lang_tag in ["zh-TW", "zh-Hant-TW", "zh-Hant", "zh-CN", "zh-Hans-CN", "zh-Hans", "en-US"]:
                try:
                    lang = Language(lang_tag)
                    engine = OcrEngine.try_create_from_language(lang)
                    if engine:
                        self.ocr_engines.append((lang_tag, engine))
                        self.log(f"成功載入 OCR 引擎: {lang_tag}")
                except Exception:
                    pass
            # Fallback to current system language if none could be loaded
            if not self.ocr_engines:
                try:
                    engine = OcrEngine.try_create_from_current_language()
                    if engine:
                        self.ocr_engines.append(("system", engine))
                        self.log("成功載入系統預設 OCR 引擎")
                except Exception:
                    pass

    def log(self, message):
        if self.log_func:
            self.log_func(message)

    def is_available(self):
        return HAS_WINSDK and len(self.ocr_engines) > 0

    def find_text_by_ocr_sync(self, target_texts, selected_hwnd=None, game_window_title="Forza Horizon"):
        """Synchronously runs OCR to find the given text list on the game screen.
        Returns (abs_x, abs_y, confidence) of the matched text center, or None.
        """
        if not self.is_available():
            return None
        try:
            if isinstance(target_texts, str):
                target_texts = [target_texts]
            return asyncio.run(self._ocr_search_multi_async(target_texts, selected_hwnd, game_window_title))
        except Exception as e:
            self.log(f"OCR 辨識過程發生異常錯誤: {e}")
            return None

    async def _ocr_search_multi_async(self, target_texts, selected_hwnd, game_window_title):
        """Asynchronously grabs screen and runs Windows Media OCR using multiple engines to find any of target_texts."""
        if not self.ocr_engines:
            return None
            
        screenshot, offset = capture_game_screen(selected_hwnd, game_window_title)
        
        # Scale the image by 2x for significantly better OCR accuracy of small texts
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
                            # Length filter for short buttons to prevent false matches in descriptions
                            short_button_targets = {"是", "确定", "確定", "yes", "ok", "no", "否", "不", "buy", "購買", "购买", "已新增", "車庫", "车库"}
                            if t_clean in short_button_targets and len(line_text_clean) > len(t_clean) + 4:
                                continue
                            matched_target = t_clean
                            break
                            
                    if matched_target:
                        words = list(line.words)
                        if words:
                            # Find the narrowest subsegment of words containing the matched target for precise clicks
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

    def detect_available_points_sync(self, selected_hwnd=None, game_window_title="Forza Horizon"):
        """Detects available mastery points from the game screen.
        Returns the number of points as an int, or None if detection failed.
        """
        if not self.is_available():
            return None
        try:
            return asyncio.run(self._detect_available_points_async(selected_hwnd, game_window_title))
        except Exception as e:
            self.log(f"偵測可用點數發生異常: {e}")
            return None

    async def _detect_available_points_async(self, selected_hwnd, game_window_title):
        if not self.ocr_engines:
            return None
            
        screenshot, offset = capture_game_screen(selected_hwnd, game_window_title)
        
        # Scale the image by 2x for accuracy
        scale_factor = 2
        new_size = (screenshot.size[0] * scale_factor, screenshot.size[1] * scale_factor)
        screenshot_scaled = screenshot.resize(new_size, Image.Resampling.LANCZOS)
        
        img_byte_arr = io.BytesIO()
        screenshot_scaled.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(img_bytes)
        await writer.store_async()
        await writer.flush_async()
        
        decoder = await BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()
        
        target_labels = ["可用的點數", "可用的点数", "availablepoints"]
        
        for lang_tag, engine in self.ocr_engines:
            try:
                result = await engine.recognize_async(software_bitmap)
                
                label_line = None
                label_y_center = None
                label_x_right = None
                
                for line in result.lines:
                    line_text_clean = "".join(line.text.lower().split())
                    matched = False
                    for target in target_labels:
                        if target in line_text_clean:
                            matched = True
                            break
                            
                    if matched:
                        label_line = line
                        rects = [w.bounding_rect for w in line.words]
                        if rects:
                            top = min(r.y for r in rects) / scale_factor
                            bottom = max(r.y + r.height for r in rects) / scale_factor
                            right = max(r.x + r.width for r in rects) / scale_factor
                            label_y_center = top + (bottom - top) / 2
                            label_x_right = right
                        break
                
                if label_line is not None:
                    import re
                    digits = re.findall(r'\d+', label_line.text)
                    if digits:
                        points = int(digits[0])
                        self.log(f"[OCR] 在同一行偵測到可用點數: {points}")
                        return points
                        
                    if label_y_center is not None and label_x_right is not None:
                        best_number = None
                        min_dist = float('inf')
                        
                        for line in result.lines:
                            if line == label_line:
                                continue
                            line_digits = re.findall(r'\d+', line.text)
                            if line_digits:
                                rects = [w.bounding_rect for w in line.words]
                                if rects:
                                    top = min(r.y for r in rects) / scale_factor
                                    bottom = max(r.y + r.height for r in rects) / scale_factor
                                    left = min(r.x for r in rects) / scale_factor
                                    y_center = top + (bottom - top) / 2
                                    
                                    if abs(y_center - label_y_center) < 30 and left >= label_x_right - 20:
                                        dist = left - label_x_right
                                        if dist < min_dist:
                                            min_dist = dist
                                            best_number = int(line_digits[0])
                                            
                        if best_number is not None:
                            self.log(f"[OCR] 在鄰近區域偵測到可用點數: {best_number}")
                            return best_number
            except Exception as e:
                self.log(f"OCR 偵測點數時在引擎 {lang_tag} 出錯: {e}")
                
        return None
