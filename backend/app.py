import datetime
import json
import os
import random
import re
import sys
import tempfile
from io import BytesIO
from pathlib import Path
import google.generativeai as genai
import mammoth
import pandas as pd
import PyPDF2
from docx import Document
from flask import (Blueprint, Flask, flash, jsonify, redirect,
                   render_template, request, send_file, url_for)
from flask_login import (LoginManager, UserMixin, current_user,
                         login_required, login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from werkzeug.security import check_password_hash, generate_password_hash
from xhtml2pdf import pisa

# Define the root directory (parent of backend)
ROOT_DIR = Path(__file__).parent.parent

# Add the root directory to the Python path
sys.path.insert(0, str(ROOT_DIR))

# Flask app with proper template and static configuration
app = Flask(__name__, 
            template_folder=os.path.join(ROOT_DIR, 'frontend'),
            static_folder=os.path.join(ROOT_DIR, 'img'))

# Add secret key for session
app.secret_key = '70315ac5aa5fee60d775f2ad95d2a163b24a4ba65583df64620acc3a283ccbc8'  # Replace with a real secret key in production

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Specify your login route

@login_manager.user_loader
def load_user(user_id):
    if isinstance(user_id, str):
        if user_id.startswith('guru_'):
            actual_id = int(user_id.split('_')[1])
            return Guru.query.get(actual_id)
        elif user_id.startswith('siswa_'):
            actual_id = int(user_id.split('_')[1])
            return Siswa.query.get(actual_id)
    return None

# Konfigurasi MySQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:@localhost/asesment_diagnostik_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['SQLALCHEMY_ECHO'] = True  # Tambahan untuk debug SQL queries
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# =========================================
# KONFIGURASI GEMINI AI
# =========================================
# Gunakan environment variable untuk API key
my_api_key_gemini = 'AIzaSyCcx9iCB6oGXUPGoW2Ot3Mk7JjIreeCzRQ' 
genai.configure(api_key=my_api_key_gemini)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# =========================================
# PROGRESS TRACKING SYSTEM
# =========================================
# Global dictionary untuk tracking progress setiap user
progress_tracker = {}

def update_progress(user_id, step, status="active", message=""):
    """Update progress untuk user tertentu"""
    if user_id not in progress_tracker:
        progress_tracker[user_id] = {
            "current_step": 1,
            "steps": {
                1: {"status": "pending", "message": "Mengunggah file modul ajar"},
                2: {"status": "pending", "message": "Menganalisis struktur dokumen"},
                3: {"status": "pending", "message": "Mengekstrak tujuan pembelajaran"},
                4: {"status": "pending", "message": "Memproses dengan AI Gemini"},
                5: {"status": "pending", "message": "Menyimpan soal ke database"}
            },
            "timestamp": datetime.datetime.now()
        }
    
    # Update status step yang spesifik
    if step in progress_tracker[user_id]["steps"]:
        progress_tracker[user_id]["steps"][step]["status"] = status
        if message:
            progress_tracker[user_id]["steps"][step]["message"] = message
        progress_tracker[user_id]["current_step"] = step
        progress_tracker[user_id]["timestamp"] = datetime.datetime.now()
        print(f"Progress updated for user {user_id}: Step {step} - {status}")

def get_progress(user_id):
    """Ambil progress untuk user tertentu"""
    return progress_tracker.get(user_id, None)

def clear_progress(user_id):
    """Bersihkan progress setelah selesai"""
    if user_id in progress_tracker:
        del progress_tracker[user_id]

# =========================================
# OPTIMIZED MODULE EXTRACTION FUNCTIONS
# =========================================

def validate_educational_content_flexible(content_text):
    """
    Validasi fleksibel untuk dokumen pembelajaran - lebih toleran tapi tetap filter yang relevan
    """
    if not content_text or len(content_text.strip()) < 300:  # Dikurangi dari 500 ke 300
        return False, "Dokumen terlalu pendek untuk modul pembelajaran (minimal 300 karakter)"
    
    content_lower = content_text.lower()
    
    # 1. Cek kata kunci pembelajaran (lebih fleksibel)
    modul_keywords = [
        'modul ajar', 'modul pembelajaran', 'rencana pembelajaran', 'rpp',
        'lesson plan', 'learning module', 'teaching module', 'silabus',
        'bahan ajar', 'materi pembelajaran', 'panduan pembelajaran'
    ]
    
    has_modul = any(keyword in content_lower for keyword in modul_keywords)
    
    # 2. Cek tujuan pembelajaran (lebih fleksibel)
    tujuan_keywords = [
        'tujuan pembelajaran', 'learning objective', 'capaian pembelajaran',
        'kompetensi dasar', 'learning outcome', 'objektif pembelajaran',
        'tujuan', 'capaian', 'kompetensi', 'indikator', 'cp'
    ]
    
    has_tujuan = any(keyword in content_lower for keyword in tujuan_keywords)
    
    # 3. Cek indikator pendidikan
    educational_indicators = [
        'siswa', 'peserta didik', 'mahasiswa', 'pelajar', 'murid',
        'guru', 'pengajar', 'dosen', 'instruktur', 'fasilitator',
        'pembelajaran', 'belajar', 'mengajar', 'pendidikan'
    ]
    
    edu_count = sum(1 for indicator in educational_indicators if indicator in content_lower)
    
    # 4. Cek struktur pembelajaran (opsional)
    struktur_keywords = [
        'kegiatan pembelajaran', 'langkah pembelajaran', 'aktivitas belajar',
        'metode pembelajaran', 'strategi pembelajaran', 'pendekatan pembelajaran',
        'asesmen', 'penilaian', 'evaluasi pembelajaran', 'kegiatan', 'metode', 'strategi'
    ]
    
    struktur_count = sum(1 for keyword in struktur_keywords if keyword in content_lower)
    
    # LOGIKA FLEKSIBEL: Minimal 2 dari 4 kriteria terpenuhi
    score = 0
    missing_criteria = []
    
    if has_modul:
        score += 1
    else:
        missing_criteria.append("kata kunci modul/pembelajaran")
    
    if has_tujuan:
        score += 1  
    else:
        missing_criteria.append("tujuan pembelajaran")
    
    if edu_count >= 2:
        score += 1
    else:
        missing_criteria.append("konteks pendidikan")
        
    if struktur_count >= 1:
        score += 1
    else:
        missing_criteria.append("struktur pembelajaran")
    
    # Minimal 2 dari 4 kriteria harus terpenuhi
    if score >= 2:
        return True, "Dokumen diterima sebagai materi pembelajaran"
    else:
        return False, f"Dokumen tidak memenuhi cukup kriteria pembelajaran. Kurang: {', '.join(missing_criteria)}"

def validate_file_format_and_content(file_stream, file_ext, filename):
    """
    Validasi format file dan konten secara fleksibel
    """
    try:
        # 1. Validasi ukuran file (lebih toleran)
        file_size = len(file_stream)
        if file_size < 512:  # Dikurangi dari 1KB ke 512 bytes
            return False, "File terlalu kecil. File pembelajaran minimal berukuran 512 bytes"
        
        if file_size > 15 * 1024 * 1024:  # Dinaikkan dari 10MB ke 15MB
            return False, "File terlalu besar. Maksimal ukuran file adalah 15MB"
        
        # 2. Validasi nama file (lebih fleksibel) - OPSIONAL
        filename_keywords = ['modul', 'pembelajaran', 'ajar', 'lesson', 'rpp', 'materi', 'bahan', 'silabus']
        has_relevant_filename = any(keyword in filename.lower() for keyword in filename_keywords)
        # Tidak reject jika nama file tidak sesuai, hanya beri peringatan
        
        # 3. Ekstrak dan validasi konten
        content_text = ""
        if file_ext == 'pdf':
            content_text = extract_text_from_pdf_bytes(file_stream)
        elif file_ext in ['doc', 'docx']:
            content_text = extract_text_from_docx_bytes(file_stream, file_ext)
        
        if not content_text:
            return False, "Tidak dapat mengekstrak teks dari file. Pastikan file tidak rusak atau terproteksi"
        
        # 4. Validasi konten pendidikan secara fleksibel
        is_valid, message = validate_educational_content_flexible(content_text)
        if not is_valid:
            return False, message
        
        # Tambahkan warning jika nama file tidak sesuai tapi tetap lanjutkan
        if not has_relevant_filename:
            print(f"WARNING: Nama file '{filename}' tidak mengindikasikan materi pembelajaran, tapi konten valid")
            
        return True, content_text
        
    except Exception as e:
        return False, f"Error validasi file: {str(e)}"

def check_content_quality_score(module_components):
    """
    Periksa kualitas ekstraksi untuk memastikan layak diproses (versi lebih toleran)
    """
    quality_score = 0
    issues = []
    
    # 1. Mata Pelajaran (20 poin) - lebih toleran
    mata_pelajaran = module_components.get("mata_pelajaran", "")
    if mata_pelajaran and len(mata_pelajaran.strip()) > 2:  # Dikurangi dari 5 ke 2
        quality_score += 20
    elif mata_pelajaran:  # Ada tapi pendek, beri setengah poin
        quality_score += 10
        issues.append("Mata pelajaran terdeteksi tapi kurang jelas")
    else:
        issues.append("Mata pelajaran tidak teridentifikasi")
    
    # 2. Tujuan Pembelajaran (40 poin - paling penting tapi lebih fleksibel)
    tujuan_list = module_components.get("tujuan_pembelajaran", [])
    if tujuan_list and len(tujuan_list) >= 1:  # Dikurangi dari 2 ke 1
        # Periksa kualitas setiap tujuan
        valid_tujuan = [t for t in tujuan_list if len(t.strip()) > 10]  # Dikurangi dari 15 ke 10
        if len(valid_tujuan) >= 2:
            quality_score += 40
        elif len(valid_tujuan) >= 1:
            quality_score += 30  # Dinaikkan dari 25 ke 30
            issues.append("Tujuan pembelajaran ditemukan tapi bisa lebih detail")
        else:
            quality_score += 15
            issues.append("Tujuan pembelajaran ditemukan tapi sangat singkat")
    else:
        issues.append("Tujuan pembelajaran tidak ditemukan")
    
    # 3. Kompetensi Awal (15 poin) - lebih toleran
    kompetensi_awal = module_components.get("kompetensi_awal", "")
    if kompetensi_awal and len(kompetensi_awal.strip()) > 20:  # Dikurangi dari 30 ke 20
        quality_score += 15
    elif kompetensi_awal and len(kompetensi_awal.strip()) > 5:
        quality_score += 8  # Beri poin parsial
        issues.append("Kompetensi awal terdeteksi tapi kurang detail")
    else:
        quality_score += 5  # Beri poin minimal bahkan jika tidak ada
        issues.append("Kompetensi awal tidak teridentifikasi")
    
    # 4. Pemahaman Bermakna (15 poin) - lebih toleran
    pemahaman_list = module_components.get("pemahaman_bermakna", [])
    if pemahaman_list and len(pemahaman_list) >= 1:
        quality_score += 15
    else:
        quality_score += 8  # Beri poin parsial meski tidak ada
        issues.append("Pemahaman bermakna tidak ditemukan")
    
    # 5. Target Peserta Didik (10 poin) - lebih toleran
    target_peserta = module_components.get("target_peserta_didik", "")
    if target_peserta and len(target_peserta.strip()) > 10:  # Dikurangi dari 20 ke 10
        quality_score += 10
    else:
        quality_score += 5  # Beri poin parsial
        issues.append("Target peserta didik tidak teridentifikasi")
    
    return quality_score, issues

def extract_specific_module_components(content_text):
    """
    Ekstrak komponen spesifik dari modul ajar dengan format Roman numeral
    ENHANCED: Pattern yang sangat fleksibel dengan fallback multiple untuk semua format dokumen
    """
    results = {
        "mata_pelajaran": "",
        "topik_utama": "",
        "kelas": "",
        "kompetensi_awal": "",
        "tujuan_pembelajaran": [],
        "pemahaman_bermakna": [],
        "target_peserta_didik": "",
        "model_pembelajaran": ""
    }
    
    content = content_text
    content_lower = content_text.lower()
    
    # 1. Ekstrak Mata Pelajaran dan Topik dari header MODUL AJAR
    modul_match = re.search(r'modul\s+ajar\s*\n([^\n]+)', content, re.IGNORECASE)
    if modul_match:
        results["mata_pelajaran"] = modul_match.group(1).strip()
        results["topik_utama"] = modul_match.group(1).strip()
    
    # 2. Ekstrak Kelas dari Identitas Modul  
    kelas_match = re.search(r'fase\s*/\s*kelas\s*:\s*([^\n]+)', content, re.IGNORECASE)
    if kelas_match:
        results["kelas"] = kelas_match.group(1).strip()
    
    # 3. PERBAIKAN: Ekstrak Kompetensi Awal dengan pattern yang lebih fleksibel
    kompetensi_patterns = [
        r'ii\.\s*kompetensi\s+awal\s*\n(.*?)(?=\niii\.|$)',
        r'kompetensi\s+awal\s*[\:\n](.*?)(?=\n[IVX]+\.|$)',
        r'ii[\.\s]*kompetensi\s+awal[^\n]*\n(.*?)(?=\n[IVX]+\.|$)'
    ]
    
    for pattern in kompetensi_patterns:
        kompetensi_match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if kompetensi_match:
            kompetensi_text = kompetensi_match.group(1).strip()
            sentences = re.split(r'[.!?]+', kompetensi_text)
            key_sentences = [s.strip() for s in sentences[:2] if s.strip()]
            results["kompetensi_awal"] = ". ".join(key_sentences) + "." if key_sentences else kompetensi_text[:400]
            break
    
    # 4. ENHANCED: Ekstrak Tujuan Pembelajaran dengan strategi berlapis
    tujuan_patterns = [
        # Pattern 1: Dalam KOMPONEN INTI dengan berbagai format
        r'komponen\s+inti.*?i\.\s*tujuan\s+pembelajaran\s*[:\n](.*?)(?=\n\s*ii\.|pemahaman\s+bermakna|pertanyaan\s+pemantik|$)',
        # Pattern 2: Roman numeral langsung dengan flexible spacing
        r'i\.\s*tujuan\s+pembelajaran\s*[:\n](.*?)(?=\n\s*ii\.|pemahaman\s+bermakna|pertanyaan\s+pemantik|$)',
        # Pattern 3: Tanpa Roman numeral tapi dengan header
        r'tujuan\s+pembelajaran\s*[:\n](.*?)(?=\n\s*(?:pemahaman\s+bermakna|pertanyaan\s+pemantik|kompetensi\s+awal|ii\.|2\.|$))',
        # Pattern 4: Dengan bullets/numbering di line yang sama
        r'tujuan\s+pembelajaran[^\n]*\n((?:[•\-\*\d\.]\s*[^\n]+\n?){2,})',
        # Pattern 5: Mencari di sekitar kata "siswa dapat/mampu"
        r'(?:setelah\s+pembelajaran|pada\s+akhir\s+pembelajaran|tujuan\s+pembelajaran)[^\n]*\n?(.*?(?:siswa\s+(?:dapat|mampu)|peserta\s+didik\s+(?:dapat|mampu))[^\n]*(?:\n[^\n]*(?:siswa\s+(?:dapat|mampu)|peserta\s+didik\s+(?:dapat|mampu)))*)',
    ]
    
    tujuan_found = False
    for i, pattern in enumerate(tujuan_patterns, 1):
        if tujuan_found:
            break
            
        tujuan_match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if tujuan_match:
            tujuan_text = tujuan_match.group(1).strip()
            print(f"DEBUG: Tujuan pembelajaran ditemukan dengan pattern {i}")
            print(f"DEBUG: Raw text (300 chars): {tujuan_text[:300]}...")
            
            # Strategy 1: Cari bullet points atau numbering
            bullets = re.findall(r'(?:^|\n)\s*[•\-\*\d\.]\s*([^\n•\-\*]+)', tujuan_text, re.MULTILINE)
            bullets = [b.strip() for b in bullets if len(b.strip()) > 15]
            
            if len(bullets) >= 2:
                results["tujuan_pembelajaran"] = bullets[:6]
                print(f"DEBUG: Bullet points found: {len(bullets)} items")
                tujuan_found = True
                break
            
            # Strategy 2: Cari kalimat dengan "siswa dapat/mampu"
            learning_sentences = re.findall(r'[^\n.!?]*(?:siswa\s+(?:dapat|mampu)|peserta\s+didik\s+(?:dapat|mampu))[^\n.!?]*[.!?\n]', 
                                          tujuan_text, re.IGNORECASE)
            learning_sentences = [s.strip().rstrip('.!?\n') for s in learning_sentences if len(s.strip()) > 20]
            
            if len(learning_sentences) >= 2:
                results["tujuan_pembelajaran"] = learning_sentences[:5]
                print(f"DEBUG: Learning sentences found: {len(learning_sentences)} items")
                tujuan_found = True
                break
            
            # Strategy 3: Split by line breaks, filter meaningful lines
            lines = [line.strip() for line in tujuan_text.split('\n') if line.strip()]
            meaningful_lines = []
            for line in lines:
                # Filter lines that look like learning objectives
                if (len(line) > 20 and 
                    any(keyword in line.lower() for keyword in ['dapat', 'mampu', 'menjelaskan', 'menganalisis', 
                                                               'menerapkan', 'memahami', 'mengidentifikasi', 
                                                               'mendemonstrasikan', 'membuat', 'merancang'])):
                    meaningful_lines.append(line)
            
            if len(meaningful_lines) >= 2:
                results["tujuan_pembelajaran"] = meaningful_lines[:5]
                print(f"DEBUG: Meaningful lines found: {len(meaningful_lines)} items")
                tujuan_found = True
                break
            
            # Strategy 4: Split by punctuation, look for objective phrases
            sentences = re.split(r'[.!?]+', tujuan_text)
            valid_sentences = []
            for sentence in sentences:
                sentence = sentence.strip()
                if (len(sentence) > 20 and 
                    any(keyword in sentence.lower() for keyword in ['dapat', 'mampu', 'menjelaskan', 'menganalisis', 
                                                                   'menerapkan', 'memahami', 'mengidentifikasi'])):
                    valid_sentences.append(sentence)
            
            if len(valid_sentences) >= 2:
                results["tujuan_pembelajaran"] = valid_sentences[:4]
                print(f"DEBUG: Valid sentences found: {len(valid_sentences)} items")
                tujuan_found = True
                break
    
    # ULTIMATE FALLBACK: Scan entire document for learning objectives
    if not tujuan_found:
        print("DEBUG: FALLBACK - Scanning entire document for learning objectives")
        
        # Look for any sentences with learning keywords
        all_learning_sentences = re.findall(
            r'[^\n.!?]*(?:siswa\s+(?:dapat|mampu|akan)|peserta\s+didik\s+(?:dapat|mampu|akan)|setelah\s+mempelajari)[^\n.!?]*[.!?\n]', 
            content, re.IGNORECASE)
        
        # Clean and filter sentences
        filtered_sentences = []
        for sentence in all_learning_sentences:
            sentence = sentence.strip().rstrip('.!?\n')
            if len(sentence) > 25 and len(sentence) < 200:  # Reasonable length
                filtered_sentences.append(sentence)
        
        if len(filtered_sentences) >= 2:
            results["tujuan_pembelajaran"] = filtered_sentences[:4]
            print(f"DEBUG: FALLBACK found {len(filtered_sentences)} learning objectives")
            tujuan_found = True
        
        # Last resort: Look for any "dapat" or "mampu" sentences near learning-related words
        if not tujuan_found:
            broader_sentences = re.findall(
                r'[^\n.!?]*(?:dapat|mampu)[^\n.!?]*(?:jaringan|komputer|internet|teknologi|informasi)[^\n.!?]*[.!?\n]', 
                content, re.IGNORECASE)
            
            if broader_sentences:
                results["tujuan_pembelajaran"] = [s.strip().rstrip('.!?\n') for s in broader_sentences[:3]]
                print(f"DEBUG: LAST RESORT found {len(broader_sentences)} tech-related objectives")
    
    # 5. ENHANCED: Ekstrak Pemahaman Bermakna dengan multiple strategies
    bermakna_patterns = [
        r'komponen\s+inti.*?ii\.\s*pemahaman\s+bermakna\s*[:\n](.*?)(?=\n\s*iii\.|pertanyaan\s+pemantik|profil\s+pelajar|$)',
        r'ii\.\s*pemahaman\s+bermakna\s*[:\n](.*?)(?=\n\s*iii\.|pertanyaan\s+pemantik|profil\s+pelajar|$)',
        r'pemahaman\s+bermakna\s*[:\n](.*?)(?=\n\s*(?:pertanyaan\s+pemantik|profil\s+pelajar|iii\.|3\.|$))',
        r'pemahaman\s+bermakna[^\n]*\n((?:[•\-\*\d\.]\s*[^\n]+\n?){1,})'
    ]
    
    for i, pattern in enumerate(bermakna_patterns, 1):
        bermakna_match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if bermakna_match:
            bermakna_text = bermakna_match.group(1).strip()
            print(f"DEBUG: Pemahaman bermakna found with pattern {i}")
            print(f"DEBUG: Bermakna text (200 chars): {bermakna_text[:200]}...")
            
            # Strategy 1: Extract bullets/numbers
            bullets = re.findall(r'(?:^|\n)\s*[•\-\*\d\.]\s*([^\n•\-\*]+)', bermakna_text, re.MULTILINE)
            bullets = [b.strip() for b in bullets if len(b.strip()) > 10]
            
            if bullets:
                results["pemahaman_bermakna"] = bullets[:4]
                print(f"DEBUG: Bermakna bullets found: {len(bullets)} items")
                break
            
            # Strategy 2: Split by lines
            lines = [line.strip() for line in bermakna_text.split('\n') if line.strip() and len(line.strip()) > 15]
            if lines:
                results["pemahaman_bermakna"] = lines[:3]
                print(f"DEBUG: Bermakna lines found: {len(lines)} items")
                break
            
            # Strategy 3: Use entire text if short enough
            if len(bermakna_text) < 300:
                results["pemahaman_bermakna"] = [bermakna_text]
                print("DEBUG: Using entire bermakna text")
                break
    
    # 6. Target Peserta Didik (tetap sama)
    target_pattern = r'v\.\s*target\s+peserta\s+didik\s*\n(.*?)(?=\nvi\.|$)'
    target_match = re.search(target_pattern, content, re.IGNORECASE | re.DOTALL)
    if target_match:
        results["target_peserta_didik"] = target_match.group(1).strip()[:300]
    
    # DEBUG: Print hasil ekstraksi
    print(f"DEBUG EKSTRAKSI FINAL:")
    print(f"- Mata Pelajaran: {results['mata_pelajaran']}")
    print(f"- Tujuan Pembelajaran: {len(results['tujuan_pembelajaran'])} items")
    for i, tujuan in enumerate(results['tujuan_pembelajaran'][:3], 1):
        print(f"  {i}. {tujuan[:120]}...")
    print(f"- Pemahaman Bermakna: {len(results['pemahaman_bermakna'])} items")
    for i, bermakna in enumerate(results['pemahaman_bermakna'][:3], 1):
        print(f"  {i}. {bermakna[:120]}...")
    
    return results

def validate_detected_keywords(module_components):
    """
    Validasi apakah keyword penting sudah terdeteksi dengan benar
    """
    validation_report = {
        "detected": [],
        "missing": [],
        "quality_score": 0
    }
    
    # Cek komponen yang terdeteksi
    if module_components.get("mata_pelajaran"):
        validation_report["detected"].append("Mata Pelajaran")
    else:
        validation_report["missing"].append("Mata Pelajaran")
    
    # Enhanced validation for Tujuan Pembelajaran
    tujuan_list = module_components.get("tujuan_pembelajaran", [])
    if tujuan_list and len(tujuan_list) >= 2:
        # Periksa apakah item-item memiliki konten yang bermakna
        meaningful_items = [item for item in tujuan_list if len(item.strip()) > 15]
        if len(meaningful_items) >= 2:
            validation_report["detected"].append(f"Tujuan Pembelajaran ({len(tujuan_list)} item)")
        else:
            validation_report["missing"].append("Tujuan Pembelajaran")
    else:
        validation_report["missing"].append("Tujuan Pembelajaran")
    
    # Enhanced validation for Kompetensi Awal
    if module_components.get("kompetensi_awal") and len(module_components["kompetensi_awal"]) > 30:
        validation_report["detected"].append("Kompetensi Awal")
    else:
        validation_report["missing"].append("Kompetensi Awal")
    
    # Enhanced validation for Pemahaman Bermakna
    bermakna_list = module_components.get("pemahaman_bermakna", [])
    if bermakna_list and len(bermakna_list) > 0:
        # Periksa apakah ada konten bermakna
        meaningful_bermakna = [item for item in bermakna_list if len(item.strip()) > 10]
        if meaningful_bermakna:
            validation_report["detected"].append(f"Pemahaman Bermakna ({len(bermakna_list)} item)")
        else:
            validation_report["missing"].append("Pemahaman Bermakna")
    else:
        validation_report["missing"].append("Pemahaman Bermakna")
    
    # Enhanced quality score calculation with bonuses
    total_components = 4
    detected_components = len(validation_report["detected"])
    base_score = (detected_components / total_components) * 100
    
    # Bonus points for quality content
    bonus = 0
    if len(tujuan_list) >= 3:  # Bonus jika tujuan pembelajaran banyak
        bonus += 5
    if len(bermakna_list) >= 2:  # Bonus jika pemahaman bermakna banyak
        bonus += 5
    if module_components.get("target_peserta_didik"):  # Bonus jika ada target
        bonus += 5
        
    validation_report["quality_score"] = min(100, base_score + bonus)
    
    return validation_report

def log_extraction_results(module_components):
    """
    Log hasil ekstraksi untuk debugging dan monitoring
    """
    print("=== HASIL EKSTRAKSI MODUL AJAR ===")
    print(f"Mata Pelajaran: {module_components.get('mata_pelajaran', 'TIDAK TERDETEKSI')}")
    print(f"Topik Utama: {module_components.get('topik_utama', 'TIDAK TERDETEKSI')}")
    print(f"Kelas: {module_components.get('kelas', 'TIDAK TERDETEKSI')}")
    
    # Detail Tujuan Pembelajaran
    tujuan_items = module_components.get('tujuan_pembelajaran', [])
    print(f"Tujuan Pembelajaran: {len(tujuan_items)} item")
    if tujuan_items:
        for i, tujuan in enumerate(tujuan_items[:3], 1):
            print(f"  {i}. {tujuan[:80]}{'...' if len(tujuan) > 80 else ''}")
        if len(tujuan_items) > 3:
            print(f"  ... dan {len(tujuan_items) - 3} tujuan lainnya")
    
    # Detail Pemahaman Bermakna
    bermakna_items = module_components.get('pemahaman_bermakna', [])
    print(f"Pemahaman Bermakna: {len(bermakna_items)} item")
    if bermakna_items:
        for i, bermakna in enumerate(bermakna_items[:3], 1):
            print(f"  {i}. {bermakna[:80]}{'...' if len(bermakna) > 80 else ''}")
    
    print(f"Kompetensi Awal: {'✓' if module_components.get('kompetensi_awal') else '✗'}")
    print(f"Target Peserta Didik: {'✓' if module_components.get('target_peserta_didik') else '✗'}")
    
    # Validasi
    validation = validate_detected_keywords(module_components)
    print(f"Quality Score: {validation['quality_score']:.1f}%")
    if validation["missing"]:
        print(f"Komponen yang tidak terdeteksi: {', '.join(validation['missing'])}")
    print("=====================================")
    
    return validation

def create_optimized_prompt_with_good_structure(module_components):
    """
    Buat prompt dengan struktur lama yang bagus tetapi data yang sudah dioptimalkan
    """
    
    # Format tujuan pembelajaran
    tujuan_list = []
    for i, tujuan in enumerate(module_components.get("tujuan_pembelajaran", [])[:6], 1):
        tujuan_list.append(f"• {tujuan.strip()}")
    
    # Format pemahaman bermakna
    pemahaman_list = []
    for i, pemahaman in enumerate(module_components.get("pemahaman_bermakna", [])[:4], 1):
        pemahaman_list.append(f"• {pemahaman.strip()}")
    
    # Menggunakan struktur prompt lama yang sudah bagus
    prompt = f"""
Anda adalah seorang ahli pembuat soal asesmen diagnostik yang bertugas membantu guru untuk membuat soal yang akan diberikan pada siswa SMA. Soal dibuat berdasarkan Tujuan Pembelajaran dan komponen modul ajar yang telah diekstrak.

ANALISIS MODUL AJAR:
========================================
MODUL/ELEMEN AJAR:
{module_components.get("mata_pelajaran", "Informatika")} - {module_components.get("topik_utama", "Pembelajaran Teknologi")}
Kelas: {module_components.get("kelas", "X (Sepuluh)")}

KOMPETENSI AWAL:
{module_components.get("kompetensi_awal", "Siswa memiliki kemampuan dasar dalam berpikir logis dan pemecahan masalah")}

TUJUAN PEMBELAJARAN:
{chr(10).join(tujuan_list) if tujuan_list else "• Memahami konsep dasar materi pembelajaran"}

PEMAHAMAN BERMAKNA:
{chr(10).join(pemahaman_list) if pemahaman_list else "• Mengembangkan pemahaman konseptual yang mendalam"}

TARGET PESERTA DIDIK:
{module_components.get("target_peserta_didik", "Peserta didik reguler/tipikal: umum, tidak ada kesulitan dalam mencerna dan memahami materi ajar")}
========================================

**Indeks Kesulitan Item untuk Diagnosis Kognitif**
Indeks kesulitan item sangat penting dalam menilai kemampuan kognitif individu di berbagai domain. Hal ini penting untuk mendapatkan pemahaman mendalam tentang kekuatan dan kelemahan kognitif seseorang.

Kesulitan item dalam diagnosis kognitif menggambarkan seberapa menantang item tes tertentu terhadap konstruk kognitif yang dievaluasi. Tingkat kesulitan ini diukur dengan indeks kesulitan item.

**Membuat Sesi Multi-Tahap Berdasarkan Taksonomi Kompetensi Teknologi**
Dalam membuat soal untuk sesi multi-tahap, gunakan taksonomi kompetensi teknologi berikut sebagai panduan untuk menentukan tipe dan tingkat kesulitan soal pada setiap level:

SPESIFIKASI SOAL PER LEVEL:
========================================
Stage I (Kotak 1) → Kesadaran Teknologi
Probabilitas (p): 0.95
Fokus soal: definisi, istilah, identifikasi teknologi dasar
Jenis pengetahuan: knowledge that
Contoh soal: "Alat yang digunakan untuk menyimpan data berbasis internet adalah..."

Stage II (Kotak 2) → Literasi Teknologi
Probabilitas (p): 0.90
Fokus soal: klasifikasi, hubungan antar teknologi, penjelasan fungsi
Jenis pengetahuan: knowledge that
Contoh soal: "Manakah teknologi yang termasuk komunikasi sinkron?"

Stage III
Kotak 3 → Kemampuan Teknologi
p: 0.75
Fokus soal: aplikasi praktis sederhana, langkah-langkah dasar teknologi
Jenis pengetahuan: knowledge that + how (level SMA)
Contoh soal: "Urutkan langkah membuat email: 1) login 2) klik compose 3) isi pesan 4) kirim"

Kotak 4 → Kreativitas Teknologi (Dasar)
p: 0.67
Fokus soal: identifikasi masalah sederhana, pemecahan masalah dasar
Jenis pengetahuan: knowledge that + how (level SMA)
Contoh soal: "Jika komputer tidak bisa terhubung internet, langkah pertama yang dilakukan adalah..."

Stage IV (Final)
Kotak 5 → Kemampuan Teknologi (penguatan)
p: 0.75
Soal aplikasi lanjutan yang sesuai SMA, tidak melibatkan coding kompleks

Kotak 6 → Kritik Teknologi
p: 0.20
Fokus soal: membandingkan teknologi sederhana, memilih solusi yang tepat
Jenis pengetahuan: knowledge that + how + why (level SMA)
Contoh soal: "Untuk menyimpan foto keluarga, mana yang lebih aman: flash disk atau cloud storage?"

Kotak 7 → Kreativitas + Kritik Teknologi (Final Tinggi)
p: 0.17
Fokus soal: merancang solusi sederhana menggunakan teknologi yang familiar
Jenis pengetahuan: knowledge that + how + why (level SMA)  
Contoh soal: "Untuk membuat presentasi sekolah yang menarik, kombinasi aplikasi terbaik adalah..."

ATURAN PENTING:
========================================
✓ Setiap soal merujuk langsung pada konten modul yang dianalisis
✓ Gunakan terminologi spesifik dari modul
✓ 4 pilihan (A, B, C, D), maksimal 15 kata per opsi
✓ Posisi jawaban benar ACAK dan bervariasi
✓ Pengecoh masuk akal, cerminkan miskonsepsi umum
✓ Bahasa lugas, sesuai jenjang siswa SMA kelas X
✓ Kalimat soal maksimal 3 baris
✓ Fokus pada konsep dan aplikasi, bukan coding kompleks
✓ Gunakan contoh teknologi yang familiar untuk siswa SMA

✗ JANGAN gunakan: "Modul Ajar", "Kompetensi Awal", "Tujuan Pembelajaran", "Siswa", "Peserta didik" dalam teks soal
✗ JANGAN buat soal generik yang lepas dari modul
✗ JANGAN buat jawaban benar selalu yang terpanjang
✗ JANGAN buat soal coding/programming yang terlalu teknis
✗ JANGAN gunakan istilah teknis tingkat universitas
✗ JANGAN buat soal yang memerlukan pengetahuan di luar kurikulum SMA

ADAPTASI KONTEKS KHUSUS SMA KELAS X:
========================================
GAYA BAHASA & KOMPLEKSITAS:
- Gunakan bahasa yang mudah dipahami siswa usia 15-16 tahun
- Contoh teknologi: smartphone, laptop, WiFi, aplikasi populer (WhatsApp, Instagram, YouTube)
- Hindari jargon teknis tingkat lanjut atau bahasa pemrograman kompleks
- Fokus pada konsep dasar teknologi informasi dan komunikasi
- Gunakan konteks sekolah dan kehidupan remaja

CONTOH SOAL YANG SESUAI:
- "Aplikasi yang paling tepat untuk mengedit video sederhana adalah..."
- "Untuk mengamankan akun media sosial, sebaiknya kita..."  
- "Perbedaan utama antara RAM dan storage adalah..."
- "Langkah pertama mengatasi komputer yang lemot adalah..."

CONTOH SOAL YANG DIHINDARI:
- Coding dengan sintaks pemrograman
- Konfigurasi server atau database kompleks  
- Analisis algoritma tingkat lanjut
- Konsep networking di level enterprise

FORMAT OUTPUT - JSON ARRAY:
PENTING: Berikan response dalam format JSON array yang valid. Jangan tambahkan teks apapun sebelum atau sesudah JSON.

Contoh format yang benar:
[{{
    "level": 1,
    "question_type": "multiple_choice",
    "soal": "Pertanyaan berdasarkan elemen ajar spesifik...",
    "options": ["Opsi A", "Opsi B", "Opsi C", "Opsi D"],
    "jawaban_benar": "Opsi A",
    "p": 0.95,
    "explanation": "Penjelasan mengapa jawaban benar",
    "modul_reference": "Bagian spesifik modul yang dirujuk"
}}]

PASTIKAN:
- Mulai langsung dengan '[' dan akhiri dengan ']'
- Tidak ada teks penjelasan sebelum atau sesudah JSON
- Gunakan double quotes untuk semua string
- Tidak ada trailing comma setelah elemen terakhir
- Jawaban benar harus tepat salah satu dari opsi A/B/C/D

PANDUAN KHUSUS UNTUK KURIKULUM SMA KELAS X:
========================================
TOPIK YANG SESUAI:
- Pengenalan komputer dan perangkat digital
- Sistem operasi dasar (Windows, Android, iOS)
- Aplikasi perkantoran (Word, Excel, PowerPoint)
- Internet dan browsing aman
- Media sosial dan etika digital
- Keamanan digital dasar
- Multimedia sederhana (foto, video, audio)

HINDARI TOPIK KOMPLEKS:
- Pemrograman dengan sintaks spesifik
- Database management tingkat lanjut  
- Network administration
- Server configuration
- Advanced cybersecurity
- Machine learning atau AI development

TARGET: 35 soal total (5 soal per level) dalam format JSON array yang valid.

PRINSIP KUNCI: Soal berkualitas = relevan dengan modul + sesuai usia SMA + mudah dipahami + membedakan kemampuan siswa secara efektif.
"""
    
    return prompt

def extract_hybrid_module_components(content_text):
    """
    Fungsi hybrid yang mencoba ekstraksi spesifik terlebih dahulu,
    jika gagal akan menggunakan fallback ke metode yang lebih umum
    """
    # Coba ekstraksi spesifik terlebih dahulu
    specific_components = extract_specific_module_components(content_text)
    validation = validate_detected_keywords(specific_components)
    
    # Jika quality score rendah, gunakan metode fallback
    if validation["quality_score"] < 30:  # Threshold rendah untuk fallback
        print(f"Ekstraksi spesifik kurang optimal (score: {validation['quality_score']:.1f}%), menggunakan metode fallback...")
        
        # Fallback: gunakan metode ekstraksi yang lebih umum
        fallback_components = extract_educational_components(content_text, return_dict=True)
        
        # Convert ke format yang sama dengan specific_components dan ambil yang terbaik
        hybrid_components = {
            "mata_pelajaran": specific_components.get("mata_pelajaran") or "Informatika", 
            "topik_utama": specific_components.get("topik_utama") or fallback_components.get("Modul/Elemen Ajar", "")[:50],
            "kelas": specific_components.get("kelas") or "X (Sepuluh)",
            "kompetensi_awal": specific_components.get("kompetensi_awal") or fallback_components.get("Kompetensi Awal", "Siswa memiliki kemampuan dasar dalam berpikir logis")[:400],
            "tujuan_pembelajaran": specific_components.get("tujuan_pembelajaran") or [fallback_components.get("Tujuan Pembelajaran", "Memahami konsep dasar materi pembelajaran")[:200]],
            "pemahaman_bermakna": specific_components.get("pemahaman_bermakna") or [fallback_components.get("Pemahaman Bermakna", "Mengembangkan pemahaman konseptual yang mendalam")[:300]],
            "target_peserta_didik": specific_components.get("target_peserta_didik") or fallback_components.get("Target Peserta Didik", "Peserta didik reguler/tipikal")[:300],
            "model_pembelajaran": "Pembelajaran berbasis masalah dan proyek"
        }
        
        print("Menggunakan metode hybrid - menggabungkan ekstraksi spesifik dengan fallback")
        return hybrid_components, {"quality_score": 60, "method": "hybrid"}
    else:
        print(f"Ekstraksi spesifik berhasil (score: {validation['quality_score']:.1f}%)")
        return specific_components, validation

# =========================================
# DATABASE MODELS
# =========================================
# Model untuk database guru
class Guru(db.Model, UserMixin):
    __tablename__ = 'guru'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    nama = db.Column(db.String(100), nullable=False)
    has_seen_welcome_guide = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Property untuk identifikasi tipe pengguna
    @property
    def user_type(self):
        return 'guru'
    
    # Override get_id method untuk Flask-Login
    def get_id(self):
        return f"guru_{self.id}"
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    # Metode untuk mengakses hasil siswa
    def get_hasil_siswa(self):
        hasil_siswa = db.session.query(SiswaResult).join(
            Siswa, SiswaResult.siswa_id == Siswa.id
        ).join(
            SiswaAnswer, SiswaAnswer.siswa_id == Siswa.id
        ).join(
            Question, SiswaAnswer.question_id == Question.id
        ).filter(
            Question.guru_id == self.id
        ).distinct(
            SiswaResult.id
        ).all()
        
        return hasil_siswa

# Model untuk pertanyaan yang dibuat oleh guru
class Question(db.Model):
    __tablename__ = 'questions'
    
    id = db.Column(db.Integer, primary_key=True)
    guru_id = db.Column(db.Integer, db.ForeignKey('guru.id'), nullable=False)
    collection_id = db.Column(db.Integer, db.ForeignKey('question_collections.id'), nullable=True)
    level = db.Column(db.Integer, nullable=False)
    soal = db.Column(db.Text, nullable=False)
    jawaban_benar = db.Column(db.Text, nullable=True)
    options = db.Column(db.Text, nullable=True)
    question_type = db.Column(db.String(20), default='multiple_choice')
    p = db.Column(db.Float, nullable=False)
    bobot = db.Column(db.Integer, nullable=False)
    explanation = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    version = db.Column(db.Integer, default=1)
    is_current = db.Column(db.Boolean, default=True)
    is_validated = db.Column(db.Boolean, default=False) # NEW: Kolom is_validated
    
    
    # Relasi dengan guru
    guru = db.relationship('Guru', backref='questions')

# Model untuk database siswa
class Siswa(db.Model, UserMixin):
    __tablename__ = 'siswa'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    nama = db.Column(db.String(100), nullable=False)
    kelas = db.Column(db.String(100), nullable=True)  # Changed from foreign key to string field
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Relasi dengan jawaban siswa
    jawaban = db.relationship('SiswaAnswer', backref='siswa', lazy=True)
    
    # Relasi dengan hasil siswa
    hasil = db.relationship('SiswaResult', backref='siswa', lazy=True)
    
    # Property untuk identifikasi tipe pengguna
    @property
    def user_type(self):
        return 'siswa'
    
    # Override get_id method untuk Flask-Login
    def get_id(self):
        return f"siswa_{self.id}"
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    # Metode untuk mendapatkan hasil sendiri
    def get_my_result(self, kelas_id):
        return SiswaResult.query.filter_by(
            siswa_id=self.id,
            kelas_id=kelas_id
        ).first()

# Model untuk hasil siswa (pengganti SiswaResult)
class SiswaResult(db.Model):
    __tablename__ = 'siswa_results'
    
    id = db.Column(db.Integer, primary_key=True)
    siswa_id = db.Column(db.Integer, db.ForeignKey('siswa.id'), nullable=False)
    collection_id = db.Column(db.Integer, db.ForeignKey('question_collections.id'), nullable=True)  # <-- TAMBAHKAN INI
    correct = db.Column(db.Integer, default=0)
    incorrect = db.Column(db.Integer, default=0)
    current_level = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

# Model untuk jawaban siswa (pengganti SiswaAnswer)
class SiswaAnswer(db.Model):
    __tablename__ = 'siswa_answers'
    
    id = db.Column(db.Integer, primary_key=True)
    siswa_id = db.Column(db.Integer, db.ForeignKey('siswa.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    siswa_answer = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)
    level = db.Column(db.Integer, nullable=False)
    answered_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Relasi dengan Question
    question = db.relationship('Question', backref="siswa_answers")

results_bp = Blueprint('results', __name__)


# =========================================
# TABEL RELASI MANY-TO-MANY (harus didefinisikan SEBELUM model yang menggunakannya)
# =========================================
collection_students = db.Table('collection_students',
    db.Column('id', db.Integer, primary_key=True),
    db.Column('collection_id', db.Integer, db.ForeignKey('question_collections.id', ondelete='CASCADE'), nullable=False),
    db.Column('siswa_id', db.Integer, db.ForeignKey('siswa.id', ondelete='CASCADE'), nullable=False),
    db.Column('added_at', db.DateTime, server_default=db.func.now()),
    db.UniqueConstraint('collection_id', 'siswa_id', name='unique_collection_student')
)

# Model untuk koleksi soal
class QuestionCollection(db.Model):
    __tablename__ = 'question_collections'
    
    id = db.Column(db.Integer, primary_key=True)
    guru_id = db.Column(db.Integer, db.ForeignKey('guru.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Relasi dengan guru
    guru = db.relationship('Guru', backref='collections')
    
    # Tambahkan relasi dengan siswa
    students = db.relationship('Siswa', secondary=collection_students, 
                              backref=db.backref('collections', lazy='dynamic'))

# Model untuk relasi many-to-many antara Question dan QuestionCollection
class CollectionQuestion(db.Model):
    __tablename__ = 'collection_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('question_collections.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    
    # Relasi
    collection = db.relationship('QuestionCollection', backref='collection_questions')
    question = db.relationship('Question', backref='collection_questions')


class QuestionVersion(db.Model):
    __tablename__ = 'question_versions'
    
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    soal = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text)
    jawaban_benar = db.Column(db.Text)
    explanation = db.Column(db.Text)
    p = db.Column(db.Float)
    version = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Relasi ke pertanyaan utama
    question = db.relationship('Question', backref='versions')

# Fungsi pemeriksaan apakah pengguna adalah guru
def is_guru():
    return hasattr(current_user, 'kelas')

def get_hasil_siswa(self):
    # Since there's no Kelas relationship, just get all student results
    hasil_siswa = SiswaResult.query.all()
    return hasil_siswa

@app.route('/guru/welcome')
@login_required
def guru_welcome_guide():
    # Pastikan hanya guru yang bisa mengakses halaman ini
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        flash("Akses ditolak. Halaman ini hanya untuk guru.", "error")
        return redirect(url_for('login'))
    return render_template('guru/guru_welcome.html') # File HTML baru yang akan kita buat

@app.route('/api/guru/mark_welcome_seen', methods=['POST'])
@login_required
def mark_welcome_seen():
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        return jsonify({'success': False, 'message': 'Akses ditolak'}), 403

    try:
        # Cari guru yang sedang login di database
        guru = Guru.query.get(current_user.id)
        if guru:
            # Update statusnya menjadi sudah melihat panduan
            guru.has_seen_welcome_guide = True
            db.session.commit()
            return jsonify({'success': True, 'message': 'Status panduan berhasil diperbarui.'})
        return jsonify({'success': False, 'message': 'Guru tidak ditemukan.'}), 404
    except Exception as e:
        db.session.rollback()
        print(f"Error saat menandai panduan selesai: {str(e)}")
        return jsonify({'success': False, 'message': 'Terjadi kesalahan server.'}), 500

@app.route('/guru/panduan')
@login_required
def guru_panduan_lengkap():
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        flash("Akses ditolak.", "error")
        return redirect(url_for('login'))
    return render_template('guru/guru_panduan.html')

# Rute untuk guru mengakses hasil siswa
@results_bp.route('/guru/hasil-siswa', methods=['GET'])
@login_required
def guru_access_hasil_siswa():
    # Pastikan pengguna adalah guru
    if not is_guru():
        return jsonify({'message': 'Akses ditolak. Hanya guru yang dapat mengakses hasil siswa.'}), 403
    
    # Ambil hasil siswa dari kelas yang dimiliki guru
    hasil_siswa = current_user.get_hasil_siswa()
    
    # Format hasil untuk response
    hasil_formatted = []
    for hasil in hasil_siswa:
        # Dapatkan data siswa
        siswa = Siswa.query.get(hasil.siswa_id)
        
        hasil_formatted.append({
            'id': hasil.id,
            'siswa': {
                'id': siswa.id,
                'nama': siswa.nama,
                'username': siswa.username,
                'kelas': siswa.kelas
            },
            'correct': hasil.correct,
            'incorrect': hasil.incorrect,
            'current_level': hasil.current_level,
            'created_at': hasil.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': hasil.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return jsonify({
        'message': 'Berhasil mengambil hasil siswa',
        'hasil': hasil_formatted
    }), 200

# Rute untuk guru mengakses detail hasil siswa tertentu
@results_bp.route('/guru/hasil-siswa/<int:siswa_id>', methods=['GET'])
@login_required
def guru_access_detail_hasil_siswa(siswa_id):
    if not is_guru():
        return jsonify({'message': 'Akses ditolak. Hanya guru yang dapat mengakses hasil siswa.'}), 403
    
    # Check if student exists
    siswa = Siswa.query.get(siswa_id)
    if not siswa:
        return jsonify({'message': 'Siswa tidak ditemukan.'}), 404
    
    # Get student results
    hasil = SiswaResult.query.filter_by(siswa_id=siswa_id).all()
    
    # Get student answers
    jawaban = SiswaAnswer.query.filter_by(siswa_id=siswa_id).all()
    
    # Format results
    hasil_formatted = []
    for h in hasil:
        hasil_formatted.append({
            'id': h.id,
            'correct': h.correct,
            'incorrect': h.incorrect,
            'current_level': h.current_level,
            'created_at': h.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': h.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    # Format answers
    jawaban_formatted = []
    for j in jawaban:
        jawaban_formatted.append({
            'id': j.id,
            'question_id': j.question_id,
            'siswa_answer': j.siswa_answer,
            'is_correct': j.is_correct,
            'level': j.level,
            'answered_at': j.answered_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return jsonify({
        'message': 'Berhasil mengambil detail hasil siswa',
        'siswa': {
            'id': siswa.id,
            'nama': siswa.nama,
            'username': siswa.username,
            'kelas': siswa.kelas
        },
        'hasil': hasil_formatted,
        'jawaban': jawaban_formatted
    }), 200

# Rute untuk siswa melihat hasil sendiri
@results_bp.route('/siswa/hasil-saya', methods=['GET'])
@login_required
def siswa_access_hasil_sendiri():
    if is_guru():
        return jsonify({'message': 'Akses ditolak. Rute ini hanya untuk siswa.'}), 403
    
    # Get student results
    hasil = SiswaResult.query.filter_by(siswa_id=current_user.id).first()
    
    if not hasil:
        return jsonify({'message': 'Hasil tidak ditemukan.'}), 404
    
    # Get student answers
    jawaban = SiswaAnswer.query.filter_by(siswa_id=current_user.id).all()
    
    # Format answers
    jawaban_formatted = []
    for j in jawaban:
        jawaban_formatted.append({
            'question_id': j.question_id,
            'siswa_answer': j.siswa_answer,
            'is_correct': j.is_correct,
            'level': j.level,
            'answered_at': j.answered_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return jsonify({
        'message': 'Berhasil mengambil hasil',
        'hasil': {
            'correct': hasil.correct,
            'incorrect': hasil.incorrect,
            'current_level': hasil.current_level,
            'kelas': current_user.kelas  # Use the student's kelas field
        },
        'jawaban': jawaban_formatted
    }), 200

# Fungsi untuk mendaftarkan blueprint ke aplikasi
def register_results_routes(app):
    app.register_blueprint(results_bp, url_prefix='/api')

# =========================================
# AUTH ROUTES
# =========================================
@login_manager.user_loader
def load_user(user_id):
    try:
        if isinstance(user_id, str):
            if user_id.startswith('guru_'):
                actual_id = int(user_id.split('_')[1])
                return Guru.query.get(actual_id)
            elif user_id.startswith('siswa_'):
                actual_id = int(user_id.split('_')[1])
                return Siswa.query.get(actual_id)
            else:
                # Coba langsung sebagai ID numerik
                return Siswa.query.get(int(user_id))
        elif isinstance(user_id, int):
            # Default ke Siswa jika ID adalah integer langsung
            return Siswa.query.get(user_id)
    except (ValueError, IndexError, TypeError) as e:
        # Log error jika terjadi masalah saat parsing ID
        print(f"Error loading user with ID {user_id}: {str(e)}")
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = Guru.query.filter_by(email=email).first()
        
        if not user:
            user = Siswa.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f'Selamat datang, {user.nama}!', 'success')

            # --- PERUBAHAN 2: Modifikasi logika redirect untuk guru ---
            if hasattr(user, 'user_type') and user.user_type == 'guru':
                # Cek apakah guru sudah pernah melihat panduan
                if not user.has_seen_welcome_guide:
                    # Jika belum, arahkan ke halaman panduan
                    return redirect(url_for('guru_welcome_guide'))
                else:
                    # Jika sudah, arahkan ke dashboard guru seperti biasa
                    return redirect(url_for('guru'))
            elif hasattr(user, 'user_type') and user.user_type == 'siswa':
                return redirect(url_for('DashboardSiswa'))
            else:
                flash("Login berhasil, tetapi peran tidak dikenal.", "info")
                return redirect(url_for('index'))
        else:
            flash("Email atau password salah", "error")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Anda telah berhasil logout', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nama = request.form.get('nama')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = request.form.get('role')
        
        # Ambil kelas dari form (akan ada di request jika role adalah siswa)
        kelas = request.form.get('kelas') 

        # Log untuk debugging
        print(f"Register attempt: Nama={nama}, Email={email}, Role={role}, Kelas={kelas}")

        if password != confirm_password:
            flash("Password dan konfirmasi password tidak sama!", "error")
            return render_template('register.html', 
                                   nama=nama, email=email, role=role, kelas=kelas)
        
        # Cek duplikasi berdasarkan peran
        if role == 'guru':
            existing_user = Guru.query.filter_by(email=email).first()
            if existing_user:
                flash("Email sudah terdaftar sebagai Guru.", "error")
                return render_template('register.html', 
                                       nama=nama, email=email, role=role, kelas=kelas)
            
            new_user = Guru(
                username=email,  # Gunakan email sebagai username untuk kompatibilitas
                email=email,
                nama=nama
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash('Registrasi guru berhasil! Silakan login.', 'success')
            return redirect(url_for('login'))
        
        elif role == 'siswa': # role == 'siswa'
            existing_user = Siswa.query.filter_by(email=email).first()
            if existing_user:
                flash("Email sudah terdaftar sebagai Siswa.", "error")
                return render_template('register.html', 
                                       nama=nama, email=email, role=role, kelas=kelas)
            
            # Pastikan kelas dipilih untuk siswa
            if not kelas:
                flash("Kelas harus dipilih untuk siswa!", "error")
                return render_template('register.html', 
                                       nama=nama, email=email, role=role, kelas=kelas)

            new_user = Siswa(
                username=email,  # Gunakan email sebagai username untuk kompatibilitas
                email=email,
                nama=nama,
                kelas=kelas # Simpan kelas siswa
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash('Registrasi siswa berhasil! Silakan login.', 'success')
            return redirect(url_for('login'))
        else: # Handle case where role is not 'guru' or 'siswa' (shouldn't happen with proper frontend)
            flash("Peran registrasi tidak valid.", "error")
            return render_template('register.html', 
                                   nama=nama, email=email, role=role, kelas=kelas)
            
    # Untuk permintaan GET, render template register
    # Peran default di sini bisa 'siswa' agar form siswa langsung muncul
    return render_template('register.html', role='siswa')

# =========================================
# TRANSISI level DENGAN PROBABILITAS
# =========================================
# Fungsi next_level yang baru berdasarkan diagram
def next_level(current_level, is_correct):
    if current_level == 1:
        return 2  # Dari level 1 selalu ke level 2
    elif current_level == 2:
        return 4 if is_correct else 3  # Benar ke atas (4), salah ke bawah (3)
    elif current_level == 4:
        return 7 if is_correct else 6  # Benar ke atas (7), salah ke bawah (6)
    elif current_level == 3:
        return 6 if is_correct else 5  # Benar ke atas (6), salah ke bawah (5)
    elif current_level in [5, 6, 7]:
        return None  # Sudah di level akhir
    else:
        return None  # Untuk keamanan

# level akhir tetap sama
FINAL_levelS = [5, 6, 7]

# =========================================
# FUNGSI MENENTUKAN BOBOT (ASSIGN_WEIGHT)
# =========================================
def assign_weight(p: float) -> int:
    if p > 0.90:
        return 1
    elif 0.90 >= p > 0.62:
        return 2
    elif abs(p - 0.62) < 1e-6:
        return 3
    elif 0.62 > p > 0.20:
        return 4
    else:
        return 5

# =========================================
# FUNGSI KETERANGAN LEVEL
# =========================================
def get_level_description(level):
    """Mengembalikan deskripsi teks untuk level numerik."""
    descriptions = {
        1: "Kesadaran Teknologi: Pemahaman dasar tentang konsep dan istilah.",
        2: "Literasi Teknologi: Mampu menjelaskan konsep dan cara kerjanya.",
        3: "Aplikasi Dasar: Mampu menerapkan konsep pada masalah sederhana.",
        4: "Aplikasi Lanjut: Mampu menganalisis dan memecahkan masalah kompleks.",
        5: "Kemampuan Rendah: Telah menyelesaikan tes dengan penguasaan pada tingkat dasar.",
        6: "Kemampuan Menengah: Telah menyelesaikan tes dengan penguasaan pada tingkat menengah.",
        7: "Kemampuan Tinggi: Telah menyelesaikan tes dengan penguasaan pada tingkat mahir.",
    }
    return descriptions.get(level, "Level Tidak Dikenal")

def get_level_description_short(level):
    """Mengembalikan deskripsi singkat untuk level numerik berdasarkan taksonomi teknologi."""
    descriptions = {
        1: "Stage I (Kotak 1) - Kesadaran Teknologi",
        2: "Stage II (Kotak 2) - Literasi Teknologi",
        3: "Stage III (Kotak 3) - Kemampuan Teknologi",
        4: "Stage III (Kotak 4) - Kreativitas Teknologi (Dasar)",
        5: "Stage IV (Kotak 5) - Kemampuan Teknologi (Penguatan)",
        6: "Stage IV (Kotak 6) - Kritik Teknologi",
        7: "Stage IV (Kotak 7) - Kreativitas + Kritik Teknologi (Final Tinggi)",
    }
    return descriptions.get(level, "Level Tidak Dikenal")

def get_technology_taxonomy(level):
    """Mengembalikan taksonomi teknologi untuk level numerik (format lengkap)."""
    technology_mapping = {
        1: "Knowledge That - Definisi, istilah, identifikasi teknologi dasar",
        2: "Knowledge That - Klasifikasi, hubungan antar teknologi, penjelasan fungsi", 
        3: "Knowledge That + How - Aplikasi praktis, instruksi, puzzle urutan",
        4: "Knowledge That + How - Modifikasi, debugging, analisis error sederhana",
        5: "Knowledge That + How - Aplikasi lanjutan, puzzle assembly terbimbing",
        6: "Knowledge That + How + Why - Evaluasi trade-off, menilai solusi, kritik teknologi",
        7: "Knowledge That + How + Why - Merancang solusi baru, integrasi multi-konsep, optimalisasi teknologi"
    }
    return technology_mapping.get(level, "Tidak Dikenal")

def get_technology_taxonomy_short(level):
    """Mengembalikan taksonomi teknologi untuk level numerik (format singkat)."""
    technology_mapping = {
        1: "Know That",
        2: "Know That", 
        3: "Know That + How",
        4: "Know That + How",
        5: "Know That + How",
        6: "Know That + How + Why",
        7: "Know That + How + Why"
    }
    return technology_mapping.get(level, "Tidak Dikenal")

# Legacy functions for backward compatibility (deprecated)
def get_bloom_taxonomy(level):
    """DEPRECATED: Gunakan get_technology_taxonomy() sebagai gantinya."""
    return get_technology_taxonomy(level)

def get_bloom_taxonomy_short(level):
    """DEPRECATED: Gunakan get_technology_taxonomy_short() sebagai gantinya.""" 
    return get_technology_taxonomy_short(level)

# =========================================
# FUNGSI EVALUASI JAWABAN
# =========================================
def is_answer_correct(user_answer, expected_answer):
    """
    Evaluasi jawaban pilihan ganda dengan membandingkan jawaban pengguna dengan jawaban yang benar
    """
    # Membersihkan dan menormalisasi jawaban
    user_answer = user_answer.lower().strip()
    expected_answer = expected_answer.lower().strip()
    
    # Untuk pilihan ganda, jawaban harus sama persis (tidak case-sensitive)
    return user_answer == expected_answer

# =========================================
# FUNGSI UNTUK CARI DAN TAMBAH KOLOM
# =========================================
def check_and_add_columns():
    try:
        print("Memeriksa struktur tabel questions...")
        # Dapatkan informasi kolom dari model
        column_info = db.inspect(db.engine).get_columns('questions')
        column_names = [col['name'] for col in column_info]
        
        # Cek dan tambahkan kolom yang diperlukan
        columns_to_add = []
        
        if 'jawaban_benar' not in column_names:
            columns_to_add.append("jawaban_benar TEXT NULL")
        
        if 'options' not in column_names:
            columns_to_add.append("options TEXT NULL")
            
        if 'question_type' not in column_names:
            columns_to_add.append("question_type VARCHAR(20) DEFAULT 'multiple_choice'")
        
        # Tambahkan kolom yang diperlukan jika ada
        if columns_to_add:
            print(f"Menambahkan kolom yang diperlukan: {', '.join(columns_to_add)}")
            alter_query = f"ALTER TABLE questions ADD COLUMN {', ADD COLUMN '.join(columns_to_add)}"
            db.session.execute(text(alter_query))
            db.session.commit()
            print("Kolom berhasil ditambahkan!")
        else:
            print("Semua kolom yang diperlukan sudah ada dalam tabel")
        
        return True
    except Exception as e:
        print(f"Error ketika memeriksa/menambahkan kolom: {str(e)}")
        return False

# =========================================
# FUNGSI UNTUK KONEKSI DATABASE
# =========================================
def test_db_connection():
    try:
        # Cek apakah koneksi ke database bisa dibuat
        db.session.execute(text("SELECT 1"))
        print("Database connection successful")
        return True
    except Exception as e:
        print(f"Database connection error: {str(e)}")
        return False

# Inisialisasi database dengan app context
def init_db():
    print("Initializing database...")
    db.create_all()
    # Cek dan tambahkan kolom yang diperlukan
    check_and_add_columns()
    print("Database initialized successfully")

# =========================================
# ROUTES
# =========================================

# Favicon route - menggunakan Education.ico sebagai favicon
@app.route('/favicon.ico')
def favicon():
    try:
        return send_file(
            os.path.join(ROOT_DIR, 'img', 'Education.ico'), 
            mimetype='image/vnd.microsoft.icon'
        )
    except FileNotFoundError:
        # Fallback jika file tidak ditemukan
        print("Warning: Education.ico not found in img folder")
        return '', 404

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/guru')
@login_required # Tambahkan decorator login_required jika belum ada untuk memastikan user terotentikasi
def guru():
    # Pastikan yang mengakses halaman guru adalah user dengan user_type 'guru'
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        flash("Akses ditolak. Hanya guru yang dapat mengakses halaman ini.", "error")
        return redirect(url_for('login'))
    return render_template('guru/Dashboard_guru.html')

@app.route('/DashboardSiswa')
@login_required # Tambahkan decorator login_required jika belum ada
def DashboardSiswa():
    # Pastikan yang mengakses halaman DashboardSiswa adalah user dengan user_type 'siswa'
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'siswa':
        flash("Akses ditolak. Hanya siswa yang dapat mengakses halaman ini.", "error")
        return redirect(url_for('login'))
    return render_template('siswa/Dashboard_siswa.html')

@app.route('/qna')
def qna():
    return render_template('siswa/qna_siswa.html')

# =========================================
# RESULTS PAGE
# =========================================

@app.route('/api/siswa/test_status', methods=['GET'])
@login_required
def get_test_status():
    user_id = request.args.get("user_id")
    collection_id = request.args.get("collection_id")
    
    # Cek keamanan: pastikan user_id sesuai dengan pengguna saat ini
    if str(current_user.id) != str(user_id):
        return jsonify({"success": False, "message": "Akses tidak diizinkan"}), 403
    
    try:
        # Ambil hasil siswa untuk koleksi ini
        result = SiswaResult.query.filter_by(
            siswa_id=user_id,
            collection_id=collection_id
        ).first()
        
        if not result:
            return jsonify({
                "success": True,
                "is_completed": False,
                "current_level": 1
            })
        
        # Cek apakah current_level adalah level final (5, 6, 7)
        is_completed = result.current_level in [5, 6, 7]
        
        return jsonify({
            "success": True,
            "is_completed": is_completed,
            "current_level": result.current_level,
            "correct": result.correct,
            "incorrect": result.incorrect
        })
        
    except Exception as e:
        print(f"Error mendapatkan status tes: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        }), 500

@app.route('/api/siswa/results/<int:collection_id>', methods=['GET'])
@login_required
def get_siswa_test_results(collection_id):
    try:
        user_id = request.args.get("user_id")
        
        # For teacher access (viewing any student's results)
        if hasattr(current_user, 'user_type') and current_user.user_type == 'guru':
            # Check if collection belongs to this teacher
            collection = QuestionCollection.query.filter_by(
                id=collection_id, 
                guru_id=current_user.id
            ).first()
            
            if not collection:
                return jsonify({"success": False, "message": "Access denied - Collection not found or not owned by you"}), 403
                
            # If user_id is provided, get that specific student's results
            # Otherwise, return all results for this collection
            if user_id:
                # Verify this student is assigned to this collection
                student_assigned = db.session.query(collection_students).filter_by(
                    collection_id=collection_id,
                    siswa_id=user_id
                ).first() is not None
                
                if not student_assigned:
                    return jsonify({"success": False, "message": "Student not assigned to this collection"}), 404
            
        # For student access (viewing own results only)
        elif hasattr(current_user, 'user_type') and current_user.user_type == 'siswa':
            # Students can only view their own results
            if str(current_user.id) != str(user_id):
                return jsonify({"success": False, "message": "You can only view your own results"}), 403
                
            # Verify student has access to this collection
            student_assigned = db.session.query(collection_students).filter_by(
                collection_id=collection_id,
                siswa_id=current_user.id
            ).first() is not None
            
            if not student_assigned:
                return jsonify({"success": False, "message": "You don't have access to this collection"}), 403
        else:
            return jsonify({"success": False, "message": "Invalid user type"}), 403
        
        # Get student results for this collection
        result_query = SiswaResult.query.filter_by(
            collection_id=collection_id
        )
        
        if user_id:
            result_query = result_query.filter_by(siswa_id=user_id)
            
        results = result_query.all()
        
        if not results:
            # Return empty result instead of error if no results found
            return jsonify({
                "success": True,
                "message": "No results found",
                "correct": 0,
                "incorrect": 0,
                "current_level": 1,
                "answers": []
            })
            
        # Format results
        formatted_results = []
        for result in results:
            # Get student
            student = Siswa.query.get(result.siswa_id)
            
            # Get answer history
            answer_history = get_student_answer_history(result.siswa_id, collection_id)
            
            formatted_results.append({
                "student_id": result.siswa_id,
                "student_name": student.nama if student else "Unknown",
                "student_class": student.kelas if student else "Unknown",
                "correct": result.correct,
                "incorrect": result.incorrect,
                "current_level": result.current_level,
                "answers": answer_history
            })
        
        # If single student requested, return first result
        if user_id:
            if formatted_results:
                return jsonify({
                    "success": True,
                    "correct": formatted_results[0]["correct"],
                    "incorrect": formatted_results[0]["incorrect"],
                    "current_level": formatted_results[0]["current_level"],
                    "answers": formatted_results[0]["answers"]
                })
            else:
                return jsonify({
                    "success": True,
                    "message": "No results found",
                    "correct": 0,
                    "incorrect": 0,
                    "current_level": 1,
                    "answers": []
                })
        
        # Return all results for teacher
        return jsonify({
            "success": True,
            "results": formatted_results
        })
        
    except Exception as e:
        print(f"Error getting student test results: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

# Helper function to get student answer history
def get_student_answer_history(student_id, collection_id):
    try:
        # Get collection questions
        collection_question_ids = db.session.query(CollectionQuestion.question_id)\
            .filter(CollectionQuestion.collection_id == collection_id).all()
        collection_question_ids = [id[0] for id in collection_question_ids]
        
        if not collection_question_ids:
            return []
            
        # Get answers for this student and these questions
        answers = db.session.query(SiswaAnswer, Question)\
            .join(Question, SiswaAnswer.question_id == Question.id)\
            .filter(
                SiswaAnswer.siswa_id == student_id,
                Question.id.in_(collection_question_ids)
            )\
            .order_by(SiswaAnswer.answered_at.desc())\
            .all()
            
        # Format answers
        formatted_answers = []
        for answer, question in answers:
            formatted_answers.append({
                "question_id": question.id,
                "question": question.soal,
                "user_answer": answer.siswa_answer,
                "correct_answer": question.jawaban_benar,
                "is_correct": answer.is_correct,
                "explanation": question.explanation,
                "level": answer.level,
                "answered_at": answer.answered_at.isoformat() if answer.answered_at else None
            })
            
        return formatted_answers
    except Exception as e:
        print(f"Error getting student answer history: {str(e)}")
        return []

@app.route('/api/collection-analytics/answers', methods=['GET'])
@login_required
def get_filtered_collection_answers():
    try:
        # Required parameter
        collection_id = request.args.get('collection_id')
        
        if not collection_id:
            return jsonify({"success": False, "message": "Collection ID is required"}), 400
            
        # Check if collection belongs to current teacher
        collection = QuestionCollection.query.filter_by(
            id=collection_id, 
            guru_id=current_user.id
        ).first()
        
        if not collection:
            return jsonify({"success": False, "message": "Collection not found or not owned by you"}), 403
            
        # Get collection questions
        collection_question_ids = db.session.query(CollectionQuestion.question_id)\
            .filter(CollectionQuestion.collection_id == collection_id).all()
        collection_question_ids = [id[0] for id in collection_question_ids]
        
        if not collection_question_ids:
            return jsonify({"success": True, "answers": [], "message": "No questions in this collection"})
            
        # Build query for student answers
        query = db.session.query(
            SiswaAnswer, Question, Siswa
        ).join(
            Question, SiswaAnswer.question_id == Question.id
        ).join(
            Siswa, SiswaAnswer.siswa_id == Siswa.id
        ).filter(
            Question.id.in_(collection_question_ids)
        )
        
        # Apply filters
        # 1. Filter by student ID
        student_id = request.args.get('student_id')
        if student_id:
            query = query.filter(SiswaAnswer.siswa_id == student_id)
            
        # 2. Filter by class
        class_filter = request.args.get('class')
        if class_filter and class_filter != 'all':
            query = query.filter(Siswa.kelas == class_filter)
            
        # 3. Filter by level
        level_filter = request.args.get('level')
        if level_filter and level_filter != 'all':
            query = query.filter(SiswaAnswer.level == level_filter)
            
        # 4. Filter by correctness
        is_correct_filter = request.args.get('is_correct')
        if is_correct_filter:
            if is_correct_filter.lower() == 'true':
                query = query.filter(SiswaAnswer.is_correct == True)
            elif is_correct_filter.lower() == 'false':
                query = query.filter(SiswaAnswer.is_correct == False)
                
        # 5. Filter by date range
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if start_date:
            try:
                start_datetime = datetime.datetime.fromisoformat(start_date)
                query = query.filter(SiswaAnswer.answered_at >= start_datetime)
            except ValueError:
                # Ignore invalid date format
                pass
                
        if end_date:
            try:
                end_datetime = datetime.datetime.fromisoformat(end_date)
                query = query.filter(SiswaAnswer.answered_at <= end_datetime)
            except ValueError:
                # Ignore invalid date format
                pass
                
        # 6. Apply time period filter (shorthand for date range)
        period_filter = request.args.get('period')
        if period_filter and not (start_date or end_date):
            now = datetime.datetime.now()
            
            if period_filter == 'today':
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(SiswaAnswer.answered_at >= today_start)
            elif period_filter == 'yesterday':
                yesterday_start = (now - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(SiswaAnswer.answered_at >= yesterday_start, SiswaAnswer.answered_at < yesterday_end)
            elif period_filter == 'week':
                week_start = (now - datetime.timedelta(days=7))
                query = query.filter(SiswaAnswer.answered_at >= week_start)
            elif period_filter == 'month':
                month_start = (now - datetime.timedelta(days=30))
                query = query.filter(SiswaAnswer.answered_at >= month_start)
                
        # Sort by most recent first
        query = query.order_by(SiswaAnswer.answered_at.desc())
        
        # Get paginated results
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        
        # Execute query with pagination
        paginated_results = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Get total count for stats
        total_count = paginated_results.total
        total_pages = paginated_results.pages
        
        # Format results
        formatted_answers = []
        for answer, question, student in paginated_results.items:
            formatted_answers.append({
                "id": answer.id,
                "student_id": student.id,
                "student_name": student.nama,
                "student_class": student.kelas,
                "question_id": question.id,
                "question": question.soal,
                "user_answer": answer.siswa_answer,
                "correct_answer": question.jawaban_benar,
                "is_correct": answer.is_correct,
                "explanation": question.explanation,
                "level": answer.level,
                "answered_at": answer.answered_at.isoformat() if answer.answered_at else None
            })
            
        # Get unique classes for class filter
        available_classes = db.session.query(Siswa.kelas).distinct().all()
        available_classes = [cls[0] for cls in available_classes if cls[0]]
        
        return jsonify({
            "success": True,
            "answers": formatted_answers,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            },
            "filters": {
                "available_classes": available_classes
            }
        })
            
    except Exception as e:
        print(f"Error getting filtered answers: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500
    
@app.route('/api/collection-analytics/level-analysis', methods=['GET'])
@login_required
def get_level_analysis():
    try:
        # Required parameter
        collection_id = request.args.get('collection_id')
        
        if not collection_id:
            return jsonify({"success": False, "message": "Collection ID is required"}), 400
            
        # Check if collection belongs to current teacher
        collection = QuestionCollection.query.filter_by(
            id=collection_id, 
            guru_id=current_user.id
        ).first()
        
        if not collection:
            return jsonify({"success": False, "message": "Collection not found or not owned by you"}), 403
            
        # Get students assigned to this collection
        student_ids = db.session.query(collection_students.c.siswa_id)\
            .filter(collection_students.c.collection_id == collection_id)\
            .all()
        student_ids = [id[0] for id in student_ids]
        
        if not student_ids:
            return jsonify({
                "success": True, 
                "message": "No students assigned to this collection",
                "level_distribution": {},
                "level_transitions": {}
            })
            
        # Get current level distribution
        level_distribution = db.session.query(
            SiswaResult.current_level, 
            db.func.count(SiswaResult.siswa_id)
        ).filter(
            SiswaResult.collection_id == collection_id,
            SiswaResult.siswa_id.in_(student_ids)
        ).group_by(
            SiswaResult.current_level
        ).all()
        
        # Format level distribution
        formatted_distribution = {str(level): count for level, count in level_distribution}
        
        # For levels not present in results, set count to 0
        for level in range(1, 8):  # levels 1-7
            if str(level) not in formatted_distribution:
                formatted_distribution[str(level)] = 0
                
        # Analyze level transitions
        # For this, we need to look at the sequence of answers for each student
        level_transitions = {
            "1-2": 0,
            "2-3": 0,
            "2-4": 0,
            "3-5": 0,
            "3-6": 0,
            "4-6": 0,
            "4-7": 0
        }
        
        # Get collection questions
        collection_question_ids = db.session.query(CollectionQuestion.question_id)\
            .filter(CollectionQuestion.collection_id == collection_id).all()
        collection_question_ids = [id[0] for id in collection_question_ids]
        
        if collection_question_ids:
            # For each student, get answers in chronological order
            for student_id in student_ids:
                answers = db.session.query(SiswaAnswer)\
                    .filter(
                        SiswaAnswer.siswa_id == student_id,
                        SiswaAnswer.question_id.in_(collection_question_ids)
                    )\
                    .order_by(SiswaAnswer.answered_at)\
                    .all()
                    
                if answers:
                    # Track level transitions
                    prev_level = None
                    for answer in answers:
                        curr_level = answer.level
                        
                        if prev_level is not None and prev_level != curr_level:
                            transition_key = f"{prev_level}-{curr_level}"
                            if transition_key in level_transitions:
                                level_transitions[transition_key] += 1
                                
                        prev_level = curr_level
        
        # Additional statistics
        # Count students in basic (1-2), intermediate (3-4), and advanced (5-7) levels
        basic_count = formatted_distribution.get("1", 0) + formatted_distribution.get("2", 0)
        intermediate_count = formatted_distribution.get("3", 0) + formatted_distribution.get("4", 0)
        advanced_count = formatted_distribution.get("5", 0) + formatted_distribution.get("6", 0) + formatted_distribution.get("7", 0)
        
        # Count completed students (reached final levels 5, 6, or 7)
        completed_count = advanced_count
        
        # Calculate percentages
        total_students = len(student_ids)
        basic_percent = (basic_count / total_students * 100) if total_students > 0 else 0
        intermediate_percent = (intermediate_count / total_students * 100) if total_students > 0 else 0
        advanced_percent = (advanced_count / total_students * 100) if total_students > 0 else 0
        completed_percent = (completed_count / total_students * 100) if total_students > 0 else 0
        
        return jsonify({
            "success": True,
            "level_distribution": formatted_distribution,
            "level_transitions": level_transitions,
            "statistics": {
                "total_students": total_students,
                "basic_levels": {
                    "count": basic_count,
                    "percentage": round(basic_percent, 2)
                },
                "intermediate_levels": {
                    "count": intermediate_count,
                    "percentage": round(intermediate_percent, 2)
                },
                "advanced_levels": {
                    "count": advanced_count,
                    "percentage": round(advanced_percent, 2)
                },
                "completed": {
                    "count": completed_count,
                    "percentage": round(completed_percent, 2)
                }
            }
        })
        
    except Exception as e:
        print(f"Error getting level analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500
    
@app.route('/api/collection-analytics/class-analysis', methods=['GET'])
@login_required
def get_class_analysis():
    try:
        # Required parameter
        collection_id = request.args.get('collection_id')
        
        if not collection_id:
            return jsonify({"success": False, "message": "Collection ID is required"}), 400
            
        # Check if collection belongs to current teacher
        collection = QuestionCollection.query.filter_by(
            id=collection_id, 
            guru_id=current_user.id
        ).first()
        
        if not collection:
            return jsonify({"success": False, "message": "Collection not found or not owned by you"}), 403
            
        # Get students assigned to this collection
        students = db.session.query(Siswa)\
            .join(
                collection_students,
                collection_students.c.siswa_id == Siswa.id
            )\
            .filter(
                collection_students.c.collection_id == collection_id
            )\
            .all()
            
        if not students:
            return jsonify({
                "success": True, 
                "message": "No students assigned to this collection",
                "class_stats": {}
            })
            
        # Group students by class
        class_groups = {}
        for student in students:
            if student.kelas not in class_groups:
                class_groups[student.kelas] = []
            class_groups[student.kelas].append(student.id)
            
        # For each class, get performance statistics
        class_stats = {}
        for kelas, student_ids in class_groups.items():
            # Get results for these students
            results = db.session.query(SiswaResult)\
                .filter(
                    SiswaResult.collection_id == collection_id,
                    SiswaResult.siswa_id.in_(student_ids)
                )\
                .all()
                
            # Calculate stats
            total_correct = sum(r.correct or 0 for r in results)
            total_incorrect = sum(r.incorrect or 0 for r in results)
            total_answers = total_correct + total_incorrect
            accuracy = (total_correct / total_answers * 100) if total_answers > 0 else 0
            
            # Count students by level
            level_counts = {str(n): 0 for n in range(1, 8)}
            for result in results:
                level = str(result.current_level or 1)
                if level in level_counts:
                    level_counts[level] += 1
                    
            # Count completed students (in levels 5-7)
            completed_count = sum(
                1 for r in results if r.current_level in [5, 6, 7]
            )
            
            class_stats[kelas] = {
                "student_count": len(student_ids),
                "total_correct": total_correct,
                "total_incorrect": total_incorrect,
                "accuracy": round(accuracy, 2),
                "level_distribution": level_counts,
                "completed_count": completed_count,
                "completion_rate": round((completed_count / len(student_ids) * 100), 2) if student_ids else 0
            }
            
        return jsonify({
            "success": True,
            "class_stats": class_stats
        })
        
    except Exception as e:
        print(f"Error getting class analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500
    
@app.route('/api/collection-analytics/question-analysis', methods=['GET'])
@login_required
def get_question_analysis():
    try:
        # Required parameter
        collection_id = request.args.get('collection_id')
        
        if not collection_id:
            return jsonify({"success": False, "message": "Collection ID is required"}), 400
            
        # Check if collection belongs to current teacher
        collection = QuestionCollection.query.filter_by(
            id=collection_id, 
            guru_id=current_user.id
        ).first()
        
        if not collection:
            return jsonify({"success": False, "message": "Collection not found or not owned by you"}), 403
            
        # Get questions in this collection
        questions = db.session.query(Question)\
            .join(
                CollectionQuestion,
                CollectionQuestion.question_id == Question.id
            )\
            .filter(
                CollectionQuestion.collection_id == collection_id
            )\
            .all()
            
        if not questions:
            return jsonify({
                "success": True, 
                "message": "No questions in this collection",
                "questions": []
            })
            
        # For each question, get answer statistics
        question_stats = []
        for question in questions:
            # Get all answers for this question
            answers = db.session.query(SiswaAnswer)\
                .filter(
                    SiswaAnswer.question_id == question.id
                )\
                .all()
                
            # Calculate statistics
            total_answers = len(answers)
            correct_answers = sum(1 for a in answers if a.is_correct)
            incorrect_answers = total_answers - correct_answers
            accuracy = (correct_answers / total_answers * 100) if total_answers > 0 else 0
            
            # Get class breakdown
            class_breakdown = {}
            for answer in answers:
                student = Siswa.query.get(answer.siswa_id)
                if student and student.kelas:
                    if student.kelas not in class_breakdown:
                        class_breakdown[student.kelas] = {
                            "correct": 0,
                            "incorrect": 0,
                            "total": 0
                        }
                    class_breakdown[student.kelas]["total"] += 1
                    if answer.is_correct:
                        class_breakdown[student.kelas]["correct"] += 1
                    else:
                        class_breakdown[student.kelas]["incorrect"] += 1
            
            # Calculate accuracy per class
            for kelas, stats in class_breakdown.items():
                stats["accuracy"] = round((stats["correct"] / stats["total"] * 100), 2) if stats["total"] > 0 else 0
                
            question_stats.append({
                "level": question.level,
                "soal": question.soal,
                "options": json.loads(question.options) if question.options else [],
                "jawaban_benar": question.jawaban_benar,
                "bobot": question.bobot,
                "total_answers": total_answers,
                "correct_answers": correct_answers,
                "incorrect_answers": incorrect_answers,
                "accuracy": round(accuracy, 2),
                "class_breakdown": class_breakdown
            })
            
        # Sort questions by level
        question_stats.sort(key=lambda q: q["level"])
        
        # Filter by level if requested
        level_filter = request.args.get('level')
        if level_filter and level_filter != 'all':
            question_stats = [q for q in question_stats if q["level"] == int(level_filter)]
            
        return jsonify({
            "success": True,
            "questions": question_stats
        })
        
    except Exception as e:
        print(f"Error getting question analysis: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500
    

@app.route('/api/siswa/refresh_answers/<int:collection_id>', methods=['GET'])
@login_required
def refresh_siswa_answers(collection_id):
    user_id = request.args.get("user_id")
    force = request.args.get("force") == "true"
    
    # Cek keamanan: pastikan user_id sesuai dengan pengguna saat ini
    if str(current_user.id) != str(user_id):
        return jsonify({"success": False, "message": "Akses ditolak"}), 403
    
    try:
        # Ambil hasil siswa untuk koleksi ini
        result = SiswaResult.query.filter_by(
            siswa_id=user_id,
            collection_id=collection_id
        ).first()
        
        if not result:
            return jsonify({
                "success": False,
                "message": "Tidak ada hasil ditemukan"
            }), 404
        
        # Dapatkan daftar question_id yang terkait dengan collection ini
        collection_question_ids = db.session.query(CollectionQuestion.question_id)\
            .filter(CollectionQuestion.collection_id == collection_id).all()
        collection_question_ids = [id[0] for id in collection_question_ids]
        
        # Hitung jawaban yang ada di database
        answer_count = db.session.query(func.count(SiswaAnswer.id)).filter(
            SiswaAnswer.siswa_id == user_id,
            SiswaAnswer.question_id.in_(collection_question_ids) if collection_question_ids else False
        ).scalar() or 0
        
        # Hitung total jawaban benar dari actual records
        correct_count = db.session.query(func.count(SiswaAnswer.id)).filter(
            SiswaAnswer.siswa_id == user_id,
            SiswaAnswer.is_correct == True,
            SiswaAnswer.question_id.in_(collection_question_ids) if collection_question_ids else False
        ).scalar() or 0
        
        # Hitung total jawaban salah dari actual records
        incorrect_count = db.session.query(func.count(SiswaAnswer.id)).filter(
            SiswaAnswer.siswa_id == user_id,
            SiswaAnswer.is_correct == False,
            SiswaAnswer.question_id.in_(collection_question_ids) if collection_question_ids else False
        ).scalar() or 0
        
        # Cek inkonsistensi
        has_inconsistency = (result.correct != correct_count or result.incorrect != incorrect_count)
        
        if has_inconsistency or force:
            # Jika ada inkonsistensi atau force=true, perbarui data
            result.correct = correct_count
            result.incorrect = incorrect_count
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "Data jawaban telah diperbarui",
                "changes": {
                    "old_correct": result.correct if has_inconsistency else correct_count,
                    "new_correct": correct_count,
                    "old_incorrect": result.incorrect if has_inconsistency else incorrect_count,
                    "new_incorrect": incorrect_count
                }
            })
        
        return jsonify({
            "success": True,
            "message": "Data jawaban sudah konsisten",
            "stats": {
                "correct": correct_count,
                "incorrect": incorrect_count,
                "total": answer_count
            }
        })
        
    except Exception as e:
        print(f"Error menyegarkan jawaban: {str(e)}")
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        }), 500

@app.route('/api/questions/<int:question_id>/set_validation', methods=['POST'])
@login_required
def set_question_validation_status(question_id):
    try:
        # Pastikan pengguna adalah guru
        if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
            return jsonify({'success': False, 'message': 'Akses ditolak. Hanya guru yang dapat mengubah status validasi.'}), 403

        question = Question.query.get(question_id)
        if not question:
            return jsonify({'success': False, 'message': 'Soal tidak ditemukan'}), 404

        # Pastikan guru yang login adalah pemilik soal
        if question.guru_id != current_user.id:
            return jsonify({'success': False, 'message': 'Anda tidak memiliki izin untuk mengubah status validasi soal ini'}), 403

        data = request.get_json()
        # Menggunakan 'is_validated' dari body request, default ke nilai saat ini jika tidak ada
        new_status = data.get('is_validated', not question.is_validated) 

        question.is_validated = bool(new_status)
        db.session.commit()

        return jsonify({'success': True, 'message': f'Status validasi soal ID {question_id} berhasil diperbarui.', 'is_validated': question.is_validated}), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error updating question validation status: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Terjadi kesalahan server: {str(e)}"}), 500

    
@app.route('/result', methods=['GET'])
@login_required  # Ensure user is logged in
def results():
    # Get collection_id from query parameters if available
    collection_id = request.args.get("collection_id")
    
    # Use the currently logged-in user instead of query param
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    # For siswa (student) users
    if hasattr(current_user, 'user_type') and current_user.user_type == 'siswa':
        # Get the student's results for the specified collection
        user_result = SiswaResult.query.filter_by(
            siswa_id=current_user.id,
            collection_id=collection_id if collection_id else None
        ).first()
        
        if not user_result:
            # Create a new result record if none exists
            return render_template('siswa/result.html', 
                                correct=0, 
                                incorrect=0, 
                                current_level=1,
                                accuracy=0,
                                answers=[],
                                collection_name="N/A",
                                collection_id=collection_id,
                                avg_time="N/A")
        
        # Calculate accuracy
        total = user_result.correct + user_result.incorrect
        accuracy = round((user_result.correct / total * 100) if total > 0 else 0, 2)
        
        # Get user answer history with questions for this collection
        query = db.session.query(
            SiswaAnswer, Question
        ).join(
            Question, SiswaAnswer.question_id == Question.id
        ).filter(
            SiswaAnswer.siswa_id == current_user.id
        )
        
        # Add collection filter if specified
        if collection_id:
            query = query.filter(Question.collection_id == collection_id)
            
        # Get collection name if available
        collection_name = "N/A"
        if collection_id:
            collection = QuestionCollection.query.get(collection_id)
            if collection:
                collection_name = collection.name
        
        # Execute query and limit to most recent answers
        answers = query.order_by(SiswaAnswer.answered_at.desc()).limit(10).all()
        
        # Format answers for template
        answer_history = []
        for ua, q in answers:
            answer_history.append({
                'question': q.soal,
                'user_answer': ua.siswa_answer,
                'is_correct': ua.is_correct,
                'level': ua.level,
                'explanation': q.explanation
            })
        
        # Calculate average answer time (if needed)
        avg_time = "N/A"  # Implement logic here if you want to track this
        
        return render_template('siswa/result.html', 
                              correct=user_result.correct, 
                              incorrect=user_result.incorrect,
                              current_level=user_result.current_level,
                              accuracy=accuracy,
                              answers=answer_history,
                              collection_name=collection_name,
                              collection_id=collection_id,
                              avg_time=avg_time)
    else:
        # For non-student users or if user_type not defined
        flash("Only students can view their results", "warning")
        return redirect(url_for('index'))
# =========================================
# ENDPOINT RESET DATABASE 
# =========================================
@app.route('/reset_database', methods=['POST'])
def reset_database_endpoint():
    try:
        # BAGIAN YANG DIMODIFIKASI - MULAI
        # Dapatkan daftar ID soal yang ada dalam koleksi (yang harus dipertahankan)
        preserved_question_ids = db.session.query(CollectionQuestion.question_id).distinct().all()
        preserved_question_ids = [id[0] for id in preserved_question_ids]
        
        if preserved_question_ids:
            print(f"Mempertahankan {len(preserved_question_ids)} soal dalam koleksi")
        
        # Pertama, hapus semua jawaban pengguna yang tidak terkait dengan soal dalam koleksi
        print("Menghapus jawaban pengguna...")
        if preserved_question_ids:
            # Hapus jawaban siswa hanya untuk soal yang tidak dalam koleksi
            SiswaAnswer.query.filter(~SiswaAnswer.question_id.in_(preserved_question_ids)).delete(synchronize_session=False)
        else:
            # Jika tidak ada soal yang dipertahankan, hapus semua jawaban
            SiswaAnswer.query.delete()
        db.session.commit()
        
        # Kedua, reset current_level semua user ke level 1
        print("Mengatur ulang level pengguna...")
        SiswaResult.query.update({
            SiswaResult.current_level: 1,
            SiswaResult.correct: 0,
            SiswaResult.incorrect: 0
        })
        db.session.commit()
        
        # Hapus relasi collection_questions untuk soal yang akan dihapus
        # tapi jangan hapus koleksi itu sendiri
        # Relasi untuk soal yang ada dalam koleksi tidak perlu dihapus
        if preserved_question_ids:
            print("Mempertahankan relasi collection_questions untuk soal yang dipertahankan...")
        else:
            print("Menghapus semua relasi collection_questions...")
            CollectionQuestion.query.delete()
            db.session.commit()
        
        # Terakhir, hapus semua soal yang tidak dalam koleksi
        print("Menghapus soal yang tidak dalam koleksi...")
        if preserved_question_ids:
            # Hapus soal yang tidak ada dalam koleksi
            Question.query.filter(~Question.id.in_(preserved_question_ids)).delete(synchronize_session=False)
        else:
            # Jika tidak ada soal yang dipertahankan, hapus semua soal
            Question.query.delete()
        db.session.commit()
        
        message = "Database berhasil direset. Silahkan upload file kembali untuk regenerasi soal."
        if preserved_question_ids:
            message += f" {len(preserved_question_ids)} soal dalam koleksi dipertahankan."
        
        print(message)
        return jsonify({"success": True, "message": message}), 200
        # BAGIAN YANG DIMODIFIKASI - SELESAI
    except Exception as e:
        print(f"Error menghapus data lama: {str(e)}")
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error menghapus data lama: {str(e)}"}), 500

# Add this to the Flask app code
@app.route('/collection-analytics/<int:collection_id>')
@login_required
def collection_analytics(collection_id):
    # Verify collection existence and ownership
    collection = QuestionCollection.query.get_or_404(collection_id)
    
    # Only allow the teacher who owns the collection to view analytics
    if collection.guru_id != current_user.id:
        flash('Anda tidak memiliki akses ke analisis koleksi ini', 'error')
        return redirect(url_for('guru'))
    
    return render_template('guru/collection-analytics.html', collection_id=collection_id)

# Add these endpoints to your Flask app

# Get detailed student answer data for a collection
@app.route('/api/siswa_answers', methods=['GET'])
@login_required
def get_siswa_answers():
    try:
        user_id = request.args.get('user_id')
        collection_id = request.args.get('collection_id')
        
        if not user_id or not collection_id:
            return jsonify({'success': False, 'message': 'Missing required parameters'}), 400
        
        # Get question IDs in this collection
        collection_question_ids = db.session.query(CollectionQuestion.question_id)\
            .filter(CollectionQuestion.collection_id == collection_id).all()
        collection_question_ids = [id[0] for id in collection_question_ids]
        
        # Get answers for these questions
        siswa_answers = db.session.query(SiswaAnswer).join(
            Question, SiswaAnswer.question_id == Question.id
        ).filter(
            SiswaAnswer.siswa_id == user_id,
            Question.id.in_(collection_question_ids)
        ).all()
        
        # Format answers for response
        formatted_answers = []
        for answer in siswa_answers:
            formatted_answers.append({
                'id': answer.id,
                'siswa_id': answer.siswa_id,
                'question_id': answer.question_id,
                'siswa_answer': answer.siswa_answer,
                'is_correct': answer.is_correct,
                'level': answer.level,
                'answered_at': answer.answered_at.isoformat() if answer.answered_at else None
            })
        
        return jsonify({
            'success': True,
            'siswa_answers': formatted_answers
        })
        
    except Exception as e:
        print(f"Error getting student answers: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Error: {str(e)}"
        }), 500

# Get collection by ID
@app.route('/api/collections/<int:collection_id>', methods=['GET'])
@login_required
def get_collection(collection_id):
    try:
        collection = QuestionCollection.query.get(collection_id)
        if not collection:
            return jsonify({'success': False, 'message': 'Collection not found'}), 404
        
        # Check if user has access to this collection
        if collection.guru_id != current_user.id and current_user.user_type != 'guru':
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        return jsonify({
            'success': True,
            'collection': {
                'id': collection.id,
                'name': collection.name,
                'description': collection.description,
                'created_at': collection.created_at.isoformat() if collection.created_at else None
            }
        })
        
    except Exception as e:
        print(f"Error getting collection: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Error: {str(e)}"
        }), 500
def emergency_json_parser(raw_text):
    """
    Emergency parser untuk mencoba mengekstrak soal dari response AI yang tidak valid JSON
    """
    try:
        questions = []
        
        # Cari pattern soal dengan berbagai format
        patterns = [
            r'"level"\s*:\s*(\d+).*?"soal"\s*:\s*"([^"]+)".*?"options"\s*:\s*\[(.*?)\].*?"jawaban_benar"\s*:\s*"([^"]+)"',
            r'level.*?(\d+).*?soal.*?"([^"]+)".*?options.*?\[(.*?)\].*?jawaban_benar.*?"([^"]+)"',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, raw_text, re.DOTALL | re.IGNORECASE)
            
            for match in matches:
                try:
                    level = int(match[0])
                    soal = match[1].strip()
                    options_text = match[2]
                    jawaban_benar = match[3].strip()
                    
                    # Parse options
                    options = []
                    option_matches = re.findall(r'"([^"]+)"', options_text)
                    if len(option_matches) >= 4:
                        options = option_matches[:4]
                    
                    if soal and options and jawaban_benar and 1 <= level <= 7:
                        questions.append({
                            "level": level,
                            "question_type": "multiple_choice",
                            "soal": soal,
                            "options": options,
                            "jawaban_benar": jawaban_benar,
                            "p": 0.75,  # Default probability
                            "explanation": f"Soal level {level} dari modul ajar"
                        })
                        
                        if len(questions) >= 35:  # Stop after 35 questions
                            break
                            
                except (ValueError, IndexError) as e:
                    continue
            
            if questions:
                break
        
        return questions if len(questions) >= 7 else None  # Minimal 7 soal
        
    except Exception as e:
        print(f"Emergency parser error: {str(e)}")
        return None

# =========================================
# PROGRESS TRACKING ENDPOINTS
# =========================================
@app.route('/api/progress/<int:user_id>', methods=['GET'])
@login_required
def get_upload_progress(user_id):
    """Endpoint untuk mengecek progress upload"""
    # Pastikan user hanya bisa akses progress sendiri atau guru bisa akses semua
    if not (current_user.id == user_id or (hasattr(current_user, 'user_type') and current_user.user_type == 'guru')):
        return jsonify({"message": "Akses ditolak"}), 403
    
    progress_data = get_progress(user_id)
    if not progress_data:
        return jsonify({"message": "Progress tidak ditemukan"}), 404
    
    return jsonify({
        "success": True,
        "progress": progress_data
    })

# =========================================
# ENDPOINT UPLOAD & GENERATE 5 SOAL PER level (35 TOTAL)
# =========================================
@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if not current_user.is_authenticated or not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        return jsonify({"message": "Hanya guru yang dapat menggenerate soal"}), 403

    user_id = current_user.id
    print(f"[{datetime.datetime.now()}] Upload file endpoint called by teacher: {current_user.username}")
    
    # Initialize progress tracking
    update_progress(user_id, 1, "active", "Memulai proses upload...")
    
    if 'file' not in request.files:
        clear_progress(user_id)
        return jsonify({"message": "Tidak ada file yang diunggah"}), 400

    file = request.files['file']
    if file.filename == '':
        clear_progress(user_id)
        return jsonify({"message": "Tidak ada file yang dipilih"}), 400

    file_ext = file.filename.rsplit('.', 1)[-1].lower()
    if file_ext not in ['doc', 'docx', 'pdf']:
        clear_progress(user_id)
        return jsonify({"message": "Format file tidak didukung. Hanya file .doc, .docx, dan .pdf yang diizinkan"}), 400

    try:
        # STEP 1: Upload dan validasi file
        update_progress(user_id, 1, "completed", "File berhasil diunggah")
        file_stream = file.read()
        
        # STEP 2: Analisis struktur dokumen
        update_progress(user_id, 2, "active", "Menganalisis struktur dan format dokumen...")
        print(f"[{datetime.datetime.now()}] Memulai validasi file...")
        
        # Validasi format dan konten
        is_valid_file, validation_result = validate_file_format_and_content(file_stream, file_ext, file.filename)
        
        if not is_valid_file:
            clear_progress(user_id)
            print(f"Validasi gagal: {validation_result}")
            return jsonify({
                "success": False,
                "message": f"File tidak memenuhi kriteria modul ajar: {validation_result}"
            }), 400
        
        content_text = validation_result
        print(f"[{datetime.datetime.now()}] File berhasil divalidasi. Panjang konten: {len(content_text)} karakter.")
        update_progress(user_id, 2, "completed", "Struktur dokumen berhasil dianalisis")
        
        # STEP 3: Ekstraksi tujuan pembelajaran
        update_progress(user_id, 3, "active", "Mengekstrak tujuan pembelajaran dan komponen modul...")
        
        # VALIDASI PENDIDIKAN: Sudah dilakukan dalam validate_file_format_and_content
        # Tidak perlu validasi ganda lagi, langsung lanjut ke ekstraksi
        
        # EKSTRAKSI KOMPONEN: Gunakan ekstraksi hybrid dengan fallback
        print("Mengekstrak komponen modul ajar...")
        module_components, validation_result = extract_hybrid_module_components(content_text)

        # VALIDASI KUALITAS: Periksa kualitas ekstraksi
        quality_score, quality_issues = check_content_quality_score(module_components)
        
        print(f"Quality score: {quality_score}/100")
        print(f"Issues: {quality_issues}")
        
        # THRESHOLD FLEKSIBEL: Minimal 40 poin untuk diproses (dikurangi dari 60)
        if quality_score < 40:
            clear_progress(user_id)
            issues_text = "; ".join(quality_issues)
            return jsonify({
                "success": False,
                "message": f"Dokumen pembelajaran tidak memenuhi standar minimum (skor: {quality_score}/100). Masalah: {issues_text}. Pastikan dokumen memiliki tujuan pembelajaran yang jelas."
            }), 400

        # Tambahkan logging dan validasi detail
        detailed_validation = log_extraction_results(module_components)

        # VALIDASI FINAL: Periksa komponen kunci (lebih fleksibel)
        tujuan_list = module_components.get("tujuan_pembelajaran", [])
        
        # Jika tidak ada tujuan sama sekali, coba ekstrak ulang atau buat default
        if not tujuan_list:
            print("WARNING: Tujuan pembelajaran tidak ditemukan, membuat tujuan default...")
            # Buat tujuan pembelajaran default berdasarkan mata pelajaran
            mata_pelajaran = module_components.get("mata_pelajaran", "")
            if mata_pelajaran:
                default_tujuan = f"Memahami konsep dasar {mata_pelajaran}"
                module_components["tujuan_pembelajaran"] = [default_tujuan]
                print(f"Tujuan default dibuat: {default_tujuan}")
            else:
                module_components["tujuan_pembelajaran"] = ["Memahami materi pembelajaran yang diberikan"]
                print("Tujuan sangat umum dibuat karena mata pelajaran tidak terdeteksi")
        
        # Set default mata pelajaran jika kosong
        if not module_components.get("mata_pelajaran"):
            module_components["mata_pelajaran"] = "Pembelajaran Umum"
            print("WARNING: Mata pelajaran tidak terdeteksi, menggunakan default 'Pembelajaran Umum'")

        print(f"[{datetime.datetime.now()}] Validasi berhasil. Melanjutkan ke pemrosesan AI...")
        update_progress(user_id, 3, "completed", "Tujuan pembelajaran berhasil diekstrak")
        
        # STEP 4: Proses dengan AI Gemini
        update_progress(user_id, 4, "active", "Memproses dengan AI Gemini untuk membuat soal...")

        # Buat DataFrame ringkas (mengganti convert_text_to_dataframe_improved)
        df = pd.DataFrame({
            'Komponen': ['Mata Pelajaran', 'Topik', 'Kelas', 'Jumlah Tujuan', 'Pemahaman Bermakna'],
            'Detail': [
                module_components.get("mata_pelajaran", "")[:30],
                module_components.get("topik_utama", "")[:30], 
                module_components.get("kelas", ""),
                str(len(module_components.get("tujuan_pembelajaran", []))),
                str(len(module_components.get("pemahaman_bermakna", [])))
            ]
        })

        # PERUBAHAN: Gunakan prompt yang dioptimalkan tapi tetap struktur lama
        prompt = create_optimized_prompt_with_good_structure(module_components)

        print(f"[{datetime.datetime.now()}] Mengirim prompt teroptimalkan ({len(prompt)} chars) ke Gemini AI...")
        print(f"Efisiensi: Ukuran prompt ~{len(prompt)} karakter (vs ~8000+ sebelumnya) - penghematan signifikan!")
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        print(f"[{datetime.datetime.now()}] Respons dari Gemini AI diterima.")
        update_progress(user_id, 4, "completed", "AI berhasil menghasilkan soal")
        
        print("Raw AI response:", raw_text[:500])
        
        # Enhanced JSON parsing with multiple strategies
        print(f"Response length: {len(raw_text)} chars")
        print(f"Response starts with: {raw_text[:100]}")
        print(f"Response ends with: {raw_text[-100:]}")
        
        # Check for JSON indicators
        json_indicators = ['[', '{', '"level"', '"soal"', '"options"']
        found_indicators = [indicator for indicator in json_indicators if indicator in raw_text]
        print(f"JSON indicators found: {found_indicators}")
        
        gen_questions = []
        try:
            # Method 1: Direct JSON parsing
            gen_questions = json.loads(raw_text)
            print("✅ Berhasil parsing JSON langsung")
        except json.JSONDecodeError:
            print("❌ Direct JSON parsing gagal, mencoba pembersihan...")
            
            try:
                # Method 2: Clean markdown and common issues
                cleaned_text = raw_text.strip()
                # Remove markdown code blocks
                cleaned_text = re.sub(r'```(?:json)?\s*\n?', '', cleaned_text)
                cleaned_text = re.sub(r'```\s*$', '', cleaned_text)
                # Remove trailing commas
                cleaned_text = re.sub(r',(\s*[}\]])', r'\1', cleaned_text)
                # Remove comments
                cleaned_text = re.sub(r'//.*?\n', '\n', cleaned_text)
                
                gen_questions = json.loads(cleaned_text)
                print("✅ Berhasil parsing JSON setelah pembersihan")
            except json.JSONDecodeError:
                print("❌ Pembersihan gagal, mencoba ekstraksi regex...")
                
                try:
                    # Method 3: Extract JSON array using regex
                    json_pattern = r'\[\s*\{.*?\}\s*\]'
                    match = re.search(json_pattern, raw_text, re.DOTALL)
                    if match:
                        json_text = match.group()
                        # Clean the extracted JSON
                        json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)
                        gen_questions = json.loads(json_text)
                        print("✅ Berhasil parsing JSON dari ekstraksi regex")
                    else:
                        raise json.JSONDecodeError("No JSON array found", raw_text, 0)
                except json.JSONDecodeError:
                    print("❌ Regex ekstraksi gagal, mencoba bracket matching...")
                    
                    try:
                        # Method 4: Find JSON by bracket matching
                        start_bracket = raw_text.find('[')
                        if start_bracket == -1:
                            raise json.JSONDecodeError("No opening bracket found", raw_text, 0)
                        
                        # Count brackets to find matching closing bracket
                        bracket_count = 0
                        end_bracket = -1
                        
                        for i in range(start_bracket, len(raw_text)):
                            if raw_text[i] == '[':
                                bracket_count += 1
                            elif raw_text[i] == ']':
                                bracket_count -= 1
                                if bracket_count == 0:
                                    end_bracket = i
                                    break
                        
                        if end_bracket == -1:
                            raise json.JSONDecodeError("No matching closing bracket found", raw_text, 0)
                        
                        json_text = raw_text[start_bracket:end_bracket+1]
                        # Clean the extracted JSON
                        json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)
                        json_text = re.sub(r'//.*?\n', '\n', json_text)
                        
                        gen_questions = json.loads(json_text)
                        print("✅ Berhasil parsing JSON dari bracket matching")
                    except json.JSONDecodeError as final_error:
                        print(f"❌ Semua metode parsing gagal. Error terakhir: {str(final_error)}")
                        
                        # ENHANCED: Log raw response untuk debugging
                        print("=== RAW AI RESPONSE (first 1000 chars) ===")
                        print(raw_text[:1000])
                        print("=== END RAW RESPONSE ===")
                        
                        # Method 5: Emergency fallback - manual parsing
                        try:
                            print("🚨 Mencoba emergency parsing...")
                            gen_questions = emergency_json_parser(raw_text)
                            if gen_questions:
                                print(f"✅ Emergency parsing berhasil: {len(gen_questions)} soal")
                            else:
                                raise Exception("Emergency parsing juga gagal")
                        except Exception as emergency_error:
                            print(f"❌ Emergency parsing gagal: {str(emergency_error)}")
                            return jsonify({
                                "message": f"Gagal memproses response AI. Raw response length: {len(raw_text)}. Silakan coba lagi atau hubungi administrator."
                            }), 500

        if not isinstance(gen_questions, list):
            print(f"Diharapkan list, tapi dapat {type(gen_questions)}")
            return jsonify({"message": "AI tidak mengembalikan array soal yang valid"}), 500
            
        print(f"Berhasil mengekstrak {len(gen_questions)} soal")
        
        if len(gen_questions) < 7:
            print(f"Jumlah soal tidak mencukupi: {len(gen_questions)}")
            return jsonify({"message": f"AI hanya menghasilkan {len(gen_questions)} soal, minimal diperlukan 7 soal"}), 500

        # Delete old questions not in collections
        try:
            preserved_question_ids_in_collections = db.session.query(CollectionQuestion.question_id).join(
                Question, Question.id == CollectionQuestion.question_id
            ).filter(
                Question.guru_id == current_user.id
            ).distinct().all()
            preserved_question_ids_in_collections = [id[0] for id in preserved_question_ids_in_collections]
            
            # Delete student answers for questions to be deleted
            siswa_answers_to_delete_q_ids = db.session.query(Question.id).filter(
                Question.guru_id == current_user.id,
                ~Question.id.in_(preserved_question_ids_in_collections)
            ).subquery()

            SiswaAnswer.query.filter(
                SiswaAnswer.question_id.in_(siswa_answers_to_delete_q_ids)
            ).delete(synchronize_session=False)
            db.session.commit()

            # Delete questions not in collections
            Question.query.filter(
                Question.guru_id == current_user.id,
                ~Question.id.in_(preserved_question_ids_in_collections)
            ).delete(synchronize_session=False)
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            print(f"Error menghapus data lama: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({"message": f"Error menghapus data lama: {str(e)}"}), 500
            
        # STEP 5: Save to database
        update_progress(user_id, 5, "active", "Menyimpan soal ke database...")
        
        # Save new questions to database
        print("Menyimpan soal baru ke database untuk guru:", current_user.username)
        new_questions_from_db = [] 
        for q in gen_questions:
            try:
                level_num = int(q.get("level"))
                if 1 <= level_num <= 7:
                    p_val = float(q.get("p", 0.75))
                    bobot = assign_weight(p_val)
                    
                    options_str = None
                    if 'options' in q and isinstance(q['options'], list):
                        options_str = json.dumps(q['options'])
                    
                    question_type = q.get('question_type', 'multiple_choice')
                    
                    new_question = Question(
                        guru_id=current_user.id,
                        level=level_num,
                        soal=q.get("soal"),
                        jawaban_benar=q.get("jawaban_benar", ""),
                        options=options_str,
                        question_type=question_type,
                        p=p_val,
                        bobot=bobot,
                        explanation=q.get("explanation", "")
                    )
                    db.session.add(new_question)
                    new_questions_from_db.append(new_question)
            except Exception as e:
                db.session.rollback()
                print(f"Error memproses soal: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({"message": f"Error memproses soal: {str(e)}"}), 500
            
        db.session.commit()
        print("Database commit berhasil: soal baru tersimpan.")

        # Prepare data for frontend
        questions_for_frontend = []
        for q_db in new_questions_from_db:
            options = []
            if q_db.options:
                try:
                    options = json.loads(q_db.options)
                except json.JSONDecodeError:
                    pass
            questions_for_frontend.append({
                "id": q_db.id,
                "guru_id": q_db.guru_id,
                "collection_id": q_db.collection_id,
                "level": q_db.level,
                "soal": q_db.soal,
                "jawaban_benar": q_db.jawaban_benar,
                "options": options,
                "question_type": q_db.question_type,
                "p": float(q_db.p),
                "bobot": q_db.bobot,
                "explanation": q_db.explanation,
                "created_at": q_db.created_at.isoformat() if q_db.created_at else None,
                "version": q_db.version,
                "is_current": q_db.is_current,
                "is_validated": q_db.is_validated
            })

        # Count questions by level
        level_counts = {}
        for q in questions_for_frontend:
            level = int(q.get("level"))
            level_counts[level] = level_counts.get(level, 0) + 1
                
        level_summary = ", ".join([f"level {level}: {count} soal" for level, count in sorted(level_counts.items())])

        # Complete step 5 and clear progress
        update_progress(user_id, 5, "completed", "Semua soal berhasil disimpan!")
        
        # Create success message without quality score
        message = f"✅ Modul ajar berhasil divalidasi dan diproses! Total {len(questions_for_frontend)} soal pilihan ganda berhasil digenerate ({level_summary})"

        # Clear progress after successful completion
        clear_progress(user_id)

        return jsonify({
            "success": True,
            "message": message,  
            "data": questions_for_frontend,
            "validation_info": {
                "quality_score": quality_score,
                "components_found": len([k for k, v in module_components.items() if v]),
                "total_objectives": len(module_components.get("tujuan_pembelajaran", []))
            }
        }), 200

    except Exception as e:
        clear_progress(user_id)
        print(f"Exception in upload_file: {str(e)}")
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Error pemrosesan: {str(e)}"}), 500

# Function to validate if a document contains educational content
def check_educational_content(content_text):
    """
    Checks if the document content appears to be educational material.
    
    Returns:
        bool: True if the document is likely educational content, False otherwise
    """
    if not content_text or len(content_text.strip()) < 100:
        print("Document content too short for validation")
        return False
    
    # Convert to lowercase for case-insensitive matching
    content = content_text.lower()
    
    # Define educational content patterns and keywords
    edu_patterns = [
        # Headers or sections typically found in educational materials
        r'\b(modul|bab|materi|pembelajaran|pendidikan|pengajaran|pelatihan|belajar)\b',
        r'\b(tujuan|capaian|sasaran|kompetensi|kemampuan)\s+(pembelajaran|belajar|pendidikan)\b',
        r'\b(indikator|pencapaian|keberhasilan|penilaian)\s+(kompetensi|pembelajaran|belajar)\b',
        r'\b(peserta\s+didik|siswa|murid|pelajar|mahasiswa)\b',
        
        # Structural elements commonly found in educational materials
        r'\b(pendahuluan|isi|penutup|daftar\s+pustaka|referensi|latihan|evaluasi|penilaian)\b',
        r'\b(kelas|mata\s+pelajaran|mapel|bidang\s+studi|pelajaran|kurikulum|silabus)\b',
        
        # Educational activities
        r'\b(diskusi|latihan|tugas|proyek|aktivitas|kegiatan|praktikum|eksperimen)\b',
        
        # Educational roles
        r'\b(guru|pendidik|pengajar|fasilitator|instruktur|dosen|tutor)\b'
    ]
    
    # Educational keyword categories with weights
    edu_keyword_categories = {
        'structural': {
            'weight': 2, 
            'keywords': ['modul', 'bab', 'materi', 'pelajaran', 'kurikulum', 'silabus', 'pendahuluan', 
                        'isi', 'penutup', 'daftar pustaka', 'referensi']
        },
        'objectives': {
            'weight': 3, 
            'keywords': ['tujuan pembelajaran', 'capaian pembelajaran', 'kompetensi dasar', 
                        'indikator pencapaian', 'sasaran pembelajaran']
        },
        'learning': {
            'weight': 1, 
            'keywords': ['belajar', 'pembelajaran', 'pendidikan', 'pengajaran', 'pelatihan', 
                        'memahami', 'menguasai', 'menganalisis']
        },
        'audience': {
            'weight': 1, 
            'keywords': ['peserta didik', 'siswa', 'murid', 'pelajar', 'mahasiswa']
        },
        'activities': {
            'weight': 1, 
            'keywords': ['diskusi', 'latihan', 'tugas', 'proyek', 'aktivitas', 'kegiatan', 
                        'praktikum', 'eksperimen', 'evaluasi']
        },
        'roles': {
            'weight': 1, 
            'keywords': ['guru', 'pendidik', 'pengajar', 'fasilitator', 'instruktur', 'dosen', 'tutor']
        }
    }
    
    # Check pattern matches
    pattern_matches = 0
    for pattern in edu_patterns:
        if re.search(pattern, content):
            pattern_matches += 1
    
    # Check keyword matches with weights
    weighted_score = 0
    keywords_found = []
    
    for category, data in edu_keyword_categories.items():
        category_score = 0
        for keyword in data['keywords']:
            if keyword in content:
                category_score += 1
                keywords_found.append(keyword)
        
        # Apply category weight to the score
        weighted_score += (category_score * data['weight'])
    
    # Log the results
    print(f"Pattern matches: {pattern_matches}/8")
    print(f"Weighted keyword score: {weighted_score}")
    print(f"Educational keywords found: {', '.join(keywords_found[:10])}{' and more' if len(keywords_found) > 10 else ''}")
    
    # Validation criteria - document passes if it:
    # 1. Has at least 3 pattern matches, OR
    # 2. Has a weighted score of at least 5
    is_educational = (pattern_matches >= 3) or (weighted_score >= 5)
    
    return is_educational

# New function to extract educational components from document content
def extract_educational_components(content_text, return_dict=False):
    """
    Extracts educational components from content text with improved flexibility.
    
    Args:
        content_text: The text content to extract educational components from
        return_dict: If True, returns a dictionary; if False, returns a tuple of components
        
    Returns:
        Either a 5-tuple of (module_elements, initial_competencies, learning_objectives, 
        pemahaman_bermakna, target_peserta_didik) or a dictionary of components
    """
    # Initialize results dictionary with "Tidak tersedia" as default values
    results = {
        "Modul/Elemen Ajar": "Tidak tersedia",
        "Kompetensi Awal": "Tidak tersedia",
        "Tujuan Pembelajaran": "Tidak tersedia",
        "Pemahaman Bermakna": "Tidak tersedia",
        "Target Peserta Didik": "Tidak tersedia"
    }
    
    # Normalize text for easier processing
    content = content_text.lower()
    original_content = content_text  # Keep original case for extraction
    
    # Use entire document as Module/Elemen Ajar if we can't find specific sections
    # Extract the first 500 characters as a fallback
    if len(original_content) > 0:
        document_preview = original_content[:min(500, len(original_content))].strip()
        results["Modul/Elemen Ajar"] = document_preview
        
    # Auto-generate learning objectives if we can't find them
    # Look for keywords that might indicate learning content
    learning_keywords = ["belajar", "memahami", "menguasai", "pembelajaran", "algoritma", 
                        "program", "komputer", "pemrograman", "coding", "kode", "struktur",
                        "fungsi", "variabel", "class", "objek", "database", "data", "web"]
                        
    # Count learning-related keywords
    keyword_count = 0
    for keyword in learning_keywords:
        if keyword in content:
            keyword_count += 1
            
    # If document has learning content, generate a generic learning objective
    if keyword_count >= 3:
        results["Tujuan Pembelajaran"] = "Memahami konsep dasar dan mampu mengaplikasikan materi yang disajikan dalam modul pembelajaran ini."
    
    # ===== Module/Element Section =====
    module_patterns = [
        r'(?:modul|elemen|materi)(?:\s+ajar|\s+pembelajaran|\s+pokok)?(.*?)(?:kompetensi|tujuan|capaian|daftar pustaka|referensi)',
        r'(?:bab|materi|konten|isi)(?:\s+pembelajaran|\s+utama)?(.*?)(?:kompetensi|tujuan|capaian|daftar pustaka|referensi)',
        r'(?:pokok|inti)(?:\s+bahasan|\s+materi|\s+pembelajaran)?(.*?)(?:kompetensi|tujuan|capaian|daftar pustaka|referensi)',
        r'(?:i\.|1\.)(?:\s+identitas\s+modul)(.*?)(?:ii\.|2\.)'  # Captures sections starting with Roman numerals
    ]
    
    for pattern in module_patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            module_text = match.group(1).strip()
            if module_text:
                results["Modul/Elemen Ajar"] = clean_extracted_text(module_text)
                break
    
    # ===== Initial Competencies Section =====
    competency_patterns = [
        r'(?:kompetensi|kemampuan)(?:\s+awal|\s+dasar|\s+prasyarat)(?:\s+[\w\s]+)?[:\r\n](.*?)(?:tujuan|capaian|indikator|materi|bab|daftar pustaka|referensi)',
        r'(?:prerequisite|prasyarat)(?:\s+[\w\s]+)?[:\r\n](.*?)(?:tujuan|capaian|indikator|materi|bab|daftar pustaka|referensi)',
        r'(?:pengetahuan|keterampilan)(?:\s+awal|\s+dasar)(?:\s+[\w\s]+)?[:\r\n](.*?)(?:tujuan|capaian|indikator|materi|bab|daftar pustaka|referensi)',
        r'(?:ii\.|2\.)(?:\s+kompetensi\s+awal)(.*?)(?:iii\.|3\.)'  # Captures sections with Roman numerals
    ]
    
    for pattern in competency_patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            comp_text = match.group(1).strip()
            if comp_text:
                results["Kompetensi Awal"] = clean_extracted_text(comp_text)
                break
    
    # ===== Learning Objectives Section =====
    objective_patterns = [
        r'(?:tujuan|capaian)(?:\s+pembelajaran|\s+belajar|\s+pendidikan|\s+instruksional|\s+pelatihan)(?:\s+[\w\s]+)?[:\r\n](.*?)(?:kompetensi|materi|bab|daftar pustaka|referensi|metodologi|pemahaman|target)',
        r'(?:learning|instructional)(?:\s+objectives|\s+goals|\s+outcomes)(?:\s+[\w\s]+)?[:\r\n](.*?)(?:kompetensi|materi|bab|daftar pustaka|referensi|metodologi|pemahaman|target)',
        r'(?:indikator|pencapaian)(?:\s+keberhasilan|\s+pembelajaran|\s+belajar)(?:\s+[\w\s]+)?[:\r\n](.*?)(?:kompetensi|materi|bab|daftar pustaka|referensi|metodologi|pemahaman|target)',
        r'(?:iii\.|3\.)(?:\s+tujuan\s+pembelajaran)(.*?)(?:iv\.|4\.)'  # Captures sections with Roman numerals
    ]
    
    for pattern in objective_patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            obj_text = match.group(1).strip()
            if obj_text:
                results["Tujuan Pembelajaran"] = clean_extracted_text(obj_text)
                break
    
    # ===== NEW: Meaningful Understanding Section =====
    understanding_patterns = [
        r'(?:pemahaman\s+bermakna|bermakna\s+pemahaman|pemahaman\s+yang\s+bermakna)[:\r\n](.*?)(?:kompetensi|tujuan|capaian|materi|bab|daftar pustaka|referensi|target)',
        r'(?:meaningful\s+understanding|understanding\s+meaningful)[:\r\n](.*?)(?:kompetensi|tujuan|capaian|materi|bab|daftar pustaka|referensi|target)',
        r'(?:big\s+ideas|gagasan\s+utama|ide\s+pokok)[:\r\n](.*?)(?:kompetensi|tujuan|capaian|materi|bab|daftar pustaka|referensi|target)',
        r'(?:iv\.|4\.)(?:\s+pemahaman\s+bermakna)(.*?)(?:v\.|5\.)'  # Captures sections with Roman numerals
    ]
    
    for pattern in understanding_patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            understanding_text = match.group(1).strip()
            if understanding_text:
                results["Pemahaman Bermakna"] = clean_extracted_text(understanding_text)
                break
    
    # ===== NEW: Target Students Section =====
    target_patterns = [
        r'(?:target\s+peserta\s+didik|sasaran\s+peserta|peserta\s+didik\s+target)[:\r\n](.*?)(?:kompetensi|tujuan|capaian|materi|bab|daftar pustaka|referensi)',
        r'(?:target\s+audience|target\s+learners|intended\s+learners)[:\r\n](.*?)(?:kompetensi|tujuan|capaian|materi|bab|daftar pustaka|referensi)',
        r'(?:siswa\s+yang\s+dituju|karakteristik\s+peserta\s+didik)[:\r\n](.*?)(?:kompetensi|tujuan|capaian|materi|bab|daftar pustaka|referensi)',
        r'(?:v\.|5\.)(?:\s+target\s+peserta\s+didik)(.*?)(?:vi\.|6\.)'  # Captures sections with Roman numerals
    ]
    
    for pattern in target_patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            target_text = match.group(1).strip()
            if target_text:
                results["Target Peserta Didik"] = clean_extracted_text(target_text)
                break
    
    # ===== Keyword-based approach for sections that weren't found =====
    lines = original_content.split('\n')
    
    # Dictionary to map section keys to their search keywords
    section_keywords = {
        "Modul/Elemen Ajar": ['modul', 'elemen', 'materi', 'bab', 'pokok bahasan', 'identitas modul'],
        "Kompetensi Awal": ['kompetensi awal', 'prasyarat', 'kemampuan dasar', 'kompetensi dasar'],
        "Tujuan Pembelajaran": ['tujuan pembelajaran', 'capaian pembelajaran', 'learning objectives'],
        "Pemahaman Bermakna": ['pemahaman bermakna', 'bermakna', 'big ideas', 'gagasan utama', 'ide pokok'],
        "Target Peserta Didik": ['target peserta', 'sasaran peserta', 'karakteristik peserta', 'target siswa', 'audience']
    }
    
    # For sections still not found, try the keyword approach
    for section, keywords in section_keywords.items():
        if results[section] == "Tidak tersedia":
            paragraph_start = -1
            
            # First look for exact section headers
            for i, line in enumerate(lines):
                line_lower = line.lower().strip()
                # Check if line matches any of our section patterns
                if any(keyword in line_lower for keyword in keywords):
                    paragraph_start = i
                    break
            
            if paragraph_start >= 0:
                # Determine where the section might end - either at next section or after several lines
                paragraph_end = paragraph_start + 1
                
                # Look for the next potential section header
                for i in range(paragraph_start + 1, min(paragraph_start + 15, len(lines))):
                    line_lower = lines[i].lower().strip()
                    
                    # Check if this line might be the start of the next section
                    if (re.match(r'^[ivxlcdm]+\.|^\d+\.', line_lower) or  # Roman numerals or numbers followed by period
                        any(keyword in line_lower for section_kw in section_keywords.values() 
                            for keyword in section_kw if section_kw != keywords)):
                        paragraph_end = i
                        break
                
                # Extract and clean the section text
                section_text = '\n'.join(lines[paragraph_start:paragraph_end]).strip()
                if section_text:
                    results[section] = clean_extracted_text(section_text)
    
    # Second pass to try to find sections by scanning the whole document
    for section, value in results.items():
        if value == "Tidak tersedia":
            # Look for sentences that might contain relevant information
            for i, line in enumerate(lines):
                line_lower = line.lower()
                
                # Get keywords for this section
                keywords = section_keywords.get(section, [])
                
                # Check each keyword
                for keyword in keywords:
                    if keyword in line_lower:
                        # Extract several lines from this point
                        extract = '\n'.join(lines[i:min(i+8, len(lines))])
                        results[section] = clean_extracted_text(extract)
                        break
                
                if results[section] != "Tidak tersedia":
                    break
    
    # Return the appropriate format based on the return_dict parameter
    if return_dict:
        return results
    else:
        return (
            results["Modul/Elemen Ajar"],
            results["Kompetensi Awal"],
            results["Tujuan Pembelajaran"],
            results["Pemahaman Bermakna"],
            results["Target Peserta Didik"]
        )

def clean_extracted_text(text):
    """Clean up extracted text by removing extra whitespace, bullet points, etc."""
    if not text or text == "Tidak tersedia":
        return text
        
    # Remove excess whitespace but preserve paragraph breaks
    text = re.sub(r'[ \t]+', ' ', text)  # Collapse multiple spaces/tabs to single space
    text = re.sub(r'\n{3,}', '\n\n', text)  # Limit consecutive newlines to max 2
    
    # Handle common formatting patterns
    text = text.replace(' .', '.')  # Fix common spacing issues
    text = text.replace(' ,', ',')
    text = text.replace(' :', ':')
    
    # Preserve bullet points but normalize their format
    text = re.sub(r'^\s*[•○●♦◘■]\s*', '• ', text, flags=re.MULTILINE)
    
    # Convert numbered lists to consistent format but preserve them
    text = re.sub(r'^\s*(\d+)[\.\)]\s*', r'\1. ', text, flags=re.MULTILINE)
    
    # Add line breaks for readability in the prompt after sentence endings
    text = re.sub(r'([.!?])\s+([A-Z])', r'\1\n\2', text)
    
    # Handle brackets or parenthetical content 
    text = re.sub(r'\(\s*(.*?)\s*\)', r'(\1)', text)  # Clean up spaces in parentheses
    
    # Fix common OCR issues
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)  # Add space between lowercase and uppercase
    
    return text.strip()
# Function to extract text from a PDF file
def extract_text_from_pdf(file_path):
    """Extract text from a PDF file"""
    text = ""
    try:
        with open(file_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {str(e)}")
        raise

def extract_text_from_pdf_bytes(file_bytes: bytes):
    """Extract text from PDF given raw bytes (no disk write)."""
    try:
        from io import BytesIO
        bio = BytesIO(file_bytes)
        pdf_reader = PyPDF2.PdfReader(bio)
        text = ""
        
        # Try to get PDF metadata
        metadata = pdf_reader.metadata
        if metadata:
            info_text = []
            for key, value in metadata.items():
                if key.startswith('/') and value and isinstance(value, str):
                    # Clean up the key (remove leading slash)
                    clean_key = key[1:] if key.startswith('/') else key
                    info_text.append(f"{clean_key}: {value}")
            
            if info_text:
                text += "\n".join(info_text) + "\n\n"
                
        # Extract text from all pages
        for page_num, page in enumerate(pdf_reader.pages, 1):
            try:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                else:
                    # If we can't extract text normally, try to get any text using a more generic approach
                    text += f"[Content from page {page_num} - text extraction limited]\n"
            except Exception as page_error:
                print(f"Warning: Error extracting text from page {page_num}: {str(page_error)}")
                text += f"[Content from page {page_num} - extraction error]\n"
                
        # If we got very little text, try an alternative extraction method
        if len(text.strip()) < 100:
            print("Warning: Limited text extracted from PDF, trying alternative extraction method")
            text += "[This PDF may contain scanned images or protected content. Limited text extraction.]\n"
            
        return text
    except Exception as e:
        print(f"Error extracting text from PDF bytes: {str(e)}")
        # Return a placeholder instead of raising, so processing can continue
        return "[PDF content could not be extracted. The file may be damaged or protected.]"


# Function to extract text from a Word document (.docx)
def extract_text_from_docx(file_path):
    """Extract text from a Word document (.docx)"""
    try:
        doc = Document(file_path)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    row_text.append(cell.text)
                if row_text:
                    text += "\n" + " | ".join(row_text)

        return text
    except Exception as e:
        print(f"Error extracting text from DOCX: {str(e)}")
        raise

def extract_text_from_docx_bytes(file_bytes: bytes, file_ext: str):
    """Extract text from a Word document (.doc or .docx) using raw bytes."""
    from io import BytesIO
    try:
        bio = BytesIO(file_bytes)
        text = ""
        
        # For DOCX format
        if file_ext == 'docx':
            doc = Document(bio)
            
            # Get document properties if available
            try:
                core_properties = doc.core_properties
                if core_properties:
                    properties_text = []
                    for prop_name in ['title', 'subject', 'author', 'keywords', 'category']:
                        prop_value = getattr(core_properties, prop_name, None)
                        if prop_value:
                            properties_text.append(f"{prop_name.title()}: {prop_value}")
                    
                    if properties_text:
                        text += "\n".join(properties_text) + "\n\n"
            except Exception as prop_error:
                print(f"Warning: Could not extract document properties: {str(prop_error)}")
            
            # Extract text from paragraphs with style information
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    # Check if paragraph has a style that might indicate a heading or important text
                    style_name = paragraph.style.name if paragraph.style else "Normal"
                    if "heading" in style_name.lower() or style_name.lower().startswith(("h1", "h2", "h3")):
                        text += f"[{style_name}] {paragraph.text}\n"
                    else:
                        text += paragraph.text + "\n"
            
            # Extract tables with better formatting
            for table in doc.tables:
                text += "\n[Table Content]\n"
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        cell_content = cell.text.strip().replace('\n', ' ')
                        row_text.append(cell_content)
                    if row_text:
                        text += " | ".join(row_text) + "\n"
                text += "[End Table]\n"
            
            # Also try to extract header and footer content which might contain important info
            try:
                header_text = []
                for section in doc.sections:
                    for header in section.header.paragraphs:
                        if header.text.strip():
                            header_text.append(header.text)
                
                if header_text:
                    text += "\n[Header Content]\n" + "\n".join(header_text) + "\n"
            except Exception as header_error:
                print(f"Warning: Could not extract headers: {str(header_error)}")
                
        else:  # .doc fallback using mammoth
            try:
                result = mammoth.extract_raw_text(bio)
                text = result.value
            except Exception as mammoth_error:
                print(f"Warning: Error extracting .doc with mammoth: {str(mammoth_error)}")
                text = "[This .doc file could not be fully extracted. Limited content available.]"
        
        # If we got very little text, add a note
        if len(text.strip()) < 100:
            print("Warning: Limited text extracted from DOC/DOCX")
            text += "[This document may contain mostly images or protected content. Limited text extraction.]\n"
            
        return text
    except Exception as e:
        print(f"Error extracting text from DOC/DOCX bytes: {str(e)}")
        # Return a placeholder instead of raising, so processing can continue
        return "[DOC/DOCX content could not be extracted. The file may be damaged or protected.]"


# =========================================
# EDUCATIONAL COMPONENT EXTRACTION HELPERS
# =========================================
# NOTE: This is a legacy implementation that's been replaced by the more advanced version above.
# This version is kept for backward compatibility with older code that might call it.
def extract_educational_components_legacy(content_text, return_dict=False):
    """
    Legacy version - Extract educational components with improved precision to avoid extracting
    irrelevant sections like "Informasi Umum" or administrative details.
    This function is maintained for backward compatibility.
    """
    print("WARNING: Using legacy extract_educational_components_legacy() function. Consider updating code to use the newer version.")
    
    # Just call the current implementation
    return extract_educational_components(content_text, return_dict)
    
    # # Old implementation would have been here
    # results = {
    #    "Modul/Elemen Ajar": "Tidak tersedia",
    #    "Kompetensi Awal": "Tidak tersedia", 
    #    "Tujuan Pembelajaran": "Tidak tersedia",
    #    "Pemahaman Bermakna": "Tidak tersedia",
    #    "Target Peserta Didik": "Tidak tersedia"
    # }
    # 
    # # Split content into sections based on clear headers
    # sections = split_document_into_sections(content_text)
    # 
    # # Extract each component with specific section targeting
    # results["Modul/Elemen Ajar"] = extract_module_elements(sections)
    results["Kompetensi Awal"] = extract_initial_competencies(sections)
    results["Tujuan Pembelajaran"] = extract_learning_objectives(sections)
    results["Pemahaman Bermakna"] = extract_meaningful_understanding(sections)
    results["Target Peserta Didik"] = extract_target_students(sections)
    
    if return_dict:
        return results
    else:
        return (
            results["Modul/Elemen Ajar"],
            results["Kompetensi Awal"],
            results["Tujuan Pembelajaran"],
            results["Pemahaman Bermakna"],
            results["Target Peserta Didik"]
        )


def split_document_into_sections(content_text):
    """
    Split document into logical sections based on headers and structure.
    Returns a dictionary with section names as keys and content as values.
    """
    sections = {}
    lines = content_text.split('\n')
    current_section = None
    current_content = []
    
    for line in lines:
        line_clean = line.strip()
        
        # Skip empty lines
        if not line_clean:
            continue
            
        # Check for major section headers (Roman numerals, numbers, or bold text)
        if is_section_header(line_clean):
            # Save previous section
            if current_section and current_content:
                sections[current_section] = '\n'.join(current_content)
            
            # Start new section
            current_section = normalize_section_name(line_clean)
            current_content = []
        else:
            # Add content to current section
            if current_section:
                current_content.append(line_clean)
    
    # Don't forget the last section
    if current_section and current_content:
        sections[current_section] = '\n'.join(current_content)
    
    return sections


def is_section_header(line):
    """Check if a line is likely a section header."""
    line_lower = line.lower()
    
    # Roman numeral patterns
    roman_pattern = r'^[ivxlcdm]+\.\s*'
    
    # Number patterns  
    number_pattern = r'^\d+\.\s*'
    
    # Bold text patterns (** or uppercase)
    bold_pattern = r'^\*\*.*\*\*$'
    uppercase_pattern = r'^[A-Z\s]{3,}$'
    
    return (re.match(roman_pattern, line_lower) or 
            re.match(number_pattern, line) or
            re.match(bold_pattern, line) or
            re.match(uppercase_pattern, line))


def normalize_section_name(header):
    """Normalize section header to standard format."""
    # Remove numbering, asterisks, and extra spaces
    normalized = re.sub(r'^[ivxlcdm]*\.?\s*', '', header, flags=re.IGNORECASE)
    normalized = re.sub(r'^\d+\.?\s*', '', normalized)
    normalized = re.sub(r'^\*\*|\*\*$', '', normalized)
    return normalized.strip().lower()


def extract_module_elements(sections):
    """Extract module/subject matter elements, excluding administrative info."""
    
    # Target sections that contain actual learning content
    target_sections = [
        'komponen inti', 'tujuan pembelajaran', 'pemahaman bermakna',
        'kegiatan pembelajaran', 'materi pembelajaran', 'isi pembelajaran'
    ]
    
    # Avoid these administrative sections
    avoid_sections = [
        'informasi umum', 'identitas modul', 'sarana dan prasarana',
        'model pembelajaran', 'refleksi guru', 'lampiran', 'daftar pustaka'
    ]
    
    content_parts = []
    
    for section_name, section_content in sections.items():
        section_lower = section_name.lower()
        
        # Skip administrative sections
        if any(avoid in section_lower for avoid in avoid_sections):
            continue
            
        # Include target sections or sections with learning keywords
        if (any(target in section_lower for target in target_sections) or
            has_learning_content_keywords(section_content)):
            
            # Extract key learning topics/concepts
            topics = extract_learning_topics(section_content)
            if topics:
                content_parts.extend(topics)
    
    if content_parts:
        return '; '.join(content_parts[:5])  # Limit to 5 main topics
    
    return "Tidak tersedia"


def extract_initial_competencies(sections):
    """Extract initial competencies with high precision."""
    
    for section_name, section_content in sections.items():
        section_lower = section_name.lower()
        
        # Look specifically for competency sections
        if ('kompetensi awal' in section_lower or 
            'kemampuan awal' in section_lower or
            'prasyarat' in section_lower):
            
            return clean_competency_text(section_content)
    
    # If no dedicated section found, look for competency mentions in content
    for section_name, section_content in sections.items():
        if 'kompetensi' in section_content.lower():
            competency_sentences = extract_competency_sentences(section_content)
            if competency_sentences:
                return '; '.join(competency_sentences[:3])
    
    return "Tidak tersedia"


def extract_learning_objectives(sections):
    """Extract learning objectives with precision."""
    
    for section_name, section_content in sections.items():
        section_lower = section_name.lower()
        
        # Target objective sections specifically
        if ('tujuan pembelajaran' in section_lower or
            'capaian pembelajaran' in section_lower or
            'learning objective' in section_lower):
            
            objectives = extract_bulleted_items(section_content)
            if objectives:
                return '; '.join(objectives[:6])  # Limit to 6 main objectives
            else:
                return clean_extracted_text(section_content)
    
    return "Tidak tersedia"


def extract_meaningful_understanding(sections):
    """Extract meaningful understanding components."""
    
    for section_name, section_content in sections.items():
        section_lower = section_name.lower()
        
        if ('pemahaman bermakna' in section_lower or
            'meaningful understanding' in section_lower):
            
            understanding_items = extract_bulleted_items(section_content)
            if understanding_items:
                return '; '.join(understanding_items[:4])
            else:
                return clean_extracted_text(section_content)
    
    return "Tidak tersedia"


def extract_target_students(sections):
    """Extract target student characteristics."""
    
    for section_name, section_content in sections.items():
        section_lower = section_name.lower()
        
        if ('target peserta didik' in section_lower or
            'sasaran peserta' in section_lower or
            'karakteristik peserta' in section_lower):
            
            return clean_extracted_text(section_content)
    
    return "Tidak tersedia"


def has_learning_content_keywords(text):
    """Check if text contains learning content keywords."""
    learning_keywords = [
        'algoritma', 'pemrograman', 'variabel', 'fungsi', 'struktur kontrol',
        'diagram alir', 'pseudokode', 'bahasa c', 'ekspresi', 'perulangan'
    ]
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in learning_keywords)


def extract_learning_topics(text):
    """Extract main learning topics from text."""
    topics = []
    
    # Look for common topic indicators
    topic_patterns = [
        r'mempelajari\s+([^.]+)',
        r'memahami\s+([^.]+)', 
        r'menguasai\s+([^.]+)',
        r'konsep\s+([^.]+)',
        r'materi\s+([^.]+)'
    ]
    
    for pattern in topic_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        topics.extend([match.strip() for match in matches])
    
    # Remove duplicates and clean
    unique_topics = []
    for topic in topics:
        cleaned_topic = clean_topic_text(topic)
        if cleaned_topic and cleaned_topic not in unique_topics:
            unique_topics.append(cleaned_topic)
    
    return unique_topics[:5]  # Limit to 5 topics


def extract_bulleted_items(text):
    """Extract bulleted or numbered items from text."""
    items = []
    
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        
        # Check for bullet points or numbers
        if (re.match(r'^[-•*]\s+', line) or 
            re.match(r'^\d+[\.)]\s+', line)):
            
            # Clean the item
            item = re.sub(r'^[-•*\d\.)]\s+', '', line)
            if item and len(item) > 10:  # Ensure meaningful content
                items.append(item.strip())
    
    return items


def extract_competency_sentences(text):
    """Extract sentences that describe competencies."""
    sentences = re.split(r'[.!?]+', text)
    competency_sentences = []
    
    competency_keywords = [
        'mampu', 'dapat', 'menguasai', 'memahami', 'menerapkan',
        'menganalisis', 'mengevaluasi', 'menciptakan'
    ]
    
    for sentence in sentences:
        sentence = sentence.strip()
        if (any(keyword in sentence.lower() for keyword in competency_keywords) and
            len(sentence) > 20):  # Ensure meaningful length
            competency_sentences.append(sentence)
    
    return competency_sentences


def clean_competency_text(text):
    """Clean competency text by removing administrative noise."""
    # Remove common administrative phrases
    admin_phrases = [
        r'materi pada unit.*berkaitan dengan',
        r'dalam unit.*siswa diajarkan',
        r'lewat unit ini.*diimplementasikan',
        r'dengan demikian.*untuk menghasilkan'
    ]
    
    cleaned = text
    for phrase in admin_phrases:
        cleaned = re.sub(phrase, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    
    return clean_extracted_text(cleaned)


def clean_topic_text(topic):
    """Clean extracted topic text."""
    # Remove common noise words and phrases
    topic = re.sub(r'\b(dengan|untuk|dalam|pada|yang|dari|dan|atau)\b', ' ', topic, flags=re.IGNORECASE)
    topic = re.sub(r'\s+', ' ', topic)
    topic = topic.strip()
    
    # Only return if meaningful length
    return topic if len(topic) > 5 else None


def clean_extracted_text(text):
    """Enhanced text cleaning function."""
    if not text or text.strip() == "":
        return "Tidak tersedia"
    
    # Remove administrative noise patterns
    noise_patterns = [
        r'lampiran.*$',
        r'daftar pustaka.*$', 
        r'referensi.*$',
        r'halaman \d+',
        r'gambar \d+',
        r'tabel \d+',
        r'^[\d\.\-\•○●]\s*',  # Remove bullet points at start
        r'\*\*([^*]+)\*\*',   # Remove bold markers
    ]
    
    cleaned = text
    for pattern in noise_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE | re.IGNORECASE)
    
    # Clean up whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip()
    
    # Return first few sentences if too long
    sentences = re.split(r'[.!?]+', cleaned)
    if len(sentences) > 5:
        cleaned = '. '.join(sentences[:5]) + '.'
    
    return cleaned if cleaned else "Tidak tersedia"

def extract_text_from_docx(file_path):
    """Extract text from a Word document (.doc or .docx)"""
    try:
        if file_path.endswith('.docx'):
            doc = Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            
            # Also extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        row_text.append(cell.text.strip())
                    text += "\t".join(row_text) + "\n"
            return text
        else:  # For .doc files
            with open(file_path, "rb") as docx_file:
                result = mammoth.extract_raw_text(docx_file)
                return result.value
    except Exception as e:
        print(f"Error extracting text from Word document: {str(e)}")
        raise

def convert_text_to_dataframe_improved(text):
    """Improved function to convert extracted text to a dataframe"""
    try:
        # Split text into lines for processing
        lines = text.split('\n')
        
        # Filter out empty lines
        lines = [line.strip() for line in lines if line.strip()]
        
        # Look for table-like patterns in the text
        table_lines = []
        
        # Check each line for tab separators or multiple spaces indicating tabular data
        for line in lines:
            if '\t' in line or re.search(r'\s{2,}', line):
                table_lines.append(line)
        
        if table_lines:
            # Create a temporary file to process the data
            with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.tsv', encoding='utf-8') as temp_file:
                for line in table_lines:
                    # Normalize spaces and tabs
                    normalized_line = re.sub(r'\s{2,}', '\t', line)
                    temp_file.write(normalized_line + '\n')
            
            try:
                # Try reading the file as a tab-separated values file
                df = pd.read_csv(temp_file.name, sep='\t', on_bad_lines='skip', encoding='utf-8')  # Updated from error_bad_lines
                os.unlink(temp_file.name)
                return df
            except Exception as e:
                # If that fails, try a different approach with more robust error handling
                print(f"First attempt at parsing failed: {str(e)}")
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
                
                # Try an alternative approach using pandas read_fwf (fixed width format)
                with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt', encoding='utf-8') as temp_file:
                    for line in table_lines:
                        temp_file.write(line + '\n')
                
                try:
                    # Try to infer the fixed width format
                    df = pd.read_fwf(temp_file.name, encoding='utf-8')
                    os.unlink(temp_file.name)
                    return df
                except Exception as e2:
                    print(f"Fixed width parsing failed: {str(e2)}")
                    os.unlink(temp_file.name)
                    
                    # Final fallback: create a simple dataframe with lines as rows
                    data = {"line": table_lines}
                    return pd.DataFrame(data)
        
        # If no tabular data found, return a dataframe with the content
        return pd.DataFrame({"content": [text]})
            
    except Exception as e:
        print(f"Error converting text to dataframe: {str(e)}")
        # Return an empty dataframe as fallback
        return pd.DataFrame()
    
# =========================================
# GET QUESTION (per level)
# =========================================
@app.route('/get_question', methods=['GET'])
def get_question():
    user_id = request.args.get("user_id", "default")
    collection_id = request.args.get("collection_id")  # Ambil collection_id dari parameter URL
    print(f"Get question untuk user_id: {user_id}")
    
    try:
        # Validasi input
        if not collection_id:
            return jsonify({
                "status": "error",
                "message": "Collection ID tidak ditemukan dalam URL!"
            }), 400
            
        # Konversi user_id menjadi integer jika bukan "default"
        siswa_id = int(user_id) if user_id != "default" else None
        
        if siswa_id is None:
            return jsonify({
                "status": "error",
                "message": "Invalid user ID. Please login properly."
            }), 400
            
        # Verifikasi akses siswa ke collection
        has_access = db.session.query(collection_students).filter_by(
            collection_id=collection_id,  
            siswa_id=siswa_id
        ).first() is not None
        
        if not has_access:
            return jsonify({
                "status": "error",
                "message": "Anda tidak memiliki akses ke koleksi soal ini."
            }), 403
            
        # Cari hasil siswa berdasarkan siswa_id DAN collection_id
        user_result = SiswaResult.query.filter_by(
            siswa_id=siswa_id,
            collection_id=collection_id
        ).first()
        
        # Jika tidak ditemukan, buat baru
        if not user_result:
            print(f"Membuat user result baru untuk siswa_id: {siswa_id} dan collection_id: {collection_id}")
            
            # Cek apakah siswa ada
            siswa = db.session.query(Siswa).filter_by(id=siswa_id).first()
            if not siswa:
                return jsonify({
                    "status": "error",
                    "message": "Siswa tidak ditemukan"
                }), 404
                
            # Buat record baru
            user_result = SiswaResult(
                siswa_id=siswa_id,
                collection_id=int(collection_id),
                current_level=1
            )
            db.session.add(user_result)
            db.session.commit()

        current_level = user_result.current_level
        print(f"Level saat ini: {current_level}")
        
        # PERBAIKAN: Ambil soal dari database berdasarkan level, collection_id, DAN is_validated
        # Gunakan CollectionQuestion untuk memastikan soal adalah bagian dari collection
        questions = db.session.query(Question).join(
            CollectionQuestion,  
            CollectionQuestion.question_id == Question.id
        ).filter(
            Question.level == current_level,
            CollectionQuestion.collection_id == int(collection_id),
            Question.is_validated == True  # <--- INI TAMBAHANNYA
        ).all()
        
        print(f"Ditemukan {len(questions)} soal yang divalidasi untuk level {current_level} dalam koleksi {collection_id}")
        
        if not questions:
            # Jika tidak ada soal yang ditemukan
            return jsonify({
                "status": "error",  
                "message": f"Tidak ada soal yang tervalidasi tersedia untuk level {current_level} dalam koleksi ini."
            }), 200

        # Pilih soal secara acak
        question = random.choice(questions)
        print(f"Soal dipilih ID: {question.id}")
        
        # Parse opsi jika soal memiliki opsi dalam format JSON
        options = []
        if hasattr(question, 'options') and question.options:
            try:
                options = json.loads(question.options)
            except:
                options = []
        
        response_data = {
            "id": question.id,
            "level": question.level,
            "question": question.soal,
            "options": options,
            "question_type": question.question_type or "multiple_choice",
            "bobot": question.bobot,
            "p": question.p,
            "explanation": question.explanation,
            "jawaban_benar": question.jawaban_benar if question.question_type == 'multiple_choice' else None
        }
        
        # Mengirimkan soal ke frontend
        return jsonify(response_data), 200
        
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "Format ID tidak valid"
        }), 400
        
    except Exception as e:
        print(f"Error di get_question: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Kesalahan server: {str(e)}"
        }), 500
# =========================================
# SUBMIT ANSWER
# =========================================
@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    data = request.json
    user_id = data.get("user_id", "default")
    answer = data.get("answer", "").strip()
    question_id = data.get("question_id")
    collection_id = data.get("collection_id")  # Ambil collection_id dari request
    
    print(f"Submit jawaban untuk user_id: {user_id}, jawaban: {answer[:50]}..., question_id: {question_id}, collection_id: {collection_id}")

    # Cari atau buat user result
    # PERBAIKAN: Filter berdasarkan collection_id juga
    user_result = SiswaResult.query.filter_by(siswa_id=user_id, collection_id=collection_id).first()
    if not user_result:
        print(f"Membuat user result baru untuk {user_id} pada collection {collection_id}")
        user_result = SiswaResult(
            siswa_id=user_id,
            collection_id=collection_id,  # Tambahkan collection_id
            correct=0,
            incorrect=0,
            current_level=1
        )
        db.session.add(user_result)
        db.session.commit()

    current_level = user_result.current_level
    print(f"Current level: {current_level}")
    
    # Dapatkan pertanyaan berdasarkan question_id
    if question_id:
        try:
            question = Question.query.get(int(question_id))
            if not question:
                return jsonify({"status": "error", "message": f"Soal dengan ID {question_id} tidak ditemukan."}), 404
        except Exception as e:
            print(f"Error mendapatkan soal dengan ID {question_id}: {str(e)}")
            return jsonify({"status": "error", "message": f"Error: {str(e)}"}), 500
    else:
        # Ambil soal yang terkait dengan koleksi
        questions = db.session.query(Question).join(
            CollectionQuestion, 
            CollectionQuestion.question_id == Question.id
        ).filter(
            Question.level == current_level,
            CollectionQuestion.collection_id == collection_id
        ).all()
        
        if not questions:
            return jsonify({"status": "game over", "message": f"Tidak ada soal untuk level {current_level} dalam koleksi ini."}), 200
        question = random.choice(questions)
    
    soal_text = question.soal
    print(f"Evaluasi jawaban untuk soal: {soal_text}")
    
    # Parse opsi jawaban
    options = []
    if hasattr(question, 'options') and question.options:
        try:
            options = json.loads(question.options)
        except:
            options = []
    
    # Evaluasi jawaban pilihan ganda dengan membandingkan dengan jawaban benar
    correct = is_answer_correct(answer, question.jawaban_benar)
    print(f"Hasil evaluasi pilihan ganda: {'Benar' if correct else 'Salah'}")

    # Simpan jawaban user ke database
    user_answer = SiswaAnswer(
        siswa_id=user_id,
        question_id=question.id,
        siswa_answer=answer,
        is_correct=correct,
        level=current_level
    )
    db.session.add(user_answer)

    # Update statistik
    if correct:
        user_result.correct += 1
        print(f"Jawaban benar. Total benar: {user_result.correct}")
        
        # Tentukan level selanjutnya jika jawaban benar
        if current_level in FINAL_levelS:
            # Jika sudah di level final, selesai
            status_message = f"Anda telah menyelesaikan semua level! level terakhir: {current_level}."
            db.session.commit()
            return jsonify({
                "status": "win", 
                "message": status_message,
                "explanation": question.explanation
            }), 200
        else:
            # Jika belum di level final, tentukan level selanjutnya untuk jawaban benar
            nxt = next_level(current_level, True)  # Passing is_correct=True
            print(f"level berikutnya: {nxt}")
            
            if nxt is None:
                db.session.commit()
                return jsonify({
                    "status": "win", 
                    "message": f"Anda telah menyelesaikan semua level!",
                    "explanation": question.explanation
                }), 200

            user_result.current_level = nxt
            db.session.commit()
            print(f"Database diperbarui: user pindah ke level {nxt}")

            return jsonify({
                "status": "continue", 
                "message": f"Jawaban benar! Lanjut ke level {nxt}",
                "explanation": question.explanation
            }), 200
    else:
        # Jika jawaban salah
        user_result.incorrect += 1
        print(f"Jawaban salah. Total salah: {user_result.incorrect}")
        
        # Tentukan level selanjutnya berdasarkan jawaban salah
        if current_level in FINAL_levelS:
            # Jika sudah di level final, selesai
            db.session.commit()
            return jsonify({
                "status": "game over", 
                "message": f"Game over! Anda telah menyelesaikan semua level dengan jawaban salah pada level {current_level}.",
                "explanation": question.explanation
            }), 200
        else:
            # Tentukan level selanjutnya berdasarkan jawaban salah
            next_level_if_wrong = next_level(current_level, False)  # Passing is_correct=False
            
            if next_level_if_wrong:
                user_result.current_level = next_level_if_wrong
                db.session.commit()
                print(f"Database diperbarui: karena salah, user pindah ke level {next_level_if_wrong}")
                
                if next_level_if_wrong in FINAL_levelS:
                    return jsonify({
                        "status": "continue", 
                        "message": f"Jawaban salah. Lanjut ke level final {next_level_if_wrong}.",
                        "explanation": question.explanation
                    }), 200
                else:
                    return jsonify({
                        "status": "continue", 
                        "message": f"Jawaban salah. Lanjut ke level {next_level_if_wrong}.",
                        "explanation": question.explanation
                    }), 200
            else:
                db.session.commit()
                return jsonify({
                    "status": "wrong", 
                    "message": "Jawaban salah. Silakan coba lagi.",
                    "explanation": question.explanation
                }), 200

# =========================================
# GET SUMMARY
# =========================================
@app.route('/get_summary', methods=['GET'])
def get_summary():
    user_id = request.args.get("user_id", "default")
    
    # Konversi user_id menjadi integer jika bukan "default"
    try:
        user_id = int(user_id) if user_id != "default" else None
    except ValueError:
        user_id = None
    
    if user_id is None:
        return jsonify({
            "status": "error", 
            "message": "ID pengguna tidak valid",
        }), 400
    
    try:
        # Ambil data hasil siswa
        user_result = SiswaResult.query.filter_by(siswa_id=user_id).first()
        if not user_result:
            # Return initial data instead of error
            return jsonify({
                "status": "success",
                "correct": 0,
                "incorrect": 0,
                "total_tests": 0,
                "completed_tests": 0
            }), 200
        
        # Hitung jumlah tes yang tersedia untuk siswa ini
        total_tests = db.session.query(func.count(collection_students.c.collection_id)).filter(
            collection_students.c.siswa_id == user_id
        ).scalar() or 0
        
        # Hitung jumlah tes yang sudah selesai
        # Tes selesai jika level saat ini adalah level final (5, 6, 7)
        completed_tests = SiswaResult.query.filter(
            SiswaResult.siswa_id == user_id,
            SiswaResult.current_level.in_([5, 6, 7])
        ).count()
        
        # Hitung jumlah jawaban benar dan salah
        total_correct = user_result.correct or 0
        total_incorrect = user_result.incorrect or 0
        
        return jsonify({
            "status": "success",
            "correct": total_correct,
            "incorrect": total_incorrect,
            "total_tests": total_tests,
            "completed_tests": completed_tests
        }), 200
    
    except Exception as e:
        print(f"Error getting summary: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500
    
@app.route("/get_questions", methods=["GET"])
@login_required # Pastikan hanya user yang login yang bisa mengakses
def get_questions():
    try:
        print("Fetching questions from database...")
        # Ambil semua soal yang dimiliki oleh guru yang sedang login
        # Gunakan SQLAlchemy ORM daripada raw SQL untuk filter ini
        questions_raw = (
            Question.query
            .filter_by(guru_id=current_user.id, is_current=True)
            .order_by(Question.level.asc(), Question.id.asc())
            .all()
        )
        
        print(f"Fetched {len(questions_raw)} questions for guru_id {current_user.id}")
        
        questions_data = []
        for q in questions_raw:
            options = []
            if q.options:
                try:
                    options = json.loads(q.options)
                except json.JSONDecodeError:
                    pass # Abaikan jika tidak valid JSON
            
            questions_data.append({
                "id": q.id,
                "guru_id": q.guru_id,
                "collection_id": q.collection_id,
                "level": q.level,
                "soal": q.soal,
                "jawaban_benar": q.jawaban_benar,
                "options": options,
                "question_type": q.question_type,
                "p": float(q.p),
                "bobot": q.bobot,
                "explanation": q.explanation,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "version": q.version,
                "is_current": q.is_current,
                "is_validated": q.is_validated 
            })
            
        print(f"Successfully formatted {len(questions_data)} questions for response")
        return jsonify({"success": True, "data": questions_data})
        
    except Exception as e:
        print(f"Error getting questions: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500
    
@app.route("/api/check_questions_count", methods=["GET"])
@login_required
def check_questions_count():
    # Hanya guru yang bisa melihat ini
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        return jsonify({"success": False, "message": "Akses ditolak."}), 403

    try:
        # Hitung soal milik guru yang sedang login
        total_count = db.session.query(db.func.count(Question.id)).filter_by(guru_id=current_user.id).scalar()
        
        # Hitung berdasarkan level milik guru yang sedang login
        level_counts = db.session.query(
            Question.level,  
            db.func.count(Question.id)
        ).filter_by(guru_id=current_user.id).group_by(Question.level).all()
        
        level_distribution = {str(level): count for level, count in level_counts}
        
        return jsonify({
            "success": True,
            "totalQuestions": total_count,
            "levelDistribution": level_distribution,
            "queryTime": 0
        })
    except Exception as e:
        print(f"Error checking questions count: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Error checking database: {str(e)}"
        }), 500
    
@app.route("/api/db_check", methods=["GET"])
def db_check():
    try:
        from sqlalchemy import text
        
        # Hitung total soal
        result = db.session.execute(text("SELECT COUNT(*) FROM questions"))
        total = result.scalar()
        
        # Hitung soal per level
        result = db.session.execute(text("SELECT level, COUNT(*) FROM questions GROUP BY level"))
        level_counts = {row[0]: row[1] for row in result}
        
        # Ambil sampel soal
        result = db.session.execute(text("SELECT id, level, soal FROM questions LIMIT 5"))
        samples = [{"id": row[0], "level": row[1], "soal": row[2]} for row in result]
        
        return jsonify({
            "success": True,
            "total_questions": total,
            "per_level": level_counts,
            "samples": samples
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
    
@app.route("/api/table_structure", methods=["GET"])
def check_table_structure():
    try:
        from sqlalchemy import text
        
        # Cek struktur tabel questions
        result = db.session.execute(text("DESCRIBE questions"))
        columns = [dict(row._mapping) for row in result]
        
        # Cek foreign key constraints
        result = db.session.execute(text("SELECT * FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE WHERE TABLE_NAME = 'questions'"))
        constraints = [dict(row._mapping) for row in result]
        
        return jsonify({
            "success": True,
            "table_structure": columns,
            "constraints": constraints
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
    
@app.route('/api/collections', methods=['GET'])
@login_required
def get_collections():
    # Ambil semua koleksi milik guru
    collections = QuestionCollection.query.filter_by(guru_id=current_user.id).all()
    
    result = []
    for collection in collections:
        # Hitung jumlah soal di tiap koleksi
        question_count = db.session.query(CollectionQuestion).filter_by(collection_id=collection.id).count()
        
        result.append({
            'id': collection.id,
            'name': collection.name,
            'description': collection.description,
            'question_count': question_count,
            'created_at': collection.created_at.isoformat() if collection.created_at else None
        })
    
    return jsonify({'success': True, 'collections': result})

@app.route('/api/collections', methods=['POST'])
@login_required
def create_collection():
    data = request.json
    
    # Validasi data
    if not data.get('name'):
        return jsonify({'success': False, 'message': 'Nama koleksi harus diisi'}), 400
    
    # Cek apakah nama koleksi sudah ada untuk guru ini
    existing_collection = QuestionCollection.query.filter_by(
        guru_id=current_user.id,
        name=data.get('name')
    ).first()
    
    if existing_collection:
        app.logger.warning(f"Attempt to create duplicate collection '{data.get('name')}' for guru {current_user.id}")
        return jsonify({
            'success': False, 
            'message': f'Koleksi dengan nama "{data.get("name")}" sudah ada. Silakan gunakan nama yang berbeda.'
        }), 400
    
    # Buat koleksi baru
    collection = QuestionCollection(
        guru_id=current_user.id,
        name=data.get('name'),
        description=data.get('description', '')
    )
    
    db.session.add(collection)
    db.session.commit()
    
    # Tambahkan soal ke koleksi jika ada
    if data.get('question_ids') and isinstance(data.get('question_ids'), list):
        for question_id in data.get('question_ids'):
            # Validasi bahwa soal ada
            question = Question.query.get(question_id)
            if question:
                collection_question = CollectionQuestion(
                    collection_id=collection.id,
                    question_id=question_id
                )
                db.session.add(collection_question)
        
        db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': 'Koleksi berhasil dibuat', 
        'collection_id': collection.id
    })

@app.route('/api/collections/check-name', methods=['POST'])
@login_required
def check_collection_name():
    """Endpoint untuk memeriksa apakah nama koleksi sudah ada"""
    data = request.json
    
    if not data.get('name'):
        return jsonify({'success': False, 'message': 'Nama koleksi harus diisi'}), 400
    
    # Cek apakah nama koleksi sudah ada untuk guru ini
    existing_collection = QuestionCollection.query.filter_by(
        guru_id=current_user.id,
        name=data.get('name')
    ).first()
    
    # Log untuk debugging
    app.logger.info(f"Checking collection name '{data.get('name')}' for guru {current_user.id}: {'exists' if existing_collection else 'available'}")
    
    return jsonify({
        'success': True,
        'exists': existing_collection is not None,
        'message': 'Nama sudah digunakan' if existing_collection else 'Nama tersedia'
    })

@app.route('/api/collections/<int:collection_id>/details', methods=['GET'])
@login_required
def get_collection_details_for_student(collection_id):
    try:
        # Cek apakah siswa memiliki akses ke koleksi ini
        has_access = db.session.query(collection_students).filter_by(
            collection_id=collection_id, 
            siswa_id=current_user.id
        ).first() is not None
        
        if not has_access:
            return jsonify({'success': False, 'message': 'Anda tidak memiliki akses ke koleksi ini'}), 403
        
        # Ambil detail koleksi
        collection = QuestionCollection.query.get(collection_id)
        if not collection:
            return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
        
        # Ambil info tentang guru
        guru = Guru.query.get(collection.guru_id)
        
        # Ambil progress siswa untuk koleksi ini
        progress = SiswaResult.query.filter_by(
            siswa_id=current_user.id,
            collection_id=collection_id
        ).first()
        
        result = {
            'success': True,
            'collection': {
                'id': collection.id,
                'name': collection.name,
                'description': collection.description,
                'created_at': collection.created_at.isoformat() if collection.created_at else None
            },
            'guru': {
                'id': guru.id,
                'nama': guru.nama,
                'email': guru.email
            },
            'progress': {
                'current_level': progress.current_level if progress else 1,
                'correct': progress.correct if progress else 0,
                'incorrect': progress.incorrect if progress else 0,
                'is_completed': progress.current_level in [5, 6, 7] if progress else False
            }
        }
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error getting collection details: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@app.route('/api/collections/<int:collection_id>/questions', methods=['GET'])
@login_required
def get_collection_questions(collection_id):
    # Verifikasi kepemilikan koleksi
    collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
    if not collection:
        return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
    
    # Ambil soal dari koleksi dengan join
    questions = db.session.query(Question).join(
        CollectionQuestion, CollectionQuestion.question_id == Question.id
    ).filter(
        CollectionQuestion.collection_id == collection_id
    ).all()
    
    # Format soal untuk response
    question_data = []
    for q in questions:
        options = []
        if hasattr(q, 'options') and q.options:
            try:
                options = json.loads(q.options)
            except:
                options = []
        
        question_data.append({
            'id': q.id,
            'level': q.level,
            'soal': q.soal,
            'jawaban_benar': q.jawaban_benar,
            'options': options,
            'question_type': q.question_type if hasattr(q, 'question_type') else 'multiple_choice',
            'p': float(q.p) if q.p else 0.5,
            'bobot': q.bobot or 1,
            'explanation': q.explanation or '',
            'is_validated': q.is_validated # NEW: Sertakan status validasi
        })
    
    return jsonify({
        'success': True, 
        'collection': {
            'id': collection.id,
            'name': collection.name,
            'description': collection.description
        },
        'questions': question_data
    })


@app.route('/api/collections/<int:collection_id>/questions', methods=['POST'])
@login_required
def add_questions_to_collection(collection_id):
    # Verifikasi kepemilikan koleksi
    collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
    if not collection:
        return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
    
    data = request.json
    question_ids = data.get('question_ids', [])
    
    # Validasi data
    if not question_ids or not isinstance(question_ids, list):
        return jsonify({'success': False, 'message': 'ID soal tidak valid'}), 400
    
    # Tambahkan soal ke koleksi
    added_count = 0
    for question_id in question_ids:
        # Cek apakah soal sudah ada di koleksi
        existing = CollectionQuestion.query.filter_by(
            collection_id=collection_id, 
            question_id=question_id
        ).first()
        
        if not existing:
            # Cek apakah soal ada
            question = Question.query.get(question_id)
            if question:
                collection_question = CollectionQuestion(
                    collection_id=collection_id,
                    question_id=question_id
                )
                db.session.add(collection_question)
                added_count += 1
    
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': f'{added_count} soal berhasil ditambahkan ke koleksi'
    })

@app.route('/api/collections/<int:collection_id>/description', methods=['PUT'])
@login_required
def update_collection_description(collection_id):
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    try:
        # Validate input
        data = request.json
        if not data or 'description' not in data:
            return jsonify({"success": False, "message": "Description is required"}), 400
            
        # Get collection and ensure it belongs to the current teacher
        collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
        
        if not collection:
            return jsonify({"success": False, "message": "Koleksi tidak ditemukan"}), 404
        
        # Update description
        collection.description = data['description']
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": "Deskripsi koleksi berhasil diperbarui",
            "collection": {
                "id": collection.id,
                "name": collection.name,
                "description": collection.description
            }
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/collections/<int:collection_id>', methods=['DELETE'])
@login_required
def delete_collection(collection_id):
    # Verifikasi kepemilikan koleksi
    collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
    if not collection:
        return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
    
    # Hapus semua relasi collection_questions terlebih dahulu
    CollectionQuestion.query.filter_by(collection_id=collection_id).delete()
    
    # Hapus koleksi
    db.session.delete(collection)
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': 'Koleksi berhasil dihapus'
    })

# Endpoint untuk menghapus soal dari koleksi
@app.route('/api/collections/<int:collection_id>/questions/<int:question_id>', methods=['DELETE'])
@login_required
def delete_question_from_collection(collection_id, question_id):
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    try:
        # Verifikasi koleksi milik guru yang sedang login
        collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
        if not collection:
            return jsonify({"success": False, "message": "Koleksi tidak ditemukan"}), 404
        
        # Verifikasi soal milik guru yang sedang login
        question = Question.query.filter_by(id=question_id, guru_id=current_user.id).first()
        if not question:
            return jsonify({"success": False, "message": "Soal tidak ditemukan"}), 404
        
        # Cek apakah ada jawaban siswa untuk soal ini
        student_answers_count = SiswaAnswer.query.filter_by(question_id=question_id).count()
        
        if student_answers_count > 0:
            # Jika ada jawaban siswa, hanya hapus dari koleksi, jangan hapus soal
            collection_question = CollectionQuestion.query.filter_by(
                collection_id=collection_id, 
                question_id=question_id
            ).first()
            
            if not collection_question:
                return jsonify({"success": False, "message": "Soal tidak ada dalam koleksi ini"}), 404
            
            # Hapus relasi dari koleksi saja
            db.session.delete(collection_question)
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": f"Soal berhasil dihapus dari koleksi. Soal tidak dihapus dari database karena sudah ada {student_answers_count} jawaban siswa."
            })
        
        # Jika tidak ada jawaban siswa, lanjutkan dengan penghapusan normal
        collection_question = CollectionQuestion.query.filter_by(
            collection_id=collection_id, 
            question_id=question_id
        ).first()
        
        if not collection_question:
            return jsonify({"success": False, "message": "Soal tidak ada dalam koleksi ini"}), 404
        
        # Hapus relasi dari koleksi
        db.session.delete(collection_question)
        
        # Cek apakah soal ini masih digunakan di koleksi lain
        other_collections = CollectionQuestion.query.filter_by(question_id=question_id).count()
        
        if other_collections == 0:
            # Jika soal tidak digunakan di koleksi lain dan tidak ada jawaban siswa, hapus soal dari database
            # Hapus semua versi soal terlebih dahulu
            QuestionVersion.query.filter_by(question_id=question_id).delete()
            
            # Hapus soal utama
            db.session.delete(question)
            message = "Soal berhasil dihapus dari koleksi dan database (tidak digunakan di koleksi lain dan tidak ada jawaban siswa)"
        else:
            message = "Soal berhasil dihapus dari koleksi (masih digunakan di koleksi lain)"
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": message
        })
    
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting question from collection: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

# Endpoint untuk memvalidasi semua soal dalam koleksi
@app.route('/api/collections/<int:collection_id>/validate-all', methods=['POST'])
@login_required
def validate_all_questions(collection_id):
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        return jsonify({"success": False, "message": "Unauthorized"}), 403
    
    try:
        # Get collection and ensure it belongs to the current teacher
        collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
        
        if not collection:
            return jsonify({"success": False, "message": "Koleksi tidak ditemukan"}), 404
        
        # Get all questions in this collection
        collection_questions = CollectionQuestion.query.filter_by(collection_id=collection_id).all()
        question_ids = [cq.question_id for cq in collection_questions]
        
        # Update validation status of all questions
        questions = Question.query.filter(Question.id.in_(question_ids)).all()
        validated_ids = []
        
        for question in questions:
            question.is_validated = True
            validated_ids.append(question.id)
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": f"{len(validated_ids)} soal berhasil divalidasi",
            "count": len(validated_ids),
            "validated": validated_ids
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# Mendapatkan siswa yang memiliki akses ke koleksi
@app.route('/api/collections/<int:collection_id>/students', methods=['GET'])
@login_required
def get_collection_students(collection_id):
    try:
        # Verifikasi kepemilikan koleksi
        collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
        if not collection:
            return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
        
        # Dapatkan siswa yang memiliki akses ke koleksi ini
        students = db.session.query(Siswa).join(
            collection_students,
            collection_students.c.siswa_id == Siswa.id
        ).filter(
            collection_students.c.collection_id == collection_id
        ).all()
        
        # Format data siswa
        students_data = []
        for student in students:
            students_data.append({
                'id': student.id,
                'nama': student.nama,
                'username': student.username,
                'kelas': student.kelas
            })
        
        return jsonify({
            'success': True,
            'students': students_data
        })
        
    except Exception as e:
        print(f"Error getting collection students: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Menambahkan siswa ke koleksi
@app.route('/api/collections/<int:collection_id>/students', methods=['POST'])
@login_required
def add_student_to_collection(collection_id):
    try:
        # 1. Verifikasi koleksi dan kepemilikan
        collection = QuestionCollection.query.filter_by(
            id=collection_id, 
            guru_id=current_user.id
        ).first()
        
        if not collection:
            return jsonify({
                'success': False,
                'message': 'Koleksi tidak ditemukan atau akses ditolak'
            }), 404

        # 2. Validasi data request
        data = request.get_json()
        if not data or 'siswa_id' not in data:
            return jsonify({
                'success': False,
                'message': 'Data siswa tidak valid'
            }), 400

        siswa_id = data['siswa_id']

        # 3. Cek keberadaan siswa
        siswa = Siswa.query.get(siswa_id)
        if not siswa:
            return jsonify({
                'success': False,
                'message': 'Siswa tidak ditemukan'
            }), 404

        # 4. Cek duplikasi relasi
        existing = db.session.execute(
            collection_students.select().where(
                (collection_students.c.collection_id == collection_id) &
                (collection_students.c.siswa_id == siswa_id)
            )
        ).fetchone()

        if existing:
            return jsonify({
                'success': True,
                'message': 'Siswa sudah terdaftar dalam koleksi ini'
            })

        # 5. Tambahkan relasi
        db.session.execute(
            collection_students.insert().values(
                collection_id=collection_id,
                siswa_id=siswa_id
            )
        )

        # 6. Buat atau update hasil siswa
        siswa_result = SiswaResult.query.filter_by(
            siswa_id=siswa_id,
            collection_id=collection_id
        ).first()

        if not siswa_result:
            new_result = SiswaResult(
                siswa_id=siswa_id,
                collection_id=collection_id,
                current_level=1,
                correct=0,
                incorrect=0
            )
            db.session.add(new_result)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Siswa berhasil ditambahkan ke koleksi',
            'data': {
                'collection_id': collection_id,
                'siswa_id': siswa_id,
                'siswa_nama': siswa.nama,
                'collection_name': collection.name
            }
        })

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Terjadi kesalahan server'
        }), 500

# Menghapus siswa dari koleksi
@app.route('/api/collections/<int:collection_id>/students/<int:student_id>', methods=['DELETE'])
@login_required
def remove_student_from_collection(collection_id, student_id):
    try:
        # Verifikasi kepemilikan koleksi
        collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
        if not collection:
            return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
        
        # Hapus akses
        stmt = collection_students.delete().where(
            collection_students.c.collection_id == collection_id,
            collection_students.c.siswa_id == student_id
        )
        result = db.session.execute(stmt)
        db.session.commit()
        
        if result.rowcount == 0:
            return jsonify({'success': False, 'message': 'Siswa tidak memiliki akses ke koleksi ini'}), 404
        
        return jsonify({
            'success': True,
            'message': 'Akses siswa berhasil dihapus'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error removing student from collection: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/collections/<int:collection_id>/student-count', methods=['GET'])
def get_collection_student_count(collection_id):
    try:
        count = db.session.query(collection_students).filter_by(
            collection_id=collection_id
        ).count()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Mendapatkan daftar semua siswa
@app.route('/api/siswa', methods=['GET'])
@login_required
def get_all_students():
    try:
        if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
            return jsonify({'success': False, 'message': 'Akses ditolak. Hanya guru yang dapat mengakses daftar siswa.'}), 403
        
        kelas_filter = request.args.get('kelas') # NEW: Ambil parameter kelas untuk filter
        
        students_query = Siswa.query

        if kelas_filter and kelas_filter != 'all':
            students_query = students_query.filter_by(kelas=kelas_filter)

        students = students_query.order_by(Siswa.kelas, Siswa.nama).all() # Urutkan berdasarkan kelas dan nama
        
        students_data = []
        for student in students:
            students_data.append({
                'id': student.id,
                'nama': student.nama,
                'username': student.username,
                'kelas': student.kelas
            })
        
        # NEW: Ambil daftar kelas unik yang ada di database
        available_classes = db.session.query(Siswa.kelas).distinct().order_by(Siswa.kelas).all()
        available_classes = [cls[0] for cls in available_classes if cls[0]] # Filter out None/empty classes
        
        return jsonify({
            'success': True,
            'students': students_data,
            'available_classes': available_classes # Kirim daftar kelas yang tersedia
        })
        
    except Exception as e:
        print(f"Error getting all students: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
# Tambahkan endpoint baru untuk menambahkan siswa berdasarkan kelas
@app.route('/api/collections/<int:collection_id>/add_students_by_class', methods=['POST'])
@login_required
def add_students_by_class(collection_id):
    try:
        # 1. Verifikasi koleksi dan kepemilikan
        collection = QuestionCollection.query.filter_by(
            id=collection_id,
            guru_id=current_user.id
        ).first()

        if not collection:
            return jsonify({
                'success': False,
                'message': 'Koleksi tidak ditemukan atau akses ditolak'
            }), 404

        # 2. Validasi data request
        data = request.get_json()
        if not data or 'class_name' not in data:
            return jsonify({
                'success': False,
                'message': 'Nama kelas tidak valid'
            }), 400

        class_name = data['class_name']

        # 3. Dapatkan semua siswa di kelas tersebut yang belum terdaftar di koleksi ini
        students_to_add = Siswa.query.filter(
            Siswa.kelas == class_name,
            # Filter siswa yang belum ada di koleksi ini
            ~Siswa.id.in_(
                db.session.query(collection_students.c.siswa_id).filter(
                    collection_students.c.collection_id == collection_id
                )
            )
        ).all()

        added_count = 0
        if students_to_add:
            # 4. Tambahkan siswa ke koleksi dan buat/update SiswaResult mereka
            for student in students_to_add:
                # Tambahkan relasi ke collection_students
                db.session.execute(
                    collection_students.insert().values(
                        collection_id=collection_id,
                        siswa_id=student.id
                    )
                )

                # Buat atau update SiswaResult
                siswa_result = SiswaResult.query.filter_by(
                    siswa_id=student.id,
                    collection_id=collection_id
                ).first()

                if not siswa_result:
                    new_result = SiswaResult(
                        siswa_id=student.id,
                        collection_id=collection_id,
                        current_level=1,
                        correct=0,
                        incorrect=0
                    )
                    db.session.add(new_result)
                added_count += 1
            db.session.commit()

        return jsonify({
            'success': True,
            'message': f'{added_count} siswa dari kelas {class_name} berhasil ditambahkan ke koleksi.',
            'added_count': added_count
        }), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error adding students by class: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': 'Terjadi kesalahan server saat menambahkan siswa berdasarkan kelas'
        }), 500

@app.route('/api/siswa/collections', methods=['GET'])
@login_required
def get_student_collections():
    if not current_user.is_authenticated or not hasattr(current_user, 'user_type') or current_user.user_type != 'siswa':
        return jsonify({'success': False, 'message': 'Akses ditolak'}), 403
    
    try:
        # Ambil koleksi yang tersedia untuk siswa ini dari tabel relasi
        collections_query = db.session.query(
            QuestionCollection, Guru
        ).join(
            Guru, QuestionCollection.guru_id == Guru.id
        ).join(
            collection_students, collection_students.c.collection_id == QuestionCollection.id
        ).filter(
            collection_students.c.siswa_id == current_user.id
        ).all()
        
        # Format data untuk respon
        teachers_dict = {}
        for collection, guru in collections_query:
            if guru.id not in teachers_dict:
                teachers_dict[guru.id] = {
                    'id': guru.id,
                    'nama': guru.nama,
                    'email': guru.email,
                    'collections': []
                }
            
            # Cek apakah koleksi baru (dibuat dalam 7 hari terakhir)
            is_new = False
            if collection.created_at:
                delta = datetime.datetime.now() - collection.created_at
                is_new = delta.days < 7
            
            teachers_dict[guru.id]['collections'].append({
                'id': collection.id,
                'name': collection.name,
                'is_new': is_new,
                'description': collection.description
            })
        
        # Konversi ke list untuk response
        teachers_list = list(teachers_dict.values())
        
        return jsonify({
            'success': True, 
            'teachers': teachers_list
        })
        
    except Exception as e:
        print(f"Error getting student collections: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
# =========================================
# ENDPOINT: GET_QUESTIONS (Dipanggil oleh result.html dan guru.html)
# Mengambil semua data soal dari database
# =========================================
@app.route("/api/get_questions", methods=["GET"])
@login_required  
def get_questions_api():  
    # Pastikan yang mengakses endpoint ini adalah guru
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        return jsonify({'success': False, 'message': 'Akses ditolak. Hanya guru yang dapat melihat semua soal.'}), 403

    try:
        # Ambil semua soal yang dimiliki oleh guru yang sedang login
        # Tambahkan filter guru_id di sini
        questions_raw = (
            Question.query
            .filter_by(guru_id=current_user.id, is_current=True)
            .order_by(Question.level.asc(), Question.id.asc())
            .all()
        )
        
        print(f"Fetched {len(questions_raw)} questions for guru_id {current_user.id} via API.")
        
        questions_data = []
        for q in questions_raw:
            options = []
            if q.options:
                try:
                    options = json.loads(q.options)
                except json.JSONDecodeError:
                    pass
            
            questions_data.append({
                "id": q.id,
                "guru_id": q.guru_id,
                "collection_id": q.collection_id,
                "level": q.level,
                "soal": q.soal,
                "jawaban_benar": q.jawaban_benar,
                "options": options,
                "question_type": q.question_type,
                "p": float(q.p),
                "bobot": q.bobot,
                "explanation": q.explanation,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "version": q.version,
                "is_current": q.is_current,
                "is_validated": q.is_validated  
            })
            
        return jsonify({"success": True, "data": questions_data}), 200
        
    except Exception as e:
        print(f"Error getting questions via API: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/api/guru', methods=['GET'])
@login_required
def get_all_teachers():
    try:
        # Only siswa should access this endpoint
        if not hasattr(current_user, 'user_type') or current_user.user_type != 'siswa':
            return jsonify({'success': False, 'message': 'Akses ditolak'}), 403
        
        # Get all teachers
        teachers = Guru.query.all()
        
        # Format teacher data
        teachers_data = []
        for teacher in teachers:
            teachers_data.append({
                'id': teacher.id,
                'nama': teacher.nama,
                'email': teacher.email
            })
        
        return jsonify({
            'success': True,
            'teachers': teachers_data
        })
        
    except Exception as e:
        print(f"Error getting all teachers: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@app.route('/dashboard')
@login_required
def dashboard():
    # Jika pengguna adalah siswa, ambil koleksi yang tersedia
    collections = []
    if hasattr(current_user, 'user_type') and current_user.user_type == 'siswa':
        try:
            # Ambil koleksi yang tersedia untuk siswa ini
            collections_data = db.session.query(
                QuestionCollection, Guru
            ).join(
                Guru, QuestionCollection.guru_id == Guru.id
            ).join(
                collection_students, collection_students.c.collection_id == QuestionCollection.id
            ).filter(
                collection_students.c.siswa_id == current_user.id
            ).all()
            
            # Format data koleksi
            for collection, guru in collections_data:
                # Cek apakah koleksi baru
                is_new = False
                if collection.created_at:
                    delta = datetime.datetime.now() - collection.created_at
                    is_new = delta.days < 7
                
                collections.append({
                    'id': collection.id,
                    'name': collection.name,
                    'is_new': is_new,
                    'description': collection.description,
                    'guru_id': guru.id,
                    'guru_name': guru.nama,
                    'guru_email': guru.email
                })
        except Exception as e:
            print(f"Error fetching collections: {str(e)}")
    
    return render_template('DashboardSiswa.html', collections=collections)
# =========================================
# VERSIONING ENDPOINTS (Tempatkan setelah definisi model)
# =========================================
# Pastikan hanya ada satu implementasi, hapus yang lama
@app.route('/api/questions/<int:id>', methods=['PUT', 'POST', 'DELETE'])
@login_required
def update_question(id):
    try:
        # Handle DELETE request
        if request.method == 'DELETE':
            # Inline delete handler with safety checks
            if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
                return jsonify({"success": False, "message": "Unauthorized"}), 403

            try:
                # Verify question belongs to current guru
                question = Question.query.filter_by(id=id, guru_id=current_user.id).first()
                if not question:
                    return jsonify({"success": False, "message": "Soal tidak ditemukan"}), 404

                # Count student answers
                student_answers_count = SiswaAnswer.query.filter_by(question_id=id).count()

                # Always remove relation to collections for this question belonging to this guru's collections
                CollectionQuestion.query.filter_by(question_id=id).delete()

                if student_answers_count > 0:
                    # If there are student answers, don't delete the question; mark as not current (archived) and detach from collections
                    question.is_current = False
                    db.session.commit()
                    return jsonify({
                        "success": True,
                        "message": f"Soal dihapus dari semua koleksi dan diarsipkan (tidak ditampilkan lagi). Tidak dihapus dari database karena sudah ada {student_answers_count} jawaban siswa."
                    })

                # No student answers: safe to delete all versions and the question
                QuestionVersion.query.filter_by(question_id=id).delete()
                db.session.delete(question)
                db.session.commit()

                return jsonify({
                    "success": True,
                    "message": "Soal berhasil dihapus dari database"
                })
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error deleting question: {str(e)}")
                return jsonify({"success": False, "message": str(e)}), 500
        
        # Log request method untuk debugging
        print(f"Request method: {request.method}")
        print(f"Request headers: {request.headers}")
        
        if request.method == 'POST' and request.headers.get('X-HTTP-Method-Override') == 'PUT':
            print("Using X-HTTP-Method-Override: PUT")
            # Lanjutkan sebagai PUT request
        
        data = request.get_json()
        print(f"Request data: {data}")
        
        # Dapatkan pertanyaan yang akan diupdate
        question = Question.query.get(id)
        if not question:
            return jsonify({'success': False, 'message': 'Pertanyaan tidak ditemukan'}), 404
        
        # Buat versi sebelum update
        prev_version = QuestionVersion(
            question_id=question.id,
            soal=question.soal,
            options=question.options,
            jawaban_benar=question.jawaban_benar,
            explanation=question.explanation,
            p=question.p,
            version=question.version  # Gunakan versi saat ini
        )
        db.session.add(prev_version)
        
        # Update pertanyaan utama
        question.soal = data.get('soal', question.soal)
        question.options = json.dumps(data.get('options')) if 'options' in data else question.options
        question.jawaban_benar = data.get('jawaban_benar', question.jawaban_benar)
        question.explanation = data.get('explanation', question.explanation)
        question.p = data.get('p', question.p)
        
        # Increment versi
        question.version += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'question': {
                'id': question.id,
                'version': question.version,
                'soal': question.soal,
                'options': json.loads(question.options) if question.options else []
            }
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating question: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/questions/<int:id>/versions', methods=['GET'])
@login_required
def get_question_versions(id):
    try:
        print(f"Fetching versions for question {id}")
        versions = QuestionVersion.query.filter_by(question_id=id).order_by(QuestionVersion.version.desc()).all()
        print(f"Found {len(versions)} versions")
        
        result = []
        for version in versions:
            result.append({
                'id': version.id,
                'soal': version.soal,
                'options': json.loads(version.options) if version.options else [],
                'jawaban_benar': version.jawaban_benar,
                'explanation': version.explanation,
                'p': version.p,
                'version': version.version,
                'created_at': version.created_at.isoformat()
            })
            
        return jsonify({'success': True, 'versions': result})
    except Exception as e:
        print(f"Error getting versions: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/questions/in_collection', methods=['GET'])
@login_required
def get_questions_in_collection():
    try:
        # Periksa apakah collection_id disediakan sebagai parameter query
        collection_id = request.args.get('collection_id')
        
        if collection_id:
            # Filter berdasarkan collection_id tertentu
            collection_question_ids = db.session.query(CollectionQuestion.question_id)\
                .filter(CollectionQuestion.collection_id == collection_id).all()
        else:
            # Dapatkan semua ID soal yang ada dalam collection apapun
            collection_question_ids = db.session.query(CollectionQuestion.question_id).distinct().all()
            
        collection_question_ids = [id[0] for id in collection_question_ids]
        
        # Jika perlu detail soal, bukan hanya ID
        include_details = request.args.get('include_details') == 'true'
        if include_details:
            # Ambil detail soal berdasarkan ID yang sudah didapat
            questions = db.session.query(Question)\
                .filter(Question.id.in_(collection_question_ids))\
                .all()
                
            # Format data soal
            question_data = []
            for q in questions:
                options = []
                if hasattr(q, 'options') and q.options:
                    try:
                        options = json.loads(q.options)
                    except:
                        pass
                
                question_data.append({
                    'id': q.id,
                    'level': q.level,
                    'soal': q.soal,
                    'jawaban_benar': q.jawaban_benar,
                    'options': options,
                    'question_type': q.question_type if hasattr(q, 'question_type') else 'multiple_choice',
                    'p': float(q.p) if q.p else 0.5,
                    'bobot': q.bobot or 1,
                    'explanation': q.explanation or ''
                })
                
            return jsonify({
                'success': True,
                'questions': question_data,
                'question_ids': collection_question_ids
            })
        else:
            # Hanya mengembalikan ID soal
            return jsonify({
                'success': True,
                'question_ids': collection_question_ids
            })
            
    except Exception as e:
        print(f"Error getting questions in collection: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@app.route('/api/collections/<int:collection_id>/status', methods=['POST'])
@login_required
def set_collection_status(collection_id):
    try:
        # Verifikasi kepemilikan koleksi
        collection = QuestionCollection.query.filter_by(id=collection_id, guru_id=current_user.id).first()
        if not collection:
            return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
        
        data = request.json
        is_active = data.get('isActive', False)
        
        # Update status
        collection.is_active = bool(is_active)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Koleksi berhasil {"diaktifkan" if is_active else "dinonaktifkan"}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    

@app.route('/guru/collections')
@login_required
def collection_page():
    # Verifikasi bahwa pengguna adalah guru
    if not hasattr(current_user, 'user_type') or current_user.user_type != 'guru':
        flash('Halaman ini hanya untuk guru', 'error')
        return redirect(url_for('login'))
    
    return render_template('guru/collections.html')

@app.route('/api/export_result_excel', methods=['GET'])
@login_required
def export_result_excel():
    try:
        user_id = request.args.get('user_id')
        collection_id = request.args.get('collection_id')
        
        # Validasi parameter
        if not user_id or not collection_id:
            return jsonify({'success': False, 'message': 'Parameter tidak lengkap'}), 400
            
        # Ambil info siswa
        student = Siswa.query.get(user_id)
        if not student:
            return jsonify({'success': False, 'message': 'Siswa tidak ditemukan'}), 404
            
        # Ambil info koleksi
        collection = QuestionCollection.query.get(collection_id)
        if not collection:
            return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
            
        # Ambil hasil tes
        result = SiswaResult.query.filter_by(
            siswa_id=user_id,
            collection_id=collection_id
        ).first()
        
        if not result:
            return jsonify({'success': False, 'message': 'Hasil tes tidak ditemukan'}), 404
            
        # Buat file Excel
        output = BytesIO()
        
        # Format untuk membuat Excel
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # Format untuk judul dan header
            workbook = writer.book
            title_format = workbook.add_format({
                'bold': True,
                'font_size': 16,
                'align': 'center',
                'valign': 'vcenter'
            })
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#D7E4BC',
                'border': 1
            })
            label_format = workbook.add_format({
                'bold': True,
                'align': 'right',
                'border': 1
            })
            data_format = workbook.add_format({
                'align': 'left',
                'border': 1
            })
            
            # Buat worksheet
            worksheet = workbook.add_worksheet('Ringkasan')
            
            # Judul utama
            worksheet.merge_range('A1:H1', f"HASIL TES DIAGNOSTIK - {collection.name}", title_format)
            
            # Detail siswa dalam format label-data
            worksheet.write('A3', 'Nama:', label_format)
            worksheet.write('B3', student.nama, data_format)
            
            worksheet.write('A4', 'Kelas:', label_format)
            worksheet.write('B4', student.kelas, data_format)
            
            worksheet.write('A5', 'Koleksi Soal:', label_format)
            worksheet.write('B5', collection.name, data_format)
            
            worksheet.write('D3', 'level Terakhir:', label_format)
            worksheet.write('E3', result.current_level, data_format)
            
            worksheet.write('D4', 'Jawaban Benar:', label_format)
            worksheet.write('E4', result.correct, data_format)
            
            worksheet.write('D5', 'Jawaban Salah:', label_format)
            worksheet.write('E5', result.incorrect, data_format)
            
            total = result.correct + result.incorrect
            accuracy = f"{round((result.correct / total * 100), 2)}%" if total > 0 else "0%"
            
            worksheet.write('G3', 'Total Soal:', label_format)
            worksheet.write('H3', total, data_format)
            
            worksheet.write('G4', 'Akurasi:', label_format)
            worksheet.write('H4', accuracy, data_format)
            
            worksheet.write('G5', 'Tanggal Pengerjaan:', label_format)
            worksheet.write('H5', result.updated_at.strftime('%d-%m-%Y %H:%M:%S') if result.updated_at else datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S'), data_format)
            
            # --- PERUBAHAN: Tambah keterangan level singkat ---
            worksheet.write('A7', 'Keterangan Level:', label_format)
            level_desc = get_level_description_short(result.current_level)
            data_format_wrap = workbook.add_format({
                'align': 'left',
                'border': 1,
                'text_wrap': True,
                'valign': 'vcenter'
            })
            worksheet.merge_range('B7:H7', level_desc, data_format_wrap)
            worksheet.set_row(6, 40)  # Atur tinggi baris
            # --- PERUBAHAN SELESAI ---
            
            # Sesuaikan lebar kolom dengan spacing yang lebih baik
            worksheet.set_column('A:A', 18)  # Label kolom
            worksheet.set_column('B:B', 28)  # Data siswa
            worksheet.set_column('C:C', 3)   # Spacer
            worksheet.set_column('D:D', 18)  # Label hasil
            worksheet.set_column('E:E', 15)  # Data hasil
            worksheet.set_column('F:F', 3)   # Spacer
            worksheet.set_column('G:G', 20)  # Label statistik
            worksheet.set_column('H:H', 25)  # Data statistik
            
            # Ambil riwayat jawaban
            answers = get_student_answer_history(user_id, collection_id)
            
            # Buat sheet untuk detail jawaban
            if answers:
                # Buat dataframe untuk jawaban
                answers_data = []
                for answer in answers:
                    answers_data.append({
                        'Soal': answer['question'],
                        'Jawaban Siswa': answer['user_answer'],
                        'Jawaban Benar': answer['correct_answer'],
                        'Status': 'Benar' if answer['is_correct'] else 'Salah',
                        'level': answer['level'],
                        'Waktu Menjawab': answer['answered_at']
                    })
                
                df_answers = pd.DataFrame(answers_data)
                # Tulis detail jawaban ke sheet kedua
                df_answers.to_excel(writer, sheet_name='Detail Jawaban', index=False)
                
                # Format sheet Detail Jawaban dengan spacing yang lebih baik
                worksheet2 = writer.sheets['Detail Jawaban']
                
                # Format headers
                header_format2 = workbook.add_format({
                    'bold': True,
                    'text_wrap': True,
                    'valign': 'top',
                    'fg_color': '#D7E4BC',
                    'border': 1
                })
                
                # Apply header format
                for col_num, value in enumerate(df_answers.columns.values):
                    worksheet2.write(0, col_num, value, header_format2)
                
                # Set column widths with proper spacing
                worksheet2.set_column('A:A', 50)  # Soal (wider untuk pertanyaan panjang)
                worksheet2.set_column('B:B', 25)  # Jawaban Siswa
                worksheet2.set_column('C:C', 25)  # Jawaban Benar
                worksheet2.set_column('D:D', 12)  # Status
                worksheet2.set_column('E:E', 8)   # Level
                worksheet2.set_column('F:F', 20)  # Waktu Menjawab
                
                # Set row height for data rows
                for row in range(1, len(df_answers) + 1):
                    worksheet2.set_row(row, 25)
        
        # Kembali ke awal file
        output.seek(0)
        
        # Buat nama file
        filename = f"Hasil_Tes_{student.nama}_{collection.name}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
        
        # Kirim file
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error mengekspor ke Excel: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500

@app.route('/api/export_result_excel_teacher', methods=['GET'])
@login_required
def export_result_excel_teacher():
    try:
        # Get parameters
        export_type = request.args.get('type', 'individual')  # 'individual' or 'class'
        user_id = request.args.get('user_id')
        class_id = request.args.get('class_id')
        collection_id = request.args.get('collection_id')
        
        # Validate parameters
        if not collection_id:
            return jsonify({'success': False, 'message': 'Parameter collection_id is required'}), 400
            
        if export_type == 'individual' and not user_id:
            return jsonify({'success': False, 'message': 'Parameter user_id is required for individual export'}), 400
            
        if export_type == 'class' and not class_id:
            return jsonify({'success': False, 'message': 'Parameter class_id is required for class export'}), 400
            
        # Create a BytesIO object to store the Excel file
        output = BytesIO()
        
        # Collection information
        collection = QuestionCollection.query.get(collection_id)
        if not collection:
            return jsonify({'success': False, 'message': 'Collection not found'}), 404
            
        # Create Excel with appropriate data based on type
        if export_type == 'individual':
            # Individual student export
            student = Siswa.query.get(user_id)
            if not student:
                return jsonify({'success': False, 'message': 'Student not found'}), 404
                
            # Get student results
            result = SiswaResult.query.filter_by(
                siswa_id=user_id,
                collection_id=collection_id
            ).first()
            
            if not result:
                return jsonify({'success': False, 'message': 'No results found for this student'}), 404
                
            # Create Excel file with student data
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Format for styling
                workbook = writer.book
                title_format = workbook.add_format({
                    'bold': True,
                    'font_size': 16,
                    'align': 'center',
                    'valign': 'vcenter'
                })
                header_format = workbook.add_format({
                    'bold': True,
                    'text_wrap': True,
                    'valign': 'top',
                    'fg_color': '#D7E4BC',
                    'border': 1
                })
                label_format = workbook.add_format({
                    'bold': True,
                    'align': 'right',
                    'border': 1
                })
                data_format = workbook.add_format({
                    'align': 'left',
                    'border': 1
                })
                
                # Create summary worksheet
                worksheet = workbook.add_worksheet('Summary')
                
                # Add title
                worksheet.merge_range('A1:H1', f"HASIL TES DIAGNOSTIK - {collection.name}", title_format)
                
                # Student details
                worksheet.write('A3', 'Nama:', label_format)
                worksheet.write('B3', student.nama, data_format)
                
                worksheet.write('A4', 'Kelas:', label_format)
                worksheet.write('B4', student.kelas, data_format)
                
                worksheet.write('A5', 'Koleksi Soal:', label_format)
                worksheet.write('B5', collection.name, data_format)
                
                # Result details
                worksheet.write('D3', 'level Terakhir:', label_format)
                worksheet.write('E3', result.current_level, data_format)
                
                worksheet.write('D4', 'Jawaban Benar:', label_format)
                worksheet.write('E4', result.correct, data_format)
                
                worksheet.write('D5', 'Jawaban Salah:', label_format)
                worksheet.write('E5', result.incorrect, data_format)
                
                # Statistics
                total = result.correct + result.incorrect
                accuracy = f"{round((result.correct / total * 100), 2)}%" if total > 0 else "0%"
                
                worksheet.write('G3', 'Total Soal:', label_format)
                worksheet.write('H3', total, data_format)
                
                worksheet.write('G4', 'Akurasi:', label_format)
                worksheet.write('H4', accuracy, data_format)
                
                worksheet.write('G5', 'Tanggal Pengerjaan:', label_format)
                worksheet.write('H5', result.updated_at.strftime('%d-%m-%Y %H:%M:%S') if result.updated_at else datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S'), data_format)
                
                # --- PERUBAHAN: Tambah keterangan level singkat ---
                worksheet.write('A7', 'Keterangan Level:', label_format)
                level_desc = get_level_description_short(result.current_level)
                data_format_wrap = workbook.add_format({
                    'align': 'left',
                    'border': 1,
                    'text_wrap': True,
                    'valign': 'vcenter'
                })
                worksheet.merge_range('B7:H7', level_desc, data_format_wrap)
                worksheet.set_row(6, 40)  # Atur tinggi baris
                # --- PERUBAHAN SELESAI ---
                
                # Format columns
                worksheet.set_column('A:A', 15)
                worksheet.set_column('B:B', 25)
                worksheet.set_column('C:C', 5)
                worksheet.set_column('D:D', 15)
                worksheet.set_column('E:E', 15)
                worksheet.set_column('F:F', 5)
                worksheet.set_column('G:G', 18)
                worksheet.set_column('H:H', 25)
                
                # Get answer history
                answers = get_student_answer_history(user_id, collection_id)
                
                # Add answers to another sheet
                if answers:
                    # Create dataframe for answers
                    answers_data = []
                    for answer in answers:
                        answers_data.append({
                            'Soal': answer['question'],
                            'Jawaban Siswa': answer['user_answer'],
                            'Jawaban Benar': answer['correct_answer'],
                            'Status': 'Benar' if answer['is_correct'] else 'Salah',
                            'level': answer['level'],
                            'Waktu Menjawab': answer['answered_at']
                        })
                    
                    # Create DataFrame and write to Excel
                    if answers_data:
                        df_answers = pd.DataFrame(answers_data)
                        df_answers.to_excel(writer, sheet_name='Detail Jawaban', index=False)
                        
                        # Format Detail Jawaban sheet dengan spacing yang lebih baik
                        answer_sheet = writer.sheets['Detail Jawaban']
                        
                        # Apply header format
                        header_format_answer = workbook.add_format({
                            'bold': True,
                            'text_wrap': True,
                            'valign': 'top',
                            'fg_color': '#D7E4BC',
                            'border': 1
                        })
                        
                        for col_num, value in enumerate(df_answers.columns.values):
                            answer_sheet.write(0, col_num, value, header_format_answer)
                        
                        # Set column widths with proper spacing
                        answer_sheet.set_column('A:A', 50)  # Soal
                        answer_sheet.set_column('B:B', 25)  # Jawaban Siswa
                        answer_sheet.set_column('C:C', 25)  # Jawaban Benar
                        answer_sheet.set_column('D:D', 12)  # Status
                        answer_sheet.set_column('E:E', 8)   # Level
                        answer_sheet.set_column('F:F', 20)  # Waktu Menjawab
                        
                        # Set row height for data rows
                        for row in range(1, len(df_answers) + 1):
                            answer_sheet.set_row(row, 25)
            
            # Generate filename
            filename = f"Hasil_Tes_{student.nama}_{collection.name}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
            
        else:
            # Class export
            # Get all students in the class
            students = Siswa.query.filter_by(kelas=class_id).all()
            if not students:
                return jsonify({'success': False, 'message': 'No students found in this class'}), 404
            
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                workbook = writer.book
                title_format = workbook.add_format({
                    'bold': True,
                    'font_size': 16,
                    'align': 'center',
                    'valign': 'vcenter'
                })
                header_format = workbook.add_format({
                    'bold': True,
                    'text_wrap': True,
                    'valign': 'top',
                    'fg_color': '#D7E4BC',
                    'border': 1
                })
                
                # Summary sheet
                worksheet = workbook.add_worksheet('Ringkasan Kelas')
                
                # Add title - disesuaikan untuk kolom baru
                worksheet.merge_range('A1:K1', f"RINGKASAN HASIL TES KELAS {class_id} - {collection.name}", title_format)
                
                # Set up headers for class summary - tambah Taksonomi Teknologi
                headers = ['No', 'Nama', 'Kelas', 'Level', 'Keterangan Level', 'Taksonomi Teknologi', 'Jawaban Benar', 'Jawaban Salah', 'Total', 'Akurasi (%)', 'Status']
                for col, header in enumerate(headers):
                    worksheet.write(2, col, header, header_format)
                
                # Gather student data
                class_data = []
                row = 3
                student_number = 1
                
                total_correct = 0
                total_incorrect = 0
                level_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0}
                completed_count = 0
                
                for student in students:
                    # Get student result
                    result = SiswaResult.query.filter_by(
                        siswa_id=student.id,
                        collection_id=collection_id
                    ).first()
                    
                    if result:
                        # Update statistics
                        correct = result.correct or 0
                        incorrect = result.incorrect or 0
                        total = correct + incorrect
                        accuracy = round((correct / total * 100), 2) if total > 0 else 0
                        current_level = result.current_level or 1
                        
                        # Track level distribution
                        if current_level in level_distribution:
                            level_distribution[current_level] += 1
                        
                        # Track completion status
                        is_completed = current_level in [5, 6, 7]
                        if is_completed:
                            completed_count += 1
                            
                        # Update totals
                        total_correct += correct
                        total_incorrect += incorrect
                        
                        # --- PERUBAHAN: Tambah keterangan level singkat ---
                        level_desc = get_level_description_short(current_level)
                        # --- PERUBAHAN SELESAI ---
                        
                        # Write row data dengan format yang rapi
                        data_format_teacher = workbook.add_format({
                            'align': 'left',
                            'border': 1
                        })
                        description_format_teacher = workbook.add_format({
                            'align': 'left',
                            'border': 1,
                            'text_wrap': True,
                            'valign': 'top'
                        })
                        num_format_teacher = workbook.add_format({
                            'align': 'right',
                            'border': 1,
                            'num_format': '0'
                        })
                        
                        worksheet.write(row, 0, student_number, num_format_teacher)
                        worksheet.write(row, 1, student.nama, data_format_teacher)
                        worksheet.write(row, 2, student.kelas, data_format_teacher)
                        worksheet.write(row, 3, current_level, num_format_teacher)
                        # --- PERUBAHAN: Tambah kolom keterangan level dan Taksonomi Teknologi ---
                        worksheet.write(row, 4, level_desc, description_format_teacher)
                        worksheet.write(row, 5, get_technology_taxonomy_short(current_level), data_format_teacher)
                        worksheet.write(row, 6, correct, num_format_teacher)
                        worksheet.write(row, 7, incorrect, num_format_teacher)
                        worksheet.write(row, 8, total, num_format_teacher)
                        worksheet.write(row, 9, accuracy, num_format_teacher)
                        worksheet.write(row, 10, "Selesai" if is_completed else "Sedang Mengerjakan" if total > 0 else "Belum Mulai", data_format_teacher)
                        # --- PERUBAHAN SELESAI ---
                        
                        # Set row height for better readability
                        worksheet.set_row(row-1, 25)
                        
                        # Prepare data for DataFrame
                        class_data.append({
                            'Nama': student.nama,
                            'Kelas': student.kelas,
                            'Level': current_level,
                            # --- PERUBAHAN: Tambah keterangan level ke DataFrame ---
                            'Keterangan Level': level_desc,
                            # --- PERUBAHAN SELESAI ---
                            'Jawaban Benar': correct,
                            'Jawaban Salah': incorrect,
                            'Total': total,
                            'Akurasi (%)': accuracy,
                            'Status': "Selesai" if is_completed else "Sedang Mengerjakan" if total > 0 else "Belum Mulai"
                        })
                        
                        row += 1
                        student_number += 1
                
                # Add totals row
                total_students = len(students)
                total_answers = total_correct + total_incorrect
                avg_accuracy = round((total_correct / total_answers * 100), 2) if total_answers > 0 else 0
                completion_rate = round((completed_count / total_students * 100), 2) if total_students > 0 else 0
                
                # Skip a row
                row += 1
                
                # Summary row - sesuaikan posisi kolom untuk Taksonomi Teknologi
                bold_format = workbook.add_format({'bold': True})
                worksheet.write(row, 0, "SUMMARY", bold_format)
                worksheet.write(row, 1, f"Total Siswa: {total_students}")
                worksheet.write(row, 6, f"Total Benar: {total_correct}")
                worksheet.write(row, 7, f"Total Salah: {total_incorrect}")
                worksheet.write(row, 8, f"Total Jawaban: {total_answers}")
                worksheet.write(row, 9, f"Akurasi Rata-rata: {avg_accuracy}%")
                worksheet.write(row, 10, f"Penyelesaian: {completion_rate}%")
                
                # Format columns dengan spacing yang lebih baik - tambah Taksonomi Teknologi
                worksheet.set_column('A:A', 5)   # No
                worksheet.set_column('B:B', 25)  # Nama
                worksheet.set_column('C:C', 12)  # Kelas
                worksheet.set_column('D:D', 8)   # Level
                worksheet.set_column('E:E', 20)  # Keterangan Level (singkat)
                worksheet.set_column('F:F', 18)  # Taksonomi Teknologi (format singkat)
                worksheet.set_column('G:G', 15)  # Jawaban Benar
                worksheet.set_column('H:H', 15)  # Jawaban Salah
                worksheet.set_column('I:I', 10)  # Total
                worksheet.set_column('J:J', 12)  # Akurasi (%)
                worksheet.set_column('K:K', 18)  # Status
                worksheet.set_column('G:G', 15)  # Jawaban Salah
                worksheet.set_column('H:H', 10)  # Total
                worksheet.set_column('I:I', 12)  # Akurasi (%)
                worksheet.set_column('J:J', 18)  # Status
                
                # level Distribution Chart Sheet
                level_sheet = workbook.add_worksheet('Distribusi Level')
                
                # Create level distribution data
                level_data = []
                for level, count in level_distribution.items():
                    level_data.append({
                        'level': f"Level {level}",
                        'Jumlah Siswa': count,
                        'Persentase': round((count / total_students * 100), 2) if total_students > 0 else 0,
                        'Keterangan': get_level_description_short(level),
                        'Taksonomi Teknologi': get_technology_taxonomy(level)
                    })
                
                # Write level distribution data
                level_sheet.merge_range('A1:E1', f"DISTRIBUSI LEVEL - {collection.name}", title_format)
                level_headers = ['Level', 'Jumlah Siswa', 'Persentase (%)', 'Keterangan', 'Taksonomi Teknologi']
                for col, header in enumerate(level_headers):
                    level_sheet.write(2, col, header, header_format)
                
                # Create format for description column
                desc_format = workbook.add_format({
                    'align': 'left',
                    'border': 1,
                    'text_wrap': True,
                    'valign': 'top'
                })
                
                for i, data in enumerate(level_data):
                    level_sheet.write(i + 3, 0, data['level'], data_format_teacher)
                    level_sheet.write(i + 3, 1, data['Jumlah Siswa'], num_format_teacher)
                    level_sheet.write(i + 3, 2, data['Persentase'], num_format_teacher)
                    level_sheet.write(i + 3, 3, data['Keterangan'], desc_format)
                    level_sheet.write(i + 3, 4, data['Taksonomi Teknologi'], data_format_teacher)
                    level_sheet.set_row(i + 3, 25)  # Set row height
                
                # Format columns dengan spacing yang lebih baik
                level_sheet.set_column('A:A', 12)  # Level
                level_sheet.set_column('B:B', 15)  # Jumlah Siswa
                level_sheet.set_column('C:C', 15)  # Persentase (%)
                level_sheet.set_column('D:D', 45)  # Keterangan
                level_sheet.set_column('E:E', 25)  # Taksonomi Teknologi
                
                # Create a chart for level distribution
                chart = workbook.add_chart({'type': 'column'})
                
                # Add data series
                chart.add_series({
                    'name': 'Jumlah Siswa',
                    'categories': ['Distribusi level', 3, 0, 9, 0],
                    'values': ['Distribusi level', 3, 1, 9, 1],
                    'data_labels': {'value': True}
                })
                
                # Configure chart
                chart.set_title({'name': 'Distribusi level'})
                chart.set_x_axis({'name': 'level'})
                chart.set_y_axis({'name': 'Jumlah Siswa'})
                
                # Insert chart
                level_sheet.insert_chart('E3', chart, {'x_offset': 25, 'y_offset': 10, 'x_scale': 1.5, 'y_scale': 1.5})
                
                # If we have student data, create a full class data sheet
                if class_data:
                    df_class = pd.DataFrame(class_data)
                    df_class.to_excel(writer, sheet_name='Data Lengkap', index=False)
                    
                    # Format columns
                    class_sheet = writer.sheets['Data Lengkap']
                    class_sheet.set_column('A:A', 25)
                    class_sheet.set_column('B:B', 10)
                    class_sheet.set_column('C:C', 10)
                    class_sheet.set_column('D:D', 15)
                    class_sheet.set_column('E:E', 15)
                    class_sheet.set_column('F:F', 10)
                    class_sheet.set_column('G:G', 12)
                    class_sheet.set_column('H:H', 18)
            
            # Generate filename
            filename = f"Hasil_Kelas_{class_id}_{collection.name}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
        
        # Reset file pointer to beginning
        output.seek(0)
        
        # Send file as attachment
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting to Excel: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500

@app.route('/api/export_all_collection_data', methods=['GET'])
@login_required
def export_all_collection_data():
    try:
        collection_id = request.args.get('collection_id')
        
        if not collection_id:
            return jsonify({'success': False, 'message': 'Collection ID is required'}), 400
            
        # Get collection info
        collection = QuestionCollection.query.get(collection_id)
        if not collection:
            return jsonify({'success': False, 'message': 'Collection not found'}), 404
            
        # Verify ownership
        if collection.guru_id != current_user.id:
            return jsonify({'success': False, 'message': 'You do not have permission to export this collection'}), 403
            
        # Get all students assigned to this collection
        students_query = db.session.query(Siswa).join(
            collection_students,
            collection_students.c.siswa_id == Siswa.id
        ).filter(
            collection_students.c.collection_id == collection_id
        ).all()
        
        if not students_query:
            return jsonify({'success': False, 'message': 'No students assigned to this collection'}), 404
            
        # Create BytesIO object for the Excel file
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            
            # ===== FORMAT DEFINITIONS =====
            title_format = workbook.add_format({
                'bold': True,
                'font_size': 16,
                'align': 'center',
                'valign': 'vcenter'
            })
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#D7E4BC',
                'border': 1
            })
            label_format = workbook.add_format({
                'bold': True,
                'align': 'right',
                'border': 1
            })
            data_format = workbook.add_format({
                'align': 'left',
                'border': 1
            })
            num_format = workbook.add_format({
                'align': 'right',
                'border': 1,
                'num_format': '0'
            })
            percent_format = workbook.add_format({
                'align': 'right',
                'border': 1,
                'num_format': '0.00%'
            })
            date_format = workbook.add_format({
                'align': 'left',
                'border': 1,
                'num_format': 'dd/mm/yyyy hh:mm:ss'
            })
            heading_format = workbook.add_format({
                'bold': True,
                'font_size': 12,
                'align': 'left',
                'valign': 'vcenter'
            })
            
            # ===== COLLECTION SUMMARY SHEET =====
            summary_sheet = workbook.add_worksheet('Ringkasan Koleksi')
            
            # Title
            summary_sheet.merge_range('A1:H1', f"RINGKASAN KOLEKSI - {collection.name}", title_format)
            
            # Collection details
            summary_sheet.write('A3', 'Nama Koleksi:', label_format)
            summary_sheet.write('B3', collection.name, data_format)
            
            summary_sheet.write('A4', 'Deskripsi:', label_format)
            summary_sheet.write('B4', collection.description or 'Tidak ada deskripsi', data_format)
            
            summary_sheet.write('A5', 'Guru:', label_format)
            guru = Guru.query.get(collection.guru_id)
            summary_sheet.write('B5', guru.nama if guru else 'Unknown', data_format)
            
            summary_sheet.write('A6', 'Tanggal Dibuat:', label_format)
            summary_sheet.write('B6', collection.created_at.strftime('%d-%m-%Y %H:%M:%S') if collection.created_at else 'Unknown', data_format)
            
            # Calculate overall statistics
            total_students = len(students_query)
            total_correct = 0
            total_incorrect = 0
            completed_count = 0
            level_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0}
            
            for student in students_query:
                # Get result
                result = SiswaResult.query.filter_by(
                    siswa_id=student.id,
                    collection_id=collection_id
                ).first()
                
                if result:
                    total_correct += result.correct or 0
                    total_incorrect += result.incorrect or 0
                    
                    # Track level distribution
                    level = result.current_level or 1
                    if level in level_distribution:
                        level_distribution[level] += 1
                    
                    # Check if completed
                    if level in [5, 6, 7]:
                        completed_count += 1
            
            # Overall statistics
            total_answers = total_correct + total_incorrect
            avg_accuracy = (total_correct / total_answers * 100) if total_answers > 0 else 0
            completion_rate = (completed_count / total_students * 100) if total_students > 0 else 0
            
            summary_sheet.write('D3', 'Total Siswa:', label_format)
            summary_sheet.write('E3', total_students, num_format)
            
            summary_sheet.write('D4', 'Jawaban Benar:', label_format)
            summary_sheet.write('E4', total_correct, num_format)
            
            summary_sheet.write('D5', 'Jawaban Salah:', label_format)
            summary_sheet.write('E5', total_incorrect, num_format)
            
            summary_sheet.write('D6', 'Total Jawaban:', label_format)
            summary_sheet.write('E6', total_answers, num_format)
            
            summary_sheet.write('G3', 'Akurasi Rata-rata:', label_format)
            summary_sheet.write('H3', avg_accuracy / 100, percent_format)
            
            summary_sheet.write('G4', 'Tingkat Penyelesaian:', label_format)
            summary_sheet.write('H4', completion_rate / 100, percent_format)
            
            summary_sheet.write('G5', 'Siswa Selesai:', label_format)
            summary_sheet.write('H5', f"{completed_count} / {total_students}", data_format)
            
            # level Distribution section
            summary_sheet.write('A9', 'Distribusi level:', heading_format)
            
            summary_sheet.write('A10', 'level', header_format)
            summary_sheet.write('B10', 'Jumlah Siswa', header_format)
            summary_sheet.write('C10', 'Persentase', header_format)
            
            row = 11
            for level, count in level_distribution.items():
                percentage = (count / total_students * 100) if total_students > 0 else 0
                
                summary_sheet.write(f'A{row}', f"level {level}", data_format)
                summary_sheet.write(f'B{row}', count, num_format)
                summary_sheet.write(f'C{row}', percentage / 100, percent_format)
                
                row += 1
            
            # ===== KETERANGAN LEVEL SECTION =====
            summary_sheet.write('A19', 'Keterangan Level Soal dan Taksonomi Teknologi:', heading_format)
            
            # Level descriptions with Technology taxonomy
            level_descriptions = [
                ('Level 1', 'Stage I (Kotak 1) - Kesadaran Teknologi: Definisi, istilah, identifikasi teknologi dasar', 'Knowledge That'),
                ('Level 2', 'Stage II (Kotak 2) - Literasi Teknologi: Klasifikasi, hubungan antar teknologi, penjelasan fungsi', 'Knowledge That'),
                ('Level 3', 'Stage III (Kotak 3) - Kemampuan Teknologi: Aplikasi praktis, instruksi, puzzle urutan', 'Knowledge That + How'),
                ('Level 4', 'Stage III (Kotak 4) - Kreativitas Teknologi (Dasar): Modifikasi, debugging, analisis error sederhana', 'Knowledge That + How'),
                ('Level 5', 'Stage IV (Kotak 5) - Kemampuan Teknologi (Penguatan): Aplikasi lanjutan, puzzle assembly terbimbing', 'Knowledge That + How'),
                ('Level 6', 'Stage IV (Kotak 6) - Kritik Teknologi: Evaluasi trade-off, menilai solusi, kritik teknologi', 'Knowledge That + How + Why'),
                ('Level 7', 'Stage IV (Kotak 7) - Kreativitas + Kritik Teknologi (Final Tinggi): Merancang solusi baru, integrasi multi-konsep', 'Knowledge That + How + Why')
            ]
            
            # Headers for level descriptions
            summary_sheet.write('A20', 'Level', header_format)
            summary_sheet.write('B20', 'Keterangan', header_format)
            summary_sheet.write('C20', 'Taksonomi Teknologi', header_format)
            
            # Create format for level descriptions with text wrapping
            description_format = workbook.add_format({
                'align': 'left',
                'border': 1,
                'text_wrap': True,
                'valign': 'top'
            })
            
            row = 21
            for level_name, description, technology_taxonomy in level_descriptions:
                summary_sheet.write(f'A{row}', level_name, data_format)
                summary_sheet.write(f'B{row}', description, description_format)
                summary_sheet.write(f'C{row}', technology_taxonomy, description_format)
                summary_sheet.set_row(row-1, 25)  # Set row height for better readability
                row += 1
            
            # Format column widths with better spacing
            summary_sheet.set_column('A:A', 15)  # Level
            summary_sheet.set_column('B:B', 50)  # Keterangan
            summary_sheet.set_column('C:C', 30)  # Taksonomi Teknologi
            summary_sheet.set_column('D:D', 20)
            summary_sheet.set_column('E:E', 15)
            summary_sheet.set_column('F:F', 3)
            summary_sheet.set_column('G:G', 22)
            summary_sheet.set_column('H:H', 18)
            
            # ===== STUDENT RESULTS SHEET =====
            students_sheet = workbook.add_worksheet('Data Siswa')
            
            # Title - disesuaikan dengan jumlah kolom baru
            students_sheet.merge_range('A1:K1', f"DATA SISWA - {collection.name}", title_format)
            
            # Headers - tambah kolom Taksonomi Teknologi
            headers = ['No', 'Nama', 'Kelas', 'Level', 'Keterangan Level', 'Taksonomi Teknologi', 'Jawaban Benar', 'Jawaban Salah', 'Total', 'Akurasi (%)', 'Status']
            for col, header in enumerate(headers):
                students_sheet.write(2, col, header, header_format)
            
            # Student data
            student_data = []
            row = 3
            for i, student in enumerate(students_query, 1):
                # Get result
                result = SiswaResult.query.filter_by(
                    siswa_id=student.id,
                    collection_id=collection_id
                ).first()
                
                if result:
                    correct = result.correct or 0
                    incorrect = result.incorrect or 0
                    total = correct + incorrect
                    accuracy = (correct / total * 100) if total > 0 else 0
                    current_level = result.current_level or 1
                    is_completed = current_level in [5, 6, 7]
                    status = "Selesai" if is_completed else "Sedang Mengerjakan" if total > 0 else "Belum Mulai"
                else:
                    correct = incorrect = total = accuracy = 0
                    current_level = 1
                    is_completed = False
                    status = "Belum Mulai"
                
                # Write to Excel - tambah kolom Taksonomi Teknologi
                students_sheet.write(row, 0, i, num_format)
                students_sheet.write(row, 1, student.nama, data_format)
                students_sheet.write(row, 2, student.kelas or "-", data_format)
                students_sheet.write(row, 3, current_level, num_format)
                students_sheet.write(row, 4, get_level_description_short(current_level), data_format)
                students_sheet.write(row, 5, get_technology_taxonomy_short(current_level), data_format)
                students_sheet.write(row, 6, correct, num_format)
                students_sheet.write(row, 7, incorrect, num_format)
                students_sheet.write(row, 8, total, num_format)
                students_sheet.write(row, 9, accuracy, num_format)
                students_sheet.write(row, 10, status, data_format)
                
                # Set row height for better readability
                students_sheet.set_row(row-1, 25)
                
                # Add to data for pandas DataFrame
                student_data.append({
                    'Nama': student.nama,
                    'Kelas': student.kelas or "-",
                    'level': current_level,
                    'Jawaban Benar': correct,
                    'Jawaban Salah': incorrect,
                    'Total': total,
                    'Akurasi (%)': accuracy,
                    'Status': status
                })
                
                row += 1
            
            # Format columns dengan spacing yang lebih baik - tambah kolom Taksonomi Bloom
            students_sheet.set_column('A:A', 5)   # No
            students_sheet.set_column('B:B', 25)  # Nama
            students_sheet.set_column('C:C', 12)  # Kelas
            students_sheet.set_column('D:D', 8)   # Level
            students_sheet.set_column('E:E', 20)  # Keterangan Level (singkat)
            students_sheet.set_column('F:F', 15)  # Taksonomi Bloom (format singkat)
            students_sheet.set_column('G:G', 15)  # Jawaban Benar
            students_sheet.set_column('H:H', 15)  # Jawaban Salah
            students_sheet.set_column('I:I', 10)  # Total
            students_sheet.set_column('J:J', 12)  # Akurasi (%)
            students_sheet.set_column('K:K', 18)  # Status
            
            # ===== CLASS SUMMARY SHEET =====
            # Group students by class
            classes = {}
            for student in students_query:
                class_name = student.kelas or "No Class"
                if class_name not in classes:
                    classes[class_name] = []
                classes[class_name].append(student.id)
            
            # Create class summary
            class_sheet = workbook.add_worksheet('Ringkasan Kelas')
            
            # Title
            class_sheet.merge_range('A1:H1', f"RINGKASAN PER KELAS - {collection.name}", title_format)
            
            # Headers
            class_headers = ['Kelas', 'Jumlah Siswa', 'Jawaban Benar', 'Jawaban Salah', 'Total Jawaban', 'Akurasi (%)', 'Siswa Selesai', 'Persentase Selesai (%)']
            for col, header in enumerate(class_headers):
                class_sheet.write(2, col, header, header_format)
            
            # Class data
            row = 3
            for class_name, student_ids in classes.items():
                student_count = len(student_ids)
                class_correct = 0
                class_incorrect = 0
                class_completed = 0
                
                # Calculate stats for this class
                for student_id in student_ids:
                    result = SiswaResult.query.filter_by(
                        siswa_id=student_id,
                        collection_id=collection_id
                    ).first()
                    
                    if result:
                        class_correct += result.correct or 0
                        class_incorrect += result.incorrect or 0
                        
                        if result.current_level in [5, 6, 7]:
                            class_completed += 1
                
                class_total = class_correct + class_incorrect
                class_accuracy = (class_correct / class_total * 100) if class_total > 0 else 0
                completion_percentage = (class_completed / student_count * 100) if student_count > 0 else 0
                
                # Write to Excel
                class_sheet.write(row, 0, class_name, data_format)
                class_sheet.write(row, 1, student_count, num_format)
                class_sheet.write(row, 2, class_correct, num_format)
                class_sheet.write(row, 3, class_incorrect, num_format)
                class_sheet.write(row, 4, class_total, num_format)
                class_sheet.write(row, 5, class_accuracy, num_format)
                class_sheet.write(row, 6, f"{class_completed} / {student_count}", data_format)
                class_sheet.write(row, 7, completion_percentage, num_format)
                
                row += 1
            
            # Format columns with better spacing
            class_sheet.set_column('A:A', 20)  # Kelas
            class_sheet.set_column('B:B', 15)  # Jumlah Siswa
            class_sheet.set_column('C:C', 15)  # Jawaban Benar
            class_sheet.set_column('D:D', 15)  # Jawaban Salah
            class_sheet.set_column('E:E', 15)  # Total Jawaban
            class_sheet.set_column('F:F', 15)  # Akurasi (%)
            class_sheet.set_column('G:G', 18)  # Siswa Selesai
            class_sheet.set_column('H:H', 22)  # Persentase Selesai (%)
            
            # ===== QUESTIONS ANALYSIS SHEET =====
            # Get questions in this collection
            questions = db.session.query(Question).join(
                CollectionQuestion, 
                CollectionQuestion.question_id == Question.id
            ).filter(
                CollectionQuestion.collection_id == collection_id
            ).all()
            
            # Create question analysis sheet
            if questions:
                question_sheet = workbook.add_worksheet('Analisis Soal')
                
                # Title - disesuaikan dengan kolom baru
                question_sheet.merge_range('A1:G1', f"ANALISIS SOAL - {collection.name}", title_format)
                
                # Headers - tambah Taksonomi Teknologi
                question_headers = ['Level', 'Taksonomi Teknologi', 'Soal', 'Jawaban Benar', 'Jawaban Salah', 'Total Jawaban', 'Akurasi (%)']
                for col, header in enumerate(question_headers):
                    question_sheet.write(2, col, header, header_format)
                
                # Question data
                row = 3
                for question in questions:
                    # Calculate question statistics
                    answers = db.session.query(SiswaAnswer).filter_by(
                        question_id=question.id
                    ).all()
                    
                    correct_count = sum(1 for a in answers if a.is_correct)
                    incorrect_count = len(answers) - correct_count
                    total_answers = len(answers)
                    accuracy = (correct_count / total_answers * 100) if total_answers > 0 else 0
                    
                    # Create format for question text with text wrapping
                    question_format = workbook.add_format({
                        'align': 'left',
                        'border': 1,
                        'text_wrap': True,
                        'valign': 'top'
                    })
                    
                    # Write to Excel - tambah kolom Taksonomi Teknologi
                    question_sheet.write(row, 0, question.level, num_format)
                    question_sheet.write(row, 1, get_technology_taxonomy_short(question.level), data_format)
                    question_sheet.write(row, 2, question.soal, question_format)
                    question_sheet.write(row, 3, correct_count, num_format)
                    question_sheet.write(row, 4, incorrect_count, num_format)
                    question_sheet.write(row, 5, total_answers, num_format)
                    question_sheet.write(row, 6, accuracy, num_format)
                    
                    # Set row height for better readability
                    question_sheet.set_row(row-1, 30)
                    
                    row += 1
                
                # Format columns dengan spacing yang lebih baik - tambah kolom Taksonomi Teknologi
                question_sheet.set_column('A:A', 8)   # Level
                question_sheet.set_column('B:B', 20)  # Taksonomi Teknologi (format singkat)
                question_sheet.set_column('C:C', 45)  # Soal
                question_sheet.set_column('D:D', 15)  # Jawaban Benar
                question_sheet.set_column('E:E', 15)  # Jawaban Salah
                question_sheet.set_column('F:F', 15)  # Total Jawaban
                question_sheet.set_column('G:G', 15)  # Akurasi (%)
                
                # Create charts worksheet
                charts_sheet = workbook.add_worksheet('Grafik')
                
                # Title
                charts_sheet.merge_range('A1:H1', f"GRAFIK ANALISIS - {collection.name}", title_format)
                
                # Add level distribution chart
                level_chart = workbook.add_chart({'type': 'column'})
                
                # Configure the chart
                level_chart.add_series({
                    'name': 'Jumlah Siswa',
                    'categories': ['Ringkasan Koleksi', 11, 0, 17, 0],
                    'values': ['Ringkasan Koleksi', 11, 1, 17, 1],
                    'data_labels': {'value': True}
                })
                
                level_chart.set_title({'name': 'Distribusi level'})
                level_chart.set_x_axis({'name': 'level'})
                level_chart.set_y_axis({'name': 'Jumlah Siswa'})
                
                # Insert chart
                charts_sheet.insert_chart('A3', level_chart, {'x_offset': 25, 'y_offset': 10, 'x_scale': 1.5, 'y_scale': 1.2})
                
                # Add class comparison chart
                class_chart = workbook.add_chart({'type': 'column'})
                
                # Configure the chart
                class_chart.add_series({
                    'name': 'Akurasi (%)',
                    'categories': ['Ringkasan Kelas', 3, 0, 3 + len(classes) - 1, 0],
                    'values': ['Ringkasan Kelas', 3, 5, 3 + len(classes) - 1, 5],
                    'data_labels': {'value': True}
                })
                
                class_chart.set_title({'name': 'Akurasi per Kelas'})
                class_chart.set_x_axis({'name': 'Kelas'})
                class_chart.set_y_axis({'name': 'Akurasi (%)'})
                
                # Insert chart
                charts_sheet.insert_chart('A20', class_chart, {'x_offset': 25, 'y_offset': 10, 'x_scale': 1.5, 'y_scale': 1.2})
        
        # Reset file pointer to beginning
        output.seek(0)
        
        # Create filename
        filename = f"Data_Koleksi_{collection.name}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
        
        # Send file as attachment
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting collection data: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500

@app.route('/api/export_result_pdf', methods=['GET'])
@login_required
def export_result_pdf():
    try:
        # Ambil parameter
        user_id = request.args.get('user_id')
        collection_id = request.args.get('collection_id')
        
        # Validasi dan ambil semua data
        if not user_id or not collection_id:
            return jsonify({'success': False, 'message': 'Parameter tidak lengkap'}), 400
        student = Siswa.query.get(user_id)
        if not student:
            return jsonify({'success': False, 'message': 'Siswa tidak ditemukan'}), 404
        collection = QuestionCollection.query.get(collection_id)
        if not collection:
            return jsonify({'success': False, 'message': 'Koleksi tidak ditemukan'}), 404
        result = SiswaResult.query.filter_by(
            siswa_id=user_id,
            collection_id=collection_id
        ).first()
        if not result:
            return jsonify({'success': False, 'message': 'Hasil tes tidak ditemukan'}), 404
        
        # Ambil jawaban siswa dan buat statistik
        answers = get_student_answer_history(user_id, collection_id)
        total = result.correct + result.incorrect
        accuracy = round((result.correct / total * 100), 2) if total > 0 else 0
        
        # Generate rekomendasi pembelajaran yang ditingkatkan
        recommendations = generate_ai_recommendations(student, result, collection_id)
        
        # Helper function untuk waktu sekarang
        def now():
            return datetime.datetime.now()
        
        # Render template HTML dengan data
        html = render_template(
            'siswa/export_pdf.html',
            student=student,
            collection=collection,
            result=result,
            answers=answers,
            accuracy=accuracy,
            recommendations=recommendations,
            total_questions=total,
            now=now
        )
        
        # Fungsi untuk mengkonversi HTML ke PDF dengan xhtml2pdf yang ditingkatkan
        def html_to_pdf(source_html):
            try:
                # Log debugging info
                print("Starting PDF conversion...")
                
                # Buat PDF buffer untuk output
                result_buffer = BytesIO()
                
                # Atur konfigurasi PDF
                pdf_options = {
                    "page-size": "A4",
                    "margin-top": "2cm",
                    "margin-bottom": "2cm",
                    "margin-left": "2cm",
                    "margin-right": "2cm",
                    "encoding": "UTF-8",
                    # Tambahan opsi untuk stabilitas
                    "quiet": 0,
                }
                
                # Konversi HTML ke PDF menggunakan xhtml2pdf
                pisa_status = pisa.CreatePDF(
                    source_html,                # HTML sumber
                    dest=result_buffer,         # Buffer tujuan
                    encoding='UTF-8',           # Encoding untuk karakter internasional
                    options=pdf_options         # Opsi format
                )
                
                # Reset pointer buffer ke awal
                result_buffer.seek(0)
                
                # Cek status konversi
                if pisa_status.err:
                    print(f"Error pada konversi PDF: {pisa_status.err}")
                    return None
                    
                return result_buffer
                
            except Exception as pdf_error:
                print(f"Exception dalam konversi PDF: {str(pdf_error)}")
                import traceback
                traceback.print_exc()
                return None

        # Konversi HTML ke PDF
        pdf_buffer = html_to_pdf(html)
        
        if pdf_buffer is None:
            return jsonify({'success': False, 'message': 'Gagal membuat PDF'}), 500
        
        # Buat nama file yang lebih deskriptif untuk download
        current_date = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        
        # Bersihkan nama file dari karakter yang tidak diperbolehkan
        safe_student_name = "".join(c for c in student.nama if c.isalnum() or c in ' _-').strip()
        safe_student_name = safe_student_name.replace(' ', '_')
        
        safe_collection_name = "".join(c for c in collection.name if c.isalnum() or c in ' _-').strip()
        safe_collection_name = safe_collection_name.replace(' ', '_')
        
        filename = f"Hasil_Tes_{safe_student_name}_{safe_collection_name}_{current_date}.pdf"
        
        # Kirim file PDF
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error exporting to PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500

def generate_ai_recommendations(student, result, collection_id):
    try:
        # Mengambil nama koleksi dan konteks materi
        collection = QuestionCollection.query.get(collection_id)
        collection_name = collection.name if collection else "N/A"
        
        # Ambil konteks materi dan tujuan pembelajaran
        questions_context = get_questions_context_for_recommendations(collection_id, result.current_level)
        learning_objectives = extract_learning_objectives(collection_id)
        performance_analysis = analyze_student_performance(student.id, result, collection_id)
        
        # Hitung persentase keberhasilan untuk menentukan tingkat penguasaan
        total_answers = result.correct + result.incorrect
        mastery_percentage = (result.correct / total_answers * 100) if total_answers > 0 else 0
        
        # Tentukan tingkat penguasaan berdasarkan persentase
        if mastery_percentage >= 80:
            mastery_level = "tinggi"
        elif mastery_percentage >= 60:
            mastery_level = "sedang"
        else:
            mastery_level = "rendah"

        # Prompt AI untuk mendapatkan rekomendasi yang lebih alami seperti dari guru
        prompt = f"""
        Anda adalah seorang GURU AHLI yang memberikan rekomendasi belajar kepada siswa Anda berdasarkan hasil tes diagnostik.
        Berikan rekomendasi yang KONKRET, PRAKTIS, dan MEMOTIVASI dengan NADA PERCAKAPAN LANGSUNG, seolah-olah Anda berbicara kepada siswa di kelas.
        
        DATA SISWA:
        - Nama: {student.nama}
        - Kelas: {student.kelas}
        - Materi Tes: {collection_name}
        - Level Pencapaian: {result.current_level} dari 7
        - Tingkat Penguasaan: {mastery_level} ({mastery_percentage:.1f}%)
        - Jawaban Benar: {result.correct}, Jawaban Salah: {result.incorrect}
        
        ANALISIS PERFORMA:
        {performance_analysis}
        
        TUJUAN PEMBELAJARAN:
        {chr(10).join([f"- {objective}" for objective in learning_objectives])}
        
        INSTRUKSI PENTING UNTUK REKOMENDASI:
        1. Berikan 5-6 rekomendasi KONKRET untuk membantu siswa meningkatkan pemahaman
        2. Gunakan BAHASA GURU yang JELAS dan PERSONAL (seperti "Kamu perlu..." atau "Coba lakukan...")
        3. Setiap rekomendasi harus memiliki TINDAKAN SPESIFIK yang bisa langsung dilakukan
        4. Untuk siswa dengan tingkat penguasaan {mastery_level}, fokuskan pada:
           - {'Pemahaman konsep dasar dan latihan terstruktur' if mastery_level == 'rendah' else 'Pendalaman konsep dan aplikasi praktis' if mastery_level == 'sedang' else 'Pengembangan kreativitas dan penerapan tingkat lanjut'}
        5. Hindari terminologi teknis yang sulit dipahami
        6. Kaitkan setiap saran dengan tujuan pembelajaran spesifik
        7. Setiap rekomendasi hanya 1-2 kalimat dengan format bullet point
        
        JANGAN GUNAKAN:
        - Kata "domain", "level", atau "prompt"
        - Huruf tebal, header, atau penanda format lainnya
        - Format teknis seperti "**Domain Kognitif:**"
        - Angka urutan pada rekomendasi (cukup gunakan bullet point)

        Berikan rekomendasi dalam format bullet point sederhana ("• ").
        """

        # Panggil AI untuk mendapatkan rekomendasi
        response = model.generate_content(prompt)
        recommendations_text = response.text
        
        # Parse hasil ke dalam format yang diinginkan
        recommendations = parse_ai_recommendations_for_teacher(recommendations_text)
        
        # Fallback jika terjadi kegagalan
        if not recommendations or len(recommendations) < 3:
            recommendations = get_teacher_style_recommendations(
                current_level=result.current_level,
                correct=result.correct,
                incorrect=result.incorrect,
                collection_name=collection_name,
                learning_objectives=learning_objectives,
                mastery_level=mastery_level
            )
        
        return recommendations
        
    except Exception as e:
        print(f"Error generating AI recommendations: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Fallback ke rekomendasi default dengan gaya guru
        return get_teacher_style_recommendations(
            current_level=result.current_level if 'result' in locals() else 1,
            correct=result.correct if 'result' in locals() else 0,
            incorrect=result.incorrect if 'result' in locals() else 0,
            collection_name=collection_name if 'collection_name' in locals() else "materi ini",
            learning_objectives=learning_objectives if 'learning_objectives' in locals() else [],
            mastery_level=mastery_level if 'mastery_level' in locals() else "sedang"
        )

# Fungsi helper untuk fokus rekomendasi berdasarkan tingkat penguasaan
def get_focus_by_mastery_level(mastery_level, domain_type):
    if domain_type == "konsep":
        if mastery_level == "rendah":
            return "memperkuat DASAR-DASAR materi dengan scaffolding dan visualisasi"
        elif mastery_level == "sedang":
            return "memperdalam HUBUNGAN ANTAR KONSEP dan aplikasi kontekstual"
        else:  # tinggi
            return "mengeksplorasi PERSPEKTIF LANJUTAN dan transfer pengetahuan"
    elif domain_type == "praktik":
        if mastery_level == "rendah":
            return "memberikan LATIHAN TERSTRUKTUR dengan panduan bertahap"
        elif mastery_level == "sedang":
            return "mencakup VARIASI KONTEKS dan pemecahan masalah mandiri"
        else:  # tinggi
            return "melibatkan KOMPLEKSITAS TINGGI dan potensi inovasi"
    elif domain_type == "evaluasi":
        if mastery_level == "rendah":
            return "berfokus pada IDENTIFIKASI KESENJANGAN pemahaman dan diagnosis kesulitan"
        elif mastery_level == "sedang":
            return "melibatkan EVALUASI STRATEGI belajar dan efektivitas pendekatan"
        else:  # tinggi
            return "mendorong SINTESIS PENGETAHUAN dan refleksi metakognitif"
    return ""

# Fungsi untuk mengekstrak tujuan pembelajaran dari modul
def extract_learning_objectives(collection_id):
    """
    Mengekstrak tujuan pembelajaran dari modul berdasarkan collection_id
    """
    try:
        # Ambil referensi modul dari koleksi soal
        questions = Question.query.filter_by(collection_id=collection_id).all()
        modul_references = []
        learning_objectives = {}
        
        # Pertama coba ekstrak dari question.modul_reference jika ada
        for question in questions:
            # Check if modul_reference attribute exists
            if hasattr(question, 'modul_reference') and question.modul_reference and question.modul_reference.strip():
                modul_ref = question.modul_reference.strip()
                modul_references.append(modul_ref)
        
        # Hapus duplikat
        unique_modules = list(set(modul_references))
        
        # Fallback: ekstrak dari konten soal
        for question in questions:
            if hasattr(question, 'explanation') and question.explanation:
                explanation_lower = question.explanation.lower()
                
                # Cari frasa yang mengandung kata tujuan pembelajaran
                if any(term in explanation_lower for term in ["tujuan pembelajaran", "learning objective", "capaian pembelajaran", "kompetensi"]):
                    # Coba ekstrak tujuan pembelajaran dari penjelasan soal
                    objective_text = extract_objective_from_text(question.explanation)
                    if objective_text:
                        ref = question.modul_reference if hasattr(question, 'modul_reference') else "unknown"
                        if ref not in learning_objectives:
                            learning_objectives[ref] = []
                        learning_objectives[ref].append(objective_text)
        
        # Format tujuan pembelajaran
        formatted_objectives = []
        for modul, objectives in learning_objectives.items():
            if isinstance(objectives, list):
                for obj in objectives:
                    formatted_objectives.append(f"Modul {modul}: {obj}")
            else:
                formatted_objectives.append(f"Modul {modul}: {objectives}")
        
        # Jika masih belum menemukan tujuan pembelajaran, coba ekstrak dari pertanyaan
        if not formatted_objectives:
            # Kategorikan pertanyaan berdasarkan level
            questions_by_level = {}
            for question in questions:
                if hasattr(question, 'level'):
                    level = question.level
                    if level not in questions_by_level:
                        questions_by_level[level] = []
                    questions_by_level[level].append(question)
            
            # Untuk setiap level, buat perkiraan tujuan pembelajaran
            for level, level_questions in sorted(questions_by_level.items()):
                # Ekstrak kata kunci dari soal-soal di level ini
                level_text = " ".join([q.soal for q in level_questions if hasattr(q, 'soal') and q.soal])
                keywords = extract_keywords_from_text(level_text, 3)
                
                if keywords:
                    keyword_phrase = ", ".join(keywords)
                    if level <= 2:
                        formatted_objectives.append(f"Level {level}: Memahami dan mengidentifikasi konsep {keyword_phrase}")
                    elif level <= 4:
                        formatted_objectives.append(f"Level {level}: Menerapkan dan menganalisis konsep {keyword_phrase}")
                    else:
                        formatted_objectives.append(f"Level {level}: Mengevaluasi dan mencipta berdasarkan konsep {keyword_phrase}")
        
        # Jika masih tidak menemukan tujuan pembelajaran, buat tujuan umum
        if not formatted_objectives:
            # Buat perkiraan tujuan pembelajaran dari konten soal
            all_text = " ".join([q.soal for q in questions if hasattr(q, 'soal') and q.soal])
            concepts = extract_keywords_from_text(all_text, 5)
            
            if concepts:
                for i, concept in enumerate(concepts[:3]):
                    if i == 0:
                        formatted_objectives.append(f"Memahami dan menerapkan konsep {concept}")
                    elif i == 1:
                        formatted_objectives.append(f"Menganalisis hubungan antara {concepts[0]} dan {concept}")
                    else:
                        formatted_objectives.append(f"Mengevaluasi penerapan {concept} dalam konteks nyata")
            else:
                # Jika tidak ada konsep spesifik, berikan tujuan generik
                formatted_objectives = [
                    "Memahami konsep-konsep dasar materi",
                    "Menerapkan pengetahuan dalam pemecahan masalah",
                    "Menganalisis dan mengevaluasi situasi berdasarkan konsep yang dipelajari"
                ]
        
        return formatted_objectives
    
    except Exception as e:
        print(f"Error extracting learning objectives: {str(e)}")
        import traceback
        traceback.print_exc()
        return ["Memahami dan menerapkan konsep dasar materi"]
    
def extract_keywords_from_text(text, count=5):
    """
    Ekstrak kata kunci dari teks berdasarkan frekuensi
    """
    if not text:
        return []
        
    # Bersihkan teks
    clean_text = re.sub(r'[^\w\s]', ' ', text.lower())
    
    # Hitung frekuensi kata
    words = clean_text.split()
    word_freq = {}
    
    stopwords = ["yang", "dan", "atau", "adalah", "untuk", "dalam", "pada", "ini", "itu", "dengan", 
                "akan", "dari", "jika", "maka", "oleh", "ada", "tidak", "kita", "saya", "kami", 
                "mereka", "dia", "suatu", "dapat", "bisa", "harus", "sebagai", "saat", "ketika"]
    
    for word in words:
        if len(word) > 3 and word not in stopwords:
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Ambil kata dengan frekuensi tertinggi
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, freq in sorted_words[:count]]

def extract_objective_from_text(text):
    """
    Ekstrak tujuan pembelajaran dari teks penjelasan
    """
    # Cari kalimat yang memuat kata 'tujuan'
    sentences = re.split(r'[.!?]', text)
    for sentence in sentences:
        if re.search(r'\b(tujuan|kompetensi|capaian)\b', sentence.lower()):
            return sentence.strip()
    return None

def extract_key_concepts_from_questions(questions):
    """
    Ekstrak konsep kunci dari kumpulan soal
    """
    # Gabungkan semua soal dan penjelasan
    all_text = ""
    for question in questions:
        if hasattr(question, 'soal') and question.soal:
            all_text += question.soal + " "
        if hasattr(question, 'explanation') and question.explanation:
            all_text += question.explanation + " "
    
    # Bersihkan teks
    all_text = re.sub(r'[^\w\s]', '', all_text.lower())
    
    # Kata-kata yang sering muncul bisa jadi merupakan konsep kunci
    # Tambahkan logika NLP di sini untuk ekstrak konsep kunci
    # Sebagai contoh sederhana, kita menggunakan frekuensi kata dengan filter
    words = all_text.split()
    word_freq = {}
    
    stopwords = ["yang", "dan", "atau", "adalah", "untuk", "dalam", "pada", "ini", "itu", "dengan"]
    for word in words:
        if len(word) > 4 and word not in stopwords:
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Ambil kata dengan frekuensi tertinggi
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, freq in sorted_words[:10]]  # Return top 10 konsep

def identify_learning_domains(collection_id):
    """
    Identifikasi domain pembelajaran yang diukur dalam koleksi soal
    """
    try:
        questions = Question.query.filter_by(collection_id=collection_id).all()
        domains = {
            "kognitif": 0,
            "praktis": 0,
            "reflektif": 0
        }
        
        for question in questions:
            # Analisis soal untuk menentukan domain
            if hasattr(question, 'soal') and question.soal:
                text = question.soal.lower()
                
                # Indikator domain kognitif
                if any(word in text for word in ["jelaskan", "definisikan", "sebutkan", "identifikasi"]):
                    domains["kognitif"] += 1
                
                # Indikator domain praktis
                if any(word in text for word in ["terapkan", "implementasikan", "lakukan", "bagaimana", "cara"]):
                    domains["praktis"] += 1
                
                # Indikator domain reflektif
                if any(word in text for word in ["evaluasi", "analisis", "bandingkan", "mengapa", "refleksikan"]):
                    domains["reflektif"] += 1
        
        # Format output
        domain_text = []
        total_questions = len(questions)
        if total_questions > 0:
            for domain, count in domains.items():
                if count > 0:
                    percentage = round((count / total_questions * 100), 1)
                    domain_text.append(f"{domain.capitalize()}: {percentage}%")
            
            return ", ".join(domain_text) if domain_text else "Domain tidak teridentifikasi"
        else:
            return "Domain Kognitif, Praktis, dan Reflektif"
    
    except Exception as e:
        print(f"Error identifying learning domains: {str(e)}")
        return "Domain Kognitif, Praktis, dan Reflektif"

def get_questions_context_for_recommendations(collection_id, current_level):
    """
    Ambil konteks dari soal-soal untuk rekomendasi yang lebih spesifik
    dengan fokus pada tujuan pembelajaran dari modul ajar
    """
    try:
        questions = Question.query.filter_by(collection_id=collection_id).all()
        
        if not questions:
            return "Tidak ada konteks materi yang tersedia."
        
        # Analisis konten soal
        context_parts = []
        
        # 1. Referensi modul ajar
        module_refs = []
        module_content = {}
        
        for question in questions:
            # Ekstrak referensi modul
            if hasattr(question, 'modul_reference') and question.modul_reference:
                module_ref = question.modul_reference.strip()
                module_refs.append(module_ref)
                
                # Kumpulkan konten berdasarkan modul
                if module_ref not in module_content:
                    module_content[module_ref] = []
                
                # Tambahkan soal dan penjelasan ke konten modul
                content = question.soal[:150] if hasattr(question, 'soal') and question.soal else ""
                if hasattr(question, 'explanation') and question.explanation:
                    content += " | " + question.explanation[:150]
                    
                if content:
                    module_content[module_ref].append(content)
        
        # 2. Ekstrak konsep-konsep kunci
        concepts = []
        for question in questions:
            # Ekstrak konsep dari explanation
            if hasattr(question, 'explanation') and question.explanation:
                # Identifikasi frasa kunci dalam penjelasan
                explanation = question.explanation.lower()
                
                # Cari frasa yang menandakan konsep penting
                for marker in ["konsep", "prinsip", "teori", "metode", "rumus"]:
                    pattern = fr'{marker}\s+(\w+[\s\w]+?)(?:\.|\,|\;|\:)'
                    matches = re.findall(pattern, explanation)
                    for match in matches:
                        if 3 < len(match) < 50:  # Filter panjang yang masuk akal
                            concepts.append(f"{marker.capitalize()}: {match.strip()}")
        
        # Format konteks
        # 1. Referensi modul
        if module_refs:
            unique_refs = list(set(module_refs))
            context_parts.append(f"REFERENSI MODUL AJAR: {', '.join(unique_refs)}")
        
        # 2. Konsep kunci
        if concepts:
            unique_concepts = list(set(concepts))[:5]  # Batasi 5 konsep paling penting
            context_parts.append(f"KONSEP KUNCI: {'; '.join(unique_concepts)}")
        
        # 3. Konten per modul
        for module, contents in module_content.items():
            if contents:
                # Ambil sample konten dari modul
                sample = contents[0]
                context_parts.append(f"ISI MODUL {module}: {sample}")
        
        # 4. Distribusi level
        level_dist = {}
        for question in questions:
            if hasattr(question, 'level'):
                level = question.level
                level_dist[level] = level_dist.get(level, 0) + 1
        
        level_info = [f"Level {level}: {count} soal" for level, count in sorted(level_dist.items())]
        context_parts.append(f"DISTRIBUSI LEVEL: {', '.join(level_info)}")
        
        return "\n".join(context_parts)
        
    except Exception as e:
        print(f"Error getting questions context: {str(e)}")
        import traceback
        traceback.print_exc()
        return "Tidak dapat menganalisis konteks materi."

def analyze_student_performance(student_id, result, collection_id):
    """
    Analisis performa siswa yang lebih detail dengan fokus pada pencapaian tujuan pembelajaran
    """
    try:
        # Ambil semua jawaban siswa untuk collection ini
        answers = SiswaAnswer.query.filter_by(
            siswa_id=student_id
        ).join(
            Question, SiswaAnswer.question_id == Question.id
        ).join(
            CollectionQuestion, 
            (CollectionQuestion.question_id == Question.id) &
            (CollectionQuestion.collection_id == collection_id)
        ).all()
        
        if not answers:
            return "Belum ada data jawaban untuk analisis detail."
        
        # Analisis per level
        level_performance = {}
        for answer in answers:
            if hasattr(answer, 'question') and answer.question and hasattr(answer.question, 'level'):
                level = answer.question.level
                if level not in level_performance:
                    level_performance[level] = {'correct': 0, 'total': 0}
                
                level_performance[level]['total'] += 1
                if answer.is_correct:
                    level_performance[level]['correct'] += 1
        
        # Analisis per modul (jika informasi tersedia)
        module_performance = {}
        for answer in answers:
            if (hasattr(answer, 'question') and answer.question and 
                hasattr(answer.question, 'modul_reference') and 
                answer.question.modul_reference):
                    
                module = answer.question.modul_reference
                if module not in module_performance:
                    module_performance[module] = {'correct': 0, 'total': 0}
                
                module_performance[module]['total'] += 1
                if answer.is_correct:
                    module_performance[module]['correct'] += 1
        
        # Format analisis
        analysis_parts = []
        
        # Level performance
        level_parts = []
        for level in sorted(level_performance.keys()):
            perf = level_performance[level]
            if perf['total'] > 0:
                accuracy = round((perf['correct'] / perf['total'] * 100), 1)
                level_parts.append(f"Level {level}: {perf['correct']}/{perf['total']} ({accuracy}%)")
        
        if level_parts:
            analysis_parts.append("PERFORMA PER LEVEL: " + "; ".join(level_parts))
        
        # Module performance
        if module_performance:
            module_parts = []
            for module, perf in module_performance.items():
                if perf['total'] > 0:
                    accuracy = round((perf['correct'] / perf['total'] * 100), 1)
                    module_parts.append(f"{module}: {accuracy}%")
            
            if module_parts:
                analysis_parts.append("PERFORMA PER MODUL: " + "; ".join(module_parts))
        
        # Identifikasi area yang perlu diperkuat
        weak_areas = []
        
        # Berdasarkan level
        weak_levels = [level for level, perf in level_performance.items() 
                      if perf['total'] > 0 and (perf['correct'] / perf['total']) < 0.6]
        if weak_levels:
            weak_areas.append(f"Level yang perlu dikuasai: {', '.join(map(str, weak_levels))}")
        
        # Berdasarkan modul
        weak_modules = [module for module, perf in module_performance.items() 
                       if perf['total'] > 0 and (perf['correct'] / perf['total']) < 0.6]
        if weak_modules:
            weak_areas.append(f"Modul yang perlu diperdalam: {', '.join(weak_modules)}")
        
        if weak_areas:
            analysis_parts.append("AREA PENGEMBANGAN: " + "; ".join(weak_areas))
        
        # Jika tidak ada analisis yang dapat dibuat
        if not analysis_parts:
            return "Data belum cukup untuk analisis mendalam."
            
        return "\n".join(analysis_parts)
        
    except Exception as e:
        print(f"Error analyzing student performance: {str(e)}")
        import traceback
        traceback.print_exc()
        return "Tidak dapat menganalisis performa detail."

def parse_ai_recommendations_for_teacher(recommendations_text):
    """
    Mengubah teks rekomendasi dari AI menjadi format bullet point yang bersih dan alami
    """
    recommendations = []
    
    # Bersihkan teks dan split berdasarkan baris
    lines = recommendations_text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Hapus format domain dan header
        if any(header in line.lower() for header in ["domain", "**", "instruksi", "catatan:", "note:"]):
            continue
            
        # Bersihkan bullet point dan format
        clean_line = re.sub(r'^[\*\-\•\+\d\.\s]+', '', line).strip()
        
        # Pastikan gaya bahasa guru yang personal
        if len(clean_line) > 15:  # Minimal panjang yang masuk akal
            # Pastikan dimulai dengan kata kerja atau kalimat personal
            if not any(clean_line.lower().startswith(word) for word in ["coba", "lakukan", "buatlah", "kamu", "anda", "mulailah", "praktekkan", "gunakan"]):
                clean_line = f"Coba {clean_line[0].lower()}{clean_line[1:]}"
                
            recommendations.append(clean_line)
    
    # Jika rekomendasi terlalu sedikit, tambahkan dari default
    if len(recommendations) < 3:
        print("Warning: AI recommendations too few, adding default recommendations")
    
    return recommendations

def get_teacher_style_recommendations(current_level, correct, incorrect, collection_name, learning_objectives=[], mastery_level="sedang"):
    """
    Membuat rekomendasi dengan gaya guru berdasarkan tingkat penguasaan
    """
    # Ekstrak kata kunci dari tujuan pembelajaran
    keywords = []
    for objective in learning_objectives:
        words = re.findall(r'\b\w{3,}\b', objective.lower())
        keywords.extend([w for w in words if w not in ["yang", "dan", "atau", "dengan", "untuk", "pada", "dari"]])
    
    # Gunakan keywords yang paling sering muncul
    from collections import Counter
    common_keywords = [word for word, count in Counter(keywords).most_common(5)] if keywords else []
    keyword = common_keywords[0] if common_keywords else collection_name
    
    recommendations = []
    
    if mastery_level == "rendah":
        recommendations = [
            f"Buatlah kartu belajar sederhana untuk konsep {keyword} dan latih pemahaman dasar setiap hari selama 15 menit.",
            f"Coba rangkum materi {collection_name} dengan kata-katamu sendiri dan mintalah guru atau temanmu mengoreksinya.",
            f"Latih pemahaman dasarmu dengan mengerjakan soal-soal tingkat awal secara bertahap dan catat bagian yang masih membingungkan.",
            f"Gunakan video pembelajaran pendek untuk memahami konsep {keyword} dari sudut pandang yang berbeda.",
            f"Bergabunglah dengan kelompok belajar untuk mendiskusikan materi yang masih sulit kamu pahami dan minta bantuan teman yang lebih paham."
        ]
    elif mastery_level == "sedang":
        recommendations = [
            f"Buatlah peta konsep yang menghubungkan {keyword} dengan konsep-konsep terkait lainnya untuk memperdalam pemahamanmu.",
            f"Coba kerjakan soal-soal dengan variasi tingkat kesulitan untuk meningkatkan kemampuan aplikasi konsep {collection_name}.",
            f"Praktekkan penjelasan konsep {keyword} kepada temanmu untuk memastikan kamu benar-benar memahaminya.",
            f"Gunakan contoh kasus nyata untuk mempraktekkan penerapan konsep yang sudah kamu pelajari dalam situasi berbeda.",
            f"Identifikasi pola kesalahan yang kamu lakukan dalam tes, dan buatlah strategi khusus untuk memperbaikinya."
        ]
    else:  # tinggi
        recommendations = [
            f"Kembangkan proyek mini yang mengintegrasikan beberapa konsep dari {collection_name} untuk menguji pemahaman mendalam.",
            f"Coba cari sumber belajar tambahan yang lebih menantang untuk memperluas wawasanmu tentang {keyword}.",
            f"Buatlah tutorial atau materi belajar untuk membantu temanmu memahami konsep yang sudah kamu kuasai.",
            f"Tantang dirimu dengan soal-soal pemecahan masalah kompleks yang membutuhkan analisis mendalam dan penerapan konsep.",
            f"Diskusikan dengan guru tentang aplikasi lanjutan dari {collection_name} yang bisa kamu eksplorasi lebih jauh."
        ]
    
    # Tambahkan satu rekomendasi motivasi
    motivational = [
        f"Ingat, kesalahan adalah bagian dari proses belajar. Terus berlatih dan kamu pasti akan menguasai {collection_name}!",
        f"Percaya pada kemampuanmu! Dengan konsistensi dan latihan rutin, pemahamanmu tentang {collection_name} akan semakin meningkat.",
        f"Tetap semangat dan jangan menyerah! Setiap langkah kecil dalam belajar {collection_name} akan membawamu pada pemahaman yang lebih baik."
    ]
    
    import random
    recommendations.append(random.choice(motivational))
    
    return recommendations

def get_contextual_default_recommendations(current_level, correct, incorrect, collection_name, 
                                           questions_context, learning_objectives, mastery_level="sedang"):
    """
    Rekomendasi default yang kontekstual dan spesifik berdasarkan tujuan pembelajaran
    """
    total = correct + incorrect
    accuracy = round((correct / total * 100), 2) if total > 0 else 0
    
    # Ekstrak kata kunci dari tujuan pembelajaran
    keywords = []
    for objective in learning_objectives:
        words = re.findall(r'\b\w{3,}\b', objective.lower())
        keywords.extend([w for w in words if w not in ["yang", "dan", "atau", "dengan", "untuk", "pada", "dari"]])
    
    # Gunakan keywords yang paling sering muncul
    from collections import Counter
    common_keywords = [word for word, count in Counter(keywords).most_common(5)] if keywords else []
    
    # Struktur rekomendasi berdasarkan domain
    recommendations = {
        "PENGUATAN KONSEP": [],
        "PRAKTIK TERAPAN": [],
        "EVALUASI & SINTESIS": []
    }
    
    # Rekomendasi berdasarkan tingkat penguasaan
    if mastery_level == "rendah":
        recommendations["PENGUATAN KONSEP"] = [
            f"Buat kartu belajar (flashcards) untuk konsep dasar {common_keywords[0] if common_keywords else collection_name}. Tulis definisi pada satu sisi kartu dan contoh sederhana pada sisi lainnya. Tinjau kartu-kartu ini selama 15 menit setiap hari untuk membangun pemahaman dasar yang kuat.",
            f"Gunakan teknik 'chunking' dengan membagi materi {collection_name} menjadi bagian-bagian kecil yang lebih mudah dipahami. Fokus pada satu konsep dalam satu waktu, dan buat diagram atau peta pikiran sederhana untuk visualisasi konsep."
        ]
        recommendations["PRAKTIK TERAPAN"] = [
            f"Selesaikan 5 soal latihan tingkat dasar tentang {common_keywords[0] if common_keywords else collection_name} dengan pendampingan. Tuliskan setiap langkah penyelesaian dan mintalah umpan balik langsung untuk mengidentifikasi kesalahan sedini mungkin.",
            "Ikuti tutorial terstruktur step-by-step dan praktikkan dengan contoh-contoh sederhana. Ulangi proses yang sama dengan variasi kecil untuk memastikan pemahaman dasar."
        ]
        recommendations["EVALUASI & SINTESIS"] = [
            f"Buat jurnal belajar harian yang mencatat: (1) Konsep {common_keywords[0] if common_keywords else 'utama'} yang dipelajari hari ini, (2) Pertanyaan spesifik yang masih membingungkan, dan (3) Contoh penerapan sederhana. Review jurnal ini setiap minggu untuk melihat kemajuan pemahaman."
        ]
    
    elif mastery_level == "sedang":
        recommendations["PENGUATAN KONSEP"] = [
            f"Buat peta hubungan (concept map) yang menghubungkan konsep {common_keywords[0] if common_keywords else 'utama'} dengan {common_keywords[1] if len(common_keywords) > 1 else 'konsep terkait'}. Identifikasi minimal 3 hubungan antar konsep dan jelaskan bagaimana konsep-konsep tersebut saling mempengaruhi.",
            f"Analisis 3-5 contoh kesalahan umum dalam penerapan {common_keywords[0] if common_keywords else collection_name}. Untuk setiap kesalahan, identifikasi miskonsepsi yang mendasarinya dan tuliskan penjelasan yang benar."
        ]
        recommendations["PRAKTIK TERAPAN"] = [
            f"Kerjakan 7 soal latihan dengan variasi konteks berbeda untuk konsep {common_keywords[0] if common_keywords else 'utama'}. Pilih soal dari tingkat kesulitan sedang dan catat pola/strategi penyelesaian untuk setiap jenis soal.",
            "Bentuk kelompok diskusi 3-4 orang untuk membahas dan memecahkan kasus penerapan dari materi yang dipelajari. Bergiliran menjelaskan pendekatan penyelesaian dan memberikan umpan balik konstruktif."
        ]
        recommendations["EVALUASI & SINTESIS"] = [
            f"Kembangkan mini proyek 3-hari yang mengintegrasikan konsep {common_keywords[0] if common_keywords else collection_name} dalam situasi praktis. Dokumentasikan: (1) Tujuan proyek, (2) Konsep yang diterapkan, (3) Tantangan yang dihadapi, dan (4) Solusi yang dikembangkan."
        ]
    
    else:  # tinggi
        recommendations["PENGUATAN KONSEP"] = [
            f"Telusuri minimal 2 sumber referensi lanjutan tentang {common_keywords[0] if common_keywords else collection_name} di luar materi kelas. Buat ringkasan perbandingan yang mengidentifikasi perspektif berbeda atau pengembangan terbaru dalam topik ini.",
            f"Kembangkan model analisis untuk mengklasifikasikan dan mengevaluasi berbagai pendekatan dalam {collection_name}. Sertakan kriteria evaluasi dan justifikasi untuk setiap kategori dalam model tersebut."
        ]
        recommendations["PRAKTIK TERAPAN"] = [
            f"Desain dan implementasikan proyek kompleks yang mengintegrasikan minimal 3 konsep utama: {', '.join(common_keywords[:3]) if len(common_keywords) > 2 else collection_name}. Proyek harus mencakup elemen kreatif dan solusi untuk masalah otentik.",
            "Ciptakan materi pembelajaran (tutorial video 5-10 menit atau panduan tertulis) untuk menjelaskan konsep kompleks kepada teman sekelas. Presentasikan materi ini dan kumpulkan umpan balik untuk perbaikan."
        ]
        recommendations["EVALUASI & SINTESIS"] = [
            f"Kembangkan portofolio digital yang mendokumentasikan perjalanan belajar Anda dalam {collection_name}. Sertakan refleksi mendalam tentang: (1) Perkembangan pemahaman konseptual, (2) Penerapan praktis yang telah dilakukan, (3) Kendala yang dihadapi dan cara mengatasinya, dan (4) Rencana pengembangan kompetensi selanjutnya."
        ]
    
    # Tambahkan konteks spesifik dari tujuan pembelajaran jika ada
    if learning_objectives and len(learning_objectives) > 0:
        # Ambil tujuan pembelajaran pertama untuk rekomendasi tambahan
        objective = learning_objectives[0]
        if ":" in objective:
            objective = objective.split(":", 1)[1].strip()
            
        recommendations["EVALUASI & SINTESIS"].append(
            f"Lakukan refleksi diri terkait tujuan pembelajaran '{objective}'. Buat rubrik evaluasi dengan skala 1-5 yang menilai tingkat pemahaman dan keterampilan saat ini. Identifikasi bukti konkret untuk setiap skor dan buat rencana spesifik untuk meningkatkan area yang masih lemah."
        )
    
    return recommendations
# =========================================
# MAIN ENTRY POINT
# =========================================
if __name__ == '__main__':  
    with app.app_context():
        try:
            # Inisialisasi database
            init_db()
            # Tes koneksi database
            test_db_connection()
        except Exception as e:
            print(f"Error inisialisasi database: {str(e)}")

    app.run(debug=True)