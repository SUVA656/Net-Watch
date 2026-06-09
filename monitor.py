import socket
import threading
import json
import glob
import io
import os
import sys
import base64
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import customtkinter as ctk
import time
from datetime import datetime, timedelta

# Import the Drag and Drop modules
from tkinterdnd2 import TkinterDnD, DND_FILES

# Maintain original network port configuration matrices
AGENT_PORT = 5005      
COMMAND_PORT = 6006    
SCREEN_STREAM_PORT = 7007  

network_database = {}

# Place near your other global dictionaries/configurations
DASHBOARD_SYNC_STATE = {
    "last_sync_date": None  # Tracks the date string (YYYY-MM-DD) of the last run
}

DATA_STORE_DIR = "data_store"

GLOBAL_DAILY_ARCHIVE_REGISTRY = {
    "current_date": datetime.now().strftime("%Y-%m-%d"),
    "processed_ips": set()
}

# Strict preservation of original length-prefixed socket background processing listenerdef start_agent_listener(update_callback):
def start_agent_listener(update_callback):
    """
    Listens for TCP telemetry data on port 5005.
    Guarantees device registration by handling empty or partial payloads safely,
    while preserving active states such as global chat room allocations and web_logs accumulation.
    Optimized for production use with all console debugging prints removed.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('0.0.0.0', 5005))
        server.listen(50)
    except Exception:
        return

    while True:
        try:
            sock, addr = server.accept()
            client_ip = str(addr[0])
            
            len_bytes = sock.recv(4)
            if not len_bytes:
                sock.close()
                continue
            payload_len = int.from_bytes(len_bytes, byteorder='big')
            
            buffer = b""
            while len(buffer) < payload_len:
                chunk = sock.recv(min(payload_len - len(buffer), 4096))
                if not chunk: break
                buffer += chunk
            sock.close()

            if len(buffer) == payload_len:
                try:
                    payload = json.loads(buffer.decode('utf-8', errors='ignore'))
                except Exception:
                    payload = {}

                # --- CHAT EXIT INTERCEPTOR ---
                if payload.get("action") == "agent_exit_chat":
                    if client_ip in network_database:
                        network_database[client_ip]["chat_status"] = "idle"
                    update_callback()
                    continue 

                # --- VIDEO CALL STATUS UPDATE INTERCEPTOR ---
                if payload.get("type") == "status_update":
                    if client_ip in network_database:
                        if payload.get("status") == "idle":
                            network_database[client_ip]["vc_status"] = "idle"
                            network_database[client_ip]["vc_peers"] = []
                        else:
                            network_database[client_ip]["vc_status"] = "in_vc"
                            network_database[client_ip]["vc_peers"] = payload.get("peers", [])
                    update_callback()
                    continue

                # Defensive initialization for core data blocks
                if "hostname" not in payload: payload["hostname"] = "WORKSTATION"
                if "os" not in payload: payload["os"] = "Windows 10/11"
                if "ram" not in payload: payload["ram"] = "Unknown RAM"
                if "cpu" not in payload: payload["cpu"] = "Unknown CPU"
                if "devices" not in payload: payload["devices"] = []
                
                # --- PROCESS DATA CAPTURE AND CACHING ---
                incoming_history = payload.get("web_logs", payload.get("history", []))
                
                existing_history_cache = []
                if client_ip in network_database:
                    existing_history_cache = network_database[client_ip].get("web_logs", network_database[client_ip].get("history", []))
                
                if not isinstance(existing_history_cache, list):
                    existing_history_cache = []

                backup_timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

                for log_item in incoming_history:
                    if isinstance(log_item, dict):
                        url_str = str(log_item.get("url", log_item.get("site", ""))).strip()
                        time_str = str(log_item.get("time", log_item.get("ip", log_item.get("timestamp", backup_timestamp)))).strip()
                        
                        if not url_str:
                            continue

                        # Dual key dictionary injection maps seamlessly to legacy/modern UI requirements
                        normalized_log = {
                            "url": url_str, 
                            "time": time_str,
                            "site": url_str,   
                            "ip": time_str     
                        }
                        
                        if normalized_log not in existing_history_cache:
                            existing_history_cache.append(normalized_log)

                payload["web_logs"] = existing_history_cache
                payload["history"] = existing_history_cache

                # Execute storage mechanics
                process_agent_daily_archive(client_ip, payload)
                
                # --- PERSIST CORRELATION STATES ---
                if client_ip in network_database and isinstance(network_database[client_ip], dict):
                    payload["chat_status"] = network_database[client_ip].get("chat_status", "idle")
                    payload["vc_status"] = network_database[client_ip].get("vc_status", "idle")
                    payload["vc_peers"] = network_database[client_ip].get("vc_peers", [])
                    payload["status"] = network_database[client_ip].get("status", "OFFLINE")
                    payload["is_active"] = network_database[client_ip].get("is_active", False)
                else:
                    payload["chat_status"] = "idle"
                    payload["vc_status"] = "idle"
                    payload["vc_peers"] = []
                    payload["status"] = "ACTIVE"
                    payload["is_active"] = True
                
                try:
                    payload["last_seen"] = datetime.now()
                except Exception:
                    payload["last_seen"] = backup_timestamp

                network_database[client_ip] = payload
                
                # Dynamic UI synchronization trigger
                update_callback()
                
                if hasattr(update_callback, '__self__'):
                    gui_instance = update_callback.__self__
                    if hasattr(gui_instance, 'compile_startup_device_list'):
                        gui_instance.compile_startup_device_list()

        except Exception:
            pass

def process_agent_daily_archive(agent_ip, payload_dict):
    """
    Saves current device hardware snapshots inside data_store/Device/<ip>/.
    Strictly discards browser history records and drops hardware state files 
    that are older than a rolling 7-day sequence window (today & past 6 days).
    """
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Reset tracking registry if calendar shifts while dashboard is running
        if GLOBAL_DAILY_ARCHIVE_REGISTRY["current_date"] != today_str:
            GLOBAL_DAILY_ARCHIVE_REGISTRY["current_date"] = today_str
            GLOBAL_DAILY_ARCHIVE_REGISTRY["processed_ips"].clear()

        # Dynamically build directory targets (Now includes the agent IP as a folder)
        device_dir = os.path.join(DATA_STORE_DIR, "Device", agent_ip)
        history_dir = os.path.join(DATA_STORE_DIR, "History")
        
        os.makedirs(device_dir, exist_ok=True)

        # --- STEP 1: IMMEDIATELY DROP/PREVENT HISTORY STORAGE ---
        if os.path.exists(history_dir):
            import shutil
            try:
                shutil.rmtree(history_dir)
            except Exception:
                pass

        # Exit if this agent has checked in and saved data already today
        if agent_ip in GLOBAL_DAILY_ARCHIVE_REGISTRY["processed_ips"]:
            return
            
        # --- STEP 2: PACKAGE AND SAVE CURRENT HARDWARE CONFIG ---
        device_payload = {
            "archive_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "system_specs": {
                "hostname": payload_dict.get("hostname"),
                "os": payload_dict.get("os"),
                "cpu": payload_dict.get("cpu"),
                "ram": payload_dict.get("ram"),
                "mac": payload_dict.get("mac")
            },
            "connected_devices": payload_dict.get("devices", []),
            "usb_status": payload_dict.get("usb_status")
        }
        
        # Save nested: data_store/Device/<ip>/hardware_<date>.json
        device_file_path = os.path.join(device_dir, f"hardware_{today_str}.json")
        with open(device_file_path, "w", encoding="utf-8") as f:
            json.dump(device_payload, f, indent=4, ensure_ascii=False)
            
        # Prevent secondary writes for this client for the remainder of the day
        GLOBAL_DAILY_ARCHIVE_REGISTRY["processed_ips"].add(agent_ip)
        print(f"[+] Hardware backup synchronized for agent: {agent_ip}")
        
        # --- STEP 3: ENFORCE ROLLING 7-DAY HARDWARE RETENTION POLICY ---
        # Generate an array containing allowed filenames for today and the last 6 days
        allowed_filenames = [
            f"hardware_{(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')}.json"
            for i in range(7)
        ]
        
        # Scan inside this specific agent's folder for expired logs
        for file_path in glob.glob(os.path.join(device_dir, "*.json")):
            filename = os.path.basename(file_path)
            
            if filename not in allowed_filenames:
                try:
                    os.remove(file_path)
                    print(f"[*] Purged expired historical hardware snapshot: {agent_ip}/{filename}")
                except Exception:
                    pass
                    
    except Exception as e:
        print(f"[-] Failed to execute daily archive filtering pass for {agent_ip}: {e}")

class RemoteSessionWindow:
    def __init__(self, parent_root, target_ip, dispatch_cmd_fn):
        self.parent_root = parent_root
        self.target_ip = target_ip
        self.dispatch_command_packet = dispatch_cmd_fn
        self.is_streaming = True
        self.stream_socket = None

        # High-end CustomTkinter Toplevel window context allocation
        self.window = ctk.CTkToplevel(parent_root)
        self.window.title(f"REMOTE SESSION // NODE: {target_ip}")
        self.window.geometry("1024x800")
        self.window.configure(bg="#0A0D14")

        # Top interactive bar using Dribbble HEX design specifications
        self.top_bar = ctk.CTkFrame(self.window, fg_color="#141923", corner_radius=12)
        self.top_bar.pack(fill=tk.X, side=tk.TOP, padx=15, pady=(15, 5))
        
        self.status_lbl = ctk.CTkLabel(
            self.top_bar, 
            text=f"LIVE FEED: {target_ip}  |  Control Active  |  Drop Files on Canvas", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), 
            text_color="#00F0FF"
        )
        self.status_lbl.pack(side=tk.LEFT, padx=20, pady=12)

        self.btn_close = ctk.CTkButton(
            self.top_bar, text="DISCONNECT", 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), 
            fg_color="#FF3B30", text_color="#F5F6F9", hover_color="#CC2F26",
            height=32, corner_radius=16, command=self.close_session
        )
        self.btn_close.pack(side=tk.RIGHT, padx=15, pady=10)

        self.btn_upload = ctk.CTkButton(
            self.top_bar, text="CHOOSE & DEPLOY FILE", 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), 
            fg_color="#1B2332", text_color="#F5F6F9", hover_color="#243147",
            border_width=1, border_color="#243147",
            height=32, corner_radius=16, command=self.execute_canvas_file_upload
        )
        self.btn_upload.pack(side=tk.RIGHT, padx=5, pady=10)

        # Canvas Wrapper container adhering to strict custom layouts
        self.window.resizable(True, True)
        self.screen_canvas = tk.Canvas(
            self.window, 
            width=800, 
            height=600, 
            bg="black", 
            highlightthickness=0, 
            bd=0
        )
        self.screen_canvas.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        # Core interaction canvas tracking metrics mapping vectors back to host machine
        self.screen_canvas.bind("<Motion>", self.send_mouse_move)
        self.screen_canvas.bind("<ButtonPress-1>", self.handle_left_click_down)
        self.screen_canvas.bind("<ButtonRelease-1>", lambda e: self.send_mouse_click(e, "left", "up"))
        self.screen_canvas.bind("<ButtonPress-3>", lambda e: self.send_mouse_click(e, "right", "down"))
        self.screen_canvas.bind("<ButtonRelease-3>", lambda e: self.send_mouse_click(e, "right", "up"))
        # --- BULLETPROOF KEYBOARD PROXY INTERFACE ---
        # We create a focused entry proxy that forces native string capturing
        self.keyboard_proxy = tk.Entry(self.window, width=0, bd=0, highlightthickness=0, bg="#0A0D14", fg="#0A0D14", insertbackground="#0A0D14")
        self.keyboard_proxy.place(x=-100, y=-100, width=1, height=1) # Hide it completely off-screen layout boundaries
        
        # Capture raw text string dumps
        self.keyboard_proxy.bind("<Key>", self.bulletproof_key_handler)
        
        # Force the entry to stay focused so typing works immediately
        self.window.bind("<Button-1>", lambda e: self.keyboard_proxy.focus_set())
        self.screen_canvas.bind("<Button-1>", lambda e: [self.handle_left_click_down(e), self.keyboard_proxy.focus_set()])
        self.keyboard_proxy.focus_force()

        # Re-attach the exact Drag and Drop protocol hooks to Tkinter Canvas widget instance
        self.screen_canvas.drop_target_register(DND_FILES)
        self.screen_canvas.dnd_bind('<<Drop>>', self.handle_file_drop_event)

        self.window.protocol("WM_DELETE_WINDOW", self.close_session)
        threading.Thread(target=self.pull_visual_stream_pipeline, daemon=True).start()

    def handle_left_click_down(self, event):
        self.screen_canvas.focus_set()
        self.send_mouse_click(event, "left", "down")

    def get_scaled_coordinates(self, event_x, event_y):
        cw = self.screen_canvas.winfo_width()
        ch = self.screen_canvas.winfo_height()
        if cw > 0 and ch > 0:
            return event_x / cw, event_y / ch
        return 0, 0

    def send_mouse_move(self, event):
        nx, ny = self.get_scaled_coordinates(event.x, event.y)
        self.dispatch_command_packet(self.target_ip, {"action": "mouse_move", "x": nx, "y": ny})

    def send_mouse_click(self, event, button, button_state):
        nx, ny = self.get_scaled_coordinates(event.x, event.y)
        self.dispatch_command_packet(self.target_ip, {"action": "mouse_click", "button": button, "state": button_state, "x": nx, "y": ny})

    def bulletproof_key_handler(self, event):
        """Captures raw characters and explicit command execution macro mappings directly."""
        char = event.char
        keysym = event.keysym
        
        # Handle systemic functional hotkeys directly as clean instructions
        functional_map = {
            "Return": "enter", "BackSpace": "backspace", "Tab": "tab", "Escape": "escape",
            "Delete": "delete", "space": "space", "Up": "up", "Down": "down", 
            "Left": "left", "Right": "right"
        }
        
        payload = {"action": "key_input", "mode": "direct"}
        
        if keysym in functional_map:
            payload["type"] = "functional"
            payload["value"] = functional_map[keysym]
        elif char:
            payload["type"] = "text"
            payload["value"] = char
        else:
            return "break" # Drop modifier keys entirely to keep pipeline clear
            
        self.dispatch_command_packet(self.target_ip, payload)
        return "break" # Prevents double-typing loops inside the hidden proxy widget

    def handle_file_drop_event(self, event):
        raw_filepath = event.data.strip()
        if raw_filepath.startswith('{') and raw_filepath.endswith('}'):
            raw_filepath = raw_filepath[1:-1].strip()
        clean_path = os.path.abspath(raw_filepath)
        if os.path.exists(clean_path) and os.path.isfile(clean_path):
            threading.Thread(target=self.process_and_transmit_file, args=(clean_path,), daemon=True).start()
        else:
            tk.messagebox.showwarning("Drop Rejection", f"Could not map input file layout path:\n{clean_path}")

    def execute_canvas_file_upload(self):
        selected_filepath = tk.filedialog.askopenfilename(title="Deploy Payload via Active Session Interface")
        if selected_filepath:
            clean_path = os.path.abspath(selected_filepath)
            threading.Thread(target=self.process_and_transmit_file, args=(clean_path,), daemon=True).start()

    def process_and_transmit_file(self, file_path):
        try:
            filename = os.path.basename(file_path)
            filesize = os.path.getsize(file_path)
            
            # 1. Create a lightweight handshake manifest metadata descriptor
            handshake_manifest = {
                "action": "drop_file", 
                "file_name": filename, 
                "file_size": filesize
            }
            
            # 2. Open a direct transmission pipe to the Agent's LISTEN_COMMAND_PORT (6006)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)
                s.connect((self.target_ip, 6006))
                
                # Encode and dispatch the JSON handshake package size first
                header_bytes = json.dumps(handshake_manifest).encode('utf-8')
                s.sendall(len(header_bytes).to_bytes(4, byteorder='big'))
                s.sendall(header_bytes)
                
                # Brief execution delay to let the Agent partition its system IO handles
                time.sleep(0.15)
                
                # 3. Stream out file content segments sequentially via 64KB block fragments
                with open(file_path, "rb") as target_file:
                    while True:
                        chunk = target_file.read(65536)
                        if not chunk:
                            break
                        s.sendall(chunk)
                        
            print(f"[File Engine] Dispatched payload asset: {filename} ({filesize} bytes)")
            
        except Exception as err:
            if hasattr(self, 'parent_root') and self.parent_root:
                self.parent_root.after(0, lambda: tk.messagebox.showerror("Canvas Engine Fault", f"Failed to transfer asset: {str(err)}"))
            elif hasattr(self, 'global_root_engine') and self.global_root_engine:
                self.global_root_engine.after(0, lambda: tk.messagebox.showerror("Canvas Engine Fault", f"Failed to transfer asset: {str(err)}"))

    def pull_visual_stream_pipeline(self):
        """Thread worker that pulls raw screen streams from the agent engine."""
        import io
        from PIL import Image, ImageTk
        import socket

        try:
            self.stream_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.stream_socket.settimeout(5.0)
            self.stream_socket.connect((self.target_ip, 7007)) # STREAM_SERVER_PORT
            
            while self.is_streaming:
                try:
                    len_bytes = self.stream_socket.recv(4)
                    if not len_bytes or len(len_bytes) < 4: 
                        break
                    size = int.from_bytes(len_bytes, byteorder='big')
                    
                    buffer = b""
                    while len(buffer) < size and self.is_streaming:
                        chunk = self.stream_socket.recv(min(size - len(buffer), 65536))
                        if not chunk: 
                            break
                        buffer += chunk
                    
                    if len(buffer) < size: 
                        break
                    
                    if not self.is_streaming:
                        break

                    # Convert and draw image frame
                    img = Image.open(io.BytesIO(buffer))
                    cw = self.screen_canvas.winfo_width()
                    ch = self.screen_canvas.winfo_height()
                    
                    if cw > 200 and ch > 200: 
                        img = img.resize((cw, ch), Image.Resampling.LANCZOS)
                    else:
                        img = img.resize((800, 600), Image.Resampling.LANCZOS)
                        
                    photo_img = ImageTk.PhotoImage(img)
                    self.parent_root.after(0, self.repaint_canvas, photo_img)
                    
                except OSError as e:
                    # Catch Windows socket errors (like 10038 / 10054) during active streaming
                    if getattr(e, 'winerror', None) == 10038:
                        break # Gracefully drop out of loop if socket was closed mid-receive
                    raise e
                    
        except Exception:
            pass # Suppress any initialization or socket connection errors from console
            
        finally:
            self.is_streaming = False
            
            # Isolated, double-guarded teardown to catch final cross-thread collision errors
            if hasattr(self, 'stream_socket') and self.stream_socket:
                try:
                    # Directly check validity via try/except blocks to satisfy the OS layer
                    self.stream_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                
                try:
                    self.stream_socket.close()
                except Exception:
                    pass
                
                self.stream_socket = None

            # Cleanly destroy the window via the main loop callback thread
            try:
                self.parent_root.after(0, self.safe_destroy_window)
            except Exception:
                pass

    def repaint_canvas(self, photo_img):
        """Safely updates the canvas element with the latest frame without gaps."""
        if not hasattr(self, 'screen_canvas') or not self.screen_canvas or not self.window.winfo_exists():
            return

        try:
            self.screen_canvas.current_display_img = photo_img

            self.screen_canvas.delete("all")
            import tkinter as tk
            self.screen_canvas.create_image(0, 0, anchor=tk.NW, image=photo_img)

        except Exception:
            pass

    def close_session(self):
        self.is_streaming = False
        try: self.dispatch_command_packet(self.target_ip, {"action": "unlock_input"})
        except Exception: pass
        if self.stream_socket:
            try: self.stream_socket.close()
            except Exception: pass
        self.safe_destroy_window()

    def safe_destroy_window(self):
        try: self.window.destroy()
        except Exception: pass


class LANMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("NEXUS // SECURE OPERATIONAL MATRIX ENGINE")
        self.root.geometry("1450x880")
        
        # --- THE DRIBBBLE HEX PALETTE DESIGN SYSTEM ---
        self.c_bg = "#0A0D14"          
        self.c_card = "#141923"        
        self.c_inner = "#1B2332"       
        self.c_accent = "#00F0FF"      
        self.c_alert = "#FF3B30"       
        self.c_text_main = "#F5F6F9"   
        self.c_text_muted = "#707E94"  
        self.c_border = "#243147"      

        # Configuration variables state matrix setup
        self.active_remote_ip = None
        self.active_session = None
        self.current_view = "history"
        
        # Tracking metrics for targeting single peripheral items
        self.selected_hardware_index = None
        self.hardware_row_widgets = []

        # Place this inside your LANMonitorGUI.__init__ constructor setup
        self.threat_whitelist = ["ayudh.net", "google.com", "github.com"]

        # Apply custom theme configurations
        ctk.set_appearance_mode("dark")
        self.root.configure(bg=self.c_bg)

        # --- MAIN RESPONSIVE APPLICATION FRAME ---
        self.main_container = ctk.CTkFrame(self.root, fg_color=self.c_bg, corner_radius=0)
        self.main_container.pack(fill=ctk.BOTH, expand=True, padx=25, pady=25)
        # Add the Broadcast Action Button in your header container layout
        # (Ensure this parent container matches where your existing dashboard headers are declared)
        # Create the container frame for the two side-by-side buttons
        button_container_frame = ctk.CTkFrame(self.root, fg_color="transparent")

        # =====================================================================
        # PLACE THIS REGISTRATION BLOCK OUTSIDE EXPLICITLY INSIDE YOUR MAIN UI GENERATOR
        # =====================================================================
        # --- NAVIGATION / UTILITY PANEL BUTTON GENERATION MATRIX ---

        self.btn_view_logs = ctk.CTkButton(
            button_container_frame,
            text="📂VIEW LOGS",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#4B5563",       # Charcoal Gray for utility system look
            hover_color="#374151",    
            text_color="#FFFFFF",
            width=110,
            height=34,
            command=self.open_list_folder
        )
        self.btn_view_logs.pack(side=tk.LEFT, fill=ctk.X, padx=(0, 5))

        btn_hw_change = ctk.CTkButton(
            button_container_frame, 
            text="HARDWARE CHANGE",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=self.c_accent, 
            hover_color="#2563EB",
            text_color="#000000",
            width=140,
            height=34,
            command=self.open_hardware_change_window
        )
        btn_hw_change.pack(side=tk.LEFT, fill=ctk.X, padx=(0, 5))

        # 2. VIDEO MATRIX BUTTON
        self.btn_video_call = ctk.CTkButton(
            button_container_frame,
            text="📹VIDEO MATRIX",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=self.c_accent,       
            hover_color="#00C8D4",       
            text_color="#0A0D14",        
            height=36,
            command=self.open_video_call_manager  
        )
        self.btn_video_call.pack(side=tk.LEFT, fill=ctk.X, padx=(5, 5))

        # 3. CHAT MANAGER BUTTON
        self.btn_chat_mgr = ctk.CTkButton(
            button_container_frame,
            text="🗨️CHAT MANAGER",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#FFFFFF",
            height=36,
            command=self.open_chat_management_window
        )
        self.btn_chat_mgr.pack(side=tk.LEFT, fill=ctk.X, padx=(5, 5))

        # 4. FILE DEPLOYER BUTTON
        self.btn_file_deployer = ctk.CTkButton(
            button_container_frame,
            text="📁 FILE DEPLOYER",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#3B82F6",       
            hover_color="#2563EB",    
            text_color="#FFFFFF",
            height=36,
            command=self.open_file_deployment_window
        )
        self.btn_file_deployer.pack(side=tk.LEFT, fill=ctk.X, padx=(5, 5))

        self.btn_threat_matrix = ctk.CTkButton(
            button_container_frame,
            text="🚨 THREAT MATRIX",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#D97706",       # Amber Warning Orange
            hover_color="#B45309",    
            text_color="#FFFFFF",
            height=36,
            command=self.open_threat_matrix_window
        )
        self.btn_threat_matrix.pack(side=tk.LEFT, fill=ctk.X, padx=(5, 5))

        # 5. BROADCAST SYSTEM ALERT BUTTON (Last on the right)
        self.btn_broadcast = ctk.CTkButton(
            button_container_frame,
            text="⚠️BROADCAST SYSTEM",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#EF4444",
            hover_color="#DC2626",
            text_color="#FFFFFF",
            height=36,
            command=self.open_broadcast_window
        )
        self.btn_broadcast.pack(side=tk.LEFT, fill=ctk.X, padx=(5, 0))

        # Render the toolbar cluster container frame
        button_container_frame.place(relx=1.0, rely=0.02, anchor="ne", x=-20)

        # --- HIGH-END SYSTEM-MATCHED TREEVIEW DESIGN SPECIFICATION ---
        style = ttk.Style()
        style.theme_use("clam")
        
        # Configure the core inner data row workspace grid Matrix
        style.configure("Treeview",background=self.c_inner,foreground=self.c_text_main,fieldbackground=self.c_inner,rowheight=32,font=("Segoe UI", 11),borderwidth=0,relief="flat")
        
        # Configure the top Sticky Column Headers Matrix
        style.configure(
            "Treeview.Heading", 
            background=self.c_card,        # Matching outer dashboard wrapper card fill (#141923)
            foreground=self.c_accent,      # Clean Cyber Neon Accent Cyan text (#00F0FF)
            relief="flat",                 # Flatten ugly hard retro beveled border dividers
            font=("Segoe UI", 11, "bold")  # Scaled typography configuration for priority tracking
        )
        
        # Handle Dynamic Interaction Selection states
        style.map(
            "Treeview", 
            background=[('selected', '#1E293B')], # Shifts background hue smoothly to highlight rows
            foreground=[('selected', self.c_accent)] # Highlights active targeted cell text string arrays
        )
        
        # Overwrite legacy styling components to strip native layout borders
        style.configure("Treeview", borderwidth=0, highlightthickness=0)
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})]) # Strips default hard white outer padding rules
        style.configure("Treeview.Heading", borderwidth=0)

        # =====================================================================
        # 1. FAR LEFT COLUMN: MANAGE ENDPOINTS LIST
        # =====================================================================
        self.endpoints_frame = ctk.CTkFrame(self.main_container, fg_color=self.c_card, corner_radius=16)
        self.endpoints_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.listbox_container = ctk.CTkFrame(self.endpoints_frame, fg_color=self.c_inner, corner_radius=12, border_width=1, border_color=self.c_border)
        self.listbox_container.pack(fill=ctk.BOTH, expand=True, padx=15, pady=20)

        # Custom Header Panel
        self.header_panel = ctk.CTkFrame(self.listbox_container, fg_color="transparent")
        self.header_panel.pack(fill=ctk.X, padx=15, pady=(15, 5))

        self.title_lbl = ctk.CTkLabel(
            self.header_panel, 
            text="MANAGED ENDPOINTS", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        )
        self.title_lbl.pack(side="left", anchor="w")

        self.refresh_btn = ctk.CTkButton(
            self.header_panel,
            text="🔄",
            width=30,
            height=30,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#10B981",
            hover_color="#059669",
            corner_radius=6,
            command=self.trigger_network_refresh
        )
        self.refresh_btn.pack(side="right", anchor="e")

        self.device_container = ctk.CTkScrollableFrame(self.listbox_container, fg_color="transparent")
        self.device_container.pack(fill=ctk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.selected_device_ip = None
        self.agent_statuses = {}
        self.trigger_network_refresh()
        # =====================================================================
        # RIGHT HAND SIDE CONTAINER
        # =====================================================================
        self.right_workspace_stack = ctk.CTkFrame(self.main_container, fg_color=self.c_bg, corner_radius=0)
        self.right_workspace_stack.grid(row=0, column=1, sticky="nsew", padx=(20, 0))

# Make sure the parent window columns scale properly when resized:
        self.main_container.grid_columnconfigure(0, weight=1) # Left side (endpoints list)
        self.main_container.grid_columnconfigure(1, weight=3) # Right side (workspace) gets more room
        self.main_container.grid_rowconfigure(0, weight=1)

        self.lbl_node_title = ctk.CTkLabel(
            self.right_workspace_stack, text="// ENDPOINT_MONITOR : STANDBY", 
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color=self.c_text_main
        )
        self.lbl_node_title.pack(anchor="w", pady=(0, 15))

        # 2. TOP STACK LAYER: SYSTEM HARDWARE SPEC
        self.build_rounded_hardware_bar()

        # 3. MIDDLE STACK LAYER: NAVIGATION INTERFACE
        self.build_rounded_navigation_row()

        # 4. BOTTOM STACK LAYER: NAVIGATION TABS DETAIL LIST
        self.workspace_detail_view = ctk.CTkFrame(self.right_workspace_stack, fg_color=self.c_card, corner_radius=16)
        self.workspace_detail_view.pack(fill=ctk.BOTH, expand=True)
        
        self.build_interactive_detail_panes()

    def open_threat_matrix_window(self):
        """Spawns the Threat Matrix window with a dynamic automatic live-refresh polling mechanism."""
        from tkinter import ttk

        threat_win = ctk.CTkToplevel(self.root)
        threat_win.title("Endpoint Threat Audit Logs")
        threat_win.geometry("850x500")
        
        # Prevent parent layer execution interactions while open
        threat_win.grab_set()  

        # --- Top Action Frame (Whitelist Add Tool) ---
        top_frame = ctk.CTkFrame(threat_win, height=60, fg_color="transparent")
        top_frame.pack(fill=ctk.X, padx=15, pady=10)

        lbl_whitelist = ctk.CTkLabel(top_frame, text="Whitelist Domain:", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"))
        lbl_whitelist.pack(side=tk.LEFT, padx=(0, 10))

        entry_domain = ctk.CTkEntry(top_frame, placeholder_text="e.g. platform.com", width=200)
        entry_domain.pack(side=tk.LEFT, padx=(0, 10))

        def add_to_whitelist():
            dom = entry_domain.get().strip().lower()
            if dom:
                if dom not in self.threat_whitelist:
                    self.threat_whitelist.append(dom)
                    tk.messagebox.showinfo("Success", f"'{dom}' added to whitelist.")
                    entry_domain.delete(0, tk.END)
                    refresh_table_data() 
                else:
                    tk.messagebox.showwarning("Notice", "Domain already whitelisted.")

        btn_add_wl = ctk.CTkButton(top_frame, text="Add Domain", fg_color="#10B981", hover_color="#059669", width=100, command=add_to_whitelist)
        btn_add_wl.pack(side=tk.LEFT)

        # --- Main Table Grid Frame ---
        table_frame = ctk.CTkFrame(threat_win)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        columns = ("ip", "threat", "url", "timestamp")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#1E293B", foreground="#F8FAFC", fieldbackground="#1E293B", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#334155", foreground="#FFFFFF", font=("Segoe UI", 11, "bold"))
        
        # FIX: Explicit style maps ensure CustomTkinter doesn't override item text highlighting
        style.map("Treeview", background=[('selected', '#3B82F6')], foreground=[('selected', '#FFFFFF')])

        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        tree.heading("ip", text="Endpoint Source IP")
        tree.heading("threat", text="Threat Status")
        tree.heading("url", text="Target Destination URL")
        tree.heading("timestamp", text="Access Timestamp")

        tree.column("ip", width=140, anchor="center")
        tree.column("threat", width=120, anchor="center")
        tree.column("url", width=380, anchor="w")
        tree.column("timestamp", width=160, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure row color alerting tags
        tree.tag_configure("suspect_alert", background="#7F1D1D", foreground="#FEE2E2")
        tree.tag_configure("clean_log", background="#1E293B", foreground="#94A3B8")

        def refresh_table_data():
            """Clears and re-reads the global database variables live."""
            # Track selected item to preserve user focus across updates
            selected_item = tree.selection()
            selected_values = tree.item(selected_item)['values'] if selected_item else None

            # Flush screen data grid canvas
            for item in tree.get_children():
                tree.delete(item)

            # Re-read active application runtime state registers
            for ip, info in network_database.items():
                if not info or not isinstance(info, dict): 
                    continue
                
                logs = info.get("web_logs", [])
                for log in logs:
                    if not isinstance(log, dict): 
                        continue

                    url = str(log.get("url", "")).strip()
                    timestamp = str(log.get("time", "UNKNOWN")).strip()

                    if not url: 
                        continue

                    # Filter tracking parameters
                    url_clean = url.lower().replace("http://", "").replace("https://", "").replace("www.", "")
                    if url_clean.startswith("172."):
                        continue

                    is_whitelisted = any(str(awl).strip().lower() in url_clean for awl in self.threat_whitelist if str(awl).strip())
                    threat_tag = "CLEAN" if is_whitelisted else "SUSPECT"
                    if threat_tag == "CLEAN":
                        continue
                    # Populate row elements
                    item_id = tree.insert("", tk.END, values=(ip, threat_tag, url, timestamp))
                    
                    # Apply row styling tags
                    if threat_tag == "SUSPECT":
                        tree.item(item_id, tags=("suspect_alert",))
                    else:
                        tree.item(item_id, tags=("clean_log",))

            # Restore user selection if the item still exists
            if selected_values:
                for item in tree.get_children():
                    if tree.item(item)['values'] == selected_values:
                        tree.selection_set(item)
                        break

        def auto_loop_refresh():
            """Triggers every 2000ms (2 seconds) to sync with background thread telemetry."""
            if threat_win.winfo_exists():  # Safely break loop cycle if operator exits the view window
                refresh_table_data()
                threat_win.after(2000, auto_loop_refresh)

        # Initial call loops to sync active state pipelines instantly
        refresh_table_data()
        auto_loop_refresh()

    def open_list_folder(self):
        """Cross-platform hook to spawn the native OS file manager pointing to data_store/list"""
        import os
        import platform
        import subprocess

        # Target directory pathing setup
        target_dir = os.path.abspath(os.path.join("data_store", "list"))
        
        # Self-healing check: Ensure the folder structural sequence exists safely
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        try:
            current_os = platform.system().lower()
            if current_os == "windows":
                os.startfile(target_dir)
            elif current_os == "darwin":  # macOS context profile
                subprocess.Popen(["open", target_dir])
            else:  # Linux distributions
                subprocess.Popen(["xdg-open", target_dir])
        except Exception as e:
            tk.messagebox.showerror(
                "System Error", 
                f"Failed to access local file matrix subsystem: {str(e)}"
            )

    def compile_startup_device_list(self):
        """
        Compiles a comprehensive structural hardware mapping across all endpoints
        by reading the latest offline JSON files on bootup.
        """
        import os
        import json
        from datetime import datetime

        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            list_dir = os.path.join("data_store", "List")
            base_device_dir = os.path.join("data_store", "Device")
            os.makedirs(list_dir, exist_ok=True)

            output_file_path = os.path.join(list_dir, f"{today_str}.txt")

            lines = [
                "======================================================================================",
                f" NETWORK SYSTEM SPECIFICATION MATRIX LOG // GENERATED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "======================================================================================",
                f"{'IP ADDRESS':<18} | {'DEVICE TYPE':<20} | DEVICE NAME",
                "-------------------|----------------------|-------------------------------------------"
            ]

            has_records = False

            # Check if directory exists and has subfolders
            if os.path.exists(base_device_dir):
                # Loop through every IP folder under data_store/Device/
                for ip_folder in sorted(os.listdir(base_device_dir)):
                    ip_path = os.path.join(base_device_dir, ip_folder)
                    
                    if os.path.isdir(ip_path):
                        # Find today's file or the most recent log file inside this IP directory
                        target_file = os.path.join(ip_path, f"hardware_{today_str}.json")
                        
                        # Fallback: if today's file doesn't exist yet, get the most recent log file
                        if not os.path.exists(target_file):
                            all_files = sorted(glob.glob(os.path.join(ip_path, "*.json")))
                            if all_files:
                                target_file = all_files[-1] # Pick freshest historical entry
                        
                        if os.path.exists(target_file):
                            try:
                                with open(target_file, "r", encoding="utf-8") as f:
                                    payload = json.load(f)
                                
                                specs = payload.get("system_specs", {})
                                ram_val = specs.get("ram")
                                cpu_val = specs.get("cpu")

                                if ram_val:
                                    lines.append(f"{ip_folder:<18} | {'SYSTEM RAM':<20} | {ram_val}")
                                    has_records = True
                                if cpu_val:
                                    lines.append(f"{ip_folder:<18} | {'SYSTEM CPU':<20} | {cpu_val}")
                                    has_records = True

                                for dev in payload.get("connected_devices", []):
                                    dev_type = str(dev.get("type", "GENERIC")).upper()
                                    dev_name = dev.get("name", "UNKNOWN COMPONENT")
                                    dev_status = dev.get("status", "Active")
                                    lines.append(f"{ip_folder:<18} | {dev_type:<20} | {dev_name} [{dev_status}]")
                                    has_records = True
                                    
                                lines.append("-------------------|----------------------|-------------------------------------------")
                            except Exception:
                                pass

            if not has_records:
                lines.append(" [!] No active hardware configurations found registered inside network storage logs.")

            with open(output_file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                
            print(f"[+] Global database inventory log table compiled at: {output_file_path}")

        except Exception as e:
            print(f"[-] Critical failure during compilation matrix generation: {e}")

    def open_hardware_change_window(self):
        """Spawns an administrative grid module panel displaying tracked differences across 7 days."""
        if hasattr(self, 'hw_change_win') and self.hw_change_win and self.hw_change_win.winfo_exists():
            self.hw_change_win.lift()
            return

        self.hw_change_win = ctk.CTkToplevel(self.root)
        self.hw_change_win.title("HARDWARE MUTATION TRACE LOGS")
        self.hw_change_win.geometry("850x550")
        self.hw_change_win.configure(fg_color=self.c_inner)
        self.hw_change_win.attributes("-topmost", True)

        # Header Title
        lbl_title = ctk.CTkLabel(
            self.hw_change_win, 
            text="// HARDWARE SPECIFICATION DRIFT MATRIX (7-DAY ANALYSIS WINDOW)", 
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), 
            text_color=self.c_accent
        )
        lbl_title.pack(anchor=tk.W, padx=25, pady=(20, 10))

        # Main Scrollable Container Table Window Frame Context
        table_container = ctk.CTkScrollableFrame(self.hw_change_win, fg_color=self.c_card, border_width=1, border_color=self.c_border)
        table_container.pack(fill=tk.BOTH, expand=True, padx=25, pady=(5, 25))

        # Grid Header Labels Layout 
        headers = ["IP ADDRESS", "DEVICE TYPE", "PREVIOUS COMPONENT SNAPSHOT", "CURRENT COMPONENT SNAPSHOT"]
        widths = [130, 120, 260, 260]

        header_frame = ctk.CTkFrame(table_container, fg_color=self.c_inner, height=36, corner_radius=4)
        header_frame.pack(fill=ctk.X, pady=(0, 10))
        header_frame.pack_propagate(False)

        for col_idx, text in enumerate(headers):
            lbl_h = ctk.CTkLabel(
                header_frame, text=text, 
                font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                text_color=self.c_text_main, width=widths[col_idx], anchor=tk.W
            )
            lbl_h.pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # --- DATA GENERATION & DELTA COMPILER PASS ---
        import os
        import glob
        import json
        from datetime import datetime, timedelta

        active_ips = [ip for ip, info in network_database.items() if info.get("status", "OFFLINE") != "OFFLINE"]
        base_device_dir = os.path.join("data_store", "Device")
        historical_days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 7)]

        has_changes = False

        for ip in active_ips:
            current_data = network_database.get(ip, {})
            current_devices = current_data.get("devices", [])
            current_specs = current_data.get("system_specs", {
                "hostname": current_data.get("hostname", "UNKNOWN"),
                "os": current_data.get("os", "UNKNOWN"),
                "cpu": current_data.get("cpu", "UNKNOWN"),
                "ram": current_data.get("ram", "UNKNOWN"),
                "mac": current_data.get("mac", "UNKNOWN")
            })
            
            # Target directory for this specific IP subfolder
            ip_device_dir = os.path.join(base_device_dir, ip)
            
            # Find baseline history data file from oldest to newest day
            old_payload = None
            for past_date in reversed(historical_days):
                hist_file = os.path.join(ip_device_dir, f"hardware_{past_date}.json")
                if os.path.exists(hist_file):
                    try:
                        with open(hist_file, "r", encoding="utf-8") as f:
                            old_payload = json.load(f)
                            break
                    except Exception:
                        pass

            if old_payload is None:
                continue

            # Check System Specs (RAM)
            old_specs = old_payload.get("system_specs", {})
            old_ram = old_specs.get("ram", "[UNKNOWN RAM]")
            new_ram = current_specs.get("ram", "[UNKNOWN RAM]")
            
            if old_ram != new_ram:
                has_changes = True
                row_frame = ctk.CTkFrame(table_container, fg_color="transparent")
                row_frame.pack(fill=ctk.X, pady=4)

                ctk.CTkLabel(row_frame, text=ip, font=ctk.CTkFont(family="Consolas", size=11), width=widths[0], anchor=tk.NW, text_color="#FFFFFF").pack(side=tk.LEFT, padx=10, fill=tk.Y)
                ctk.CTkLabel(row_frame, text="SYSTEM RAM", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), width=widths[1], anchor=tk.NW, text_color="#F59E0B").pack(side=tk.LEFT, padx=10, fill=tk.Y)
                ctk.CTkLabel(row_frame, text=old_ram, font=ctk.CTkFont(family="Segoe UI", size=11), width=widths[2], justify=tk.LEFT, anchor=tk.NW, text_color="#94A3B8").pack(side=tk.LEFT, padx=10, fill=tk.Y)
                ctk.CTkLabel(row_frame, text=new_ram, font=ctk.CTkFont(family="Segoe UI", size=11), width=widths[3], justify=tk.LEFT, anchor=tk.NW, text_color="#10B981").pack(side=tk.LEFT, padx=10, fill=tk.Y)

                sep = ctk.CTkFrame(table_container, height=1, fg_color=self.c_border)
                sep.pack(fill=ctk.X, pady=4)

            # Peripheral device diffing loop
            old_devices_list = old_payload.get("connected_devices", [])
            
            current_map = {}
            for d in current_devices:
                dtype = str(d.get("type", "GENERIC")).strip().upper()
                current_map.setdefault(dtype, []).append(f"{d.get('name', 'UNKNOWN')} [{d.get('status', 'ACTIVE')}]")

            old_map = {}
            for d in old_devices_list:
                dtype = str(d.get("type", "GENERIC")).strip().upper()
                old_map.setdefault(dtype, []).append(f"{d.get('name', 'UNKNOWN')} [{d.get('status', 'ACTIVE')}]")

            all_types = set(list(current_map.keys()) + list(old_map.keys()))

            for dev_type in all_types:
                old_list = sorted(old_map.get(dev_type, []))
                new_list = sorted(current_map.get(dev_type, []))

                if old_list != new_list:
                    has_changes = True
                    old_str = "\n".join(old_list) if old_list else "[COMPONENT REMOVED / NONE]"
                    new_str = "\n".join(new_list) if new_list else "[COMPONENT REMOVED / NONE]"

                    row_frame = ctk.CTkFrame(table_container, fg_color="transparent")
                    row_frame.pack(fill=ctk.X, pady=4)

                    ctk.CTkLabel(row_frame, text=ip, font=ctk.CTkFont(family="Consolas", size=11), width=widths[0], anchor=tk.NW, text_color="#FFFFFF").pack(side=tk.LEFT, padx=10, fill=tk.Y)
                    ctk.CTkLabel(row_frame, text=dev_type, font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), width=widths[1], anchor=tk.NW, text_color=self.c_accent).pack(side=tk.LEFT, padx=10, fill=tk.Y)
                    ctk.CTkLabel(row_frame, text=old_str, font=ctk.CTkFont(family="Segoe UI", size=11), width=widths[2], justify=tk.LEFT, anchor=tk.NW, text_color="#94A3B8").pack(side=tk.LEFT, padx=10, fill=tk.Y)
                    ctk.CTkLabel(row_frame, text=new_str, font=ctk.CTkFont(family="Segoe UI", size=11), width=widths[3], justify=tk.LEFT, anchor=tk.NW, text_color="#10B981").pack(side=tk.LEFT, padx=10, fill=tk.Y)

                    sep = ctk.CTkFrame(table_container, height=1, fg_color=self.c_border)
                    sep.pack(fill=ctk.X, pady=4)

        if not has_changes:
            lbl_empty = ctk.CTkLabel(
                table_container, 
                text="✔ No hardware modifications or configuration anomalies detected across active endpoints within the last 6 days.", 
                font=ctk.CTkFont(family="Segoe UI", size=12, slant="italic"), 
                text_color="#94A3B8"
            )
            lbl_empty.pack(pady=40)

    def open_video_call_manager(self):
        """Spawns an auto-refreshing checkbox-driven dashboard displaying real-time 
        endpoint availability, filtering for verified active webcams, current room peers, and busy locks."""
        
        vc_win = tk.Toplevel(self.root) 
        vc_win.title("VIDEO CALL LINK MANAGER")
        vc_win.geometry("550x480") 
        vc_win.configure(bg=self.c_bg)
        vc_win.resizable(False, False)

        lbl_header = tk.Label(
            vc_win, 
            text="// ACTIVE PEER VIDEO MATRIX SYSTEM", 
            font=("Consolas", 11, "bold"), 
            fg=self.c_accent, 
            bg=self.c_bg, 
            anchor="w"
        )
        lbl_header.pack(fill=tk.X, padx=20, pady=(20, 5))

        lbl_status = tk.Label(
            vc_win, 
            text="STATUS: STANDBY // SELECT AT LEAST 2 PARTICIPANTS WITH VERIFIED WEBCAMS", 
            font=("Segoe UI", 9, "bold"), 
            fg=self.c_text_muted, 
            bg=self.c_card, 
            bd=0, 
            height=2
        )
        lbl_status.pack(fill=tk.X, padx=20, pady=5)

        # Scrollable frame container to neatly stack our checkbox rows
        scroll_container = ctk.CTkScrollableFrame(
            vc_win, 
            fg_color=self.c_inner, 
            border_width=1, 
            border_color=self.c_border,
            corner_radius=12
        )
        scroll_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Tracking states across redraw cycles
        checkbox_registry = {}  # Format: { ip: {"variable": BooleanVar, "widget": CTkCheckBox, "label": CTkLabel} }

        def rebuild_and_sync_roster():
            """Queries the network layout grid dynamically every 1.5 seconds,
            filtering out devices without cameras updating statuses and locks cleanly."""
            if not vc_win.winfo_exists():
                return

            # Gather currently active endpoints from layout container
            discovered_pcs = []
            try:
                for widget in self.device_container.winfo_children():
                    if hasattr(widget, "winfo_children"):
                        for sub_w in widget.winfo_children():
                            txt = getattr(sub_w, "_text", "") or ""
                            if not txt and hasattr(sub_w, "cget"):
                                try: txt = sub_w.cget("text")
                                except: pass
                            
                            parts = str(txt).replace("\n", " ").split()
                            for part in parts:
                                part_clean = part.strip()
                                if part_clean.count(".") == 3 and all(i.isdigit() for i in part_clean.split(".")):
                                    if part_clean not in discovered_pcs:
                                        discovered_pcs.append(part_clean)
            except:
                pass

            if not discovered_pcs:
                try: discovered_pcs = list(self.active_agents.keys())
                except: discovered_pcs = []

            # --- DYNAMIC WEBCAM TELEMETRY FILTERING BLOCK ---
            live_pcs = []
            for ip in discovered_pcs:
                if ip in ["127.0.0.1", "localhost"]:
                    continue

                # Check if agent exists in database and is marked online
                if "network_database" in globals() and ip in network_database:
                    db_payload = network_database[ip]
                    if isinstance(db_payload, dict):
                        # Verify the general agent runtime state is not flagged offline
                        if str(db_payload.get("status", "ACTIVE")).strip().upper() == "OFFLINE":
                            continue

                        # Inspect core device tree telemetry arrays for video capture indicators
                        raw_devices = db_payload.get("devices", [])
                        has_hardware_webcam = False
                        
                        for dev in raw_devices:
                            dev_type = str(dev.get("type", "")).strip().upper()
                            dev_status = str(dev.get("status", "ACTIVE")).strip().upper()
                            
                            # Look for Camera, Imaging, or Video Capture device keys that are active
                            if dev_type in ["CAMERA", "IMAGE", "VIDEO_CAPTURE"] and dev_status == "ACTIVE":
                                has_hardware_webcam = True
                                break
                        
                        # Only append to the visible roster loop pass if hardware verification checks clear
                        if has_hardware_webcam:
                            live_pcs.append(ip)

            # Remove widgets for devices that went offline or disconnected their webcam
            for old_ip in list(checkbox_registry.keys()):
                if old_ip not in live_pcs:
                    checkbox_registry[old_ip]["frame"].destroy()
                    del checkbox_registry[old_ip]

            # Render or update device rows
            for ip in live_pcs:
                agent_state_info = "Idle (Camera Verified)"
                is_busy = False
                
                try:
                    if "network_database" in globals() and ip in network_database:
                        db_payload = network_database[ip]
                        if isinstance(db_payload, dict) and db_payload.get("vc_status") == "in_vc":
                            peer_list = ", ".join(db_payload.get("vc_peers", []))
                            agent_state_info = f"In VC with [{peer_list}]"
                            is_busy = True
                    elif hasattr(self, "active_agents") and isinstance(self.active_agents, dict) and ip in self.active_agents:
                        payload = self.active_agents[ip]
                        if isinstance(payload, dict) and payload.get("vc_status") == "in_vc":
                            peer_list = ", ".join(payload.get("vc_peers", []))
                            agent_state_info = f"In VC with [{peer_list}]"
                            is_busy = True
                except Exception as e:
                    print(f"[VC Sync Debug]: {e}")

                # If this IP is completely new and verified, generate its UI row components
                if ip not in checkbox_registry:
                    row_frame = ctk.CTkFrame(scroll_container, fg_color="transparent")
                    row_frame.pack(fill=ctk.X, pady=4, padx=5)

                    chk_var = tk.BooleanVar(value=False)
                    
                    cb = ctk.CTkCheckBox(
                        row_frame,
                        text=f"  {ip}",
                        variable=chk_var,
                        font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                        text_color=self.c_text_main,
                        border_color=self.c_border,
                        checkmark_color=self.c_bg,
                        fg_color=self.c_accent,
                        hover_color="#00C8D4"
                    )
                    cb.pack(side=tk.LEFT, anchor="w")

                    lbl_state = ctk.CTkLabel(
                        row_frame,
                        text="",
                        font=ctk.CTkFont(family="Consolas", size=10, weight="bold")
                    )
                    lbl_state.pack(side=tk.RIGHT, anchor="e", padx=10)

                    checkbox_registry[ip] = {
                        "frame": row_frame,
                        "variable": chk_var,
                        "checkbox": cb,
                        "label": lbl_state
                    }

                # Dynamically update structural attributes based on real-time status changes
                registry_item = checkbox_registry[ip]
                registry_item["label"].configure(text=f"// {agent_state_info.upper()}")
                
                if is_busy:
                    registry_item["variable"].set(False)
                    registry_item["checkbox"].configure(state="disabled", text_color=self.c_text_muted)
                    registry_item["label"].configure(text_color=self.c_alert)
                else:
                    registry_item["checkbox"].configure(state="normal", text_color=self.c_text_main)
                    registry_item["label"].configure(text_color=self.c_accent)

            # Queue secondary recursive sync cycle execution pass in 1500ms
            vc_win.after(1500, rebuild_and_sync_roster)

        def initiate_video_broadcast():
            """Assembles chosen hosts, ensures zero policy violations, and dispatches webcam directives."""
            selected_ips = [ip for ip, data in checkbox_registry.items() if data["variable"].get() == True]

            if len(selected_ips) < 2:
                lbl_status.config(
                    text=f"INVALID SELECTION: CHOSE {len(selected_ips)} PCs. AT LEAST 2 REQUIRED TO START VC.", 
                    fg=self.c_alert
                )
                return

            # Update database status locally for all selected hosts immediately so UI doesn't delay
            for ip in selected_ips:
                other_peers = [p for p in selected_ips if p != ip]
                if "network_database" in globals() and ip in network_database:
                    network_database[ip]["vc_status"] = "in_vc"
                    network_database[ip]["vc_peers"] = other_peers

            lbl_status.config(text=f"ESTABLISHING VIDEO ROUTE AMONG {len(selected_ips)} HOSTS...", fg="#10B981")

            payload = json.dumps({
                "action": "setup_video_room",
                "peers": selected_ips
            }).encode('utf-8')
            payload_len = len(payload)

            def broadcast_worker():
                for target_ip in selected_ips:
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.settimeout(2.0)
                            s.connect((target_ip, 6006))
                            s.sendall(payload_len.to_bytes(4, byteorder='big'))
                            s.sendall(payload)
                    except:
                        pass
                
                try:
                    lbl_status.config(text="// VIDEO CALL REQUEST DISPATCHED SUCCESSFULLY", fg=self.c_accent)
                except:
                    pass

            threading.Thread(target=broadcast_worker, daemon=True).start()

        # Initialize the live background updating runtime loop instantly
        rebuild_and_sync_roster()

        # Single Main Button Core Frame Controller Layout
        btn_start_vc = ctk.CTkButton(
            vc_win, 
            text="START VIDEO CALL MATRIX", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), 
            fg_color="#10B981", 
            hover_color="#059669", 
            text_color="#FFFFFF",
            height=40,
            corner_radius=8,
            command=initiate_video_broadcast
        )
        btn_start_vc.pack(fill=tk.X, padx=20, pady=20)
        
    def trigger_network_refresh(self):
        """Asynchronously dispatches status requests to prevent UI lag."""
        import threading
        threading.Thread(target=self.broadcast_status_poll, daemon=True).start()


    def broadcast_status_poll(self):
        """
        Dynamically discovers the local LAN subnet subnet, sweeps all host IPs, 
        and adds discovered endpoints to the matrix state registry.
        """
        import socket
        import json
        import threading

        # --- STEP 1: RESOLVE LOCAL SUBNET RANGE DYNAMICALLY ---
        base_subnet = "192.168.1." # Default fallback
        try:
            # Open a temporary datagram socket to determine the active outbound interface IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                # Extract the subnet prefix (e.g., converts '192.168.1.45' into '192.168.1.')
                base_subnet = ".".join(local_ip.split(".")[:3]) + "."
        except Exception:
            pass

        # Generate a list of all potential host IPs on a typical /24 subnet (1 to 254)
        scan_targets = [f"{base_subnet}{i}" for i in range(1, 255)]

        payload = {"action": "poll_status"}
        payload_bytes = json.dumps(payload).encode('utf-8')
        payload_len = len(payload_bytes)

        # Thread-safe result container
        discovered_states = {}
        lock = threading.Lock()

        # --- STEP 2: HIGH-SPEED WORKER SUB-ROUTINE ---
        def probe_target_ip(ip):
            try:
                # Target the administrative listening infrastructure port 6006 bound by agents
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.4)  # Aggressive timeout for blazing fast LAN sweeps
                    s.connect((ip, 6006))
                    
                    # Direct binary payload length packet framing transmission
                    s.sendall(payload_len.to_bytes(4, byteorder='big'))
                    s.sendall(payload_bytes)
                    
                    # If connection passes, store verified online data structures
                    with lock:
                        discovered_states[ip] = {
                            "status": "ACTIVE",
                            "is_active": True,
                            "hostname": f"NODE-{ip.split('.')[-1]}", # Temporary fallback name
                            "os": "Windows 10/11",
                            "chat_status": "idle"
                        }
            except (socket.timeout, ConnectionRefusedError, OSError):
                # If a device was previously found but is now dark, flag it offline safely
                if 'network_database' in globals() and ip in network_database:
                    with lock:
                        discovered_states[ip] = network_database[ip].copy()
                        discovered_states[ip]["status"] = "OFFLINE"
                        discovered_states[ip]["is_active"] = False

        # Dispatch probe workers across multiple parallel threads to avoid lag
        threads = []
        for target_ip in scan_targets:
            t = threading.Thread(target=probe_target_ip, args=(target_ip,))
            t.daemon = True
            threads.append(t)
            t.start()

        # Wait for all network probe operations to return
        for t in threads:
            t.join()

        # --- STEP 3: MERGE DISCOVERIES WITH MEMORY STATE MAP ---
        if 'network_database' not in globals():
            globals()['network_database'] = {}

        for ip, fresh_data in discovered_states.items():
            if ip in network_database:
                # Merge fields selectively so you don't overwrite chat states or telemetry arrays
                network_database[ip]["status"] = fresh_data["status"]
                network_database[ip]["is_active"] = fresh_data["is_active"]
            else:
                # Register entirely brand new machine found on the LAN wire
                network_database[ip] = fresh_data

        # Re-sync with main thread to rebuild the user interface views safely
        if hasattr(self, 'refresh_device_list'):
            self.root.after(0, self.refresh_device_list)
        elif hasattr(self, 'update_data_panes'):
            self.root.after(0, lambda: self.update_data_panes(self.selected_device_ip))

    def open_file_deployment_window(self):
        """Spawns a styled deployment controller panel matching the design system."""
        deploy_win = ctk.CTkToplevel(self.root)
        deploy_win.title("NEXUS // FILE DEPLOYMENT SUB-SYSTEM")
        deploy_win.geometry("580x460") # Slightly increased height to accommodate the toggle
        deploy_win.configure(fg_color=self.c_bg)
        deploy_win.attributes("-topmost", True)
        deploy_win.resizable(False, False)

        # Main wrapper padding layout card
        wrapper = ctk.CTkFrame(deploy_win, fg_color=self.c_card, corner_radius=12, border_width=1, border_color=self.c_border)
        wrapper.pack(fill=ctk.BOTH, expand=True, padx=20, pady=20)

        # Title Label
        ctk.CTkLabel(
            wrapper, text="REMOTE FILE DISTRIBUTION ENGINE", 
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), text_color=self.c_accent
        ).pack(anchor="w", padx=20, pady=(20, 15))

        # --- SECTION 1: SOURCE FILE SELECTOR ---
        ctk.CTkLabel(wrapper, text="Select Source File:", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_text_muted).pack(anchor="w", padx=20)
        
        file_selection_frame = ctk.CTkFrame(wrapper, fg_color="transparent")
        file_selection_frame.pack(fill=ctk.X, padx=20, pady=(4, 15))

        selected_file_path = tk.StringVar(value="No file selected...")
        
        file_entry = ctk.CTkEntry(file_selection_frame, textvariable=selected_file_path, font=ctk.CTkFont(family="Segoe UI", size=11), fg_color=self.c_inner, border_color=self.c_border, text_color=self.c_text_main, state="readonly")
        file_entry.pack(side=tk.LEFT, fill=ctk.X, expand=True, padx=(0, 8))

        def browse_local_file():
            from tkinter import filedialog
            chosen = filedialog.askopenfilename()
            if chosen:
                selected_file_path.set(chosen)

        browse_btn = ctk.CTkButton(file_selection_frame, text="Browse...", width=90, fg_color=self.c_inner, border_width=1, border_color=self.c_border, hover_color="#243147", command=browse_local_file)
        browse_btn.pack(side=tk.RIGHT)

        # --- SECTION 2: DESTINATION PATH CONFIGURATOR ---
        ctk.CTkLabel(wrapper, text="Target Deployment Destination Path:", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_text_muted).pack(anchor="w", padx=20)
        
        dest_path_entry = ctk.CTkEntry(
            wrapper, 
            font=ctk.CTkFont(family="Segoe UI", size=11), 
            fg_color=self.c_inner, 
            border_color=self.c_border, 
            text_color=self.c_accent,
            placeholder_text=r"C:\Program Files\Agent_track"
        )
        dest_path_entry.pack(fill=ctk.X, padx=20, pady=(4, 15))
        dest_path_entry.insert(0, r"C:\Program Files\Agent_track") 

        # --- NEW SECTION: AUTO-RUN EXECUTION TOGGLE ---
        auto_run_var = tk.BooleanVar(value=False)
        auto_run_check = ctk.CTkCheckBox(
            wrapper, 
            text="Execute immediately on remote endpoint upon landing (Auto-Run)",
            variable=auto_run_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=self.c_text_main,
            fg_color="#3B82F6",
            hover_color="#2563EB"
        )
        auto_run_check.pack(anchor="w", padx=20, pady=(0, 15))

        # --- SECTION 3: DEPLOYMENT EXECUTION CONTROL ---
        status_lbl = ctk.CTkLabel(wrapper, text="Status: Standby.", font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"), text_color=self.c_text_muted)
        status_lbl.pack(anchor="w", padx=20, pady=(0, 10))

        def trigger_mass_distribution():
            src = selected_file_path.get()
            dest = dest_path_entry.get().strip()
            should_execute = auto_run_var.get()
            
            import os
            if not src or src == "No file selected..." or not os.path.exists(src):
                status_lbl.configure(text="Status Error: Please specify a valid local source file.", text_color=self.c_alert)
                return
            if not dest:
                status_lbl.configure(text="Status Error: Deployment path cannot be empty.", text_color=self.c_alert)
                return

            status_lbl.configure(text="Status: Distributing packets...", text_color=self.c_accent)
            
            import threading
            threading.Thread(target=execute_network_file_push, args=(src, dest, should_execute, status_lbl), daemon=True).start()

        def execute_network_file_push(local_file, remote_target_dir, auto_run_flag, feedback_ui_lbl):
            import socket
            import json
            import os

            filename = os.path.basename(local_file)
            file_size = os.path.getsize(local_file)

            active_targets = []
            if 'network_database' in globals():
                for ip, data in network_database.items():
                    if data.get("status") == "ACTIVE" or data.get("is_active") is True:
                        active_targets.append(ip)

            if not active_targets:
                deploy_win.after(0, lambda: feedback_ui_lbl.configure(text="Status: Cancelled. No active endpoint machines detected.", text_color=self.c_alert))
                return

            success_counter = 0
            
            # Formulate clear instructions payload dynamically mapped to UI checkbox context
            directive = {
                "action": "drop_file",
                "file_name": filename,
                "file_size": file_size,
                "target_directory": remote_target_dir,
                "auto_run": auto_run_flag  # Dynamic execution context
            }
            directive_bytes = json.dumps(directive).encode('utf-8')
            directive_len = len(directive_bytes)

            for target_ip in active_targets:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(6.0) 
                        s.connect((target_ip, 6006))
                        
                        s.sendall(directive_len.to_bytes(4, byteorder='big'))
                        s.sendall(directive_bytes)
                        
                        with open(local_file, "rb") as f:
                            while True:
                                chunk = f.read(65536)
                                if not chunk:
                                    break
                                s.sendall(chunk)
                        success_counter += 1
                except Exception as e:
                    print(f"[DEPLOYMENT PIPELINE EXCEPTION] Node connection failure ({target_ip}): {e}")

            final_msg = f"Status: Completed. Uploaded successfully to [{success_counter}/{len(active_targets)}] endpoints."
            txt_color = "#10B981" if success_counter > 0 else self.c_alert
            deploy_win.after(0, lambda: feedback_ui_lbl.configure(text=final_msg, text_color=txt_color))

        action_btn = ctk.CTkButton(
            wrapper, text="🚀 UPDATE AGENT FILES", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#3B82F6", hover_color="#2563EB", height=40,
            command=trigger_mass_distribution
        )
        action_btn.pack(fill=ctk.X, padx=20, pady=(10, 10))

    def get_device_signature(self, device_dict):
        """
        Generates a normalized, unique lookup key for a hardware device
        by combining its core properties and stripping white spaces/casing.
        """
        if not device_dict:
            return ""
        dev_name = str(device_dict.get("name", "")).strip().upper()
        dev_type = str(device_dict.get("type", "")).strip().upper()
        raw_id = str(device_dict.get("raw_id", "")).strip().upper()
        
        return f"{dev_type}_{dev_name}_{raw_id}"

    def update_browsing_history_display(self, raw_history_data):
        if not hasattr(self, 'history_table'):
            return

        # Wipe out old entries cleanly
        for item in self.history_table.get_children():
            self.history_table.delete(item)

        if not raw_history_data:
            return

        # Parse new incoming entries safely
        for line in raw_history_data.split("\n"):
            if not line.strip():
                continue
            try:
                parts = line.split("|")
                if len(parts) >= 3:
                    self.history_table.insert("", tk.END, values=(parts[0].strip(), parts[1].strip(), parts[2].strip()))
                else:
                    self.history_table.insert("", tk.END, values=(line.strip(), "N/A", "N/A"))
            except Exception:
                pass

    def build_rounded_hardware_bar(self):
        specs_wrapper = ctk.CTkFrame(self.right_workspace_stack, fg_color=self.c_card, corner_radius=16)
        specs_wrapper.pack(fill=ctk.X, pady=(0, 20))

        inner_content = ctk.CTkFrame(specs_wrapper, fg_color="transparent")
        inner_content.pack(fill=ctk.X, padx=20, pady=18)

        ctk.CTkLabel(
            inner_content, text="SYSTEM HARDWARE SPECIFICATION TELEMETRY", 
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), text_color=self.c_text_muted
        ).pack(anchor="w", pady=(0, 12))

        self.flex_row = ctk.CTkFrame(inner_content, fg_color="transparent", corner_radius=0)
        self.flex_row.pack(fill=ctk.X)

        self.specs_labels = {}
        fields_definitions = ["IP Address","Device Name","Operating System","Memory (RAM)","Processor","MAC Address"]
        
        for field in fields_definitions:
            item_capsule = ctk.CTkFrame(self.flex_row, fg_color=self.c_inner, corner_radius=25, border_width=1, border_color=self.c_border)
            item_capsule.pack(side=tk.LEFT, expand=True, fill=ctk.X, padx=5)
            
            lbl_f = ctk.CTkFrame(item_capsule, fg_color="transparent")
            lbl_f.pack(fill=ctk.BOTH, padx=18, pady=10)
            
            ctk.CTkLabel(lbl_f, text=field.upper(), font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"), text_color=self.c_accent).pack(anchor="w")
            lbl_val = ctk.CTkLabel(lbl_f, text="-", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=self.c_text_main)
            lbl_val.pack(anchor="w", pady=(2, 0))
            
            self.specs_labels[field] = lbl_val

    def build_rounded_navigation_row(self):
        nav_wrapper = ctk.CTkFrame(self.right_workspace_stack, fg_color=self.c_bg, corner_radius=0)
        nav_wrapper.pack(fill=ctk.X, pady=(0, 20))

        self.nav_buttons = {}
        tab_definitions = [
            ("history", "🕒  Browsing History"),
            ("hardware", "🛡️  Connected Hardware"),
            ("remote", "🖥️  Remote Live Session"),
            ("notify", "🔔  Notification Engine")
        ]

        for key, text in tab_definitions:
            btn = ctk.CTkButton(
                nav_wrapper, text=text, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color=self.c_text_muted, fg_color=self.c_card, hover_color=self.c_inner,
                height=48, corner_radius=24, border_width=0, cursor="hand2",
                command=lambda k=key: self.switch_view(k)
            )
            btn.pack(side=tk.LEFT, fill=ctk.X, expand=True, padx=(0, 10))
            self.nav_buttons[key] = btn

    def build_interactive_detail_panes(self):
        # -----------------------------------------------------------------
        # PANE 1: BROWSING HISTORY LOG GRID
        # -----------------------------------------------------------------

        self.history_frame = ctk.CTkFrame(self.workspace_detail_view,fg_color=self.c_card,corner_radius=22)

        # OUTER PADDING LAYER
        outer_pad = ctk.CTkFrame(self.history_frame,fg_color="transparent")
        outer_pad.pack(fill=ctk.BOTH, expand=True, padx=12, pady=12)

        # INNER ROUNDED CONTAINER
        inner_hist = ctk.CTkFrame(outer_pad,fg_color=self.c_inner,corner_radius=18)
        inner_hist.pack(fill=ctk.BOTH, expand=True)

        columns = ("url", "timestamp")

        self.history_table = ttk.Treeview(inner_hist,columns=columns,show="headings",style="Treeview")

        self.history_table.heading("url", text="URL / Website Address")
        self.history_table.heading("timestamp", text="Time Stamp")

        self.history_table.column("url", anchor=tk.NW, width=500, minwidth=250)
        self.history_table.column("timestamp", anchor=tk.CENTER, width=110, minwidth=90)

        scrollbar = ctk.CTkScrollbar(inner_hist,orientation="vertical",command=self.history_table.yview)

        self.history_table.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT,fill=tk.Y,padx=(0, 8),pady=8)

        self.history_table.pack(side=tk.LEFT,fill=tk.BOTH,expand=True,padx=(8, 0),pady=8)
        # --------------------------------------------------------
        # Note: Your original raw text widget string parser line (self.tree) 
        # can remain or be removed depending on whether you're transitioning 
        # fully over to the Treeview widget system!
        # -----------------------------------------------------------------
        # PANE 2: CONNECTED HARDWARE SUBSYSTEM LIST (With Sticky Top Headers)
        # -----------------------------------------------------------------
        self.hardware_frame = ctk.CTkFrame(self.workspace_detail_view, fg_color=self.c_card, corner_radius=16)
        inner_hw = ctk.CTkFrame(self.hardware_frame, fg_color="transparent")
        inner_hw.pack(fill=ctk.BOTH, expand=True, padx=20, pady=20)

        self.hw_action_header = ctk.CTkFrame(inner_hw, fg_color="transparent")
        self.hw_action_header.pack(fill=tk.X, side=tk.TOP, pady=(0, 12))

        self.hw_info_lbl = ctk.CTkLabel(
            self.hw_action_header, text="SELECT A CONNECTED DEVICE ROW ITEM BELOW TO TARGET INTERACTION:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_text_muted
        )
        self.hw_info_lbl.pack(side=tk.LEFT, anchor="w")

        self.btn_smart_unblock = ctk.CTkButton(
            self.hw_action_header, text="SMART UNBLOCK DEVICE", 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), 
            fg_color="#22c55e", text_color="#ffffff", hover_color="#1aa14c",
            height=34, corner_radius=17, command=lambda: self.execute_smart_hardware_action("unblock")
        )
        self.btn_smart_unblock.pack(side=tk.RIGHT, padx=5)
        
        self.btn_smart_block = ctk.CTkButton(
            self.hw_action_header, text="SMART BLOCK DEVICE", 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), 
            fg_color=self.c_alert, text_color="#ffffff", hover_color="#CC2F26",
            height=34, corner_radius=17, command=lambda: self.execute_smart_hardware_action("block")
        )
        self.btn_smart_block.pack(side=tk.RIGHT, padx=5)
        
        # Live Scrollable Container for Interactive Selection Rows
        self.hw_scroll_container = ctk.CTkScrollableFrame(
            inner_hw, fg_color=self.c_inner, corner_radius=12, border_width=1, border_color=self.c_border
        )
        self.hw_scroll_container.pack(fill=ctk.BOTH, expand=True)
        # -----------------------------------------------------------------
        # PANE 3: REMOTE DESKTOP LIVE STREAM SHELL
        # -----------------------------------------------------------------
        self.remote_frame = ctk.CTkFrame(self.workspace_detail_view, fg_color=self.c_card, corner_radius=16)
        inner_rem = ctk.CTkFrame(self.remote_frame, fg_color="transparent")
        inner_rem.pack(fill=ctk.BOTH, expand=True, padx=25, pady=25)

        ctk.CTkLabel(inner_rem, text="[ REMOTE MANAGEMENT ENGINE ]", font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"), text_color=self.c_text_main).pack(anchor="w")
        ctk.CTkLabel(inner_rem, text="Click the option below to launch interactive live visualization interfaces.\nPrepares highly-optimized secure frame socket pipes to hook display pipeline metrics natively.", font=ctk.CTkFont(family="Segoe UI", size=12), text_color=self.c_text_muted, justify=tk.LEFT).pack(anchor="w", pady=(4, 25))
        
        self.btn_launch_gui = ctk.CTkButton(
            inner_rem, text="LAUNCH LIVE REMOTE CONTROL WINDOW", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), 
            fg_color="#22c55e", text_color="#ffffff", hover_color="#1aa14c",
            height=44, corner_radius=22, command=self.open_remote_session
        )
        self.btn_launch_gui.pack(anchor="w")
        # -----------------------------------------------------------------
        # PANE 4: DIRECTIVE NOTIFICATION ALERT TRANSMITTER ENGINE
        # -----------------------------------------------------------------
        self.notify_frame = ctk.CTkFrame(self.workspace_detail_view, fg_color=self.c_card, corner_radius=16)
        inner_notif = ctk.CTkFrame(self.notify_frame, fg_color="transparent")
        inner_notif.pack(fill=ctk.BOTH, expand=True, padx=25, pady=25)

        ctk.CTkLabel(inner_notif, text="[ DIRECT CONSOLE NOTIFICATION ENGINE ]", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), text_color=self.c_accent).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(inner_notif, text="Transmit native Windows Toast pop-ups to the target client active user session.", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=self.c_text_muted).pack(anchor="w", pady=(0, 20))
        
        ctk.CTkLabel(inner_notif, text="NOTIFICATION HEADER / TITLE:", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_text_muted).pack(anchor="w", pady=(0, 6))
        self.ent_title = ctk.CTkEntry(
            inner_notif, fg_color=self.c_inner, text_color=self.c_text_main, border_color=self.c_border,
            height=42, corner_radius=12, font=ctk.CTkFont(family="Segoe UI", size=12)
        )
        self.ent_title.pack(fill=ctk.X, pady=(0, 20))
        self.ent_title.insert(0, "ADMINISTRATIVE ALERT")

        ctk.CTkLabel(inner_notif, text="NOTIFICATION BODY / MESSAGE CONTENT:", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_text_muted).pack(anchor="w", pady=(0, 6))
        self.txt_message = ctk.CTkTextbox(
            inner_notif, fg_color=self.c_inner, text_color=self.c_text_main, border_color=self.c_border, border_width=1,
            height=110, corner_radius=12, font=ctk.CTkFont(family="Segoe UI", size=12)
        )
        self.txt_message.pack(fill=ctk.X, pady=(0, 25))
        self.txt_message.insert("1.0", "Attention: A remote system maintenance sequence is currently being deployed to this workstation.")

        self.btn_send_notify = ctk.CTkButton(
            inner_notif, text="BROADCAST NOTIFICATION TO AGENT", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), 
            fg_color="#3b82f6", text_color="#ffffff", hover_color="#2563eb",
            height=46, corner_radius=23, command=self.submit_notification_payload
        )
        self.btn_send_notify.pack(anchor="w")

        # Allocate default visible panel view
        self.history_frame.pack(fill=ctk.BOTH, expand=True)
        self.repaint_navigation_tabs()

    def switch_view(self, target_view):
        self.current_view = target_view
        self.history_frame.pack_forget()
        self.hardware_frame.pack_forget()
        self.remote_frame.pack_forget()
        self.notify_frame.pack_forget()

        if target_view == "history":
            self.history_frame.pack(fill=ctk.BOTH, expand=True)
        elif target_view == "hardware":
            self.hardware_frame.pack(fill=ctk.BOTH, expand=True)
        elif target_view == "remote":
            self.remote_frame.pack(fill=ctk.BOTH, expand=True)
        elif target_view == "notify":
            self.notify_frame.pack(fill=ctk.BOTH, expand=True)
            
        self.repaint_navigation_tabs()
        self.refresh_current_selection_data()

    def repaint_navigation_tabs(self):
        for key, btn in self.nav_buttons.items():
            if key == self.current_view:
                btn.configure(fg_color=self.c_inner, text_color=self.c_accent)
            else:
                btn.configure(fg_color=self.c_card, text_color=self.c_text_muted)

    def refresh_current_selection_data(self):
        """
        Refreshes data panes based on the explicitly tracked 
        selected IP string instead of legacy listbox item positions.
        """
        # --- FIX: Read directly from the class pointer instead of self.device_listbox ---
        if hasattr(self, 'selected_device_ip') and self.selected_device_ip:
            self.update_data_panes(self.selected_device_ip)
        else:
            # Fallback handling if no client device has been selected yet
            for item in self.history_table.get_children():
                self.history_table.delete(item)
            self.lbl_node_title.configure(text="// ENDPOINT_MONITOR : STANDBY")

            
    def refresh_device_list(self):
        """Thread-safe caller wrapper that safely schedules a UI update execution."""
        if hasattr(self, 'root') and self.root:
            self.root.after(0, self._update_ui)

    def _update_ui(self):
        """
        Upgraded UI renderer. Replaces old mono-color listbox items 
        with vibrant, multi-colored custom element asset cards.
        """
        # 1. Clear out all existing row widgets from the container
        for child in self.device_container.winfo_children():
            child.destroy()

        if not network_database:
            placeholder = ctk.CTkLabel(
                self.device_container, 
                text="Waiting for corporate agent check-ins...", 
                font=ctk.CTkFont(family="Segoe UI", size=12, slant="italic"),
                text_color=self.c_text_muted if hasattr(self, 'c_text_muted') else "#888888"
            )
            placeholder.pack(pady=20)
            return

        # 2. Rebuild the device deck dynamically
        for ip, data in network_database.items():
            is_active = data.get("is_active", True)
            hostname = data.get("hostname", "WORKSTATION")
            
            # Establish explicit color rules independently from the text font color
            badge_color = "#22c55e" if is_active else "#ef4444" # Vivid Green vs Corporate Red
            arrow_symbol = "" if is_active else ""
            status_text = "ACTIVE" if is_active else "OFFLINE"
            
            # Determine card background style if this specific device is clicked/selected
            is_selected = (ip == self.selected_device_ip)
            if is_selected:
                card_bg = self.c_inner if hasattr(self, 'c_inner') else "#2b2b2b"
                border_color = self.c_accent if hasattr(self, 'c_accent') else "#1f6aa5"
            else:
                card_bg = self.c_card if hasattr(self, 'c_card') else "#212121"
                border_color = self.c_border if hasattr(self, 'c_border') else "#333333"

            # Create the clickable base container card for the device row
            row_card = ctk.CTkFrame(
                self.device_container, 
                fg_color=card_bg, 
                border_color=border_color, 
                border_width=1, 
                height=42, 
                corner_radius=6,
                cursor="hand2"
            )
            row_card.pack(fill=ctk.X, pady=4, padx=2)
            row_card.pack_propagate(False)

            # A. The Dot & Arrow Indicator (Vibrant Colored Component)
            lbl_indicator = ctk.CTkLabel(
                row_card, 
                text=f"● {arrow_symbol}", 
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color=badge_color
            )
            lbl_indicator.pack(side=tk.LEFT, padx=(12, 4))

            # B. System Details String (Standard Main Text Font Color)
            display_details = f"{ip}  ({hostname})"
            lbl_details = ctk.CTkLabel(
                row_card, 
                text=display_details, 
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="normal"),
                text_color=self.c_text_main if hasattr(self, 'c_text_main') else "#ffffff"
            )
            lbl_details.pack(side=tk.LEFT, padx=6)

            # C. Inactive/Active Right-Aligned Badge Tag
            lbl_status_tag = ctk.CTkLabel(
                row_card,
                text=status_text,
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color=badge_color
            )
            lbl_status_tag.pack(side=tk.RIGHT, padx=12)

            # 3. Bind the mouse-click action across all child elements inside the row card
            # This ensures clicking anywhere on the row registers the selection perfectly
            bind_selection = lambda e, target_ip=ip: self.select_device_endpoint(target_ip)
            row_card.bind("<Button-1>", bind_selection)
            lbl_indicator.bind("<Button-1>", bind_selection)
            lbl_details.bind("<Button-1>", bind_selection)
            lbl_status_tag.bind("<Button-1>", bind_selection)
    
        if hasattr(self, 'chat_mgr_win') and self.chat_mgr_win and self.chat_mgr_win.winfo_exists():
            self.refresh_chat_matrix_list()


    def select_device_endpoint(self, ip):
        """Sets the active system focus pointer and updates side panels instantly."""
        self.selected_device_ip = ip
        
        # Redraw the device panel deck to update highlight border frames dynamically
        self._update_ui()
        
        # Repopulate hardware specifications, histories, or stream server sockets downstream
        self.update_data_panes(ip)

    def on_device_select(self, event):
        self.selected_hardware_index = None
        self.refresh_current_selection_data()

    def highlight_hardware_row(self, index):
        """Highlights a single row to mark it as the selected device targeting matrix."""
        self.selected_hardware_index = index
        for idx, row_card in enumerate(self.hardware_row_widgets):
            if idx == index:
                row_card.configure(fg_color="#1E293B", border_color=self.c_accent) 
            else:
                row_card.configure(fg_color=self.c_card, border_color=self.c_border)

    def update_data_panes(self, ip):
        data = network_database.get(ip)
        if not data: 
            return
            
        is_active = data.get("is_active", True)
        
        # --- 1. SAFE DATA PANELS EXTRACTION & ASSIGNMENTS ---
        if "IP Address" in self.specs_labels:
            self.specs_labels["IP Address"].configure(text=ip)
            
        if "Device Name" in self.specs_labels:
            self.specs_labels["Device Name"].configure(text=str(data.get('hostname')))
            
        if "Operating System" in self.specs_labels:
            self.specs_labels["Operating System"].configure(text=str(data.get('os')))
        
        # Pull MAC address string safely (Supports both common payload naming structures)
        mac_address = str(data.get('mac', data.get('mac_address', 'N/A'))).strip()

        # COMPACT FIT CONFIGURATION: Ensure labels wrap nicely without ruining layout alignment
        for label_key in ["Operating System", "Memory (RAM)", "Processor", "MAC Address"]:
            if label_key in self.specs_labels:
                self.specs_labels[label_key].configure(wraplength=200, justify="left")

        # --- 2. OFFLINE STANDBY STATE OVERRIDES ---
        if not is_active:
            # Mask hardware variables cleanly when the endpoint drops off the matrix
            if "Memory (RAM)" in self.specs_labels:
                self.specs_labels["Memory (RAM)"].configure(text="Unavailable (Offline)")
            if "Processor" in self.specs_labels:
                self.specs_labels["Processor"].configure(text="Unavailable (Offline)")
            if "MAC Address" in self.specs_labels:
                self.specs_labels["MAC Address"].configure(text="Unavailable (Offline)")
                
            self.lbl_node_title.configure(text=f"// DATA FEED: SYSTEM_NODE_{ip} [DISCONNECTED]")
            self.active_remote_ip = None 

            # Wipe table frames
            for item in self.history_table.get_children():
                self.history_table.delete(item)
                
            for child in self.hw_scroll_container.winfo_children():
                child.destroy()
                
            placeholder = ctk.CTkLabel(
                self.hw_scroll_container, 
                text="Telemetry disconnected. Cannot pull asset profiles.", 
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), 
                text_color=self.c_alert
            )
            placeholder.pack(pady=20)
            
            # Recalculate layout for the offline placeholder message
            self.root.update_idletasks()
            if hasattr(self.hw_scroll_container, "_update_scrollbar"):
                self.hw_scroll_container._update_scrollbar()
            return  
            
        # --- 3. ACTIVE LIVE TELEMETRY STATE POPULATION ---
        if "Memory (RAM)" in self.specs_labels:
            self.specs_labels["Memory (RAM)"].configure(text=str(data.get('ram')))
            
        if "Processor" in self.specs_labels:
            self.specs_labels["Processor"].configure(text=str(data.get('cpu')))
            
        if "MAC Address" in self.specs_labels:
            # FIX: Force continuous hex strings to break into double stack columns so it fits compact UI tiles
            if len(mac_address) > 12 and " " not in mac_address:
                formatted_mac = f"{mac_address[:9]}\n{mac_address[9:]}"
            else:
                formatted_mac = mac_address
            self.specs_labels["MAC Address"].configure(text=formatted_mac)
            
        self.lbl_node_title.configure(text=f"// DATA FEED: SYSTEM_NODE_{ip}")
        self.active_remote_ip = ip

        # --- TABULAR BROWSING HISTORY VIEWER ---
        if self.current_view == "history":
            for item in self.history_table.get_children():
                self.history_table.delete(item)
                
            for item in data.get("history", []):
                site_url = str(item.get('site', 'N/A')).strip() 
                timestamp = str(item.get('ip', 'N/A')).strip()   
                self.history_table.insert("", tk.END, values=(site_url, timestamp))
            
        # --- SINGLE-ROW SELECTION HARDWARE INTERFACE ---
        elif self.current_view == "hardware":
            for child in self.hw_scroll_container.winfo_children():
                child.destroy()
                
            self.hardware_row_widgets = []
            raw_devices = data.get("devices", [])
            
            if not raw_devices:
                placeholder = ctk.CTkLabel(self.hw_scroll_container, text="No active peripheral channels reported.", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=self.c_text_muted)
                placeholder.pack(pady=20)
            else:
                BLOCKABLE_CLASSES = {"KEYBOARD", "MOUSE", "DISKDRIVE", "PRINTER", "PRINTQUEUE", "CAMERA", "IMAGE"}
                blockable_devices = []
                non_blockable_devices = []
                
                for dev in raw_devices:
                    dev_type = str(dev.get("type", "GENERIC")).strip().upper()
                    dev_name = str(dev.get("name", "")).strip().upper()
                    raw_id = str(dev.get("raw_id", "")).strip().upper()
                    
                    if "MICROSOFT" in dev_name or "ONENOTE" in dev_name or "PDF" in dev_name or "XPS" in dev_name:
                        is_blockable = False
                    elif "ROOT" in dev_name or "CONTROLLER" in dev_name or "ROOT" in raw_id:
                        is_blockable = False
                    elif dev_type == "DISKDRIVE":
                        if "USBSTOR" in raw_id or "USB" in raw_id:
                            is_blockable = True
                        else:
                            is_blockable = False 
                    else:
                        is_blockable = dev_type in BLOCKABLE_CLASSES

                    if is_blockable:
                        blockable_devices.append(dev)
                    else:
                        non_blockable_devices.append(dev)
                
                devices_list = blockable_devices + non_blockable_devices
                data["devices"] = devices_list

                if not hasattr(self, 'selected_device_id_key'):
                    self.selected_device_id_key = None
                
                def handle_hardware_click(event, target_device):
                    # FIX: Uses the unified signature engine method so event assignments match perfectly
                    self.selected_device_id_key = self.get_device_signature(target_device)
                    try:
                        actual_idx = data["devices"].index(target_device)
                        self.highlight_hardware_row(actual_idx)
                    except ValueError:
                        pass

                for idx, dev in enumerate(devices_list):
                    dev_type = str(dev.get("type", "GENERIC")).strip().upper()
                    dev_name = str(dev.get("name", "")).strip().upper()
                    raw_id = str(dev.get("raw_id", "")).strip().upper()
                    
                    if "MICROSOFT" in dev_name or "ONENOTE" in dev_name or "PDF" in dev_name or "XPS" in dev_name:
                        row_is_blockable = False
                    elif "ROOT" in dev_name or "CONTROLLER" in dev_name or "ROOT" in raw_id:
                        row_is_blockable = False
                    elif dev_type == "DISKDRIVE":
                        row_is_blockable = "USBSTOR" in raw_id or "USB" in raw_id
                    else:
                        row_is_blockable = dev_type in BLOCKABLE_CLASSES
                    
                    # FIX: Normalizes row strings casing context matching via helper function mapping
                    current_dev_sig = self.get_device_signature(dev)

                    row_card = ctk.CTkFrame(self.hw_scroll_container, fg_color=self.c_card, height=48, corner_radius=8, border_width=1, border_color=self.c_border, cursor="hand2")
                    row_card.pack(fill=ctk.X, pady=4, padx=5)
                    row_card.pack_propagate(False)
                    
                    self.hardware_row_widgets.append(row_card)
                    
                    if row_is_blockable:
                        dev_status = str(dev.get("status", "ACTIVE")).strip().upper()
                        status_color = "#22c55e" if dev_status == "ACTIVE" else self.c_alert
                        
                        status_dot = ctk.CTkFrame(row_card, width=10, height=10, corner_radius=5, fg_color=status_color)
                        status_dot.pack(side=tk.LEFT, padx=(15, 5))
                        status_dot.bind("<Button-1>", lambda e, d=dev: handle_hardware_click(e, d))
                    else:
                        status_spacer = ctk.CTkFrame(row_card, width=10, height=10, fg_color="transparent")
                        status_spacer.pack(side=tk.LEFT, padx=(15, 5))
                        status_spacer.bind("<Button-1>", lambda e, d=dev: handle_hardware_click(e, d))
                    
                    lbl_name = ctk.CTkLabel(
                        row_card, text=f"{str(dev.get('name'))}",
                        font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                        text_color=self.c_text_main
                    )
                    lbl_name.pack(side=tk.LEFT, padx=10)
                    
                    if row_is_blockable:
                        status_badge = ctk.CTkLabel(
                            row_card, text=dev_status,
                            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                            text_color="#ffffff", fg_color=status_color, corner_radius=6, width=75, height=24
                        )
                        status_badge.pack(side=tk.RIGHT, padx=15)
                        status_badge.bind("<Button-1>", lambda e, d=dev: handle_hardware_click(e, d))
                    
                    type_badge = ctk.CTkLabel(
                        row_card, text=dev_type,
                        font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                        text_color=self.c_accent, fg_color=self.c_inner, corner_radius=6, width=95, height=24
                    )
                    type_badge.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

                    row_card.bind("<Button-1>", lambda e, d=dev: handle_hardware_click(e, d))
                    lbl_name.bind("<Button-1>", lambda e, d=dev: handle_hardware_click(e, d))
                    type_badge.bind("<Button-1>", lambda e, d=dev: handle_hardware_click(e, d))
                    
                    if self.selected_device_id_key == current_dev_sig:
                        self.highlight_hardware_row(idx)

            # === CRITICAL GEOMETRY RECALCULATION SYNC ===
            # Force processing of dynamic widget allocations and un-collapse the CustomTkinter canvas
            self.root.update_idletasks()
            if hasattr(self.hw_scroll_container, "_update_scrollbar"):
                self.hw_scroll_container._update_scrollbar()
        # =====================================================================
        # --- MASTER USB SECURITY BAR GENERATION ---
        # =====================================================================
        
        # 1. Clean up old references to prevent layout compounding or widget overlapping
        if hasattr(self, 'usb_control_frame') and self.usb_control_frame:
            try:
                self.usb_control_frame.destroy()
            except Exception:
                pass

        # 2. Re-instantiate the panel container inside the hardware frame context
        self.usb_control_frame = ctk.CTkFrame(self.hardware_frame, fg_color=self.c_card, height=60)
        # Force it to anchor cleanly at the very bottom of the view panel
        self.usb_control_frame.pack(fill=ctk.X, padx=25, pady=(15, 20), side=tk.BOTTOM)
        self.usb_control_frame.pack_propagate(False) # Keep fixed height alignment sleek

        # 3. Pull status data from the database state engine (FIXED to use 'ip')
        active_data = network_database.get(ip, {}) if ip else {}
        current_usb_stat = active_data.get("usb_status", "ACTIVE") 

        # 4. Map conditions based on agent status responses
        if current_usb_stat == "BLOCKED":
            status_text = "BLOCKED"
            status_color = "#EF4444"      # Crimson Red
            btn_text = "ENABLE ALL USB PORTS"
            btn_color = "#10B981"      # Emerald Green
            btn_hover = "#059669"
            target_action = "unblock"
        else:
            status_text = "ACTIVE"
            status_color = "#10B981"      # Emerald Green (or fall back to self.c_accent)
            btn_text = "BLOCK ALL USB PORTS"
            btn_color = "#EF4444"      # Crimson Red
            btn_hover = "#DC2626"
            target_action = "block"

        # 5. Populate and render UI Matrix Components
        lbl_usb_title = ctk.CTkLabel(
            self.usb_control_frame, 
            text=f"// USB PORTS SECURITY MATRIX: [{status_text}]", 
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=status_color
        )
        lbl_usb_title.pack(side=tk.LEFT, padx=20, expand=False)

        btn_master_usb = ctk.CTkButton(
            self.usb_control_frame,
            text=btn_text,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=btn_color,
            hover_color=btn_hover,
            text_color="#FFFFFF",
            width=190,
            height=34,
            command=lambda: self.execute_master_usb_action(target_action)
        )
        btn_master_usb.pack(side=tk.RIGHT, padx=20)

    def _render_canvas_frame(self, pil_image):
        """Executes safely on the main Tkinter thread context via .after()"""
        from PIL import ImageTk
        try:
            # Check if window wasn't destroyed while the frame was in transit
            if hasattr(self, 'stream_canvas') and self.stream_canvas.winfo_exists():
                # Resize image dynamically to match canvas size if desired
                canvas_w = self.stream_canvas.winfo_width()
                canvas_h = self.stream_canvas.winfo_height()
                if canvas_w > 10 and canvas_h > 10:
                    pil_image = pil_image.resize((canvas_w, canvas_h))

                tk_img = ImageTk.PhotoImage(pil_image)
                
                # Save reference to prevent immediate garbage collection
                self.stream_canvas.current_frame = tk_img 
                self.stream_canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)
        except Exception:
            pass

    def open_remote_session(self):
        """Cleanly instantiates the dedicated high-end RemoteSessionWindow class."""
        if not self.active_remote_ip:
            tk.messagebox.showwarning("Routing Error", "Please select an active agent host from the left endpoint index panel.")
            return

        # Check if an active session window already exists to prevent duplicate windows
        if hasattr(self, 'active_session') and self.active_session and self.active_session.window.winfo_exists():
            self.active_session.window.lift()
            return

        # Launch using your high-end dedicated session window class
        self.active_session = RemoteSessionWindow(
            parent_root=self.root, 
            target_ip=self.active_remote_ip, 
            dispatch_cmd_fn=self.dispatch_command_packet
        )

    def close_remote_session(self):
        """Handles proper teardown, killing threads and cleaning transparency issues."""
        
        # 1. SAFETY CHECK: If this function already ran, exit immediately!
        if self.stream_canvas is None:
            return

        # 2. Safely break the worker thread network loop flag
        try:
            self.stream_canvas.is_streaming = False
        except AttributeError:
            pass

        # 3. Destroy the Toplevel window container
        if hasattr(self, 'stream_win') and self.stream_win and self.stream_win.winfo_exists():
            try:
                self.stream_win.destroy()
            except Exception:
                pass

        # 4. Wipe references ONLY after window objects are fully destroyed
        self.stream_canvas = None
        self.stream_win = None

        # 5. Force the dashboard to repaint cleanly
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    def submit_notification_payload(self):
        if not self.active_remote_ip:
            tk.messagebox.showwarning("Routing Error", "Please select an active agent host from the left endpoint index panel.")
            return
        
        heading_text = self.ent_title.get().strip()
        body_text = self.txt_message.get("1.0", tk.END).strip()
        
        if not heading_text or not body_text:
            tk.messagebox.showwarning("Validation Error", "Notification Header and Message content entries cannot be blank.")
            return
            
        self.dispatch_command_packet(self.active_remote_ip, {
            "action": "send_notification",
            "title": heading_text,
            "message": body_text
        })

    def open_broadcast_window(self):
        """Spawns a sleek, dedicated modal UI window to broadcast a message to all endpoints."""
        # Prevent opening multiple broadcast windows simultaneously
        if hasattr(self, 'broadcast_win') and self.broadcast_win and self.broadcast_win.winfo_exists():
            self.broadcast_win.lift()
            return

        # Setup the Toplevel dialog context
        self.broadcast_win = ctk.CTkToplevel(self.root)
        self.broadcast_win.title("SYSTEM BROADCAST ENGINE")
        self.broadcast_win.geometry("400x320")
        self.broadcast_win.resizable(False, False)
        self.broadcast_win.attributes("-topmost", True)
        self.broadcast_win.configure(fg_color=self.c_inner)

        # Header Title
        lbl_header = ctk.CTkLabel(
            self.broadcast_win, 
            text="// EMERGENCY BROADCAST MATRIX", 
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), 
            text_color=self.c_accent
        )
        lbl_header.pack(anchor=tk.W, padx=20, pady=(20, 10))

        # --- FIELD 1: Type of Broadcast ---
        lbl_type = ctk.CTkLabel(self.broadcast_win, text="Broadcast Category / Type:", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_text_main)
        lbl_type.pack(anchor=tk.W, padx=20, pady=(5, 2))
        
        ent_type = ctk.CTkEntry(
            self.broadcast_win, 
            width=360, 
            height=32, 
            fg_color=self.c_card, 
            border_color=self.c_border, 
            text_color=self.c_text_main,
            placeholder_text="e.g., SYSTEM UPDATE, ALERT, MAINTENANCE"
        )
        ent_type.pack(padx=20, pady=(0, 10))

        # --- FIELD 2: Detail of Broadcast ---
        lbl_detail = ctk.CTkLabel(self.broadcast_win, text="Broadcast Context / Details:", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_text_main)
        lbl_detail.pack(anchor=tk.W, padx=20, pady=(5, 2))
        
        txt_detail = ctk.CTkTextbox(
            self.broadcast_win, 
            width=360, 
            height=100, 
            fg_color=self.c_card, 
            border_color=self.c_border, 
            text_color=self.c_text_main,
            wrap="word"
        )
        txt_detail.pack(padx=20, pady=(0, 15))

        # --- DISPATCH TRANSMISSION SYSTEM ---
        def execute_broadcast_dispatch():
            b_type = ent_type.get().strip()
            b_detail = txt_detail.get("1.0", tk.END).strip()

            # Optional guard validation (keeps user from sending empty packets by accident)
            if not b_type or not b_detail:
                return

            # Extract every available online IP address registered in the database
            connected_agent_ips = list(network_database.keys())

            # If there are no targets available, just exit cleanly
            if not connected_agent_ips:
                self.broadcast_win.destroy()
                return

            # Construct payload block
            payload = {
                "action": "send_notification",
                "title": b_type,
                "message": b_detail
            }

            # Map packets concurrently through background dispatch workers
            for target_ip in connected_agent_ips:
                self.dispatch_command_packet(target_ip, payload)
            
            # Destroy modal window immediately with no popups
            self.broadcast_win.destroy()

        # Action Buttons Wrapper
        btn_send = ctk.CTkButton(
            self.broadcast_win,
            text="TRANSMIT BROADCAST",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#EF4444", 
            hover_color="#DC2626",
            text_color="#FFFFFF",
            height=36,
            command=execute_broadcast_dispatch
        )
        btn_send.pack(fill=ctk.X, padx=20, pady=5)

    def open_chat_management_window(self):
        """Spawns the enlarged chat management control frame and binds a dynamic refresher."""
        if hasattr(self, 'chat_mgr_win') and self.chat_mgr_win and self.chat_mgr_win.winfo_exists():
            self.chat_mgr_win.lift()
            return

        self.chat_mgr_win = ctk.CTkToplevel(self.root)
        self.chat_mgr_win.title("GLOBAL CHAT ORCHESTRATOR")
        
        # --- INCREASED WINDOW GEOMETRY DIMENSIONS ---
        self.chat_mgr_win.geometry("550x500") 
        self.chat_mgr_win.resizable(False, False)
        self.chat_mgr_win.attributes("-topmost", True)
        self.chat_mgr_win.configure(fg_color=self.c_inner)
        
        lbl_title = ctk.CTkLabel(
            self.chat_mgr_win, 
            text="// ACTIVE CHAT MATRIX ROUTER", 
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), 
            text_color=self.c_accent
        )
        lbl_title.pack(anchor=tk.W, padx=25, pady=(20, 10))

        # --- EXPANDED INTERNAL SCROLLABLE CONTAINER SIZE ---
        self.chat_scroll_frame = ctk.CTkScrollableFrame(self.chat_mgr_win, width=500, height=330)
        self.chat_scroll_frame.pack(padx=25, pady=5, fill=tk.BOTH, expand=True)
        
        self.chat_checkbox_references = {}

        # Initial populate call to draw checkboxes when opened
        self.refresh_chat_matrix_list()

        def dispatch_chat_session():
            selected_ips = [ip for ip, cb in self.chat_checkbox_references.items() if cb.get() == 1]
            if len(selected_ips) < 2:
                tk.messagebox.showwarning("Routing Scope", "A chat room requires at least 2 active endpoints checked.")
                return

            participants_label = "in chat with " + ", ".join(selected_ips)
            chat_init_payload = {
                "action": "setup_chat_room",
                "peers": selected_ips
            }

            for target_ip in selected_ips:
                if target_ip in network_database:
                    network_database[target_ip]["chat_status"] = participants_label
                    self.dispatch_command_packet(target_ip, chat_init_payload)

            self.update_data_panes(self.active_remote_ip)
            self.chat_mgr_win.destroy()

        btn_start = ctk.CTkButton(
            self.chat_mgr_win,
            text="START CHAT SESSION",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#10B981",
            hover_color="#059669",
            height=42, # Made slightly chunkier to match the scale
            command=dispatch_chat_session
        )
        btn_start.pack(fill=ctk.X, padx=25, pady=20)

    def refresh_chat_matrix_list(self):
        """Wipes and completely regenerates the checkbox listing while preserving active selections."""
        if not hasattr(self, 'chat_mgr_win') or not self.chat_mgr_win or not self.chat_mgr_win.winfo_exists():
            return

        # --- STEP 1: SAVE CURRENT CHECKBOX STATES ---
        saved_selections = {}
        if hasattr(self, 'chat_checkbox_references'):
            for ip, cb in self.chat_checkbox_references.items():
                try:
                    saved_selections[ip] = cb.get()  # Stores 1 if checked, 0 if unchecked
                except:
                    pass

        # Destroy old checkboxes inside scroll container to prevent overlaps
        for widget in self.chat_scroll_frame.winfo_children():
            widget.destroy()

        self.chat_checkbox_references.clear()

        # Scan running runtime database matrix
        for ip, info in network_database.items():
            if not info or not isinstance(info, dict):
                continue
                
            status = str(info.get("status", "ACTIVE")).strip().upper()
            if status == "OFFLINE":
                continue
                
            hostname = info.get("hostname", f"Endpoint-{ip}")
            
            if "chat_status" not in info:
                info["chat_status"] = "idle"
                
            current_chat_state = str(info.get("chat_status", "idle")).strip().lower()
            display_label = f"{hostname} ({ip}) - [{current_chat_state.upper()}]"
            is_busy = "in chat" in current_chat_state
            
            chk = ctk.CTkCheckBox(
                self.chat_scroll_frame, 
                text=display_label,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                state="disabled" if is_busy else "normal"
            )
            chk.pack(anchor=tk.W, padx=10, pady=5)
            
            # --- STEP 2: RESTORE SELECTION STATE ---
            if not is_busy:
                self.chat_checkbox_references[ip] = chk
                if ip in saved_selections and saved_selections[ip] == 1:
                    chk.select()  # Re-check it automatically!

    def dispatch_command_packet(self, target_ip, data_dict):
        if not target_ip: return
        def worker():
            try:
                payload = json.dumps(data_dict).encode('utf-8')
                payload_len = len(payload)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    timeout_limit = 60.0 if data_dict.get("action") == "drop_file" else 5.0
                    s.settimeout(timeout_limit)
                    s.connect((target_ip, COMMAND_PORT))
                    s.sendall(payload_len.to_bytes(4, byteorder='big'))
                    s.sendall(payload)
            except Exception: 
                pass
        threading.Thread(target=worker, daemon=True).start()

    def execute_smart_hardware_action(self, process_type):
        if not self.active_remote_ip: return
        
        if not hasattr(self, 'selected_device_id_key') or self.selected_device_id_key is None:
            tk.messagebox.showwarning("Selection Required", "Please click on a specific device row item from the connection grid list first.")
            return

        data = network_database.get(self.active_remote_ip)
        if not data or not data.get("devices"): return

        devices_list = data.get("devices", [])
        
        target_dev = None
        for dev in devices_list:
            # FIX: Use the new unified casing generator method so signature lookups match perfectly
            if self.get_device_signature(dev) == self.selected_device_id_key:
                target_dev = dev
                break

        if target_dev is None:
            tk.messagebox.showerror("Sync Error", "Selected hardware is no longer reported by the target machine.")
            return

        # Double-check blockable status right before sending command packets
        check_name = str(target_dev.get("name", "")).upper()
        check_type = str(target_dev.get("type", "")).upper()
        check_id = str(target_dev.get("raw_id", "")).upper()
        
        is_actionable = True
        if "MICROSOFT" in check_name or "ONENOTE" in check_name or "PDF" in check_name or "XPS" in check_name:
            is_actionable = False
        elif "ROOT" in check_name or "CONTROLLER" in check_name or "ROOT" in check_id:
            is_actionable = False
        elif check_type == "DISKDRIVE" and not ("USBSTOR" in check_id or "USB" in check_id):
            is_actionable = False

        if not is_actionable:
            tk.messagebox.showwarning("Action Denied", "Protection protocols prevent modifications to core internal system assets.")
            return
        
        device_name = target_dev.get("name", "")
        device_class = target_dev.get("type", "")
        raw_id = target_dev.get("raw_id") if target_dev.get("raw_id") and target_dev.get("raw_id") != "None" else device_name

        # Mutate status changes safely
        target_dev["status"] = "BLOCKED" if process_type == "block" else "ACTIVE"
        
        # Repaint screen components layout immediately
        self.update_data_panes(self.active_remote_ip)

        if device_class.strip().lower() == "keyboard":
            action_directive = "lock_input" if process_type == "block" else "unlock_input"
            self.dispatch_command_packet(self.active_remote_ip, {"action": action_directive, "device_type": "Keyboard", "device_name": device_name, "raw_id": raw_id})
        else:
            action_directive = "block_device" if process_type == "block" else "unblock_device"
            self.dispatch_command_packet(self.active_remote_ip, {"action": action_directive, "device_type": device_class, "device_name": device_name, "raw_id": raw_id})

    def execute_master_usb_action(self, process_type):
        """Sends a global command to the agent to block or unblock all USB storage."""
        if not hasattr(self, 'active_remote_ip') or not self.active_remote_ip: 
            tk.messagebox.showwarning("Selection Required", "Please select an active computer endpoint target from the connection list first.")
            return
            
        confirm = tk.messagebox.askyesno(
            "Security Escalation", 
            f"Are you sure you want to {process_type.upper()} ALL USB storage devices on target PC [{self.active_remote_ip}]?"
        )
        if not confirm: 
            return

        action_directive = "block_all_usb" if process_type == "block" else "unblock_all_usb"
        
        # Optimistically set the local UI database state so it feels responsive
        if self.active_remote_ip in network_database:
            network_database[self.active_remote_ip]["usb_status"] = "BLOCKED" if process_type == "block" else "ACTIVE"
        
        # Construct and dispatch payload block via your thread background system
        payload = {"action": action_directive}
        self.dispatch_command_packet(self.active_remote_ip, payload)
        
        # Refresh the display immediately to reflect changes
        self.update_data_panes(self.active_remote_ip)

if __name__ == "__main__":
    # Pre-startup cleaning pass to parse nested IP subfolders
    import os
    import glob
    from datetime import datetime, timedelta
    
    base_device_dir = os.path.join("data_store", "Device")
    if os.path.exists(base_device_dir):
        allowed_filenames = [
            f"hardware_{(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')}.json"
            for i in range(7)
        ]
        
        for root_dir, dirs, files in os.walk(base_device_dir):
            for file in files:
                if file.endswith(".json") and file not in allowed_filenames:
                    try:
                        os.remove(os.path.join(root_dir, file))
                    except Exception:
                        pass

    root = TkinterDnD.Tk()
    ctk.deactivate_automatic_dpi_awareness()
    root.block_update_dimensions_event = lambda: None
    root.unblock_update_dimensions_event = lambda: None
    
    if hasattr(root, 'tk'):
        class TkExtensionWrapper:
            def __init__(self, original_tk):
                self._orig = original_tk
                self.block_update_dimensions_event = lambda: None
                self.unblock_update_dimensions_event = lambda: None
                
            def __getattr__(self, attr):
                return getattr(self._orig, attr)
        
        root.tk = TkExtensionWrapper(root.tk)
        
    app = LANMonitorGUI(root)

    # Note: app.compile_startup_device_list() has been removed from here
    # to avoid empty database generation runs on initial boot.

    threading.Thread(target=start_agent_listener, args=(app.refresh_device_list,), daemon=True).start()
    root.mainloop()