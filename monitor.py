import socket
import threading
import json
import io
import os
import base64
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import customtkinter as ctk

# Import the Drag and Drop modules
from tkinterdnd2 import TkinterDnD, DND_FILES

# Maintain original network port configuration matrices
AGENT_PORT = 5005      
COMMAND_PORT = 6006    
SCREEN_STREAM_PORT = 7007  

network_database = {}

# Strict preservation of original length-prefixed socket background processing listener
def start_agent_listener(update_callback):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', AGENT_PORT))
    server_socket.listen(10)
    while True:
        try:
            client_sock, client_addr = server_socket.accept()
            client_ip = client_addr[0]
            
            len_bytes = client_sock.recv(4)
            if len_bytes and len(len_bytes) == 4:
                size = int.from_bytes(len_bytes, byteorder='big')
                buffer = b""
                while len(buffer) < size:
                    chunk = client_sock.recv(min(size - len(buffer), 4096))
                    if not chunk: break
                    buffer += chunk
                
                if len(buffer) == size:
                    network_database[client_ip] = json.loads(buffer.decode('utf-8'))
                    update_callback()
            client_sock.close()
        except Exception:
            pass


class RemoteSessionWindow:
    def __init__(self, parent_root, target_ip, dispatch_cmd_fn):
        self.parent_root = parent_root
        self.target_ip = target_ip
        self.dispatch_command_packet = dispatch_cmd_fn
        self.is_streaming = True
        self.stream_socket = None

        # AUTOMATIC LOCKOUT EXECUTED ON TARGET NODE (Preserved Action)
        self.dispatch_command_packet(self.target_ip, {"action": "lock_input"})

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
        self.screen_canvas.bind("<Key>", self.send_key_event)

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

    def send_key_event(self, event):
        if event.keysym in ["Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"]: return
        self.dispatch_command_packet(self.target_ip, {"action": "key_input", "key": event.keysym})

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
            with open(file_path, "rb") as target_file:
                binary_payload = target_file.read()
            b64_encoded_payload = base64.b64encode(binary_payload).decode('utf-8')
            delivery_manifest = {"action": "drop_file", "file_name": filename, "file_data": b64_encoded_payload}
            
            self.dispatch_command_packet(self.target_ip, delivery_manifest)
        except Exception as err:
            self.parent_root.after(0, lambda: tk.messagebox.showerror("Canvas Engine Fault", f"Failed to transfer asset: {str(err)}"))

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

        # Apply custom theme configurations
        ctk.set_appearance_mode("dark")
        self.root.configure(bg=self.c_bg)

        # --- MAIN RESPONSIVE APPLICATION FRAME ---
        self.main_container = ctk.CTkFrame(self.root, fg_color=self.c_bg, corner_radius=0)
        self.main_container.pack(fill=ctk.BOTH, expand=True, padx=25, pady=25)
        # Add the Broadcast Action Button in your header container layout
        # (Ensure this parent container matches where your existing dashboard headers are declared)
        self.btn_broadcast = ctk.CTkButton(
            self.root, # Swap with self.header_frame or equivalent wrapper if available
            text="⚠️ BROADCAST MESSAGE",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#DF2E38", 
            hover_color="#A41921",
            text_color="#FFFFFF",
            width=160,
            height=32,
            corner_radius=6,
            command=self.open_broadcast_window
        )
        
        # Place it cleanly in the top-right corner of your grid/frame layout configuration
        self.btn_broadcast.place(relx=1.0, rely=0.02, anchor="ne", x=-20)

        # --- HIGH-END SYSTEM-MATCHED TREEVIEW DESIGN SPECIFICATION ---
        style = ttk.Style()
        style.theme_use("clam")
        
        # Configure the core inner data row workspace grid Matrix
        style.configure(
            "Treeview", 
            background=self.c_inner,       # Custom dark slate inner container color (#1B2332)
            foreground=self.c_text_main,   # Off-white crisp text main color (#F5F6F9)
            fieldbackground=self.c_inner,  # Solid background matching inner container filling
            rowheight=32,                  # Expanded row padding height for optimal scannability
            font=("Segoe UI", 11)          # Custom font tracking configuration matching GUI layout
        )
        
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

        # =====================================================================
        # 1. FAR LEFT COLUMN: MANAGE ENDPOINTS LIST
        # =====================================================================
        self.endpoints_frame = ctk.CTkFrame(self.main_container, fg_color=self.c_card, width=280, corner_radius=16)
        self.endpoints_frame.pack(side=ctk.LEFT, fill=ctk.Y)
        self.endpoints_frame.pack_propagate(False)

        ctk.CTkLabel(
            self.endpoints_frame, text="MANAGE ENDPOINTS", 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.c_accent
        ).pack(anchor="w", padx=20, pady=(20, 12))

        self.listbox_container = ctk.CTkFrame(self.endpoints_frame, fg_color=self.c_inner, corner_radius=12, border_width=1, border_color=self.c_border)
        self.listbox_container.pack(fill=ctk.BOTH, expand=True, padx=15, pady=(0, 20))

        self.device_listbox = tk.Listbox(
            self.listbox_container, bg=self.c_inner, fg=self.c_accent, bd=0,
            highlightthickness=0, font=("Consolas", 10, "bold"),
            selectbackground="#1e3a8a", selectforeground="#00F0FF"
        )
        self.device_listbox.pack(fill=ctk.BOTH, expand=True, padx=10, pady=10)
        self.device_listbox.bind('<<ListboxSelect>>', self.on_device_select)

        # =====================================================================
        # RIGHT HAND SIDE CONTAINER
        # =====================================================================
        self.right_workspace_stack = ctk.CTkFrame(self.main_container, fg_color=self.c_bg, corner_radius=0)
        self.right_workspace_stack.pack(side=ctk.LEFT, fill=ctk.BOTH, expand=True, padx=(20, 0))

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
        fields_definitions = ["IP Address", "Device Name", "Operating System", "Memory (RAM)", "Processor"]
        
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
            ("notify", "💬  Notification Engine")
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
        self.history_frame = ctk.CTkFrame(self.workspace_detail_view, fg_color=self.c_card, corner_radius=16)
        inner_hist = ctk.CTkFrame(self.history_frame, fg_color="transparent")
        inner_hist.pack(fill=ctk.BOTH, expand=True, padx=20, pady=20)

        columns = ("url", "timestamp")
        self.history_table = ttk.Treeview(inner_hist, columns=columns, show="headings", style="Treeview")

        self.history_table.heading("url", text="URL / Website Address")
        self.history_table.heading("timestamp", text="Time Stamp")

        self.history_table.column("url", anchor=tk.NW, width=500, minwidth=250)
        self.history_table.column("timestamp", anchor=tk.CENTER, width=110, minwidth=90)

        scrollbar = ctk.CTkScrollbar(inner_hist, orientation="vertical", command=self.history_table.yview)
        self.history_table.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
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
        current_selection = self.device_listbox.curselection()
        if current_selection:
            selected_txt = self.device_listbox.get(current_selection[0])
            ip = selected_txt.split(" // ")[1].split(" ")[0]
            self.update_data_panes(ip)

    def refresh_device_list(self):
        self.root.after(0, self._update_ui)

    def _update_ui(self):
        current_selection = self.device_listbox.curselection()
        selected_ip = None
        if current_selection:
            selected_txt = self.device_listbox.get(current_selection[0])
            selected_ip = selected_txt.split(" // ")[1].split(" ")[0]

        self.device_listbox.delete(0, tk.END)
        for idx, (ip, data) in enumerate(network_database.items()):
            self.device_listbox.insert(tk.END, f" NODE // {ip} ({data.get('hostname')})")
            if ip == selected_ip: self.device_listbox.selection_set(idx)
        if selected_ip: self.update_data_panes(selected_ip)

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
        if not data: return
        self.specs_labels["IP Address"].configure(text=ip)
        self.specs_labels["Device Name"].configure(text=str(data.get('hostname')))
        self.specs_labels["Operating System"].configure(text=str(data.get('os')))
        self.specs_labels["Memory (RAM)"].configure(text=str(data.get('ram')))
        self.specs_labels["Processor"].configure(text=str(data.get('cpu')))
        self.lbl_node_title.configure(text=f"// DATA FEED: SYSTEM_NODE_{ip}")
        self.active_remote_ip = ip

        # --- TABULAR BROWSING HISTORY VIEWER ---
        if self.current_view == "history":
            # Wipe out old entries cleanly first so they don't stack up on re-selection
            for item in self.history_table.get_children():
                self.history_table.delete(item)
                
            # Loop through incoming history objects and drop them into explicit columns
            for item in data.get("history", []):
                site_url = str(item.get('site', 'N/A')).strip()# Safely extract date metric if present
                timestamp = str(item.get('ip', 'N/A')).strip()   # Maps back to your timestamp JSON payload key
                
                # Insert directly as a structured multi-column row unit
                self.history_table.insert("", tk.END, values=(site_url, timestamp))
            
        # --- SINGLE-ROW SELECTION HARDWARE INTERFACE ---
        elif self.current_view == "hardware":
            for child in self.hw_scroll_container.winfo_children():
                child.destroy()
                
            self.hardware_row_widgets = []
            devices_list = data.get("devices", [])
            
            if not devices_list:
                placeholder = ctk.CTkLabel(self.hw_scroll_container, text="No active peripheral channels reported.", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=self.c_text_muted)
                placeholder.pack(pady=20)
            else:
                for idx, dev in enumerate(devices_list):
                    row_card = ctk.CTkFrame(self.hw_scroll_container, fg_color=self.c_card, height=48, corner_radius=8, border_width=1, border_color=self.c_border, cursor="hand2")
                    row_card.pack(fill=ctk.X, pady=4, padx=5)
                    row_card.pack_propagate(False)
                    
                    self.hardware_row_widgets.append(row_card)
                    
                    # Extract Status Variable Metric (Defaults safely to ACTIVE if missing)
                    dev_status = str(dev.get("status", "ACTIVE")).strip().upper()
                    status_color = "#22c55e" if dev_status == "ACTIVE" else self.c_alert
                    
                    # Connection State Indicator dot mapping the status color
                    status_dot = ctk.CTkFrame(row_card, width=10, height=10, corner_radius=5, fg_color=status_color)
                    status_dot.pack(side=tk.LEFT, padx=(15, 5))
                    
                    lbl_name = ctk.CTkLabel(
                        row_card, text=f"{str(dev.get('name'))}",
                        font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                        text_color=self.c_text_main
                    )
                    lbl_name.pack(side=tk.LEFT, padx=10)
                    
                    # RIGHT-ALIGNED BADGES MATRIX
                    # 1. State Status Badge (ACTIVE / BLOCKED)
                    status_badge = ctk.CTkLabel(
                        row_card, text=dev_status,
                        font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                        text_color="#ffffff", fg_color=status_color, corner_radius=6, width=75, height=24
                    )
                    status_badge.pack(side=tk.RIGHT, padx=15)
                    
                    # 2. Hardware Subsystem Class Type Badge
                    type_badge = ctk.CTkLabel(
                        row_card, text=str(dev.get('type', 'GENERIC')).upper(),
                        font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                        text_color=self.c_accent, fg_color=self.c_inner, corner_radius=6, width=95, height=24
                    )
                    type_badge.pack(side=tk.RIGHT, padx=5)

                    # Event map clicks securely to pick single elements
                    bind_cmd = lambda e, i=idx: self.highlight_hardware_row(i)
                    row_card.bind("<Button-1>", bind_cmd)
                    lbl_name.bind("<Button-1>", bind_cmd)
                    status_dot.bind("<Button-1>", bind_cmd)
                    type_badge.bind("<Button-1>", bind_cmd)
                    status_badge.bind("<Button-1>", bind_cmd)
                
                if self.selected_hardware_index is not None and self.selected_hardware_index < len(devices_list):
                    self.highlight_hardware_row(self.selected_hardware_index)

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
        
        if self.selected_hardware_index is None:
            tk.messagebox.showwarning("Selection Required", "Please click on a specific device row item from the connection grid list first.")
            return

        data = network_database.get(self.active_remote_ip)
        if not data or not data.get("devices"): return

        devices_list = data.get("devices", [])
        if self.selected_hardware_index >= len(devices_list): return
        
        target_dev = devices_list[self.selected_hardware_index]
        device_name = target_dev.get("name", "")
        device_class = target_dev.get("type", "")
        raw_id = target_dev.get("raw_id") if target_dev.get("raw_id") and target_dev.get("raw_id") != "None" else device_name

        # Local state fallback updating so UI toggles state locally instantly on press
        target_dev["status"] = "BLOCKED" if process_type == "block" else "ACTIVE"
        self.update_data_panes(self.active_remote_ip)

        if device_class.strip().lower() == "keyboard":
            action_directive = "lock_input" if process_type == "block" else "unlock_input"
            self.dispatch_command_packet(self.active_remote_ip, {"action": action_directive, "device_type": "Keyboard", "device_name": device_name, "raw_id": raw_id})
        else:
            action_directive = "block_device" if process_type == "block" else "unblock_device"
            self.dispatch_command_packet(self.active_remote_ip, {"action": action_directive, "device_type": device_class, "device_name": device_name, "raw_id": raw_id})


if __name__ == "__main__":
    root = TkinterDnD.Tk()
    ctk.deactivate_automatic_dpi_awareness()
    root.block_update_dimensions_event = lambda: None
    root.unblock_update_dimensions_event = lambda: None
    
    if hasattr(root, 'tk'):
        class TkExtensionWrapper:
            def __init__(self, original_tk):
                self._orig = original_tk
                # Add BOTH handlers here to satisfy customtkinter's scaling loop
                self.block_update_dimensions_event = lambda: None
                self.unblock_update_dimensions_event = lambda: None
                
            def __getattr__(self, attr):
                # Fall back to native C attributes for everything else
                return getattr(self._orig, attr)
        
        root.tk = TkExtensionWrapper(root.tk)
    app = LANMonitorGUI(root)
    threading.Thread(target=start_agent_listener, args=(app.refresh_device_list,), daemon=True).start()
    root.mainloop()
