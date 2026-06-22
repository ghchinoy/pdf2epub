import os
import sys
import sqlite3
import glob

def find_kobo_mounts():
    """Scans macOS /Volumes/ directory for any mounted Kobo devices containing a .kobo folder."""
    mounts = []
    if not os.path.exists("/Volumes"):
        return mounts
        
    for vol in os.listdir("/Volumes"):
        vol_path = os.path.join("/Volumes", vol)
        if os.path.isdir(vol_path):
            kobo_dir = os.path.join(vol_path, ".kobo")
            sqlite_db = os.path.join(kobo_dir, "KoboReader.sqlite")
            if os.path.exists(kobo_dir) and os.path.exists(sqlite_db):
                mounts.append((vol_path, sqlite_db))
    return mounts

def run_diagnostics():
    print("=" * 65)
    print("KOBO eREADER IMPORT DIAGNOSTICS TOOL")
    print("=" * 65)
    
    # 1. Detect connected Kobo devices
    print("Step 1: Scanning for connected Kobo eReaders on macOS...")
    kobos = find_kobo_mounts()
    if not kobos:
        print("\n❌ NO KOBO DEVICES DETECTED.")
        print("Please check that:")
        print("  1. Your Kobo eReader is connected via USB.")
        print("  2. You tapped 'Connect' on your Kobo screen.")
        print("  3. The drive is mounted and visible in macOS Finder.")
        sys.exit(1)
        
    kobo_mount, db_path = kobos[0]
    print(f"  -> Found Kobo Mount: {kobo_mount}")
    print(f"  -> Found Database:   {db_path}")
    
    # 2. Check for physical files in Kobo storage
    print("\nStep 2: Checking physical storage files...")
    # Search for compiled EPUB and KEPUB files in the main user partition (onboard storage)
    # We look for files matching *kepub.epub, *kepubified.epub, or *.epub recursively in the drive
    kobo_epub_files = []
    for root, dirs, files in os.walk(kobo_mount):
        # Skip hidden system directories (starting with a dot like .kobo, .adobe-digital-editions)
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith(".epub"):
                kobo_epub_files.append(os.path.join(root, f))
                
    if not kobo_epub_files:
        print("  ⚠️ No epub or kepub.epub files found on your Kobo's onboard storage.")
        print("  Please make sure you copied the files from your 'outputs/' folder onto the Kobo.")
        sys.exit(0)
        
    print(f"  Found {len(kobo_epub_files)} physical .epub/kepub.epub file(s) on the Kobo:")
    for f in kobo_epub_files:
        rel_path = os.path.relpath(f, kobo_mount)
        print(f"  - Onboard Path: {rel_path}")
        
    # 3. Check KoboReader.sqlite database records
    print("\nStep 3: Checking Kobo database index (KoboReader.sqlite)...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check total books currently cataloged in the database
        cursor.execute("SELECT COUNT(*) FROM content WHERE BookID IS NOT NULL AND BookID != ''")
        total_books = cursor.fetchone()[0]
        print(f"  Total cataloged books in Kobo database: {total_books}")
        
        # Check if our specific files have records in the database
        print("\n  Analyzing database import records for our books:")
        for f in kobo_epub_files:
            filename = os.path.basename(f)
            # Kobo stores the file path in 'ContentID' as a URI, e.g., 'file:///mnt/onboard/filename.epub'
            query_path = f"%{filename}"
            cursor.execute(
                "SELECT ContentID, Title, Attribution, MimeType, ___BookTitle FROM content WHERE ContentID LIKE ?", 
                (query_path,)
            )
            records = cursor.fetchall()
            
            if not records:
                print(f"  ❌ {filename:<40} | NOT INDEXED BY KOBO DATABASE")
                print(f"     -> Kobo's parser has NOT scanned this file into its database.")
                print(f"     -> Action: Safely eject the USB, wait for Kobo's 'Importing...' screen to finish.")
            else:
                print(f"  ✅ {filename:<40} | INDEXED SUCCESSFULLY")
                for r in records:
                    content_id, title, author, mime, book_title = r
                    # Check if there are null values which indicate parser corruption
                    if not title:
                        print("     ⚠️ WARNING: Title field is null. Kobo failed to parse book metadata.")
                    else:
                        print(f"     - Title:    {title}")
                    print(f"     - Author:   {author or 'Unknown'}")
                    print(f"     - MimeType: {mime}")
                    print(f"     - ID:       {content_id}")
                    
        conn.close()
    except Exception as e:
        print(f"  Error reading Kobo SQLite database: {e}")
        
    # 4. Read Kobo general error logs
    print("\nStep 4: Checking Kobo Reader system logs...")
    log_paths = [
        os.path.join(kobo_mount, ".kobo", "KoboReader.log"),
        os.path.join(kobo_mount, ".kobo", "syslog")
    ]
    
    found_logs = False
    for lp in log_paths:
        if os.path.exists(lp):
            found_logs = True
            print(f"  Analyzing log: {os.path.basename(lp)}")
            # Read last 30 lines of logs to search for XML or parsing failures
            try:
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                last_lines = lines[-50:]
                
                # Search for keywords like "XML", "parse", "error", "corrupt", "failed"
                errors = []
                for idx, line in enumerate(last_lines):
                    lower_line = line.lower()
                    if "error" in lower_line or "fail" in lower_line or "xml" in lower_line or "parse" in lower_line:
                        errors.append(f"    Line {idx+1}: {line.strip()}")
                        
                if errors:
                    print("    Recent system warnings/errors detected:")
                    for err in errors[:10]:
                        print(err)
                else:
                    print("    No obvious parsing or database errors found in the last 50 log lines.")
            except Exception as e:
                print(f"    Failed to read log: {e}")
                
    if not found_logs:
        print("  No active on-device log files (.kobo/KoboReader.log) found. (This is normal for some Kobos).")
        
    print("\n" + "=" * 65)
    print("DIAGNOSTICS COMPLETED!")
    print("=" * 65)

if __name__ == "__main__":
    run_diagnostics()
