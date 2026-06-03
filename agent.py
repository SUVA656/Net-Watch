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

# ==========================================
# CONSTANTS & ADDRESS CONFIGURATIONS
# ==========================================
DASHBOARD_IPS = ["", "", "", ""]  # Change this to the dashboard computer's IP address
TELEMETRY_PORT = 5005
LISTEN_COMMAND_PORT = 6006

EDGE_HISTORY_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default")
EDGE_HISTORY_FILE = os.path.join(EDGE_HISTORY_DIR, "History")

# ==========================================
# SYSTEM COMPONENT DISCOVERY QUERIES
# ==========================================
def fetch_system_specs():
    try:
        cmd_ram = 'powershell "(Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize"'
        ram_raw = subprocess.check_output(cmd_ram, shell=True).decode().strip()
        ram_gb = round(int(ram_raw) / (1024**2))
    except:
        ram_gb = "Unknown"
        
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor(),
        "ram": f"{ram_gb} GB RAM" if isinstance(ram_gb, int) else ram_gb
    }

def gather_pnp_hardware_assets():
    devices = []
    
    # UPDATED: Now queries devices where Status is 'OK' OR 'Error' (Disabled)
    target_classes = "'Mouse', 'Keyboard', 'Camera', 'Image', 'USB', 'DiskDrive'"
    cmd_pnp = f'powershell "Get-PnpDevice | Where-Object {{$_.Status -in (\'OK\', \'Error\') -and $_.Class -in ({target_classes})}} | Select-Object FriendlyName, Class, InstanceId, Status | ConvertTo-Json -Compress"'
    
    try:
        out = subprocess.check_output(cmd_pnp, shell=True).decode('utf-8', errors='ignore').strip()
        if out:
            data = json.loads(out)
            if isinstance(data, dict): data = [data]
            for item in data:
                name = item.get("FriendlyName", "")
                if "root" in name.lower() or "controller" in name.lower() or "hub" in name.lower():
                    continue
                
                # Determine display status
                status_raw = item.get("Status", "OK")
                display_status = "BLOCKED" if status_raw == "Error" else "Active"
                    
                devices.append({
                    "name": name,
                    "type": item.get("Class", "Peripheral"),
                    "mfg": display_status, # We pass the status here so the Dashboard can see it clearly
                    "raw_id": item.get("InstanceId")
                })
    except:
        pass

    # Capture print spooler assets
    cmd_printers = 'powershell "Get-Printer | Select-Object Name, DriverName | ConvertTo-Json -Compress"'
    try:
        out_pr = subprocess.check_output(cmd_printers, shell=True).decode('utf-8', errors='ignore').strip()
        if out_pr:
            data_pr = json.loads(out_pr)
            if isinstance(data_pr, dict): data_pr = [data_pr]
            for item in data_pr:
                devices.append({
                    "name": item.get("Name"),
                    "type": "Printer",
                    "mfg": "Active",
                    "raw_id": item.get("Name")
                })
    except:
        pass
    return devices

def gather_browsing_history():
    logs = []
    if not os.path.exists(EDGE_HISTORY_FILE):
        return logs
    
    temp_db = "edge_hist_temp.db"
    try:
        shutil.copy2(EDGE_HISTORY_FILE, temp_db)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT url, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 35")
        
        for row in cursor.fetchall():
            url = row[0]
            epoch_start = row[1]
            try:
                converted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime((epoch_start / 1000000) - 11644473600))
            except:
                converted_time = "Recent Visit"
            
            logs.append({"site": url, "ip": converted_time})
        conn.close()
    except Exception as e:
        print(f"[-] Database extraction collision: {e}")
    finally:
        if os.path.exists(temp_db):
            try: os.remove(temp_db)
            except: pass
    return logs

# ==========================================
# TELEMETRY OUTBOUND TRANSMISSION ENGINE
# ==========================================
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
        except:
            pass

def cyclic_heartbeat_loop():
    while True:
        print(f"[*] [{time.strftime('%H:%M:%S')}] [Periodic Heartbeat] Dispatching payload...")
        package_and_transmit_telemetry()
        time.sleep(20)

# ==========================================
# TWO-WAY COMMAND LISTENER & ENFORCEMENT
# ==========================================
def process_administrative_enforcement(client_socket):
    try:
        raw_data = client_socket.recv(4096).decode('utf-8')
        if not raw_data: return
        
        directive = json.loads(raw_data)
        action = directive.get("action")
        target_id = directive.get("raw_id")
        dev_type = directive.get("device_type")
        dev_name = directive.get("device_name")
        
        print(f"[!] ENFORCEMENT DIRECTIVE INGESTED: Action={action}, Target={dev_name}")
        
        # New Unblock Action logic handles reversing a device ban state
        if action == "unblock_device":
            if dev_type == "Printer":
                client_socket.sendall(b"SUCCESS: Printer skip unblock request.")
                return
            else:
                ps_script = f"Enable-PnpDevice -InstanceId '{target_id}' -Confirm:$false -ErrorAction Stop"
        else:
            if dev_type == "Printer":
                ps_script = f"Remove-Printer -Name '{target_id}'"
            else:
                ps_script = f"Disable-PnpDevice -InstanceId '{target_id}' -Confirm:$false -ErrorAction Stop"
        
        execution_shell = f'powershell -Command "{ps_script}"'
        proc = subprocess.run(execution_shell, shell=True, capture_output=True, text=True)
        
        if proc.returncode == 0:
            print(f"[+] ACTION COMPLETED: Status modified for '{dev_name}' successfully.")
            client_socket.sendall(b"SUCCESS: State updated.")
            package_and_transmit_telemetry() 
        else:
            err_msg = proc.stderr.strip()
            print(f"[-] ACTION ABORTED: FAILED: {err_msg}")
            client_socket.sendall(f"FAILED: {err_msg}".encode('utf-8'))
    except Exception as e:
        print(f"[-] Exception processing command structure: {e}")
        try: client_socket.sendall(f"ERROR: {e}".encode('utf-8'))
        except: pass
    finally:
        client_socket.close()

def command_listener_interface():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('0.0.0.0', LISTEN_COMMAND_PORT))
        server.listen(5)
        print(f"[*] TWO-WAY COMMAND INTERFACE ONLINE: Awaiting directives on port {LISTEN_COMMAND_PORT}...")
    except Exception as e:
        print(f"[CRITICAL] Failed binding local command architecture to port {LISTEN_COMMAND_PORT}: {e}")
        return

    while True:
        try:
            sock, _ = server.accept()
            threading.Thread(target=process_administrative_enforcement, args=(sock,), daemon=True).start()
        except:
            pass

if __name__ == "__main__":
    print(f"[*] AGENT ENGINE ONLINE: Tracking browser changes in {EDGE_HISTORY_DIR}")
    print(f"[*] [{time.strftime('%H:%M:%S')}] [Agent Initialization] Dispatching payload...")
    package_and_transmit_telemetry()
    
    threading.Thread(target=cyclic_heartbeat_loop, daemon=True).start()
    threading.Thread(target=command_listener_interface, daemon=True).start()
    
    while True:
        time.sleep(1)