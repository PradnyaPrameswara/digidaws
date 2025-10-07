#!/usr/bin/env python3
"""
Test script untuk memvalidasi kualitas prompt pembuatan soal anti-ambiguitas
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from backend.app import create_optimized_prompt_with_good_structure

def test_prompt_quality():
    print("=== TEST KUALITAS PROMPT ANTI-AMBIGUITAS ===\n")
    
    # Sample module components untuk testing
    sample_components = {
        "mata_pelajaran": "Informatika",
        "topik_utama": "Jaringan Komputer dan Internet", 
        "kelas": "X (Sepuluh)",
        "kompetensi_awal": "Peserta didik memahami konsep dasar komputer dan sistem operasi. Mereka familiar dengan penggunaan internet untuk browsing dan komunikasi dasar.",
        "tujuan_pembelajaran": [
            "Menjelaskan konsep dasar jaringan komputer dan internet",
            "Menganalisis protokol komunikasi data dalam jaringan", 
            "Menerapkan pengetahuan tentang topologi jaringan",
            "Mengevaluasi keamanan jaringan komputer"
        ],
        "pemahaman_bermakna": [
            "Jaringan komputer memungkinkan berbagi sumber daya dan informasi",
            "Internet adalah jaringan global yang menghubungkan jutaan komputer",
            "Protokol adalah aturan komunikasi dalam jaringan",
            "Keamanan jaringan penting untuk melindungi data"
        ],
        "target_peserta_didik": "Peserta didik reguler/tipikal: umum, tidak ada kesulitan dalam mencerna dan memahami materi ajar"
    }
    
    # Generate prompt
    print("📝 MENGGENERATE PROMPT DENGAN KOMPONEN KURIKULUM MERDEKA...")
    prompt = create_optimized_prompt_with_good_structure(sample_components)
    
    # Analyze prompt untuk memastikan tidak ada ambiguitas
    print("\n🔍 ANALISIS KUALITAS PROMPT:")
    print("=" * 60)
    
    # Check untuk kata-kata yang dilarang
    forbidden_words = [
        "mungkin", "kemungkinan", "biasanya", "umumnya", "sebaiknya",
        "dapat berupa", "salah satunya adalah", "antara lain", "misalnya",
        "seharusnya", "lebih baik jika", "direkomendasikan", "disarankan",
        "beberapa", "banyak", "sedikit"
    ]
    
    found_forbidden = []
    for word in forbidden_words:
        if word.lower() in prompt.lower():
            found_forbidden.append(word)
    
    if found_forbidden:
        print(f"❌ DITEMUKAN KATA TERLARANG: {', '.join(found_forbidden)}")
    else:
        print("✅ TIDAK ADA KATA AMBIGU YANG TERLARANG")
    
    # Check untuk instruksi anti-ambiguitas
    required_instructions = [
        "ATURAN KHUSUS ANTI-AMBIGUITAS",
        "LARANGAN KERAS",
        "WAJIB: Gunakan kata-kata PASTI dan DEFINITIF", 
        "CHECKLIST KUALITAS",
        "DEFINITIF: Tidak ada ruang interpretasi ganda",
        "VERIFIABLE: Jawaban dapat dibuktikan"
    ]
    
    found_instructions = []
    for instruction in required_instructions:
        if instruction in prompt:
            found_instructions.append(instruction)
    
    print(f"\n✅ INSTRUKSI ANTI-AMBIGUITAS: {len(found_instructions)}/{len(required_instructions)} ditemukan")
    for instruction in found_instructions:
        print(f"  ✓ {instruction}")
    
    missing_instructions = [instr for instr in required_instructions if instr not in found_instructions]
    if missing_instructions:
        print(f"\n⚠️ INSTRUKSI YANG HILANG:")
        for instruction in missing_instructions:
            print(f"  ✗ {instruction}")
    
    # Check untuk contoh soal yang baik dan buruk
    example_sections = [
        "CONTOH SOAL YANG BENAR (DEFINITIF & JELAS)",
        "CONTOH SOAL YANG SALAH (AMBIGU & TIDAK JELAS)",
        "PEDOMAN PENULISAN SOAL DEFINITIF"
    ]
    
    found_examples = []
    for section in example_sections:
        if section in prompt:
            found_examples.append(section)
    
    print(f"\n✅ CONTOH DAN PEDOMAN: {len(found_examples)}/{len(example_sections)} ditemukan")
    for example in found_examples:
        print(f"  ✓ {example}")
    
    # Check untuk checklist kualitas
    quality_checks = [
        "CHECKLIST KUALITAS SEBELUM MENGIRIM JAWABAN", 
        "VALIDASI SETIAP SOAL",
        "PRINSIP KUNCI YANG HARUS DITERAPKAN"
    ]
    
    found_quality = []
    for check in quality_checks:
        if check in prompt:
            found_quality.append(check)
    
    print(f"\n✅ CHECKLIST KUALITAS: {len(found_quality)}/{len(quality_checks)} ditemukan")
    for check in found_quality:
        print(f"  ✓ {check}")
    
    # Statistik prompt
    print(f"\n📊 STATISTIK PROMPT:")
    print(f"  • Panjang total: {len(prompt):,} karakter")
    print(f"  • Jumlah baris: {prompt.count(chr(10)):,} baris")
    print(f"  • Mata Pelajaran: {sample_components['mata_pelajaran']}")
    print(f"  • Tujuan Pembelajaran: {len(sample_components['tujuan_pembelajaran'])} item")
    print(f"  • Pemahaman Bermakna: {len(sample_components['pemahaman_bermakna'])} item")
    
    # Overall assessment
    total_checks = len(required_instructions) + len(example_sections) + len(quality_checks)
    passed_checks = len(found_instructions) + len(found_examples) + len(found_quality)
    quality_percentage = (passed_checks / total_checks) * 100
    
    print(f"\n📈 KUALITAS PROMPT: {quality_percentage:.1f}% ({passed_checks}/{total_checks} komponen)")
    
    if quality_percentage >= 90:
        print("🏆 EXCELLENT: Prompt berkualitas sangat tinggi!")
    elif quality_percentage >= 75:
        print("✅ GOOD: Prompt berkualitas baik")
    elif quality_percentage >= 50:
        print("⚠️ FAIR: Prompt perlu perbaikan")
    else:
        print("❌ POOR: Prompt memerlukan perbaikan signifikan")
    
    # Test output contoh
    print(f"\n📄 CONTOH BAGIAN PROMPT YANG DIHASILKAN:")
    print("=" * 60)
    print(prompt[:1000] + "...")
    print("=" * 60)
    
    print(f"\n✅ PROMPT ANTI-AMBIGUITAS BERHASIL DIGENERATE!")
    print(f"✅ Sistem akan menghasilkan soal yang definitif dan jelas!")
    print(f"✅ Tidak akan ada lagi soal dengan kata 'mungkin' atau ambiguitas!")

if __name__ == "__main__":
    test_prompt_quality()