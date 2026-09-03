import cv2
import os
import time
import io
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, Response, jsonify, request, flash, make_response, session
import database.db as db
from yolov8_ocr import PlateDetector
import pandas as pd
import re
import threading

# ==============================
# KONFIGURASI APLIKASI         =  
# ==============================
class Config:
    """Konfigurasi aplikasi"""
    SECRET_KEY = 'parking_system_uty_secret_key_2026'
    MODEL_PATH = 'D:/percobaan pake patch/models/best.pt'
    TESSERACT_PATH = r"C:\Users\LENOVO\Videos\tocr\tesseract.exe"
    CAMERA_INDEX = 0
    UPLOAD_FOLDER = 'static/entries'
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
    OCR_PROCESSING_TIMEOUT = 3.0  # Timeout untuk OCR processing (detik)
    MAX_ACTIVE_VEHICLES = 100  # Maksimal kendaraan aktif yang dilacak

# ==============================
# INISIALISASI APLIKASI        =
# ==============================
app = Flask(__name__)
app.config.from_object(Config)

# Buat folder upload jika belum ada
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

# Inisialisasi detektor plat nomor dengan pipeline OCR baru
plate_detector = PlateDetector(model_path=Config.MODEL_PATH)

# Variabel global untuk manajemen kamera dan tracking
latest_frame = None
camera_active = False
active_vehicles = {}  # Dictionary untuk tracking kendaraan aktif
active_vehicles_lock = threading.Lock()  # Lock untuk thread safety

# ==============================
# UTILITY FUNCTIONS
# ==============================
def generate_timestamp():
    """Generate timestamp untuk nama file"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def save_snapshot(frame, prefix):
    """Simpan snapshot frame ke file"""
    if frame is not None:
        timestamp = generate_timestamp()
        image_path = f"{Config.UPLOAD_FOLDER}/{prefix}_{timestamp}.jpg"
        plate_detector.save_snapshot(image_path, frame)
        return image_path
    return None

def normalize_plate(plate_text):
    """Normalisasi format plat nomor: HAPUS SEMUA SPASI"""
    if not plate_text:
        return None
    # Hapus semua spasi dan convert ke uppercase
    return re.sub(r'\s+', '', plate_text).upper()

def validate_manual_entry_data(data):
    """Validasi data untuk entry manual"""
    required_fields = ['kategori', 'plat_nomor']
    for field in required_fields:
        if not data.get(field):
            return False, f'Field {field} wajib diisi'
    
    plat_nomor = normalize_plate(data.get('plat_nomor', ''))
    if not plat_nomor:
        return False, 'Plat nomor wajib diisi'
    
    # Validasi format plat nomor (TANPA SPASI)
    plat_pattern = r'^[A-Z]{1,2}\d{1,4}[A-Z]{1,3}$'
    if not re.match(plat_pattern, plat_nomor):
        return False, 'Format plat nomor tidak valid. Contoh: AB1234CD atau B123XYZ'
    
    return True, plat_nomor

def validate_registration_data(data):
    """Validasi data untuk registrasi pengguna baru - FIXED TANPA KEPERLUAN"""
    required_fields = ['nama', 'kategori', 'plat_nomor', 'no_telp', 'email', 'merk_model', 'warna']
    
    # Cek field required dengan handling None
    for field in required_fields:
        if not data.get(field):
            return False, f'Field {field} wajib diisi'
    
    # Validasi kategori
    kategori = data.get('kategori')
    if kategori not in ['Mahasiswa', 'Dosen', 'Staff', 'Tamu']:
        return False, 'Kategori tidak valid'
    
    # Validasi NPM/NIP untuk non-tamu - FIXED None handling
    if kategori != 'Tamu':
        npm_nip = data.get('npm_nip')
        if not npm_nip:
            return False, f'NPM/NIP wajib diisi untuk {kategori}'
        # Validasi NPM/NIP hanya angka
        if not re.match(r'^\d+$', str(npm_nip)):
            return False, f'NPM/NIP hanya boleh mengandung angka untuk {kategori}'
    
    # Untuk tamu, TIDAK ADA validasi keperluan di registrasi
    
    # Validasi no telepon (angka saja, 10-13 digit) - FIXED None handling
    no_telp = str(data.get('no_telp', ''))
    if not re.match(r'^\d{10,13}$', no_telp):
        return False, 'Nomor telepon harus 10-13 digit angka'
    
    # Validasi email - FIXED None handling
    email = str(data.get('email', ''))
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return False, 'Format email tidak valid'
    
    # Validasi plat nomor - FIXED: NORMALIZE PLAT (TANPA SPASI)
    plat_nomor = normalize_plate(data.get('plat_nomor', ''))
    plat_pattern = r'^[A-Z]{1,2}\d{1,4}[A-Z]{1,3}$'
    if not re.match(plat_pattern, plat_nomor):
        return False, 'Format plat nomor tidak valid. Contoh: AB1234CD atau B123XYZ'
    
    # Validasi nama (huruf dan spasi saja) - FIXED None handling
    nama = str(data.get('nama', ''))
    if not re.match(r'^[a-zA-Z\s]+$', nama):
        return False, 'Nama hanya boleh mengandung huruf dan spasi'
    
    # Validasi merk_model (huruf, angka, spasi) - FIXED None handling
    merk_model = str(data.get('merk_model', ''))
    if not re.match(r'^[a-zA-Z0-9\s]+$', merk_model):
        return False, 'Merk & model hanya boleh mengandung huruf, angka, dan spasi'
    
    # Validasi warna (huruf dan spasi saja) - FIXED None handling
    warna = str(data.get('warna', ''))
    if not re.match(r'^[a-zA-Z\s]+$', warna):
        return False, 'Warna hanya boleh mengandung huruf dan spasi'
    
    # Cek apakah plat sudah terdaftar (DI SEMUA KATEGORI)
    if db.check_plate_exists(plat_nomor):
        return False, f'Plat nomor {plat_nomor} sudah terdaftar di sistem'
    
    return True, plat_nomor

def add_active_vehicle(plat_nomor, entry_id, entry_time):
    """Menambahkan kendaraan ke tracking aktif"""
    with active_vehicles_lock:
        if len(active_vehicles) < Config.MAX_ACTIVE_VEHICLES:
            active_vehicles[plat_nomor] = {
                'entry_id': entry_id,
                'entry_time': entry_time,
                'last_seen': datetime.now(),
                'status': 'parked'
            }
            print(f"✅ Kendaraan {plat_nomor} ditambahkan ke tracking aktif")
            return True
        else:
            print(f"⚠️  Tidak bisa menambahkan {plat_nomor}, maksimal {Config.MAX_ACTIVE_VEHICLES} kendaraan aktif")
            return False

def remove_active_vehicle(plat_nomor):
    """Menghapus kendaraan dari tracking aktif"""
    with active_vehicles_lock:
        if plat_nomor in active_vehicles:
            del active_vehicles[plat_nomor]
            print(f"✅ Kendaraan {plat_nomor} dihapus dari tracking aktif")
            return True
        return False

def get_active_vehicle(plat_nomor):
    """Mendapatkan info kendaraan aktif"""
    with active_vehicles_lock:
        return active_vehicles.get(plat_nomor)

def update_active_vehicle_seen(plat_nomor):
    """Update last seen untuk kendaraan aktif"""
    with active_vehicles_lock:
        if plat_nomor in active_vehicles:
            active_vehicles[plat_nomor]['last_seen'] = datetime.now()
            return True
        return False

def cleanup_inactive_vehicles(max_inactive_minutes=120):
    """Membersihkan kendaraan yang sudah tidak aktif"""
    with active_vehicles_lock:
        now = datetime.now()
        removed_count = 0
        
        for plat_nomor, vehicle_info in list(active_vehicles.items()):
            inactive_minutes = (now - vehicle_info['last_seen']).total_seconds() / 60
            
            if inactive_minutes > max_inactive_minutes:
                del active_vehicles[plat_nomor]
                removed_count += 1
                print(f"🧹 Kendaraan {plat_nomor} dihapus (inactive: {inactive_minutes:.1f} menit)")
        
        if removed_count > 0:
            print(f"🧹 Cleanup: {removed_count} kendaraan dihapus karena tidak aktif")

def get_active_vehicles_count():
    """Mendapatkan jumlah kendaraan aktif"""
    with active_vehicles_lock:
        return len(active_vehicles)

def calculate_parking_duration(entry_time, exit_time=None):
    """Menghitung durasi parkir"""
    if not exit_time:
        exit_time = datetime.now()
    
    duration = exit_time - entry_time
    total_seconds = duration.total_seconds()
    
    # Format duration
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    
    if hours > 0:
        return f"{hours} jam {minutes} menit"
    elif minutes > 0:
        return f"{minutes} menit {seconds} detik"
    else:
        return f"{seconds} detik"

# ==============================
# VIDEO STREAMING
# ==============================
def generate_frames():
    """Generator untuk video streaming real-time dengan deteksi YOLO"""
    global latest_frame, camera_active
    
    cap = cv2.VideoCapture(Config.CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    camera_active = True
    
    try:
        while camera_active:
            success, frame = cap.read()
            if not success:
                break
            
            # Deteksi plat nomor dengan YOLO dan OCR pipeline baru
            detection_result = plate_detector.detect_plate(frame)
            processed_frame = detection_result['frame_with_overlay']
            
            # Encode frame untuk streaming
            ret, buffer = cv2.imencode('.jpg', processed_frame)
            frame_bytes = buffer.tobytes()
            
            # Simpan frame terbaru untuk snapshot
            latest_frame = frame.copy()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            time.sleep(0.03)
            
    except Exception as e:
        print(f"❌ Error dalam video stream: {str(e)}")
    finally:
        cap.release()
        camera_active = False

# ==============================
# BACKGROUND TASKS
# ==============================
def background_cleanup_task():
    """Background task untuk membersihkan kendaraan tidak aktif"""
    while True:
        try:
            cleanup_inactive_vehicles()
            time.sleep(300)  # Cek setiap 5 menit
        except Exception as e:
            print(f"❌ Error dalam background cleanup: {str(e)}")
            time.sleep(60)

# Start background cleanup thread
cleanup_thread = threading.Thread(target=background_cleanup_task, daemon=True)
cleanup_thread.start()
print("✅ Background cleanup task started")

# ==============================
# ROUTES - HALAMAN UTAMA & MENU
# ==============================
@app.route('/')
def index():
    """Halaman utama dengan menu dan statistik real-time"""
    # Ambil statistik kendaraan untuk ditampilkan
    stats = db.get_statistics()
    vehicle_stats = stats.get('vehicle_statistics', {})
    
    # Hitung kendaraan aktif dari tracking
    active_count = get_active_vehicles_count()
    
    return render_template('index.html', 
                          vehicle_stats=vehicle_stats,
                          active_vehicles_count=active_count)

@app.route('/masuk')
def masuk():
    """Halaman entry kendaraan masuk"""
    return render_template('masuk.html')

@app.route('/keluar')
def keluar():
    """Halaman exit kendaraan keluar"""
    return render_template('keluar.html')

@app.route('/riwayat')
def riwayat():
    """Halaman riwayat aktifitas dengan filter dan pagination"""
    try:
        # Get filter parameters
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        kategori = request.args.get('kategori')
        status = request.args.get('status')
        
        # Calculate offset for pagination
        offset = (page - 1) * limit
        
        # Get filtered logs
        logs, total_count = db.get_filtered_logs(
            start_date=start_date,
            end_date=end_date,
            kategori=kategori,
            status=status,
            limit=limit,
            offset=offset
        )
        
        # Get statistics
        total_stats = db.get_statistics()
        
        # Calculate total pages
        total_pages = (total_count + limit - 1) // limit
        
        # Build filter params for pagination
        filter_params = ""
        if start_date:
            filter_params += f"&start_date={start_date}"
        if end_date:
            filter_params += f"&end_date={end_date}"
        if kategori:
            filter_params += f"&kategori={kategori}"
        if status:
            filter_params += f"&status={status}"
        
        # Tambahkan info kendaraan aktif
        active_count = get_active_vehicles_count()
        
        return render_template('riwayat.html', 
                             logs=logs,
                             total_stats=total_stats,
                             page=page,
                             limit=limit,
                             total_pages=total_pages,
                             filter_params=filter_params,
                             active_vehicles_count=active_count)
                             
    except Exception as e:
        flash(f"Error loading riwayat: {str(e)}", "error")
        return render_template('riwayat.html', 
                             logs=[],
                             total_stats={'total_transactions': 0, 'active_entries': 0, 'today_entries': 0, 'manual_verifications': 0},
                             page=1,
                             limit=50,
                             total_pages=1,
                             filter_params="",
                             active_vehicles_count=0)

@app.route('/registrasi')
def registrasi():
    """Halaman registrasi pengguna dan kendaraan baru"""
    return render_template('registrasi.html')

@app.route('/daftar_kendaraan')
def daftar_kendaraan():
    """Halaman daftar kendaraan terdaftar"""
    try:
        # Get filter parameters
        kategori = request.args.get('kategori', '')
        search = request.args.get('search', '')
        
        # Get all pengguna dengan kendaraan
        pengguna_list = db.get_all_pengguna()
        
        # Filter data jika ada parameter
        filtered_data = []
        for pengguna in pengguna_list:
            # Filter by kategori
            if kategori and pengguna['kategori'] != kategori:
                continue
            
            # Filter by search (nama, npm_nip, plat_nomor)
            if search:
                search_lower = search.lower()
                if (search_lower not in pengguna['nama'].lower() and 
                    (not pengguna['npm_nip'] or search_lower not in str(pengguna['npm_nip']).lower()) and
                    (not pengguna['plat_nomor'] or search_lower not in pengguna['plat_nomor'].lower())):
                    continue
            
            filtered_data.append(pengguna)
        
        # Get vehicle statistics
        stats = db.get_statistics()
        vehicle_stats = stats.get('vehicle_statistics', {})
        
        return render_template('daftar_kendaraan.html', 
                             pengguna_list=filtered_data,
                             vehicle_stats=vehicle_stats,
                             selected_kategori=kategori,
                             search_query=search)
                             
    except Exception as e:
        flash(f"Error loading daftar kendaraan: {str(e)}", "error")
        return render_template('daftar_kendaraan.html', 
                             pengguna_list=[],
                             vehicle_stats={},
                             selected_kategori='',
                             search_query='')

# ==============================
# ROUTES - VIDEO & DETECTION
# ==============================
@app.route('/video_feed')
def video_feed():
    """Endpoint untuk video streaming"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/detect_entry', methods=['POST'])
def detect_entry():
    """Endpoint untuk deteksi dan proses masuk otomatis dengan OCR pipeline baru"""
    try:
        if latest_frame is None:
            return jsonify({
                'success': False, 
                'message': 'Tidak ada frame dari kamera',
                'error_type': 'camera_error'
            })
        
        print("🔄 Memulai proses deteksi masuk...")
        
        # Deteksi plat nomor dengan OCR pipeline baru
        detection_result = plate_detector.detect_plate(latest_frame)
        plate_text = detection_result['plate_text']
        yolo_confidence = detection_result['confidence']
        ocr_confidence = detection_result['ocr_confidence']
        processing_time = detection_result['processing_time']
        
        print(f"📊 Hasil Deteksi: {plate_text}")
        print(f"📊 Confidence - YOLO: {yolo_confidence:.2f}, OCR: {ocr_confidence:.2f}")
        print(f"⏱️  Processing Time: {processing_time:.3f}s")
        
        # NORMALIZE PLAT: HAPUS SPASI
        normalized_plate = normalize_plate(plate_text) if plate_text else None
        
        if not normalized_plate:
            return jsonify({
                'success': False, 
                'message': 'Plat nomor tidak terdeteksi',
                'detected_plate': None,
                'yolo_confidence': 0,
                'ocr_confidence': 0,
                'processing_time': processing_time,
                'error_type': 'no_plate_detected'
            })
        
        # CEK KENDARAAN AKTIF DARI TRACKING
        active_tracking = get_active_vehicle(normalized_plate)
        if active_tracking:
            return jsonify({
                'success': False,
                'message': f'Kendaraan dengan plat {normalized_plate} masih berada di dalam area parkir',
                'detected_plate': normalized_plate,
                'yolo_confidence': yolo_confidence,
                'ocr_confidence': ocr_confidence,
                'processing_time': processing_time,
                'need_manual_verify': True,
                'error_type': 'double_entry',
                'entry_time': active_tracking['entry_time'].strftime('%Y-%m-%d %H:%M:%S')
            })
        
        # CEK DOUBLE ENTRY: Cek apakah sudah ada aktifitas aktif di database
        active_entry = db.get_active_entry_by_plate(normalized_plate)
        if active_entry:
            # Update tracking jika ada di database tapi tidak di tracking
            add_active_vehicle(normalized_plate, active_entry.get('id_log'), 
                             active_entry.get('waktu_masuk'))
            return jsonify({
                'success': False,
                'message': f'Kendaraan dengan plat {normalized_plate} masih berada di dalam area parkir',
                'detected_plate': normalized_plate,
                'yolo_confidence': yolo_confidence,
                'ocr_confidence': ocr_confidence,
                'processing_time': processing_time,
                'need_manual_verify': True,
                'error_type': 'double_entry',
                'entry_time': active_entry.get('waktu_masuk').strftime('%Y-%m-%d %H:%M:%S')
            })
        
        # Simpan snapshot masuk
        entry_image_path = save_snapshot(latest_frame, 'entry')
        
        # Cek apakah kendaraan terdaftar (GUNAKAN PLAT NORMALIZED)
        user_info = db.find_user_by_npm_or_plate(normalized_plate)
        
        response_data = {
            'success': True,
            'message': 'Kendaraan terdaftar - Palang terbuka',
            'detected_plate': normalized_plate,
            'yolo_confidence': yolo_confidence,
            'ocr_confidence': ocr_confidence,
            'total_confidence': (yolo_confidence + ocr_confidence) / 2,
            'processing_time': processing_time,
            'entry_image': entry_image_path
        }
        
        if user_info:
            # Kendaraan terdaftar - buat entry otomatis
            id_petugas = 1  # Default petugas
            
            entry_id = db.create_entry(
                plat=normalized_plate,
                id_petugas=id_petugas,
                entry_image=entry_image_path,
                method='otomatis'
            )
            
            if entry_id:
                # Tambahkan ke tracking aktif
                add_active_vehicle(normalized_plate, entry_id, datetime.now())
                response_data.update({
                    'user_info': user_info,
                    'entry_id': entry_id,
                    'status': 'registered'
                })
            else:
                response_data.update({
                    'success': False,
                    'message': 'Gagal membuat entry di database',
                    'status': 'database_error'
                })
        else:
            # Kendaraan tidak terdaftar - butuh verifikasi manual
            response_data.update({
                'success': False,
                'message': 'Kendaraan tidak terdaftar - Verifikasi manual diperlukan',
                'need_manual_verify': True,
                'status': 'unregistered'
            })
        
        return jsonify(response_data)
            
    except Exception as e:
        print(f"❌ Error dalam detect_entry: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

@app.route('/verify_exit', methods=['POST'])
def verify_exit():
    """Endpoint untuk verifikasi dan proses keluar dengan OCR pipeline baru"""
    try:
        if latest_frame is None:
            return jsonify({
                'success': False, 
                'message': 'Tidak ada frame dari kamera',
                'error_type': 'camera_error'
            })
        
        print("🔄 Memulai proses verifikasi keluar...")
        
        # Deteksi plat nomor dengan OCR pipeline baru
        detection_result = plate_detector.detect_plate(latest_frame)
        plate_text = detection_result['plate_text']
        yolo_confidence = detection_result['confidence']
        ocr_confidence = detection_result['ocr_confidence']
        processing_time = detection_result['processing_time']
        
        print(f"📊 Hasil Deteksi: {plate_text}")
        print(f"📊 Confidence - YOLO: {yolo_confidence:.2f}, OCR: {ocr_confidence:.2f}")
        
        # NORMALIZE PLAT: HAPUS SPASI
        normalized_plate = normalize_plate(plate_text) if plate_text else None
        
        if not normalized_plate:
            return jsonify({
                'success': False, 
                'message': 'Plat nomor tidak terdeteksi',
                'detected_plate': None,
                'yolo_confidence': 0,
                'ocr_confidence': 0,
                'processing_time': processing_time,
                'error_type': 'no_plate_detected'
            })
        
        # CEK TRACKING AKTIF PERTAMA
        active_tracking = get_active_vehicle(normalized_plate)
        
        if not active_tracking:
            # Jika tidak ada di tracking, cek di database
            active_entry = db.get_active_entry_by_plate(normalized_plate)
            
            if active_entry:
                # Ada di database, tambahkan ke tracking
                add_active_vehicle(normalized_plate, active_entry.get('id_log'), 
                                 active_entry.get('waktu_masuk'))
                active_tracking = get_active_vehicle(normalized_plate)
            else:
                # Tidak ada aktifitas masuk aktif
                return jsonify({
                    'success': False,
                    'message': 'Tidak ada aktifitas masuk aktif untuk plat ini',
                    'detected_plate': normalized_plate,
                    'yolo_confidence': yolo_confidence,
                    'ocr_confidence': ocr_confidence,
                    'need_manual_verify': True,
                    'error_type': 'no_active_entry',
                    'processing_time': processing_time
                })
        
        # Proses exit
        exit_image_path = save_snapshot(latest_frame, 'exit')
        id_petugas = 1
        
        # Complete exit process di database
        success = db.complete_exit(
            plat=normalized_plate,
            id_petugas=id_petugas,
            exit_image=exit_image_path
        )
        
        if success:
            # Hapus dari tracking aktif
            remove_active_vehicle(normalized_plate)
            
            # Dapatkan info user untuk response
            user_info = db.find_user_by_npm_or_plate(normalized_plate)
            
            # Hitung durasi parkir
            entry_time = active_tracking['entry_time']
            exit_time = datetime.now()
            parking_duration = calculate_parking_duration(entry_time, exit_time)
            
            return jsonify({
                'success': True,
                'message': 'Exit berhasil - Palang terbuka',
                'detected_plate': normalized_plate,
                'yolo_confidence': yolo_confidence,
                'ocr_confidence': ocr_confidence,
                'total_confidence': (yolo_confidence + ocr_confidence) / 2,
                'processing_time': processing_time,
                'user_info': user_info,
                'entry_info': {
                    'entry_time': entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'parking_duration': parking_duration
                },
                'exit_image': exit_image_path
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Gagal mencatat exit di database',
                'detected_plate': normalized_plate,
                'yolo_confidence': yolo_confidence,
                'ocr_confidence': ocr_confidence,
                'processing_time': processing_time,
                'error_type': 'database_error'
            })
            
    except Exception as e:
        print(f"❌ Error dalam verify_exit: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

# ==============================
# ROUTES - MANUAL VERIFICATION
# ==============================
@app.route('/manual_verify', methods=['POST'])
def manual_verify():
    """Endpoint untuk verifikasi manual oleh petugas"""
    try:
        data = request.get_json()
        
        # Validasi action_type wajib
        action_type = data.get('action_type')
        if not action_type:
            return jsonify({
                'success': False, 
                'message': 'Tipe aksi wajib diisi',
                'error_type': 'validation_error'
            })
        
        if action_type == 'masuk':
            return handle_manual_entry(data)
        elif action_type == 'keluar':
            return handle_manual_exit(data)
        else:
            return jsonify({
                'success': False, 
                'message': 'Tipe aksi tidak valid',
                'error_type': 'validation_error'
            })
            
    except Exception as e:
        print(f"❌ Error dalam manual_verify: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

def handle_manual_entry(data):
    """Handle verifikasi manual untuk MASUK"""
    try:
        # Validasi data
        is_valid, result = validate_manual_entry_data(data)
        if not is_valid:
            return jsonify({
                'success': False, 
                'message': result,
                'error_type': 'validation_error'
            })
        
        plat_nomor = result  # Sudah dinormalisasi (tanpa spasi)
        kategori = data.get('kategori')
        
        # CEK TRACKING AKTIF
        active_tracking = get_active_vehicle(plat_nomor)
        if active_tracking:
            return jsonify({
                'success': False,
                'message': f'Kendaraan dengan plat {plat_nomor} masih berada di dalam area parkir',
                'detected_plate': plat_nomor,
                'error_type': 'double_entry',
                'entry_time': active_tracking['entry_time'].strftime('%Y-%m-%d %H:%M:%S')
            })
        
        # CEK DOUBLE ENTRY di database
        active_entry = db.get_active_entry_by_plate(plat_nomor)
        if active_entry:
            # Update tracking
            add_active_vehicle(plat_nomor, active_entry.get('id_log'), 
                             active_entry.get('waktu_masuk'))
            return jsonify({
                'success': False,
                'message': f'Kendaraan dengan plat {plat_nomor} masih berada di dalam area parkir',
                'detected_plate': plat_nomor,
                'error_type': 'double_entry',
                'entry_time': active_entry.get('waktu_masuk').strftime('%Y-%m-%d %H:%M:%S')
            })
        
        # Default petugas
        id_petugas = 1
        
        # VALIDASI BERDASARKAN KATEGORI
        if kategori == 'Tamu':
            return handle_tamu_entry(data, plat_nomor, id_petugas)
        else:  # Mahasiswa, Dosen, atau Staff
            return handle_registered_entry(data, plat_nomor, kategori, id_petugas)
        
    except Exception as e:
        print(f"❌ Error handle manual entry: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error handle manual entry: {str(e)}',
            'error_type': 'server_error'
        })

def handle_tamu_entry(data, plat_nomor, id_petugas):
    """Handle entry untuk tamu"""
    nama = str(data.get('nama', '')).strip()
    keperluan = str(data.get('keperluan', '')).strip()
    
    if not nama:
        return jsonify({
            'success': False, 
            'message': 'Nama tamu wajib diisi',
            'error_type': 'validation_error'
        })
    if not keperluan:
        return jsonify({
            'success': False, 
            'message': 'Keperluan tamu wajib diisi',
            'error_type': 'validation_error'
        })
    
    # Validasi nama (huruf dan spasi saja)
    if not re.match(r'^[a-zA-Z\s]+$', nama):
        return jsonify({
            'success': False, 
            'message': 'Nama hanya boleh mengandung huruf dan spasi',
            'error_type': 'validation_error'
        })
    
    # Cek dulu apakah plat sudah ada di database (DI SEMUA KATEGORI)
    existing_user = db.find_user_by_npm_or_plate(plat_nomor)
    
    if existing_user:
        # Plat sudah terdaftar, gunakan data existing
        user_info = existing_user
        user_id = user_info['id_pengguna']
    else:
        # Buat user baru untuk tamu - TANPA KEPERLUAN di database
        user_id, message = db.create_pengguna(
            nama=nama,
            npm_nip=None,  # Tamu tidak punya NPM/NIP
            kategori='Tamu',
            no_telp=data.get('no_telp', '081234567890'),  # Default jika tidak ada
            email=data.get('email', 'tamu@example.com')   # Default jika tidak ada
        )
        
        if not user_id:
            return jsonify({
                'success': False, 
                'message': f'Gagal membuat data tamu: {message}',
                'error_type': 'database_error'
            })
        
        # Daftarkan kendaraan tamu
        success, message = db.create_kendaraan(
            id_pengguna=user_id,
            plat_nomor=plat_nomor,
            merk_model=data.get('merk_model', 'Kendaraan Tamu'),
            warna=data.get('warna', 'Tidak Diketahui')
        )
        
        if not success:
            return jsonify({
                'success': False, 
                'message': f'Gagal mendaftarkan kendaraan tamu: {message}',
                'error_type': 'database_error'
            })
        
        user_info = {
            'id_pengguna': user_id,
            'nama': nama,
            'kategori': 'Tamu',
            'plat_nomor': plat_nomor
        }
    
    return create_manual_entry(plat_nomor, user_info, id_petugas, 'Tamu', keperluan)

def handle_registered_entry(data, plat_nomor, kategori, id_petugas):
    """Handle entry untuk mahasiswa/dosen/staff terdaftar"""
    user_info = db.find_user_by_npm_or_plate(plat_nomor)
    
    if not user_info:
        return jsonify({
            'success': False, 
            'message': f'Plat {plat_nomor} tidak terdaftar sebagai {kategori}',
            'error_type': 'unregistered_plate'
        })
    
    # Validasi kategori sesuai
    if user_info['kategori'] != kategori:
        return jsonify({
            'success': False, 
            'message': f'Plat {plat_nomor} terdaftar sebagai {user_info["kategori"]}, bukan {kategori}',
            'error_type': 'category_mismatch'
        })
    
    keperluan = data.get('keperluan', f'Verifikasi manual - {kategori}')
    
    return create_manual_entry(plat_nomor, user_info, id_petugas, kategori, keperluan)

def create_manual_entry(plat_nomor, user_info, id_petugas, kategori, keperluan):
    """Buat entry manual di database dan tracking"""
    # Simpan snapshot masuk
    entry_image_path = save_snapshot(latest_frame, 'manual_entry')
    
    # Buat entry akses
    entry_id = db.create_entry(
        plat=plat_nomor,
        id_petugas=id_petugas,
        entry_image=entry_image_path,
        method='manual',
        keterangan=keperluan
    )
    
    if not entry_id:
        return jsonify({
            'success': False, 
            'message': 'Gagal mencatat aktifitas masuk',
            'error_type': 'database_error'
        })
    
    # Tambahkan ke tracking aktif
    add_active_vehicle(plat_nomor, entry_id, datetime.now())
    
    return jsonify({
        'success': True,
        'message': f'Verifikasi manual berhasil - Palang terbuka untuk {kategori}',
        'entry_id': entry_id,
        'user_info': user_info,
        'kategori': kategori,
        'entry_image': entry_image_path,
        'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

def handle_manual_exit(data):
    """Handle verifikasi manual untuk KELUAR"""
    try:
        plat_nomor = normalize_plate(data.get('plat_nomor', ''))  # NORMALIZE PLAT
        keperluan = str(data.get('keperluan', '')).strip()
        
        if not plat_nomor:
            return jsonify({
                'success': False, 
                'message': 'Plat nomor wajib diisi',
                'error_type': 'validation_error'
            })
        
        if not keperluan:
            return jsonify({
                'success': False, 
                'message': 'Keterangan/alasan wajib diisi untuk verifikasi manual keluar',
                'error_type': 'validation_error'
            })
        
        # Default petugas
        id_petugas = 1
        
        # CEK TRACKING AKTIF
        active_tracking = get_active_vehicle(plat_nomor)
        
        if active_tracking:
            return process_normal_exit(plat_nomor, id_petugas, keperluan, active_tracking)
        else:
            # Cek di database
            active_entry = db.get_active_entry_by_plate(plat_nomor)
            if active_entry:
                # Tambahkan ke tracking
                add_active_vehicle(plat_nomor, active_entry.get('id_log'), 
                                 active_entry.get('waktu_masuk'))
                active_tracking = get_active_vehicle(plat_nomor)
                return process_normal_exit(plat_nomor, id_petugas, keperluan, active_tracking)
            else:
                return process_override_exit(plat_nomor, id_petugas, keperluan)
                
    except Exception as e:
        print(f"❌ Error handle manual exit: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error handle manual exit: {str(e)}',
            'error_type': 'server_error'
        })

def process_normal_exit(plat_nomor, id_petugas, keperluan, active_tracking):
    """Proses exit normal dengan aktifitas aktif"""
    exit_image_path = save_snapshot(latest_frame, 'manual_exit')
    
    # Complete exit di database
    success = db.complete_exit(
        plat=plat_nomor,
        id_petugas=id_petugas,
        exit_image=exit_image_path
    )
    
    if success:
        # Hapus dari tracking
        remove_active_vehicle(plat_nomor)
        
        user_info = db.find_user_by_npm_or_plate(plat_nomor)
        
        # Hitung durasi parkir
        entry_time = active_tracking['entry_time']
        exit_time = datetime.now()
        parking_duration = calculate_parking_duration(entry_time, exit_time)
        
        return jsonify({
            'success': True,
            'message': 'Exit manual berhasil - Palang terbuka',
            'keterangan': keperluan,
            'user_info': user_info,
            'entry_info': {
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M:%S'),
                'parking_duration': parking_duration
            },
            'exit_image': exit_image_path
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Gagal mencatat exit di database',
            'error_type': 'database_error'
        })

def process_override_exit(plat_nomor, id_petugas, keperluan):
    """Proses exit override tanpa aktifitas aktif"""
    exit_image_path = save_snapshot(latest_frame, 'override_exit')
    
    # Dapatkan info user jika ada
    user_info = db.find_user_by_npm_or_plate(plat_nomor)
    
    # Untuk kasus override, kita buat log khusus
    override_id = db.create_entry(
        plat=plat_nomor,
        id_petugas=id_petugas,
        entry_image=None,  # Tidak ada foto masuk untuk override
        method='manual',
        keterangan=f"OVERRIDE EXIT: {keperluan}"
    )
    
    if override_id:
        # Langsung complete exit untuk override
        db.complete_exit(
            plat=plat_nomor,
            id_petugas=id_petugas,
            exit_image=exit_image_path
        )
        
        return jsonify({
            'success': True,
            'message': 'Exit manual dicatat - Palang terbuka',
            'log_id': override_id,
            'keterangan': keperluan,
            'user_info': user_info,
            'exit_image': exit_image_path,
            'status': 'override_exit'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Gagal mencatat override exit di database',
            'error_type': 'database_error'
        })

# ==============================
# ROUTES - REGISTRASI PENGGUNA
# ==============================
@app.route('/api/register_user', methods=['POST'])
def api_register_user():
    """API untuk registrasi pengguna dan kendaraan baru - FIXED TANPA KEPERLUAN"""
    try:
        data = request.get_json()
        
        # Debug: Print data yang diterima
        print("📝 Data received:", data)
        
        # Validasi data
        is_valid, result = validate_registration_data(data)
        if not is_valid:
            return jsonify({
                'success': False, 
                'message': result,
                'error_type': 'validation_error'
            })
        
        plat_nomor = result  # Sudah dinormalisasi (tanpa spasi)
        
        # Siapkan data pengguna - FIXED None handling
        data_pengguna = {
            'nama': str(data.get('nama', '')).strip(),
            'npm_nip': str(data.get('npm_nip', '')).strip() if data.get('npm_nip') else None,
            'kategori': data.get('kategori'),
            'no_telp': str(data.get('no_telp', '')).strip(),
            'email': str(data.get('email', '')).strip()
        }
        
        # Siapkan data kendaraan - FIXED None handling
        data_kendaraan = {
            'plat_nomor': plat_nomor,  # GUNAKAN PLAT NORMALIZED
            'merk_model': str(data.get('merk_model', '')).strip(),
            'warna': str(data.get('warna', '')).strip()
        }
        
        print("📝 Processed user data:", data_pengguna)
        print("📝 Processed vehicle data:", data_kendaraan)
        
        # Default petugas (admin)
        id_petugas = 1
        
        # Proses registrasi - TANPA KEPERLUAN di database
        user_id, message = db.registrasi_pengguna_baru(data_pengguna, data_kendaraan, id_petugas)
        
        if user_id:
            return jsonify({
                'success': True,
                'message': 'Registrasi berhasil! Pengguna dan kendaraan telah terdaftar.',
                'user_id': user_id,
                'plat_nomor': plat_nomor,
                'status': 'registered'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Gagal melakukan registrasi: {message}',
                'error_type': 'database_error'
            })
            
    except Exception as e:
        print(f"❌ Error in api_register_user: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

# ==============================
# ROUTES - TAMBAH KENDARAAN UNTUK PENGGUNA EXISTING
# ==============================
@app.route('/api/add_vehicle', methods=['POST'])
def api_add_vehicle():
    """API untuk menambah kendaraan baru ke pengguna yang sudah terdaftar"""
    try:
        data = request.get_json()
        
        # Validasi data yang diperlukan
        required_fields = ['user_id', 'plat_nomor', 'merk_model', 'warna']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False, 
                    'message': f'Field {field} wajib diisi',
                    'error_type': 'validation_error'
                })
        
        plat_nomor = normalize_plate(data.get('plat_nomor', ''))  # NORMALIZE PLAT
        
        # Validasi format plat nomor (TANPA SPASI)
        plat_pattern = r'^[A-Z]{1,2}\d{1,4}[A-Z]{1,3}$'
        if not re.match(plat_pattern, plat_nomor):
            return jsonify({
                'success': False, 
                'message': 'Format plat nomor tidak valid. Contoh: AB1234CD atau B123XYZ',
                'error_type': 'validation_error'
            })
        
        # Cek apakah plat sudah terdaftar (DI SEMUA KATEGORI)
        if db.check_plate_exists(plat_nomor):
            return jsonify({
                'success': False, 
                'message': f'Plat nomor {plat_nomor} sudah terdaftar di sistem',
                'error_type': 'duplicate_plate'
            })
        
        # Validasi merk_model (huruf, angka, spasi)
        merk_model = str(data.get('merk_model', ''))
        if not re.match(r'^[a-zA-Z0-9\s]+$', merk_model):
            return jsonify({
                'success': False, 
                'message': 'Merk & model hanya boleh mengandung huruf, angka, dan spasi',
                'error_type': 'validation_error'
            })
        
        # Validasi warna (huruf dan spasi saja)
        warna = str(data.get('warna', ''))
        if not re.match(r'^[a-zA-Z\s]+$', warna):
            return jsonify({
                'success': False, 
                'message': 'Warna hanya boleh mengandung huruf dan spasi',
                'error_type': 'validation_error'
            })
        
        # Dapatkan user_id
        user_id = data.get('user_id')
        
        # Tambahkan kendaraan baru
        success, message = db.create_kendaraan(
            id_pengguna=user_id,
            plat_nomor=plat_nomor,
            merk_model=merk_model,
            warna=warna
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Kendaraan berhasil ditambahkan!',
                'plat_nomor': plat_nomor,
                'status': 'vehicle_added'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Gagal menambahkan kendaraan: {message}',
                'error_type': 'database_error'
            })
            
    except Exception as e:
        print(f"❌ Error in api_add_vehicle: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

@app.route('/api/search_users')
def api_search_users():
    """API untuk mencari pengguna berdasarkan nama atau NPM/NIP"""
    try:
        query = request.args.get('query', '').strip()
        
        print(f"🔍 DEBUG api_search_users: Searching for '{query}'")
        
        if not query or len(query) < 2:
            return jsonify({'success': True, 'users': []})
        
        # Cari pengguna di database menggunakan fungsi dari db.py
        users = db.search_pengguna(query)
        print(f"🔍 DEBUG api_search_users: Found {len(users)} users")
        
        return jsonify({
            'success': True,
            'users': users,
            'count': len(users)
        })
            
    except Exception as e:
        print(f"❌ Error in api_search_users: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

@app.route('/api/check_plate')
def api_check_plate():
    """API untuk mengecek ketersediaan plat nomor"""
    try:
        plate = request.args.get('plate', '').strip()
        normalized_plate = normalize_plate(plate)  # NORMALIZE PLAT
        
        if not normalized_plate:
            return jsonify({
                'success': False, 
                'message': 'Plat nomor tidak boleh kosong',
                'error_type': 'validation_error'
            })
        
        # Validasi format plat nomor (TANPA SPASI)
        plat_pattern = r'^[A-Z]{1,2}\d{1,4}[A-Z]{1,3}$'
        if not re.match(plat_pattern, normalized_plate):
            return jsonify({
                'success': False, 
                'message': 'Format plat nomor tidak valid. Contoh: AB1234CD atau B123XYZ',
                'error_type': 'validation_error'
            })
        
        exists = db.check_plate_exists(normalized_plate)
        
        return jsonify({
            'success': True,
            'exists': exists,
            'message': 'Plat sudah terdaftar' if exists else 'Plat tersedia',
            'normalized_plate': normalized_plate  # Return normalized version
        })
            
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

# ==============================
# ROUTES - API ENDPOINTS BARU
# ==============================
@app.route('/api/search_user')
def api_search_user():
    """API untuk mencari user berdasarkan plat nomor"""
    try:
        plate = request.args.get('plate', '').strip()
        normalized_plate = normalize_plate(plate)  # NORMALIZE PLAT
        
        if not normalized_plate:
            return jsonify({
                'success': False, 
                'message': 'Plat nomor tidak boleh kosong',
                'error_type': 'validation_error'
            })
        
        user_info = db.find_user_by_npm_or_plate(normalized_plate)
        
        if user_info:
            return jsonify({
                'success': True,
                'user': {
                    'id_pengguna': user_info['id_pengguna'],
                    'nama': user_info['nama'],
                    'npm_nip': user_info.get('npm_nip'),
                    'kategori': user_info['kategori'],
                    'no_telp': user_info.get('no_telp'),
                    'email': user_info.get('email'),
                    'plat_nomor': user_info.get('plat_nomor', normalized_plate),
                    'merk_model': user_info.get('merk_model'),
                    'warna': user_info.get('warna')
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Data tidak ditemukan',
                'error_type': 'not_found'
            })
            
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

@app.route('/api/check_active_entry')
def api_check_active_entry():
    """API untuk mengecek apakah ada aktifitas aktif untuk plat tertentu"""
    try:
        plate = request.args.get('plate', '').strip()
        normalized_plate = normalize_plate(plate)  # NORMALIZE PLAT
        
        if not normalized_plate:
            return jsonify({
                'success': False, 
                'message': 'Plat nomor tidak boleh kosong',
                'error_type': 'validation_error'
            })
        
        # Cek di tracking aktif
        active_tracking = get_active_vehicle(normalized_plate)
        
        if active_tracking:
            return jsonify({
                'success': True,
                'active': True,
                'entry_time': active_tracking['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'last_seen': active_tracking['last_seen'].strftime('%Y-%m-%d %H:%M:%S')
            })
        
        # Cek di database
        active_entry = db.get_active_entry_by_plate(normalized_plate)
        
        if active_entry:
            # Tambahkan ke tracking
            add_active_vehicle(normalized_plate, active_entry.get('id_log'), 
                             active_entry.get('waktu_masuk'))
            
            return jsonify({
                'success': True,
                'active': True,
                'entry_time': active_entry.get('waktu_masuk').strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'database'
            })
        
        return jsonify({
            'success': True,
            'active': False,
            'message': 'Tidak ada aktifitas aktif'
        })
            
    except Exception as e:
        print(f"❌ Error in api_check_active_entry: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

@app.route('/api/active_vehicles')
def api_active_vehicles():
    """API untuk mendapatkan daftar kendaraan aktif"""
    try:
        with active_vehicles_lock:
            vehicles_list = []
            for plat_nomor, info in active_vehicles.items():
                # Dapatkan info user dari database
                user_info = db.find_user_by_npm_or_plate(plat_nomor)
                
                vehicle_info = {
                    'plat_nomor': plat_nomor,
                    'entry_time': info['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                    'last_seen': info['last_seen'].strftime('%Y-%m-%d %H:%M:%S'),
                    'status': info['status'],
                    'entry_id': info.get('entry_id')
                }
                
                if user_info:
                    vehicle_info['user'] = {
                        'nama': user_info.get('nama'),
                        'kategori': user_info.get('kategori')
                    }
                
                # Hitung durasi parkir
                duration = calculate_parking_duration(info['entry_time'])
                vehicle_info['parking_duration'] = duration
                
                vehicles_list.append(vehicle_info)
            
            # Urutkan berdasarkan entry_time terbaru
            vehicles_list.sort(key=lambda x: x['entry_time'], reverse=True)
            
            return jsonify({
                'success': True,
                'count': len(vehicles_list),
                'vehicles': vehicles_list
            })
            
    except Exception as e:
        print(f"❌ Error in api_active_vehicles: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

@app.route('/api/ocr_debug', methods=['POST'])
def api_ocr_debug():
    """API untuk debugging OCR (hanya untuk development)"""
    try:
        if latest_frame is None:
            return jsonify({
                'success': False, 
                'message': 'Tidak ada frame dari kamera'
            })
        
        # Deteksi dengan pipeline lengkap
        detection_result = plate_detector.detect_plate(latest_frame)
        
        # Siapkan response dengan detail
        response = {
            'success': True,
            'plate_text': detection_result['plate_text'],
            'yolo_confidence': detection_result['confidence'],
            'ocr_confidence': detection_result['ocr_confidence'],
            'total_confidence': (detection_result['confidence'] + detection_result['ocr_confidence']) / 2,
            'processing_time': detection_result['processing_time'],
            'yolo_time': detection_result['yolo_time'],
            'ocr_time': detection_result['processing_time'] - detection_result['yolo_time'],
            'boxes': detection_result['boxes'],
            'ocr_runs_count': len(detection_result['ocr_results'])
        }
        
        # Tambahkan detail OCR runs jika ada
        if detection_result['ocr_results']:
            response['ocr_details'] = detection_result['ocr_results']
        
        return jsonify(response)
            
    except Exception as e:
        print(f"❌ Error in api_ocr_debug: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}'
        })

@app.route('/api/statistics')
def api_statistics():
    """API untuk mendapatkan statistik terbaru"""
    try:
        stats = db.get_statistics()
        
        # Tambahkan statistik tracking
        stats['active_tracking_count'] = get_active_vehicles_count()
        stats['max_active_vehicles'] = Config.MAX_ACTIVE_VEHICLES
        
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': str(e),
            'error_type': 'server_error'
        })

@app.route('/api/vehicle_stats')
def api_vehicle_stats():
    """API untuk mendapatkan statistik kendaraan"""
    try:
        stats = db.get_vehicle_statistics()
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': str(e),
            'error_type': 'server_error'
        })

@app.route('/api/logs')
def api_logs():
    """API endpoint untuk mendapatkan data logs"""
    limit = request.args.get('limit', 50, type=int)
    logs = db.get_all_logs(limit=limit)
    return jsonify(logs)

@app.route('/api/system_status')
def api_system_status():
    """API untuk mendapatkan status sistem"""
    try:
        status = {
            'camera_active': camera_active,
            'latest_frame_available': latest_frame is not None,
            'active_vehicles_count': get_active_vehicles_count(),
            'plate_detector_initialized': True,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'system_uptime': 'N/A'  # Bisa ditambahkan jika diperlukan
        }
        
        return jsonify({
            'success': True,
            'status': status
        })
        
    except Exception as e:
        print(f"❌ Error in api_system_status: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Error: {str(e)}',
            'error_type': 'server_error'
        })

@app.route('/api/export')
def api_export():
    """API untuk export data"""
    try:
        export_format = request.args.get('export', 'excel')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        kategori = request.args.get('kategori')
        status = request.args.get('status')
        
        # Get data
        logs, _ = db.get_filtered_logs(
            start_date=start_date,
            end_date=end_date,
            kategori=kategori,
            status=status,
            limit=10000  # Large limit for export
        )
        
        if export_format == 'excel':
            # Create DataFrame
            df = pd.DataFrame(logs)
            
            # Create response
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Riwayat Parkir', index=False)
            
            output.seek(0)
            
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            response.headers['Content-Disposition'] = f'attachment; filename=riwayat_parkir_{generate_timestamp()}.xlsx'
            return response
            
        else:  # PDF/HTML
            from flask import render_template_string
            
            html_content = render_template_string('''
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>Riwayat Parkir UTY</title>
                    <style>
                        body { font-family: Arial, sans-serif; }
                        h1 { color: #2c3e50; text-align: center; }
                        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                        th { background-color: #f2f2f2; }
                        .header { text-align: center; margin-bottom: 20px; }
                    </style>
                </head>
                <body>
                    <div class="header">
                        <h1>RIWAYAT PARKIR UNIVERSITAS TEKNOLOGI YOGYAKARTA</h1>
                        <p>Tanggal Export: {{ export_time }}</p>
                        <p>Total Data: {{ logs|length }} aktifitas</p>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Plat Nomor</th>
                                <th>Nama</th>
                                <th>Kategori</th>
                                <th>Waktu Masuk</th>
                                <th>Waktu Keluar</th>
                                <th>Status</th>
                                <th>Metode</th>
                                <th>Petugas</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for log in logs %}
                            <tr>
                                <td>{{ log.plat_nomor }}</td>
                                <td>{{ log.nama or '-' }}</td>
                                <td>{{ log.kategori or '-' }}</td>
                                <td>{{ log.waktu_masuk.strftime('%d/%m/%Y %H:%M') if log.waktu_masuk else '-' }}</td>
                                <td>{{ log.waktu_keluar.strftime('%d/%m/%Y %H:%M') if log.waktu_keluar else '-' }}</td>
                                <td>{{ log.status }}</td>
                                <td>{{ log.metode_verifikasi }}</td>
                                <td>{{ log.nama_petugas }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </body>
                </html>
            ''', logs=logs, export_time=datetime.now().strftime("%d/%m/%Y %H:%M"))
            
            response = make_response(html_content)
            response.headers['Content-Type'] = 'text/html'
            response.headers['Content-Disposition'] = f'attachment; filename=riwayat_parkir_{generate_timestamp()}.html'
            return response
            
    except Exception as e:
        return jsonify({
            'success': False, 
            'message': f'Export error: {str(e)}',
            'error_type': 'export_error'
        })

# ==============================
# ERROR HANDLERS
# ==============================
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Endpoint tidak ditemukan',
        'error_type': 'not_found'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'error': 'Terjadi kesalahan internal server',
        'error_type': 'server_error'
    }), 500

# ==============================
# MAIN EXECUTION
# ==============================
if __name__ == '__main__':
    print("=" * 50)
    print("🚀 SISTEM PARKIR UTY - STARTING")
    print("=" * 50)
    print(f"📁 Upload Folder: {Config.UPLOAD_FOLDER}")
    print(f"🤖 Model Path: {Config.MODEL_PATH}")
    print(f"🔤 OCR Pipeline: Multi-stage dengan voting system")
    print(f"🚗 Max Active Vehicles: {Config.MAX_ACTIVE_VEHICLES}")
    print("=" * 50)
    
    # Jalankan aplikasi
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)