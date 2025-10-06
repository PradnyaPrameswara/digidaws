#!/usr/bin/env python3
"""
Script untuk membuat tabel progress_tracker di database production.
Jalankan script ini di VPS untuk menambahkan tabel baru.
"""

import sys
import os
from pathlib import Path
import datetime

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app import app, db, ProgressTracker

def create_progress_table():
    """Membuat tabel progress_tracker di database"""
    try:
        with app.app_context():
            # Cek apakah tabel sudah ada
            inspector = db.inspect(db.engine)
            if 'progress_tracker' in inspector.get_table_names():
                print("✓ Tabel progress_tracker sudah ada")
                return True
            
            print("Membuat tabel progress_tracker...")
            
            # Buat tabel progress_tracker
            db.create_all()
            
            print("✓ Tabel progress_tracker berhasil dibuat")
            
            # Test insert dan query untuk memastikan tabel berfungsi
            print("Testing tabel progress_tracker...")
            
            test_progress = ProgressTracker(
                user_id='test_123',
                current_step=1,
                step_1_status='active',
                step_1_message='Test progress tracking'
            )
            
            db.session.add(test_progress)
            db.session.commit()
            
            # Query test data
            retrieved = ProgressTracker.query.filter_by(user_id='test_123').first()
            if retrieved:
                print("✓ Test insert dan query berhasil")
                
                # Cleanup test data
                db.session.delete(retrieved)
                db.session.commit()
                print("✓ Test data berhasil dihapus")
                
                return True
            else:
                print("✗ Test query gagal")
                return False
                
    except Exception as e:
        print(f"✗ Error saat membuat tabel: {str(e)}")
        return False

def main():
    print("=== PROGRESS TRACKER TABLE CREATOR ===")
    print(f"Waktu: {datetime.datetime.now()}")
    print("Membuat tabel progress_tracker untuk sistem production...")
    print()
    
    success = create_progress_table()
    
    if success:
        print()
        print("🎉 BERHASIL!")
        print("Tabel progress_tracker telah dibuat dan siap digunakan.")
        print("Progress tracking akan bekerja dengan benar di environment production.")
        print()
        print("Langkah selanjutnya:")
        print("1. Restart aplikasi Flask/Gunicorn di VPS")
        print("2. Test upload file untuk memastikan progress tracking berfungsi")
        
    else:
        print()
        print("❌ GAGAL!")
        print("Terjadi error saat membuat tabel. Cek log error di atas.")
        print("Pastikan:")
        print("1. Database connection berfungsi")
        print("2. User database memiliki permission untuk CREATE TABLE")
        print("3. Tidak ada conflict dengan tabel yang sudah ada")

if __name__ == "__main__":
    main()