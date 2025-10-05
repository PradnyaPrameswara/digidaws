# Pencegahan Duplikasi Nama Koleksi Soal

## Deskripsi
Fitur ini mencegah guru membuat koleksi soal dengan nama yang sama, namun tetap memungkinkan deskripsi yang identik untuk koleksi yang berbeda.

## Fitur yang Diimplementasikan

### 1. Validasi Backend
- **Endpoint**: `POST /api/collections`
- **Validasi**: Memeriksa nama koleksi untuk guru yang sama sebelum membuat koleksi baru
- **Error Response**: Status 400 dengan pesan error yang informatif
- **Log**: Mencatat upaya pembuatan nama duplikat

### 2. Endpoint Pengecekan Real-time
- **Endpoint**: `POST /api/collections/check-name`
- **Fungsi**: Memeriksa ketersediaan nama koleksi secara real-time
- **Response**: 
  ```json
  {
    "success": true,
    "exists": false,
    "message": "Nama tersedia"
  }
  ```

### 3. Validasi Frontend
- **Real-time Check**: Memvalidasi nama saat user mengetik (delay 500ms)
- **Visual Feedback**: Menampilkan pesan error jika nama sudah ada
- **Prevent Submit**: Mencegah submit form jika validasi gagal
- **User Experience**: Menggunakan SweetAlert2 untuk modal yang user-friendly

## Aturan Bisnis
- ✅ **Nama koleksi**: Harus unik per guru
- ✅ **Deskripsi**: Boleh sama antar koleksi
- ✅ **Case Sensitivity**: Nama dibandingkan secara exact match
- ✅ **Whitespace**: Nama di-trim sebelum validasi

## Cara Kerja

### Backend Validation Flow
1. User submit form pembuatan koleksi
2. Backend memeriksa `QuestionCollection.query.filter_by(guru_id, name)`
3. Jika ada, return error 400
4. Jika tidak ada, buat koleksi baru

### Frontend Real-time Validation Flow
1. User mengetik di input nama koleksi
2. Setelah 500ms delay, kirim request ke `/api/collections/check-name`
3. Tampilkan pesan error jika nama sudah ada
4. Prevent form submission jika validasi gagal

## File yang Dimodifikasi
- `backend/app.py`: Endpoints `/api/collections` dan `/api/collections/check-name`
- `frontend/guru/collections.html`: JavaScript untuk real-time validation

## Testing
Untuk test fitur ini:
1. Buat koleksi dengan nama "Test Collection"
2. Coba buat koleksi lagi dengan nama yang sama
3. Sistem harus mencegah dan menampilkan error
4. Buat koleksi dengan nama berbeda tapi deskripsi sama → harus berhasil

## Logging
- Info: Setiap pengecekan nama koleksi
- Warning: Upaya pembuatan nama duplikat
- Location: `logs/app.log`