# PROGRESS TRACKING FIX - DEPLOYMENT GUIDE

## MASALAH
Progress pembuatan soal tidak terlihat di VPS karena Gunicorn menggunakan multiple workers yang tidak share memory untuk global dictionary `progress_tracker`.

## SOLUSI
Mengubah progress tracking dari **in-memory dictionary** menjadi **database-based system** yang compatible dengan multiple workers.

## PERUBAHAN YANG DIBUAT

### 1. Model Database Baru
- **Tabel**: `progress_tracker`
- **Fields**: user_id, current_step, step_1-5_status, step_1-5_message, timestamps
- **Index**: user_id untuk query cepat

### 2. Fungsi Progress Tracking Baru
- `update_progress()` - Database-based dengan fallback ke memory
- `get_progress()` - Query dari database dengan fallback
- `clear_progress()` - Delete dari database dengan fallback

### 3. Fitur Keamanan
- **Fallback system**: Jika database error, otomatis fallback ke in-memory tracking
- **Error handling**: Robust error handling dengan rollback
- **Concurrent access**: Support untuk multiple Gunicorn workers

## INSTRUKSI DEPLOYMENT VPS

### Step 1: Upload Files
```bash
# Upload files yang sudah dimodifikasi ke VPS
scp backend/app.py serverlani@your-server:/var/www/digidaws/backend/
scp backend/create_progress_table.py serverlani@your-server:/var/www/digidaws/backend/
scp backend/test_progress_production.py serverlani@your-server:/var/www/digidaws/backend/
```

### Step 2: Backup Database (Opsional tapi Recommended)
```bash
ssh serverlani@your-server
cd /var/www/digidaws
mysqldump -u root -p asesment_diagnostik_db > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Step 3: Buat Tabel Progress Tracker
```bash
cd /var/www/digidaws/backend
python create_progress_table.py
```

Expected output:
```
=== PROGRESS TRACKER TABLE CREATOR ===
Membuat tabel progress_tracker...
✓ Tabel progress_tracker berhasil dibuat
✓ Test insert dan query berhasil
✓ Test data berhasil dihapus

🎉 BERHASIL!
```

### Step 4: Test System (Opsional)
```bash
python test_progress_production.py
```

Expected output:
```
🎉 SEMUA SISTEM BERFUNGSI DENGAN BAIK!
Progress tracking siap untuk production dengan multiple workers.
```

### Step 5: Restart Services
```bash
# Restart Gunicorn service
sudo systemctl restart digidaws

# Restart Nginx (optional)
sudo systemctl restart nginx

# Check status
sudo systemctl status digidaws nginx
```

### Step 6: Verify Deployment
1. Buka aplikasi web
2. Login sebagai guru  
3. Upload file modul ajar
4. **Progress bar seharusnya terlihat bergerak dari Step 1-5**

## MONITORING & TROUBLESHOOTING

### Cek Log Aplikasi
```bash
# Log Gunicorn
sudo journalctl -u digidaws -f

# Log Nginx
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

### Cek Database
```bash
mysql -u root -p
USE asesment_diagnostik_db;

-- Lihat tabel progress_tracker
DESCRIBE progress_tracker;

-- Lihat data progress (saat ada upload)
SELECT * FROM progress_tracker;
```

### Troubleshooting Common Issues

#### 1. Tabel tidak terbuat
```bash
# Manual create table
mysql -u root -p asesment_diagnostik_db
CREATE TABLE progress_tracker (
    id INTEGER NOT NULL AUTO_INCREMENT,
    user_id VARCHAR(50) NOT NULL,
    current_step INTEGER DEFAULT 1,
    step_1_status VARCHAR(20) DEFAULT 'pending',
    step_1_message VARCHAR(255) DEFAULT 'Mengunggah file modul ajar',
    step_2_status VARCHAR(20) DEFAULT 'pending',
    step_2_message VARCHAR(255) DEFAULT 'Menganalisis struktur dokumen',
    step_3_status VARCHAR(20) DEFAULT 'pending',
    step_3_message VARCHAR(255) DEFAULT 'Mengekstrak tujuan pembelajaran',
    step_4_status VARCHAR(20) DEFAULT 'pending',
    step_4_message VARCHAR(255) DEFAULT 'Memproses dengan AI Gemini',
    step_5_status VARCHAR(20) DEFAULT 'pending',
    step_5_message VARCHAR(255) DEFAULT 'Menyimpan soal ke database',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX ix_progress_tracker_user_id (user_id)
);
```

#### 2. Progress masih tidak terlihat
- Cek apakah services sudah restart
- Cek log error di journalctl
- Verifikasi database connection
- Test dengan browser private/incognito

#### 3. Database connection error
- Cek MySQL service: `sudo systemctl status mysql`
- Cek database credentials di app.py
- Test connection: `mysql -u root -p asesment_diagnostik_db`

## BENEFITS SETELAH FIX

### ✅ Production Ready
- Compatible dengan multiple Gunicorn workers
- Database persistence - progress tidak hilang saat restart
- Robust error handling dengan fallback system

### ✅ Real-time Progress
- Progress terlihat bergerak dari Step 1-5
- Update real-time setiap 500ms
- Sinkronisasi antar multiple workers

### ✅ Scalable
- Mendukung concurrent uploads dari multiple users
- Database-based - tidak terbatas memory
- Index optimized untuk query cepat

## VERIFICATION CHECKLIST

- [ ] File app.py ter-upload
- [ ] Tabel progress_tracker terbuat
- [ ] Gunicorn service restart berhasil
- [ ] Login guru berhasil
- [ ] Upload file modul berhasil
- [ ] **Progress bar bergerak dari Step 1-5** ✨
- [ ] Soal berhasil digenerate
- [ ] No error di log

## CONTACT
Jika ada masalah saat deployment, cek log dan compare dengan expected output di atas.