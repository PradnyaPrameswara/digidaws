# DIGIDAWS (Asesmen Diagnostik Cerdas)

Platform untuk generasi soal diagnostik adaptif, manajemen koleksi soal, dan analitik hasil belajar.

## Fitur Utama
- Upload modul ajar (PDF/DOC/DOCX) → ekstraksi komponen pembelajaran → generate soal otomatis
- Seleksi & simpan soal ke koleksi
- Analisis hasil siswa dan rekomendasi lanjutan
- Soft delete & arsip soal dengan jawaban siswa
- Branding: DIGIDAWS

## Arsitektur Singkat
- Backend: Flask + SQLAlchemy
- Frontend: HTML + Bootstrap + JS
- DB: MySQL/MariaDB
- AI: Gemini API (generative)
- WSGI Production: Gunicorn

## Persiapan Lokal (Development)
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
# File .env sudah disertakan. Jika ingin mulai dari template: cp .env.example .env
python backend/app.py  # (mode dev; atur FLASK_DEBUG=1 di .env jika perlu)
```

## Struktur Penting
```
backend/app.py         # Aplikasi utama Flask
backend/wsgi.py        # Entry point WSGI untuk Gunicorn
backend/gunicorn.conf.py
.env.example           # Template variabel lingkungan
requirements.txt
frontend/              # Halaman HTML
```

## Variabel Lingkungan (.env)
Variabel lingkungan tersedia di `.env` (siap diedit) dan referensi template di `.env.example`.

## Jalankan di Produksi dengan Gunicorn
Minimal (langsung):
```bash
cd backend
gunicorn -c gunicorn.conf.py wsgi:application
```
Atau tanpa config file:
```bash
gunicorn --bind 0.0.0.0:8000 app:app
```

## Systemd Service Contoh
`/etc/systemd/system/digidaws.service`
```
[Unit]
Description=DIGIDAWS Gunicorn Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/path/ke/proyek/backend
EnvironmentFile=/path/ke/proyek/.env
ExecStart=/path/ke/proyek/venv/bin/gunicorn -c gunicorn.conf.py wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```
Aktifkan:
```bash
sudo systemctl daemon-reload
sudo systemctl enable digidaws
sudo systemctl start digidaws
```

## Nginx Reverse Proxy Contoh
```
server {
	listen 80;
	server_name your_domain_or_ip;

	location / {
		proxy_pass http://127.0.0.1:8000;
		proxy_set_header Host $host;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
	}
}
```

## Cloudflare Tunnel (Production)
Untuk deployment dengan Cloudflare Tunnel (mengatasi error 1033):
```bash
cd cloudflare
sudo ./setup.sh
# Ikuti instruksi manual untuk melengkapi konfigurasi
```
Lihat `cloudflare/README.md` untuk panduan lengkap.

## Keamanan & Best Practices
- Jangan commit file .env ke repo publik.
- Gunakan user DB non-root dengan hak minimal.
- Pastikan SECRET_KEY unik & panjang.
- Tambah HTTPS (Let's Encrypt) via Nginx atau Cloudflare Tunnel.
- Rotasi log (sudah ada RotatingFileHandler + bisa tambah logrotate).

## Migrasi
Jika model database berubah: siapkan skrip migrasi (misal pakai Alembic) – saat ini belum terintegrasi.

## Lisensi
Internal / pendidikan.

## Kontribusi
Pull request & issue dipersilakan.

