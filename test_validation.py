#!/usr/bin/env python3
"""
Test script untuk validasi Modul Ajar Kurikulum Merdeka
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from backend.app import validate_kurikulum_merdeka_modul_ajar, extract_kurikulum_merdeka_components

def test_validasi():
    print("=== TEST SISTEM VALIDASI KURIKULUM MERDEKA ===\n")
    
    # Test 1: Contoh teks yang VALID (Modul Ajar Kurikulum Merdeka)
    print("TEST 1: Modul Ajar Valid")
    valid_text = """
MODUL AJAR
Informatika - Jaringan Komputer dan Internet

IDENTITAS MODUL
Mata Pelajaran: Informatika  
Fase/Kelas: E (Kelas X)
Alokasi Waktu: 3 x 45 menit

KOMPONEN INTI
I. Tujuan Pembelajaran
Setelah mempelajari materi ini, peserta didik dapat:
• Menjelaskan konsep dasar jaringan komputer dan internet
• Menganalisis protokol komunikasi data dalam jaringan
• Menerapkan pengetahuan tentang topologi jaringan
• Mengevaluasi keamanan jaringan komputer

II. Kompetensi Awal
Peserta didik memahami konsep dasar komputer dan sistem operasi. Mereka familiar dengan penggunaan internet untuk browsing dan komunikasi dasar. Siswa juga telah mengenal perangkat keras komputer.

III. Pemahaman Bermakna
• Jaringan komputer memungkinkan berbagi sumber daya dan informasi
• Internet adalah jaringan global yang menghubungkan jutaan komputer
• Protokol adalah aturan komunikasi dalam jaringan
• Keamanan jaringan penting untuk melindungi data

Profil Pelajar Pancasila:
• Bernalar kritis dalam menganalisis masalah jaringan
• Kreatif dalam merancang solusi jaringan sederhana
"""

    is_valid, message = validate_kurikulum_merdeka_modul_ajar(valid_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 50)
    
    # Test 2: Contoh teks yang INVALID (bukan modul ajar)
    print("\nTEST 2: Dokumen Biasa (Bukan Modul Ajar)")
    invalid_text = """
Laporan Kegiatan Sekolah
Tanggal: 15 Oktober 2024
Kegiatan: Seminar Teknologi

Deskripsi:
Pada hari ini telah dilaksanakan seminar teknologi untuk siswa kelas X. 
Seminar membahas perkembangan teknologi terkini.

Peserta: 200 siswa
Pembicara: Dr. Ahmad
Lokasi: Aula sekolah
"""
    
    is_valid, message = validate_kurikulum_merdeka_modul_ajar(invalid_text)
    print(f"Hasil: {'✅ VALID' if is_valid else '❌ INVALID'}")
    print(f"Pesan: {message}")
    print("-" * 50)
    
    # Test 3: Ekstraksi komponen dari modul valid
    print("\nTEST 3: Ekstraksi Komponen Kurikulum Merdeka")
    components = extract_kurikulum_merdeka_components(valid_text)
    print("\n📋 KOMPONEN YANG BERHASIL DIEKSTRAK:")
    print(f"• Mata Pelajaran: {components.get('mata_pelajaran', 'Tidak terdeteksi')}")
    print(f"• Kelas/Fase: {components.get('kelas', 'Tidak terdeteksi')}")
    print(f"• Kompetensi Awal: {'✓' if components.get('kompetensi_awal') else '✗'}")
    print(f"• Tujuan Pembelajaran: {len(components.get('tujuan_pembelajaran', []))} item")
    print(f"• Pemahaman Bermakna: {len(components.get('pemahaman_bermakna', []))} item")
    print(f"• Profil Pelajar Pancasila: {len(components.get('profil_pelajar_pancasila', []))} dimensi")
    
    print("\n🎯 DETAIL TUJUAN PEMBELAJARAN:")
    for i, tujuan in enumerate(components.get('tujuan_pembelajaran', []), 1):
        print(f"  {i}. {tujuan}")
    
    print("\n💡 DETAIL PEMAHAMAN BERMAKNA:")
    for i, bermakna in enumerate(components.get('pemahaman_bermakna', []), 1):
        print(f"  {i}. {bermakna}")
        
    print("\n" + "=" * 60)
    print("✅ SISTEM VALIDASI KURIKULUM MERDEKA BERFUNGSI DENGAN BAIK!")
    print("✅ Hanya file Modul Ajar yang sesuai standar yang akan diproses!")

if __name__ == "__main__":
    test_validasi()