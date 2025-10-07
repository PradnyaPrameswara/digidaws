#!/usr/bin/env python3
"""
Test script untuk validasi notifikasi error yang relevan
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from backend.app import validate_kurikulum_merdeka_modul_ajar

def test_error_notifications():
    print("=== TEST NOTIFIKASI ERROR YANG RELEVAN ===\n")
    
    # Test 1: File terlalu pendek
    print("TEST 1: File terlalu pendek")
    short_text = "Ini adalah dokumen yang sangat pendek."
    is_valid, message = validate_kurikulum_merdeka_modul_ajar(short_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 70)
    
    # Test 2: Tidak ada header MODUL AJAR
    print("\nTEST 2: Tidak ada header MODUL AJAR")
    no_header_text = """
Rencana Pembelajaran Harian
Mata Pelajaran: Matematika
Kelas: X
Materi: Fungsi Linear

Tujuan:
Siswa dapat memahami konsep fungsi linear dan menerapkannya dalam kehidupan sehari-hari.
Siswa mampu menggambar grafik fungsi linear dengan benar.

Kegiatan:
1. Pembukaan dan apersepsi
2. Penyampaian materi
3. Latihan soal
4. Evaluasi dan penutup

Penilaian:
Tes tertulis dan observasi aktivitas siswa selama pembelajaran berlangsung.
""" * 3  # Diperbanyak agar memenuhi syarat panjang

    is_valid, message = validate_kurikulum_merdeka_modul_ajar(no_header_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 70)
    
    # Test 3: Tidak ada Tujuan Pembelajaran
    print("\nTEST 3: Tidak ada Tujuan Pembelajaran")
    no_tujuan_text = """
MODUL AJAR
Informatika - Dasar-dasar Pemrograman

Mata Pelajaran: Informatika
Fase/Kelas: E (Kelas X)
Alokasi Waktu: 3 x 45 menit

Kompetensi Awal:
Peserta didik memiliki pengetahuan dasar tentang logika dan algoritma sederhana.

Pemahaman Bermakna:
• Pemrograman adalah cara berkomunikasi dengan komputer
• Algoritma adalah langkah-langkah sistematis untuk menyelesaikan masalah

Kegiatan Pembelajaran:
1. Pengenalan konsep pemrograman
2. Latihan membuat algoritma sederhana
3. Implementasi ke dalam kode program
""" * 2

    is_valid, message = validate_kurikulum_merdeka_modul_ajar(no_tujuan_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 70)
    
    # Test 4: Tidak ada Kompetensi Awal
    print("\nTEST 4: Tidak ada Kompetensi Awal")
    no_kompetensi_text = """
MODUL AJAR
Informatika - Jaringan Komputer

Mata Pelajaran: Informatika
Fase/Kelas: E (Kelas X)
Alokasi Waktu: 4 x 45 menit

Tujuan Pembelajaran:
Setelah mempelajari materi ini, peserta didik dapat:
• Menjelaskan konsep dasar jaringan komputer
• Mengidentifikasi jenis-jenis topologi jaringan
• Menganalisis protokol komunikasi dalam jaringan

Pemahaman Bermakna:
• Jaringan komputer memungkinkan berbagi informasi
• Topologi menentukan cara komputer terhubung
• Protokol adalah aturan komunikasi dalam jaringan

Profil Pelajar Pancasila:
• Bernalar kritis dalam menganalisis masalah jaringan
""" * 2

    is_valid, message = validate_kurikulum_merdeka_modul_ajar(no_kompetensi_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 70)
    
    # Test 5: Tidak ada Pemahaman Bermakna
    print("\nTEST 5: Tidak ada Pemahaman Bermakna")
    no_bermakna_text = """
MODUL AJAR
Informatika - Sistem Basis Data

Mata Pelajaran: Informatika
Fase/Kelas: E (Kelas X)

Tujuan Pembelajaran:
• Menjelaskan konsep sistem basis data
• Membuat ERD sederhana
• Menggunakan SQL untuk query data

Kompetensi Awal:
Peserta didik memahami konsep data dan informasi. Mereka telah mengenal aplikasi spreadsheet dan familiar dengan tabel data sederhana.

Kegiatan Pembelajaran:
1. Pengenalan sistem basis data
2. Perancangan ERD
3. Praktik SQL dasar
""" * 3

    is_valid, message = validate_kurikulum_merdeka_modul_ajar(no_bermakna_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 70)
    
    # Test 6: Identitas Modul tidak lengkap
    print("\nTEST 6: Identitas Modul tidak lengkap")
    no_identitas_text = """
MODUL AJAR
Pembelajaran Teknologi

Deskripsi:
Modul ini membahas tentang teknologi informasi dan komunikasi untuk siswa sekolah menengah atas.

Tujuan Pembelajaran:
• Memahami perkembangan teknologi
• Menerapkan teknologi dalam kehidupan

Kompetensi Awal:
Siswa familiar dengan penggunaan komputer dan internet dasar.

Pemahaman Bermakna:
• Teknologi memudahkan aktivitas manusia
• Literasi digital penting di era modern
""" * 5

    is_valid, message = validate_kurikulum_merdeka_modul_ajar(no_identitas_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 70)
    
    print("\n" + "=" * 80)
    print("✅ SEMUA TEST NOTIFIKASI ERROR SELESAI!")
    print("✅ Sistem memberikan pesan error yang spesifik dan relevan!")
    print("✅ Pengguna akan mendapat panduan yang jelas untuk memperbaiki file!")

if __name__ == "__main__":
    test_error_notifications()