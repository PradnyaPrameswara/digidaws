#!/usr/bin/env python3
"""
Script untuk mengecek dan mengoptimalkan favicon Education.ico
"""

import os
from pathlib import Path

def check_favicon():
    """Cek apakah favicon Education.ico ada dan valid"""
    
    # Path ke file favicon
    project_root = Path(__file__).parent
    favicon_path = project_root / 'img' / 'Education.ico'
    
    print("🔍 Mengecek favicon...")
    print(f"📂 Project root: {project_root}")
    print(f"🖼️  Favicon path: {favicon_path}")
    
    # Cek apakah file ada
    if favicon_path.exists():
        file_size = favicon_path.stat().st_size
        print(f"✅ File Education.ico ditemukan!")
        print(f"📊 Ukuran file: {file_size:,} bytes ({file_size/1024:.1f} KB)")
        
        # Cek ukuran file (ideal < 50KB untuk favicon)
        if file_size > 50 * 1024:  # 50KB
            print("⚠️  Warning: File favicon terlalu besar (> 50KB)")
            print("💡 Pertimbangkan untuk kompres file favicon")
        else:
            print("✅ Ukuran file favicon optimal")
            
        return True
    else:
        print("❌ File Education.ico tidak ditemukan!")
        print("💡 Pastikan file Education.ico ada di folder img/")
        return False

def check_routes():
    """Cek apakah route favicon sudah ditambahkan di app.py"""
    
    app_py_path = Path(__file__).parent / 'backend' / 'app.py'
    
    if app_py_path.exists():
        with open(app_py_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if '/favicon.ico' in content and 'Education.ico' in content:
            print("✅ Route favicon sudah ditambahkan di app.py")
            return True
        else:
            print("❌ Route favicon belum ditambahkan di app.py")
            return False
    else:
        print("❌ File app.py tidak ditemukan")
        return False

def check_html_templates():
    """Cek apakah favicon meta tag sudah ditambahkan di template HTML"""
    
    frontend_path = Path(__file__).parent / 'frontend'
    templates_with_favicon = []
    templates_without_favicon = []
    
    # Template files to check
    templates_to_check = [
        'index.html',
        'login.html', 
        'register.html',
        'guru/Dashboard_guru.html',
        'siswa/Dashboard_siswa.html'
    ]
    
    for template in templates_to_check:
        template_path = frontend_path / template
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if 'favicon.ico' in content:
                templates_with_favicon.append(template)
            else:
                templates_without_favicon.append(template)
        else:
            print(f"⚠️  Template tidak ditemukan: {template}")
    
    print(f"\n📋 Template dengan favicon: {len(templates_with_favicon)}")
    for template in templates_with_favicon:
        print(f"  ✅ {template}")
        
    if templates_without_favicon:
        print(f"\n📋 Template tanpa favicon: {len(templates_without_favicon)}")
        for template in templates_without_favicon:
            print(f"  ❌ {template}")
    
    return len(templates_without_favicon) == 0

def main():
    """Main function"""
    print("🚀 DIGIDAWS Favicon Checker")
    print("=" * 40)
    
    favicon_ok = check_favicon()
    print("\n" + "-" * 40)
    
    routes_ok = check_routes()
    print("\n" + "-" * 40)
    
    templates_ok = check_html_templates()
    print("\n" + "=" * 40)
    
    # Summary
    if favicon_ok and routes_ok and templates_ok:
        print("🎉 SEMUA SETUP FAVICON BERHASIL!")
        print("✅ File Education.ico tersedia")
        print("✅ Route favicon sudah dikonfigurasi")
        print("✅ Semua template sudah memiliki favicon meta tag")
        print("\n🌐 Favicon akan muncul saat aplikasi di-hosting!")
    else:
        print("⚠️  Ada beberapa masalah yang perlu diperbaiki:")
        if not favicon_ok:
            print("❌ File favicon tidak ditemukan")
        if not routes_ok:
            print("❌ Route favicon belum dikonfigurasi")
        if not templates_ok:
            print("❌ Beberapa template belum memiliki favicon meta tag")

if __name__ == "__main__":
    main()