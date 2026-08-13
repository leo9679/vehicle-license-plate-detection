import mysql.connector
from datetime import datetime
import os
import re

# ==============================
# KONFIGURASI DATABASE
# ==============================
class DatabaseConfig:
    """Konfigurasi koneksi database MySQL"""
    HOST = 'localhost'
    USER = ''
    PASSWORD = ''
    DATABASE = 'parking_system_uty2026'
    CHARSET = 'utf8mb4'

# ==============================
# VALIDATION FUNCTIONS
# ==============================
class DataValidator:
    """Class untuk validasi data input"""
    
    @staticmethod
    def validate_telepon(no_telp):
        """Validasi nomor telepon: hanya angka, 10-13 digit"""
        if not no_telp:
            return False, "Nomor telepon wajib diisi"
        
        no_telp_str = str(no_telp)
        
        # Hanya angka
        if not re.match(r'^\d+$', no_telp_str):
            return False, "Nomor telepon hanya boleh mengandung angka"
        
        # Panjang 10-13 digit
        if len(no_telp_str) < 10 or len(no_telp_str) > 13:
            return False, "Nomor telepon harus 10-13 digit"
        
        return True, "Valid"
    
    @staticmethod
    def validate_npm_nip(npm_nip, kategori):
        """Validasi NPM/NIP: hanya angka, required untuk non-tamu"""
        if kategori != 'Tamu':
            if not npm_nip:
                return False, f"NPM/NIP wajib diisi untuk {kategori}"
            
            npm_nip_str = str(npm_nip)
            # Hanya angka
            if not re.match(r'^\d+$', npm_nip_str):
                return False, "NPM/NIP hanya boleh mengandung angka"
        
        # Untuk tamu, NPM/NIP opsional tapi jika diisi harus angka
        elif npm_nip and not re.match(r'^\d+$', str(npm_nip)):
            return False, "NPM/NIP hanya boleh mengandung angka jika diisi"
        
        return True, "Valid"
    
    @staticmethod
    def validate_plat_nomor(plat_nomor):
        """Validasi plat nomor: format huruf-angka-huruf TANPA SPASI"""
        if not plat_nomor:
            return False, "Plat nomor wajib diisi"
        
        plat_nomor_str = str(plat_nomor)
        # Format: 1-2 huruf + 1-4 angka + 1-3 huruf (TANPA SPASI)
        plat_pattern = r'^[A-Z]{1,2}\d{1,4}[A-Z]{1,3}$'
        if not re.match(plat_pattern, plat_nomor_str.upper()):
            return False, "Format plat nomor tidak valid. Contoh: AB1234CD atau B123XYZ"
        
        return True, "Valid"
    
    @staticmethod
    def validate_nama(nama):
        """Validasi nama: hanya huruf dan spasi"""
        if not nama:
            return False, "Nama wajib diisi"
        
        nama_str = str(nama)
        if not re.match(r'^[a-zA-Z\s]+$', nama_str):
            return False, "Nama hanya boleh mengandung huruf dan spasi"
        
        return True, "Valid"
    
    @staticmethod
    def validate_merk_model(merk_model):
        """Validasi merk & model: huruf, angka, dan spasi"""
        if not merk_model:
            return False, "Merk & model wajib diisi"
        
        merk_model_str = str(merk_model)
        if not re.match(r'^[a-zA-Z0-9\s]+$', merk_model_str):
            return False, "Merk & model hanya boleh mengandung huruf, angka, dan spasi"
        
        return True, "Valid"
    
    @staticmethod
    def validate_warna(warna):
        """Validasi warna: hanya huruf dan spasi"""
        if not warna:
            return False, "Warna wajib diisi"
        
        warna_str = str(warna)
        if not re.match(r'^[a-zA-Z\s]+$', warna_str):
            return False, "Warna hanya boleh mengandung huruf dan spasi"
        
        return True, "Valid"
    
    @staticmethod
    def validate_email(email):
        """Validasi format email"""
        if not email:
            return False, "Email wajib diisi"
        
        email_str = str(email)
        email_pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_pattern, email_str):
            return False, "Format email tidak valid"
        
        return True, "Valid"

# ==============================
# KELAS UTAMA DATABASE HANDLER
# ==============================
class DatabaseHandler:
    def __init__(self):
        self.config = DatabaseConfig()
        self.validator = DataValidator()
        self._initialize_database()

    def get_connection(self):
        """Membuat koneksi ke database MySQL"""
        try:
            conn = mysql.connector.connect(
                host=self.config.HOST,
                user=self.config.USER,
                password=self.config.PASSWORD,
                database=self.config.DATABASE,
                charset=self.config.CHARSET
            )
            return conn
        except mysql.connector.Error as err:
            print(f"❌ Error koneksi database: {err}")
            return None

    def _initialize_database(self):
        """Inisialisasi database dan tabel"""
        try:
            # Buat database jika belum ada
            self._create_database_if_not_exists()
            
            # Buat semua tabel
            self._create_tables()
            
            # Buat data default petugas saja
            self._create_default_petugas()
            
            print("✅ Database berhasil diinisialisasi")
            
        except mysql.connector.Error as err:
            print(f"❌ Error inisialisasi database: {err}")

    def _create_database_if_not_exists(self):
        """Membuat database jika belum ada"""
        try:
            temp_config = {
                'host': self.config.HOST,
                'user': self.config.USER,
                'password': self.config.PASSWORD,
                'charset': self.config.CHARSET
            }
            
            conn = mysql.connector.connect(**temp_config)
            cursor = conn.cursor()
            
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.config.DATABASE}")
            cursor.close()
            conn.close()
            
        except mysql.connector.Error as err:
            print(f"❌ Error membuat database: {err}")
            raise

    def _create_tables(self):
        """Membuat semua tabel yang diperlukan"""
        table_queries = [
            # Tabel pengguna (mahasiswa/dosen/staff/tamu) - HAPUS updated_at
            """
            CREATE TABLE IF NOT EXISTS pengguna (
                id_pengguna INT AUTO_INCREMENT PRIMARY KEY,
                nama VARCHAR(255) NOT NULL,
                npm_nip VARCHAR(50) NULL,
                kategori ENUM('Mahasiswa', 'Dosen', 'Staff', 'Tamu') NOT NULL,
                no_telp VARCHAR(20) NOT NULL,
                email VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_npm_nip (npm_nip),
                INDEX idx_kategori (kategori)
            )
            """,
            
            # Tabel kendaraan (satu pengguna bisa punya banyak kendaraan) - HAPUS updated_at
            """
            CREATE TABLE IF NOT EXISTS kendaraan (
                id_kendaraan INT AUTO_INCREMENT PRIMARY KEY,
                id_pengguna INT NOT NULL,
                plat_nomor VARCHAR(20) NOT NULL,
                merk_model VARCHAR(200) NOT NULL,
                warna VARCHAR(50) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_pengguna) REFERENCES pengguna(id_pengguna) ON DELETE CASCADE,
                UNIQUE KEY unique_plat (plat_nomor),
                INDEX idx_plat_nomor (plat_nomor)
            )
            """,
            
            # Tabel petugas (untuk admin/petugas parkir)
            """
            CREATE TABLE IF NOT EXISTS petugas (
                id_petugas INT AUTO_INCREMENT PRIMARY KEY,
                nama_petugas VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # Tabel akses_log (aktifitas masuk/keluar)
            """
            CREATE TABLE IF NOT EXISTS akses_log (
                id_log INT AUTO_INCREMENT PRIMARY KEY,
                plat_nomor VARCHAR(20) NOT NULL,
                id_petugas INT NOT NULL,
                waktu_masuk DATETIME NOT NULL,
                waktu_keluar DATETIME NULL,
                status ENUM('Masuk', 'Keluar') DEFAULT 'Masuk',
                metode_verifikasi ENUM('otomatis', 'manual') NOT NULL,
                foto_masuk VARCHAR(500) NULL,
                foto_keluar VARCHAR(500) NULL,
                keterangan TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_petugas) REFERENCES petugas(id_petugas),
                INDEX idx_plat_nomor (plat_nomor),
                INDEX idx_waktu_masuk (waktu_masuk),
                INDEX idx_status (status)
            )
            """,
            
            # Tabel registrasi (history pendaftaran pengguna & kendaraan) - HAPUS tanggal_registrasi
            """
            CREATE TABLE IF NOT EXISTS registrasi (
                id_registrasi INT AUTO_INCREMENT PRIMARY KEY,
                id_pengguna INT NOT NULL,
                id_petugas INT NOT NULL,
                plat_nomor VARCHAR(20) NOT NULL,
                status ENUM('Aktif', 'Nonaktif') DEFAULT 'Aktif',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (id_pengguna) REFERENCES pengguna(id_pengguna),
                FOREIGN KEY (id_petugas) REFERENCES petugas(id_petugas),
                INDEX idx_created_at (created_at)
            )
            """
        ]
        
        conn = self.get_connection()
        if not conn:
            return
            
        cursor = conn.cursor()
        
        try:
            for query in table_queries:
                cursor.execute(query)
            
            conn.commit()
            print("✅ Tabel berhasil dibuat/diperiksa")
            
        except mysql.connector.Error as err:
            print(f"❌ Error membuat tabel: {err}")
        finally:
            cursor.close()
            conn.close()

    def _create_default_petugas(self):
        """Membuat petugas default saja (tanpa data demo)"""
        conn = self.get_connection()
        if not conn:
            return
            
        cursor = conn.cursor()
        
        try:
            # Cek apakah sudah ada petugas
            cursor.execute("SELECT COUNT(*) FROM petugas")
            if cursor.fetchone()[0] == 0:
                # Buat petugas default (hanya nama_petugas)
                cursor.execute("""
                    INSERT INTO petugas (nama_petugas) 
                    VALUES (%s)
                """, ('Petugas Parkir',))
                
                conn.commit()
                print("✅ Petugas default berhasil dibuat (Petugas Parkir)")
            else:
                print("ℹ️  Petugas sudah ada, skip pembuatan default")
                
        except mysql.connector.Error as err:
            print(f"❌ Error membuat petugas default: {err}")
        finally:
            cursor.close()
            conn.close()


# ==============================
# FUNGSI CRUD UNTUK APLIKASI
# ==============================
class ParkingDatabase:
    def __init__(self):
        self.handler = DatabaseHandler()
        self.validator = DataValidator()

    # ==============================
    # OPERASI PENGGUNA & KENDARAAN
    # ==============================
    def create_pengguna(self, nama, npm_nip, kategori, no_telp, email):
        """Membuat pengguna baru dengan validasi"""
        # Validasi data
        valid, message = self.validator.validate_nama(nama)
        if not valid:
            return None, message
        
        valid, message = self.validator.validate_npm_nip(npm_nip, kategori)
        if not valid:
            return None, message
            
        valid, message = self.validator.validate_telepon(no_telp)
        if not valid:
            return None, message
            
        valid, message = self.validator.validate_email(email)
        if not valid:
            return None, message
        
        conn = self.handler.get_connection()
        if not conn:
            return None, "Error koneksi database"
            
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO pengguna (nama, npm_nip, kategori, no_telp, email)
                VALUES (%s, %s, %s, %s, %s)
            """, (nama, npm_nip, kategori, no_telp, email))
            
            user_id = cursor.lastrowid
            conn.commit()
            return user_id, "Berhasil"
            
        except mysql.connector.Error as err:
            print(f"❌ Error create_pengguna: {err}")
            return None, f"Error database: {err}"
        finally:
            cursor.close()
            conn.close()

    def create_kendaraan(self, id_pengguna, plat_nomor, merk_model, warna):
        """Mendaftarkan kendaraan baru dengan validasi"""
        # Validasi data
        valid, message = self.validator.validate_plat_nomor(plat_nomor)
        if not valid:
            return False, message
            
        valid, message = self.validator.validate_merk_model(merk_model)
        if not valid:
            return False, message
            
        valid, message = self.validator.validate_warna(warna)
        if not valid:
            return False, message
        
        conn = self.handler.get_connection()
        if not conn:
            return False, "Error koneksi database"
            
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO kendaraan (id_pengguna, plat_nomor, merk_model, warna)
                VALUES (%s, %s, %s, %s)
            """, (id_pengguna, plat_nomor.upper(), merk_model, warna))
            
            conn.commit()
            return True, "Berhasil"
            
        except mysql.connector.Error as err:
            print(f"❌ Error create_kendaraan: {err}")
            return False, f"Error database: {err}"
        finally:
            cursor.close()
            conn.close()

    def find_user_by_npm_or_plate(self, npm_or_plate):
        """Mencari pengguna berdasarkan NPM/NIP atau plat nomor"""
        conn = self.handler.get_connection()
        if not conn:
            return None
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Cari berdasarkan plat nomor dengan join ke kendaraan
            cursor.execute("""
                SELECT 
                    p.id_pengguna,
                    p.nama,
                    p.npm_nip,
                    p.kategori,
                    p.no_telp,
                    p.email,
                    k.plat_nomor,
                    k.merk_model,
                    k.warna
                FROM pengguna p
                JOIN kendaraan k ON p.id_pengguna = k.id_pengguna
                WHERE k.plat_nomor = %s AND k.is_active = TRUE
            """, (npm_or_plate,))
            
            result = cursor.fetchone()
            
            if not result:
                # Jika tidak ditemukan, cari berdasarkan NPM/NIP
                cursor.execute("""
                    SELECT 
                        p.id_pengguna,
                        p.nama,
                        p.npm_nip,
                        p.kategori,
                        p.no_telp,
                        p.email,
                        k.plat_nomor,
                        k.merk_model,
                        k.warna
                    FROM pengguna p
                    LEFT JOIN kendaraan k ON p.id_pengguna = k.id_pengguna AND k.is_active = TRUE
                    WHERE p.npm_nip = %s
                    ORDER BY k.created_at DESC
                    LIMIT 1
                """, (npm_or_plate,))
                
                result = cursor.fetchone()
            
            return result
            
        except mysql.connector.Error as err:
            print(f"❌ Error find_user_by_npm_or_plate: {err}")
            return None
        finally:
            cursor.close()
            conn.close()

    def get_all_pengguna(self):
        """Mendapatkan semua data pengguna dengan SEMUA kendaraannya"""
        conn = self.handler.get_connection()
        if not conn:
            return []
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Ambil semua pengguna
            cursor.execute("""
                SELECT 
                    p.*
                FROM pengguna p
                ORDER BY p.created_at DESC
            """)
            
            pengguna_list = cursor.fetchall()
            
            # Untuk setiap pengguna, ambil semua kendaraannya
            for pengguna in pengguna_list:
                cursor.execute("""
                    SELECT 
                        k.plat_nomor,
                        k.merk_model,
                        k.warna,
                        k.is_active as kendaraan_active,
                        k.created_at
                    FROM kendaraan k
                    WHERE k.id_pengguna = %s AND k.is_active = TRUE
                    ORDER BY k.created_at DESC
                """, (pengguna['id_pengguna'],))
                
                kendaraan_list = cursor.fetchall()
                pengguna['kendaraan'] = kendaraan_list
                # Untuk kompatibilitas dengan template yang ada, set kendaraan pertama sebagai default
                if kendaraan_list:
                    first_kendaraan = kendaraan_list[0]
                    pengguna['plat_nomor'] = first_kendaraan['plat_nomor']
                    pengguna['merk_model'] = first_kendaraan['merk_model']
                    pengguna['warna'] = first_kendaraan['warna']
                    pengguna['kendaraan_active'] = first_kendaraan['kendaraan_active']
                else:
                    pengguna['plat_nomor'] = None
                    pengguna['merk_model'] = None
                    pengguna['warna'] = None
                    pengguna['kendaraan_active'] = False
            
            return pengguna_list
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_all_pengguna: {err}")
            return []
        finally:
            cursor.close()
            conn.close()

    def search_pengguna(self, query):
        """Mencari pengguna berdasarkan nama atau NPM/NIP untuk autocomplete"""
        conn = self.handler.get_connection()
        if not conn:
            return []
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            # PERBAIKAN: Gunakan parameterized query dengan wildcard yang benar
            search_term = f"%{query}%"
            cursor.execute("""
                SELECT 
                    id_pengguna,
                    nama,
                    npm_nip,
                    kategori,
                    no_telp,
                    email
                FROM pengguna 
                WHERE nama LIKE %s OR npm_nip LIKE %s
                ORDER BY nama
                LIMIT 10
            """, (search_term, search_term))
            
            users = cursor.fetchall()
            print(f"🔍 DEBUG search_pengguna: Found {len(users)} users for query '{query}'")  # Debug line
            return users
            
        except mysql.connector.Error as err:
            print(f"❌ Error search_pengguna: {err}")
            return []
        finally:
            cursor.close()
            conn.close()

    def get_kendaraan_by_user(self, id_pengguna):
        """Mendapatkan semua kendaraan milik seorang pengguna"""
        conn = self.handler.get_connection()
        if not conn:
            return []
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                SELECT 
                    k.*,
                    p.nama,
                    p.kategori
                FROM kendaraan k
                JOIN pengguna p ON k.id_pengguna = p.id_pengguna
                WHERE k.id_pengguna = %s AND k.is_active = TRUE
                ORDER BY k.created_at DESC
            """, (id_pengguna,))
            
            return cursor.fetchall()
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_kendaraan_by_user: {err}")
            return []
        finally:
            cursor.close()
            conn.close()

    # ==============================
    # OPERASI REGISTRASI - FIXED TANPA KEPERLUAN
    # ==============================
    def registrasi_pengguna_baru(self, data_pengguna, data_kendaraan, id_petugas):
        """Registrasi pengguna dan kendaraan baru sekaligus dengan validasi lengkap"""
        # Validasi data pengguna
        valid, message = self.validator.validate_nama(data_pengguna.get('nama', ''))
        if not valid:
            return None, message
        
        valid, message = self.validator.validate_npm_nip(data_pengguna.get('npm_nip'), data_pengguna.get('kategori', ''))
        if not valid:
            return None, message
            
        valid, message = self.validator.validate_telepon(data_pengguna.get('no_telp', ''))
        if not valid:
            return None, message
            
        valid, message = self.validator.validate_email(data_pengguna.get('email', ''))
        if not valid:
            return None, message
        
        # Validasi data kendaraan
        valid, message = self.validator.validate_plat_nomor(data_kendaraan.get('plat_nomor', ''))
        if not valid:
            return None, message
            
        valid, message = self.validator.validate_merk_model(data_kendaraan.get('merk_model', ''))
        if not valid:
            return None, message
            
        valid, message = self.validator.validate_warna(data_kendaraan.get('warna', ''))
        if not valid:
            return None, message
        
        conn = self.handler.get_connection()
        if not conn:
            return None, "Error koneksi database"
            
        cursor = conn.cursor()
        
        try:
            # 1. Cek apakah plat nomor sudah ada (DI SEMUA KATEGORI)
            cursor.execute("SELECT 1 FROM kendaraan WHERE plat_nomor = %s", (data_kendaraan.get('plat_nomor', '').upper(),))
            if cursor.fetchone():
                return None, f"Plat nomor {data_kendaraan.get('plat_nomor', '')} sudah terdaftar di sistem"
            
            # 2. Cek apakah user sudah ada (berdasarkan NPM/NIP untuk non-tamu)
            if data_pengguna.get('kategori') != 'Tamu' and data_pengguna.get('npm_nip'):
                cursor.execute("SELECT id_pengguna FROM pengguna WHERE npm_nip = %s", (data_pengguna.get('npm_nip'),))
                existing_user = cursor.fetchone()
                
                if existing_user:
                    user_id = existing_user[0]
                    # User sudah ada, hanya tambahkan kendaraan baru
                    success, message = self.create_kendaraan(
                        user_id, 
                        data_kendaraan.get('plat_nomor', ''), 
                        data_kendaraan.get('merk_model', ''), 
                        data_kendaraan.get('warna', '')
                    )
                    
                    if success:
                        # Buat data registrasi untuk kendaraan baru - TANPA tanggal_registrasi
                        cursor.execute("""
                            INSERT INTO registrasi (id_pengguna, id_petugas, plat_nomor, status)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            user_id,
                            id_petugas,
                            data_kendaraan.get('plat_nomor', '').upper(),
                            'Aktif'
                        ))
                        
                        conn.commit()
                        return user_id, "Kendaraan berhasil ditambahkan ke pengguna yang sudah ada"
                    else:
                        conn.rollback()
                        return None, message
                else:
                    # User belum ada, buat user baru dan kendaraan
                    user_id, message = self.create_pengguna(
                        data_pengguna.get('nama', ''),
                        data_pengguna.get('npm_nip'),
                        data_pengguna.get('kategori', ''),
                        data_pengguna.get('no_telp', ''),
                        data_pengguna.get('email', '')
                    )
                    
                    if user_id:
                        success, message = self.create_kendaraan(
                            user_id, 
                            data_kendaraan.get('plat_nomor', ''), 
                            data_kendaraan.get('merk_model', ''), 
                            data_kendaraan.get('warna', '')
                        )
                        
                        if success:
                            # Buat data registrasi - TANPA tanggal_registrasi
                            cursor.execute("""
                                INSERT INTO registrasi (id_pengguna, id_petugas, plat_nomor, status)
                                VALUES (%s, %s, %s, %s)
                            """, (
                                user_id,
                                id_petugas,
                                data_kendaraan.get('plat_nomor', '').upper(),
                                'Aktif'
                            ))
                            
                            conn.commit()
                            return user_id, "Registrasi berhasil"
                        else:
                            conn.rollback()
                            return None, message
                    else:
                        return None, message
            else:
                # Untuk tamu atau tanpa NPM/NIP, buat user baru
                user_id, message = self.create_pengguna(
                    data_pengguna.get('nama', ''),
                    data_pengguna.get('npm_nip'),
                    data_pengguna.get('kategori', ''),
                    data_pengguna.get('no_telp', ''),
                    data_pengguna.get('email', '')
                )
                
                if user_id:
                    success, message = self.create_kendaraan(
                        user_id, 
                        data_kendaraan.get('plat_nomor', ''), 
                        data_kendaraan.get('merk_model', ''), 
                        data_kendaraan.get('warna', '')
                    )
                    
                    if success:
                        # Buat data registrasi - TANPA tanggal_registrasi
                        cursor.execute("""
                            INSERT INTO registrasi (id_pengguna, id_petugas, plat_nomor, status)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            user_id,
                            id_petugas,
                            data_kendaraan.get('plat_nomor', '').upper(),
                            'Aktif'
                        ))
                        
                        conn.commit()
                        return user_id, "Registrasi berhasil"
                    else:
                        conn.rollback()
                        return None, message
                else:
                    return None, message
            
        except mysql.connector.Error as err:
            print(f"❌ Error registrasi_pengguna_baru: {err}")
            conn.rollback()
            return None, f"Error database: {err}"
        finally:
            cursor.close()
            conn.close()

    # ==============================
    # OPERASI STATISTIK
    # ==============================
    def get_vehicle_statistics(self):
        """Mendapatkan statistik kendaraan terdaftar per kategori"""
        conn = self.handler.get_connection()
        if not conn:
            return {}
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                SELECT 
                    p.kategori,
                    COUNT(DISTINCT p.id_pengguna) as jumlah_pengguna,
                    COUNT(k.id_kendaraan) as jumlah_kendaraan
                FROM pengguna p
                LEFT JOIN kendaraan k ON p.id_pengguna = k.id_pengguna AND k.is_active = TRUE
                GROUP BY p.kategori
                ORDER BY p.kategori
            """)
            
            stats = {}
            for row in cursor.fetchall():
                stats[row['kategori']] = {
                    'pengguna': row['jumlah_pengguna'],
                    'kendaraan': row['jumlah_kendaraan']
                }
            
            return stats
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_vehicle_statistics: {err}")
            return {}
        finally:
            cursor.close()
            conn.close()

    # ==============================
    # OPERASI ENTRY/EXIT KENDARAAN
    # ==============================
    def create_entry(self, plat, id_petugas, entry_image, method='otomatis', keterangan=None):
        """Membuat record akses masuk kendaraan"""
        conn = self.handler.get_connection()
        if not conn:
            return None
            
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO akses_log (plat_nomor, id_petugas, waktu_masuk, metode_verifikasi, foto_masuk, keterangan)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (plat, id_petugas, datetime.now(), method, entry_image, keterangan))
            
            entry_id = cursor.lastrowid
            conn.commit()
            return entry_id
            
        except mysql.connector.Error as err:
            print(f"❌ Error create_entry: {err}")
            return None
        finally:
            cursor.close()
            conn.close()

    def get_active_entry_by_plate(self, plat):
        """Mendapatkan record masuk aktif (belum keluar) berdasarkan plat"""
        conn = self.handler.get_connection()
        if not conn:
            return None
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                SELECT 
                    al.*,
                    TIMESTAMPDIFF(MINUTE, al.waktu_masuk, NOW()) as durasi_menit
                FROM akses_log al
                WHERE al.plat_nomor = %s AND al.waktu_keluar IS NULL
                ORDER BY al.waktu_masuk DESC
                LIMIT 1
            """, (plat,))
            
            return cursor.fetchone()
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_active_entry_by_plate: {err}")
            return None
        finally:
            cursor.close()
            conn.close()

    def complete_exit(self, plat, id_petugas, exit_image):
        """Menyelesaikan aktifitas exit (mengisi waktu_keluar)"""
        conn = self.handler.get_connection()
        if not conn:
            return False
            
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE akses_log 
                SET waktu_keluar = %s, status = 'Keluar', foto_keluar = %s
                WHERE plat_nomor = %s AND waktu_keluar IS NULL
                ORDER BY waktu_masuk DESC
                LIMIT 1
            """, (datetime.now(), exit_image, plat))
            
            rows_affected = cursor.rowcount
            conn.commit()
            
            return rows_affected > 0
            
        except mysql.connector.Error as err:
            print(f"❌ Error complete_exit: {err}")
            return False
        finally:
            cursor.close()
            conn.close()

    # ==============================
    # OPERASI RIWAYAT & STATISTIK
    # ==============================
    def get_all_logs(self, limit=50):
        """Mendapatkan semua log akses untuk riwayat"""
        conn = self.handler.get_connection()
        if not conn:
            return []
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                SELECT 
                    al.*,
                    p.nama,
                    p.kategori,
                    p.npm_nip,
                    pt.nama_petugas,
                    TIMESTAMPDIFF(MINUTE, al.waktu_masuk, COALESCE(al.waktu_keluar, NOW())) as durasi_menit
                FROM akses_log al
                LEFT JOIN kendaraan k ON al.plat_nomor = k.plat_nomor
                LEFT JOIN pengguna p ON k.id_pengguna = p.id_pengguna
                JOIN petugas pt ON al.id_petugas = pt.id_petugas
                ORDER BY al.waktu_masuk DESC
                LIMIT %s
            """, (limit,))
            
            return cursor.fetchall()
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_all_logs: {err}")
            return []
        finally:
            cursor.close()
            conn.close()

    def get_filtered_logs(self, start_date=None, end_date=None, kategori=None, status=None, limit=50, offset=0):
        """Mendapatkan log dengan filter dan pagination"""
        conn = self.handler.get_connection()
        if not conn:
            return [], 0
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Base query
            query = """
                SELECT 
                    al.*,
                    p.nama,
                    p.kategori,
                    p.npm_nip,
                    pt.nama_petugas,
                    TIMESTAMPDIFF(MINUTE, al.waktu_masuk, COALESCE(al.waktu_keluar, NOW())) as durasi_menit
                FROM akses_log al
                LEFT JOIN kendaraan k ON al.plat_nomor = k.plat_nomor
                LEFT JOIN pengguna p ON k.id_pengguna = p.id_pengguna
                JOIN petugas pt ON al.id_petugas = pt.id_petugas
                WHERE 1=1
            """
            
            count_query = """
                SELECT COUNT(*) as total
                FROM akses_log al
                LEFT JOIN kendaraan k ON al.plat_nomor = k.plat_nomor
                LEFT JOIN pengguna p ON k.id_pengguna = p.id_pengguna
                WHERE 1=1
            """
            
            params = []
            count_params = []
            
            # Apply filters
            if start_date:
                query += " AND DATE(al.waktu_masuk) >= %s"
                count_query += " AND DATE(al.waktu_masuk) >= %s"
                params.append(start_date)
                count_params.append(start_date)
                
            if end_date:
                query += " AND DATE(al.waktu_masuk) <= %s"
                count_query += " AND DATE(al.waktu_masuk) <= %s"
                params.append(end_date)
                count_params.append(end_date)
                
            if kategori:
                query += " AND p.kategori = %s"
                count_query += " AND p.kategori = %s"
                params.append(kategori)
                count_params.append(kategori)
                
            if status:
                query += " AND al.status = %s"
                count_query += " AND al.status = %s"
                params.append(status)
                count_params.append(status)
            
            # Order and limit
            query += " ORDER BY al.waktu_masuk DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            # Execute main query
            cursor.execute(query, params)
            logs = cursor.fetchall()
            
            # Execute count query
            cursor.execute(count_query, count_params)
            total_count = cursor.fetchone()['total']
            
            return logs, total_count
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_filtered_logs: {err}")
            return [], 0
        finally:
            cursor.close()
            conn.close()

    def get_statistics(self):
        """Mendapatkan statistik sistem"""
        conn = self.handler.get_connection()
        if not conn:
            return self._get_default_stats()
            
        cursor = conn.cursor(dictionary=True)
        
        try:
            stats = {}
            
            # Total transactions
            cursor.execute("SELECT COUNT(*) as total FROM akses_log")
            stats['total_transactions'] = cursor.fetchone()['total']
            
            # Active entries (masuk tanpa keluar)
            cursor.execute("SELECT COUNT(*) as total FROM akses_log WHERE waktu_keluar IS NULL")
            stats['active_entries'] = cursor.fetchone()['total']
            
            # Today's entries
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("SELECT COUNT(*) as total FROM akses_log WHERE DATE(waktu_masuk) = %s", (today,))
            stats['today_entries'] = cursor.fetchone()['total']
            
            # Manual verifications
            cursor.execute("SELECT COUNT(*) as total FROM akses_log WHERE metode_verifikasi = 'manual'")
            stats['manual_verifications'] = cursor.fetchone()['total']
            
            # Vehicle statistics
            vehicle_stats = self.get_vehicle_statistics()
            stats['vehicle_statistics'] = vehicle_stats
            
            return stats
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_statistics: {err}")
            return self._get_default_stats()
        finally:
            cursor.close()
            conn.close()

    def _get_default_stats(self):
        """Return default stats ketika database error"""
        return {
            'total_transactions': 0,
            'active_entries': 0,
            'today_entries': 0,
            'manual_verifications': 0,
            'vehicle_statistics': {}
        }

    # ==============================
    # OPERASI UTILITAS
    # ==============================
    def check_plate_exists(self, plat_nomor):
        """Cek apakah plat nomor sudah terdaftar (DI SEMUA KATEGORI)"""
        conn = self.handler.get_connection()
        if not conn:
            return False
            
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT 1 FROM kendaraan WHERE plat_nomor = %s AND is_active = TRUE", (plat_nomor.upper(),))
            return cursor.fetchone() is not None
            
        except mysql.connector.Error as err:
            print(f"❌ Error check_plate_exists: {err}")
            return False
        finally:
            cursor.close()
            conn.close()

    def get_active_entries_count(self):
        """Mendapatkan jumlah kendaraan yang sedang parkir"""
        conn = self.handler.get_connection()
        if not conn:
            return 0
            
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) as total FROM akses_log WHERE waktu_keluar IS NULL")
            result = cursor.fetchone()
            return result[0] if result else 0
            
        except mysql.connector.Error as err:
            print(f"❌ Error get_active_entries_count: {err}")
            return 0
        finally:
            cursor.close()
            conn.close()

# ==============================
# INSTANCE GLOBAL UNTUK IMPORT
# ==============================
db_handler = ParkingDatabase()

# Fungsi-fungsi kompatibilitas untuk import yang ada
def get_connection():
    return db_handler.handler.get_connection()

def create_entry(plat, id_petugas, entry_image, method='otomatis', keterangan=None):
    return db_handler.create_entry(plat, id_petugas, entry_image, method, keterangan)

def get_active_entry_by_plate(plat):
    return db_handler.get_active_entry_by_plate(plat)

def complete_exit(plat, id_petugas, exit_image):
    return db_handler.complete_exit(plat, id_petugas, exit_image)

def get_all_logs(limit=50):
    return db_handler.get_all_logs(limit)

def get_filtered_logs(start_date=None, end_date=None, kategori=None, status=None, limit=50, offset=0):
    return db_handler.get_filtered_logs(start_date, end_date, kategori, status, limit, offset)

def get_statistics():
    return db_handler.get_statistics()

def find_user_by_npm_or_plate(npm_or_plate):
    return db_handler.find_user_by_npm_or_plate(npm_or_plate)

def create_pengguna(nama, npm_nip=None, kategori='Tamu', no_telp=None, email=None):
    return db_handler.create_pengguna(nama, npm_nip, kategori, no_telp, email)

def create_kendaraan(id_pengguna, plat_nomor, merk_model, warna):
    return db_handler.create_kendaraan(id_pengguna, plat_nomor, merk_model, warna)

def registrasi_pengguna_baru(data_pengguna, data_kendaraan, id_petugas):
    return db_handler.registrasi_pengguna_baru(data_pengguna, data_kendaraan, id_petugas)

def get_all_pengguna():
    return db_handler.get_all_pengguna()

def check_plate_exists(plat_nomor):
    return db_handler.check_plate_exists(plat_nomor)

def get_active_entries_count():
    return db_handler.get_active_entries_count()

def get_vehicle_statistics():
    return db_handler.get_vehicle_statistics()

def get_kendaraan_by_user(id_pengguna):
    return db_handler.get_kendaraan_by_user(id_pengguna)

# FUNGSI BARU UNTUK FITUR TAMBAH KENDARAAN
def search_pengguna(query):
    """Mencari pengguna berdasarkan nama atau NPM/NIP"""
    return db_handler.search_pengguna(query)

# Inisialisasi sudah dilakukan di kelas, tidak perlu dipanggil lagi
def init_database():
    pass
