import cv2
import pytesseract
import re
import numpy as np
from ultralytics import YOLO
import os
from difflib import SequenceMatcher
import time
from collections import Counter

# TODO: Sesuaikan path Tesseract dengan environment Anda
pytesseract.pytesseract.tesseract_cmd = r"C:\Users\LENOVO\Videos\tocr\tesseract.exe"

class PlateDetector:
    def __init__(self, model_path='D:/Kuliah/Semester 7/Proyek Profesional/Final Project/final banget/models/best.pt'):
        """
        Inisialisasi PlateDetector dengan model YOLO dan OCR pipeline lengkap
        
        Args:
            model_path (str): Path ke model YOLO (.pt file)
        """
        try:
            # Load YOLO model
            self.model = YOLO(model_path)
            
            # Parameter deteksi
            self.model.overrides['conf'] = 0.75  # Confidence threshold
            self.model.overrides['iou'] = 0.5    # IOU threshold
            
            # Parameter OCR
            self.MIN_SIMILARITY = 0.65
            self.PLATE_PATTERN = r'^[A-Z]{1,2}\d{1,4}[A-Z]{1,3}$'  # Format: TANPA SPASI
            self.OCR_TIMEOUT = 2.0  # Timeout untuk OCR processing (detik)
            
            # Konfigurasi Tesseract untuk multiple runs
            self.OCR_CONFIGS = [
                {
                    'psm': 11,  # Sparse text
                    'config': r'--oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                },
                {
                    'psm': 8,   # Single word
                    'config': r'--oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                },
                {
                    'psm': 7,   # Single line
                    'config': r'--oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                },
                {
                    'psm': 6,   # Uniform block of text
                    'config': r'--oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                }
            ]
            
            print(f"✅ PlateDetector berhasil diinisialisasi dengan model: {model_path}")
            print(f"📊 OCR Pipeline: {len(self.OCR_CONFIGS)} konfigurasi berbeda")
            
        except Exception as e:
            print(f"❌ Error inisialisasi PlateDetector: {str(e)}")
            raise

    def detect_plate(self, frame):
        """
        Mendeteksi plat nomor dalam frame menggunakan YOLO + OCR pipeline lengkap
        
        Args:
            frame (numpy.ndarray): Frame BGR dari kamera
            
        Returns:
            dict: Hasil deteksi dengan keys:
                - 'frame_with_overlay': Frame dengan bounding box
                - 'plate_text': Teks plat yang terdeteksi (None jika gagal)
                - 'confidence': Confidence level deteksi
                - 'boxes': Koordinat bounding boxes
                - 'ocr_confidence': Confidence level OCR (rata-rata dari multiple runs)
                - 'processing_time': Waktu processing total (detik)
                - 'ocr_results': Hasil dari setiap run OCR (untuk debugging)
        """
        start_time = time.time()
        
        try:
            # Salin frame untuk overlay
            frame_with_overlay = frame.copy()
            
            # ============================================
            # STEP 1: DETEKSI YOLO
            # ============================================
            yolo_start = time.time()
            results = self.model(frame)
            yolo_time = time.time() - yolo_start
            
            # Inisialisasi variabel hasil
            plate_text = None
            confidence = 0.0
            boxes = []
            ocr_confidence = 0.0
            ocr_results = []
            
            if len(results[0].boxes) > 0:
                # Ambil deteksi dengan confidence tertinggi
                best_idx = np.argmax(results[0].boxes.conf.cpu().numpy())
                confidence = float(results[0].boxes.conf.cpu().numpy()[best_idx])
                
                # Dapatkan koordinat bounding box
                x1, y1, x2, y2 = map(int, results[0].boxes.xyxy.cpu().numpy()[best_idx])
                boxes = [(x1, y1, x2, y2)]
                
                # ============================================
                # STEP 2: CROPPING REGION PLAT
                # ============================================
                plate_region = self._extract_plate_region(frame, (x1, y1, x2, y2))
                
                if plate_region.size > 0 and plate_region.shape[0] > 20 and plate_region.shape[1] > 50:
                    # ============================================
                    # STEP 3: PRE-PROCESSING PIPELINE LENGKAP
                    # ============================================
                    print(f"🔍 Memulai OCR pipeline untuk region {plate_region.shape}")
                    
                    # Multiple pre-processing stages
                    processed_images = self._multi_stage_preprocessing(plate_region)
                    
                    # ============================================
                    # STEP 4: MULTIPLE OCR RUNS
                    # ============================================
                    ocr_start = time.time()
                    
                    # Jalankan OCR untuk setiap image yang sudah diproses
                    all_ocr_texts = []
                    for i, processed_img in enumerate(processed_images):
                        # Multiple OCR runs dengan konfigurasi berbeda
                        for config_idx, ocr_config in enumerate(self.OCR_CONFIGS):
                            try:
                                text = pytesseract.image_to_string(
                                    processed_img,
                                    config=f'--psm {ocr_config["psm"]} {ocr_config["config"]}'
                                )
                                
                                cleaned_text = self._clean_text(text)
                                if cleaned_text and len(cleaned_text) >= 4:
                                    all_ocr_texts.append(cleaned_text)
                                    ocr_results.append({
                                        'stage': i,
                                        'config': config_idx,
                                        'text': cleaned_text,
                                        'raw_text': text.strip()
                                    })
                            except Exception as e:
                                print(f"⚠️ OCR run {i}-{config_idx} error: {str(e)}")
                    
                    # Hitung waktu OCR
                    ocr_time = time.time() - ocr_start
                    
                    # ============================================
                    # STEP 5: VOTING SYSTEM UNTUK HASIL TERBAIK
                    # ============================================
                    if all_ocr_texts:
                        # Gunakan voting system
                        plate_text = self._vote_best_result(all_ocr_texts)
                        
                        # Hitung OCR confidence berdasarkan konsistensi hasil
                        if plate_text:
                            ocr_confidence = self._calculate_ocr_confidence(all_ocr_texts, plate_text)
                            
                            # Validasi format plat
                            validated_text = self._validate_plate_format(plate_text)
                            if validated_text:
                                plate_text = validated_text
                            else:
                                print(f"⚠️ Format plat tidak valid: {plate_text}")
                                # Tetap gunakan meski tidak sesuai format, tapi beri flag
                                ocr_confidence *= 0.8  # Kurangi confidence jika format tidak valid
                    
                    # ============================================
                    # STEP 6: DRAW OVERLAY PADA FRAME
                    # ============================================
                    if plate_text:
                        print(f"✅ OCR Success: {plate_text} (Confidence: {ocr_confidence:.2f})")
                        frame_with_overlay = self._draw_detection_overlay(
                            frame_with_overlay, (x1, y1, x2, y2), plate_text, confidence, ocr_confidence
                        )
                    else:
                        print(f"❌ OCR gagal membaca plat")
                        # Tetap gambar bounding box meski OCR gagal
                        frame_with_overlay = self._draw_detection_overlay(
                            frame_with_overlay, (x1, y1, x2, y2), "No OCR Result", confidence, 0
                        )
                    
                    # Debug info
                    print(f"📊 YOLO: {yolo_time:.3f}s, OCR: {ocr_time:.3f}s, Total: {time.time()-start_time:.3f}s")
            
            # Jika tidak ada deteksi, tetap kembalikan frame asli
            if len(boxes) == 0:
                frame_with_overlay = frame.copy()
            
            processing_time = time.time() - start_time
            
            return {
                'frame_with_overlay': frame_with_overlay,
                'plate_text': plate_text,
                'confidence': confidence,
                'ocr_confidence': ocr_confidence,
                'boxes': boxes,
                'processing_time': processing_time,
                'ocr_results': ocr_results,
                'yolo_time': yolo_time
            }
            
        except Exception as e:
            print(f"❌ Error dalam deteksi plat: {str(e)}")
            # Return frame asli jika error
            return {
                'frame_with_overlay': frame.copy(),
                'plate_text': None,
                'confidence': 0.0,
                'ocr_confidence': 0.0,
                'boxes': [],
                'processing_time': time.time() - start_time,
                'ocr_results': [],
                'yolo_time': 0
            }

    def _extract_plate_region(self, frame, bbox):
        """
        Mengekstrak region plat nomor dengan padding dan cropping optimal
        
        Args:
            frame (numpy.ndarray): Frame asli
            bbox (tuple): Koordinat bounding box (x1, y1, x2, y2)
            
        Returns:
            numpy.ndarray: Region plat yang sudah dipotong dan dioptimalkan
        """
        try:
            x1, y1, x2, y2 = bbox
            
            # Hitung aspect ratio bounding box
            bbox_width = x2 - x1
            bbox_height = y2 - y1
            aspect_ratio = bbox_width / bbox_height if bbox_height > 0 else 1
            
            # Adaptive padding berdasarkan ukuran bounding box
            padding_x = int(bbox_width * 0.15)  # 15% padding horizontal
            padding_y = int(bbox_height * 0.1)   # 10% padding vertikal
            
            # Apply padding dengan boundary check
            h, w = frame.shape[:2]
            x1_pad = max(0, x1 - padding_x)
            y1_pad = max(0, y1 - padding_y)
            x2_pad = min(w, x2 + padding_x)
            y2_pad = min(h, y2 + padding_y)
            
            # Ekstrak region
            plate_region = frame[y1_pad:y2_pad, x1_pad:x2_pad]
            
            # Jika region terlalu kecil, return array kosong
            if plate_region.size == 0 or plate_region.shape[0] < 10 or plate_region.shape[1] < 30:
                return np.array([])
                
            # Normalisasi ukuran jika diperlukan
            min_height = 50
            min_width = 150
            
            if plate_region.shape[0] < min_height or plate_region.shape[1] < min_width:
                # Resize untuk memastikan ukuran minimum
                scale = max(min_height / plate_region.shape[0], min_width / plate_region.shape[1])
                new_width = int(plate_region.shape[1] * scale)
                new_height = int(plate_region.shape[0] * scale)
                plate_region = cv2.resize(plate_region, (new_width, new_height))
            
            return plate_region
            
        except Exception as e:
            print(f"❌ Error ekstraksi region plat: {str(e)}")
            return np.array([])

    def _multi_stage_preprocessing(self, img):
        """
        Multi-stage pre-processing pipeline untuk OCR
        
        Args:
            img (numpy.ndarray): Gambar input BGR
            
        Returns:
            list: List gambar yang sudah diproses dengan metode berbeda
        """
        processed_images = []
        
        try:
            # Convert to grayscale
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img
            
            # ============================================
            # STAGE 1: Basic Enhancement
            # ============================================
            # Denoising
            denoised = cv2.fastNlMeansDenoising(gray, None, h=10, 
                                              templateWindowSize=7, 
                                              searchWindowSize=21)
            
            # Contrast enhancement dengan CLAHE
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            contrast1 = clahe.apply(denoised)
            
            # Thresholding Otsu
            _, binary1 = cv2.threshold(contrast1, 0, 255, 
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            processed_images.append(binary1)
            
            # ============================================
            # STAGE 2: Sharpening & Edge Enhancement
            # ============================================
            # Sharpening kernel
            kernel_sharpen = np.array([[-1,-1,-1],
                                       [-1, 9,-1],
                                       [-1,-1,-1]])
            sharpened = cv2.filter2D(denoised, -1, kernel_sharpen)
            
            # Edge enhancement dengan Canny + dilation
            edges = cv2.Canny(sharpened, 50, 150)
            kernel = np.ones((2,2), np.uint8)
            edges_dilated = cv2.dilate(edges, kernel, iterations=1)
            
            # Gabungkan edges dengan image asli
            enhanced = cv2.addWeighted(sharpened, 0.7, edges_dilated, 0.3, 0)
            
            # Contrast enhancement lagi
            contrast2 = clahe.apply(enhanced)
            _, binary2 = cv2.threshold(contrast2, 0, 255, 
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            processed_images.append(binary2)
            
            # ============================================
            # STAGE 3: Morphological Operations
            # ============================================
            # Closing untuk menghubungkan karakter yang putus
            kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
            closed = cv2.morphologyEx(binary1, cv2.MORPH_CLOSE, kernel_close)
            
            # Opening untuk menghilangkan noise kecil
            kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
            opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel_open)
            
            processed_images.append(opened)
            
            # ============================================
            # STAGE 4: Adaptive Thresholding
            # ============================================
            adaptive = cv2.adaptiveThreshold(denoised, 255, 
                                           cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, 11, 2)
            
            processed_images.append(adaptive)
            
            print(f"📸 Pre-processing: {len(processed_images)} stage berhasil")
            
        except Exception as e:
            print(f"❌ Error pre-processing: {str(e)}")
            # Jika error, tetap return minimal 1 image
            if len(processed_images) == 0:
                processed_images.append(gray if 'gray' in locals() else img)
        
        return processed_images

    def _clean_text(self, text):
        """
        Membersihkan teks hasil OCR
        
        Args:
            text (str): Teks mentah dari OCR
            
        Returns:
            str: Teks yang sudah dibersihkan
        """
        if not text:
            return None
        
        # Hapus karakter non-alphanumeric kecuali spasi (untuk sementara)
        cleaned = re.sub(r'[^A-Z0-9\s]', '', text.upper())
        
        # Hapus whitespace berlebihan
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Hapus karakter tunggal yang mungkin noise
        if len(cleaned) <= 2:
            return None
        
        return cleaned

    def _vote_best_result(self, all_texts):
        """
        Voting system untuk memilih hasil OCR terbaik
        
        Args:
            all_texts (list): List semua hasil OCR dari berbagai runs
            
        Returns:
            str: Hasil terpilih
        """
        if not all_texts:
            return None
        
        # Hitung frekuensi setiap teks
        text_counter = Counter(all_texts)
        
        # Ambil teks dengan frekuensi tertinggi
        most_common = text_counter.most_common(1)
        if most_common:
            best_text, count = most_common[0]
            
            # Jika frekuensi cukup tinggi (minimal 2 kali muncul)
            if count >= 2:
                print(f"🏆 Voting: '{best_text}' muncul {count} kali dari {len(all_texts)} runs")
                return best_text
        
        # Jika tidak ada yang muncul lebih dari sekali, ambil yang terpanjang
        # (biasanya yang lebih lengkap)
        longest_text = max(all_texts, key=len)
        print(f"📏 Fallback ke teks terpanjang: '{longest_text}'")
        return longest_text

    def _calculate_ocr_confidence(self, all_texts, selected_text):
        """
        Menghitung confidence level berdasarkan konsistensi hasil
        
        Args:
            all_texts (list): List semua hasil OCR
            selected_text (str): Teks yang terpilih
            
        Returns:
            float: Confidence level (0-1)
        """
        if not all_texts:
            return 0.0
        
        # Hitung berapa kali selected_text muncul
        count_selected = all_texts.count(selected_text)
        
        # Confidence berdasarkan konsistensi
        consistency = count_selected / len(all_texts)
        
        # Confidence berdasarkan kemiripan dengan teks lain
        similarities = []
        for text in set(all_texts):
            if text != selected_text:
                similarity = SequenceMatcher(None, selected_text, text).ratio()
                similarities.append(similarity)
        
        avg_similarity = np.mean(similarities) if similarities else 0
        
        # Gabungkan consistency dan similarity
        confidence = 0.7 * consistency + 0.3 * avg_similarity
        
        # Penalti jika teks terlalu pendek
        if len(selected_text) < 5:
            confidence *= 0.7
        
        return min(confidence, 1.0)

    def _validate_plate_format(self, plate_text):
        """
        Validasi format plat nomor
        
        Args:
            plate_text (str): Teks plat untuk divalidasi
            
        Returns:
            str: Plat yang sudah diformat (None jika tidak valid)
        """
        if not plate_text:
            return None
        
        # HAPUS SEMUA SPASI
        clean_text = re.sub(r'\s+', '', plate_text.upper())
        
        # Cari pola: 1-2 huruf + 1-4 angka + 1-3 huruf (TANPA SPASI)
        match = re.search(r'([A-Z]{1,2})(\d{1,4})([A-Z]{1,3})', clean_text)
        
        if match:
            # Format: AB1234CD (TANPA SPASI)
            formatted = f"{match.group(1)}{match.group(2)}{match.group(3)}"
            return formatted
        else:
            # Jika format tidak sesuai, coba ekstrak karakter alphanumeric saja
            alphanumeric = re.sub(r'[^A-Z0-9]', '', clean_text)
            if len(alphanumeric) >= 5:
                return alphanumeric[:10]  # Batasi panjang
        
        return None

    def _draw_detection_overlay(self, frame, bbox, plate_text, yolo_confidence, ocr_confidence):
        """
        Menggambar bounding box dan teks pada frame dengan info lengkap
        
        Args:
            frame (numpy.ndarray): Frame asli
            bbox (tuple): Koordinat bounding box
            plate_text (str): Teks plat yang terdeteksi
            yolo_confidence (float): Confidence dari YOLO
            ocr_confidence (float): Confidence dari OCR
            
        Returns:
            numpy.ndarray: Frame dengan overlay
        """
        try:
            x1, y1, x2, y2 = bbox
            
            # Warna berdasarkan confidence total
            total_confidence = (yolo_confidence + ocr_confidence) / 2
            
            if total_confidence > 0.7:
                color = (0, 255, 0)  # Hijau
            elif total_confidence > 0.5:
                color = (0, 255, 255)  # Kuning
            else:
                color = (0, 0, 255)  # Merah
            
            # Gambar bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            # Label dengan info lengkap
            label = f"{plate_text}"
            confidence_label = f"YOLO: {yolo_confidence:.2f}, OCR: {ocr_confidence:.2f}"
            
            # Background untuk label utama
            (label_width, label_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
            )
            label_bg_top = y1 - label_height - 10
            
            # Gambar background
            cv2.rectangle(frame, (x1, label_bg_top - 5), 
                         (x1 + label_width + 10, y1), color, -1)
            
            # Teks label utama
            cv2.putText(frame, label, (x1 + 5, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            
            # Label confidence (lebih kecil)
            (conf_width, conf_height), _ = cv2.getTextSize(
                confidence_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1
            )
            
            cv2.putText(frame, confidence_label, (x1, y2 + conf_height + 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            
            return frame
            
        except Exception as e:
            print(f"❌ Error menggambar overlay: {str(e)}")
            return frame

    def save_snapshot(self, path, frame):
        """
        Menyimpan snapshot frame ke file
        
        Args:
            path (str): Path untuk menyimpan file
            frame (numpy.ndarray): Frame yang akan disimpan
            
        Returns:
            bool: True jika berhasil, False jika gagal
        """
        try:
            # Buat directory jika belum ada
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            # Simpan frame
            success = cv2.imwrite(path, frame)
            
            if success:
                print(f"✅ Snapshot disimpan: {path}")
            else:
                print(f"❌ Gagal menyimpan snapshot: {path}")
                
            return success
            
        except Exception as e:
            print(f"❌ Error menyimpan snapshot: {str(e)}")
            return False

    def normalize_plate(self, plate_text):
        """
        Normalisasi format plat nomor: HAPUS SEMUA SPASI
        
        Args:
            plate_text (str): Teks plat untuk dinormalisasi
            
        Returns:
            str: Plat yang sudah dinormalisasi
        """
        try:
            if not plate_text:
                return None
                
            # Hapus semua spasi dan karakter non-alphanumeric, convert ke uppercase
            normalized = re.sub(r'[^A-Z0-9]', '', plate_text.upper())
            
            # Validasi format minimal
            if len(normalized) < 5:  # Minimal AB123C
                return None
                
            return normalized
            
        except Exception as e:
            print(f"❌ Error normalisasi plat: {str(e)}")
            return None

    def get_processing_stats(self):
        """
        Mendapatkan statistik processing untuk monitoring
        
        Returns:
            dict: Statistik processing
        """
        # Fungsi ini bisa digunakan untuk monitoring performance
        return {
            'ocr_configs': len(self.OCR_CONFIGS),
            'min_confidence': self.model.overrides['conf'],
            'plate_pattern': self.PLATE_PATTERN
        }

# Contoh penggunaan untuk testing
if __name__ == "__main__":
    print("🧪 Testing PlateDetector OCR Pipeline")
    
    # Test dengan gambar sample
    test_image_path = "D:/percobaan pake patch/plat-113-_jpg.rf.cc2e2724368b20be9dd1ad548545671e.jpg"
    
    detector = PlateDetector('models/best.pt')
    
    if os.path.exists(test_image_path):
        test_frame = cv2.imread(test_image_path)
        
        if test_frame is not None:
            print(f"📷 Membaca gambar test: {test_image_path}")
            result = detector.detect_plate(test_frame)
            
            print(f"\n📊 HASIL DETEKSI:")
            print(f"  Plate Text: {result['plate_text']}")
            print(f"  YOLO Confidence: {result['confidence']:.2f}")
            print(f"  OCR Confidence: {result['ocr_confidence']:.2f}")
            print(f"  Total Processing Time: {result['processing_time']:.3f}s")
            print(f"  YOLO Time: {result['yolo_time']:.3f}s")
            print(f"  OCR Time: {result['processing_time'] - result['yolo_time']:.3f}s")
            
            if result['ocr_results']:
                print(f"\n🔍 DETAIL OCR RUNS:")
                for i, ocr_result in enumerate(result['ocr_results']):
                    print(f"  Run {i+1}: Stage {ocr_result['stage']}, Config {ocr_result['config']}")
                    print(f"    Text: {ocr_result['text']}")
                    print(f"    Raw: {ocr_result['raw_text']}")
            
            # Test normalisasi
            test_plates = ["AB 1234 CD", "AB1234CD", "B 123 XYZ", "B123XYZ", "INVALID123"]
            print(f"\n🔧 TESTING NORMALISASI PLAT:")
            for plate in test_plates:
                normalized = detector.normalize_plate(plate)
                print(f"  '{plate}' -> '{normalized}'")
            
            # Tampilkan hasil
            cv2.imshow('Detection Result', result['frame_with_overlay'])
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        else:
            print("❌ Gagal membaca gambar test")
    else:
        print(f"⚠️  File test tidak ditemukan: {test_image_path}")
        print("✅ Inisialisasi detector berhasil")