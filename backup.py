"""Safe online backup of the database. Run daily (cron). Keeps the 14 newest copies."""
import os, sqlite3, time, glob
D = os.getenv("DATA_DIR", "."); os.makedirs(f"{D}/backups", exist_ok=True)
dst = f"{D}/backups/minesight-{time.strftime('%Y%m%d-%H%M')}.db"
src, out = sqlite3.connect(f"{D}/minesight.db"), sqlite3.connect(dst); src.backup(out); out.close(); src.close()
for old in sorted(glob.glob(f"{D}/backups/minesight-*.db"))[:-14]: os.remove(old)
print("backup written:", dst)
