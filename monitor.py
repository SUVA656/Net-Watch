import socket
import threading
import json
import io
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

AGENT_PORT = 5005      
COMMAND_PORT = 6006    
SCREEN_STREAM_PORT = 7007  

network_database = {}

def start_agent_listener(update_callback):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', AGENT_PORT))
    server_socket.listen(10)
    while True:
        try:
            client_sock, client_addr = server_socket.accept()
            client_ip = client_addr[0]
            data = client_sock.recv(65536).decode('utf-8') 
            if data:
                network_database[client_ip] = json.loads(data)
                update_callback()
            client_sock.close()
        except Exception as e:
            pass


class RemoteSessionWindow:
    def __init__(self, parent_root, target_ip, dispatch_cmd_fn):
        self.parent_root = parent_root
        self.target_ip = target_ip
        self.dispatch_command_packet = dispatch_cmd_fn
        self.is_streaming = True
        self.stream_socket = None

        self.window = tk.Toplevel(parent_root)
        self.window.title(f"REMOTE SESSION // NODE: {target_ip}")
        self.window.geometry("1024x768")
        self.window.configure(bg="#020617")

        self.top_bar = tk.Frame(self.window, bg="#0b1329", pady=8, padx=10)
        self.top_bar.pack(fill=tk.X, side=tk.TOP)
        
        tk.Label(
            self.top_bar, 
            text=f"CONNECTED TO: {target_ip}  |  Controls: Active (Click canvas to capture keyboard)", 
            font=("Consolas", 10, "bold"), fg="#39ff14", bg="#0b1329"
        ).pack(side=tk.LEFT)

        self.btn_close = tk.Button(
            self.top_bar, text="[ DISCONNECT ]", font=("Consolas", 9, "bold"), 
            bg="#ef4444", fg="#ffffff", bd=0, padx=10, pady=3, command=self.close_session
        )
        self.btn_close.pack(side=tk.RIGHT)

        self.canvas_container = tk.Frame(self.window, bg="#020617", bd=1, relief=tk.SOLID)
        self.canvas_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.screen_canvas = tk.Canvas(self.canvas_container, bg="#0b1329", highlightthickness=0)
        self.screen_canvas.pack(fill=tk.BOTH, expand=True)
        
        self.screen_canvas.bind("<Button-1>", self.forward_mouse_click)
        self.screen_canvas.bind("<Key>", self.forward_keyboard_stroke)
        self.screen_canvas.bind("<Enter>", lambda e: self.screen_canvas.focus_set())

        self.window.protocol("WM_DELETE_WINDOW", self.close_session)

        threading.Thread(target=self.pull_visual_stream_pipeline, daemon=True).start()

    def pull_visual_stream_pipeline(self):
        try:
            self.stream_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.stream_socket.settimeout(5.0)
            self.stream_socket.connect((self.target_ip, SCREEN_STREAM_PORT))
            
            while self.is_streaming:
                len_bytes = self.stream_socket.recv(4)
                if not len_bytes or len(len_bytes) < 4: break
                size = int.from_bytes(len_bytes, byteorder='big')
                
                buffer = b""
                while len(buffer) < size:
                    chunk = self.stream_socket.recv(min(size - len(buffer), 4096))
                    if not chunk: break
                    buffer += chunk
                
                if len(buffer) < size: break
                try:
                    img = Image.open(io.BytesIO(buffer))
                    cw = self.screen_canvas.winfo_width()
                    ch = self.screen_canvas.winfo_height()
                    if cw > 50 and ch > 50:
                        img = img.resize((cw, ch), Image.Resampling.LANCZOS)
                    photo_img = ImageTk.PhotoImage(img)
                    self.parent_root.after(0, self.repaint_canvas, photo_img)
                except: pass
        except: pass
        finally:
            self.is_streaming = False
            self.parent_root.after(0, self.safe_destroy_window)

    def repaint_canvas(self, photo_img):
        if not self.window.winfo_exists(): return
        self.current_display_img = photo_img 
        self.screen_canvas.create_image(0, 0, anchor=tk.NW, image=self.current_display_img)

    def forward_mouse_click(self, event):
        cw = self.screen_canvas.winfo_width()
        ch = self.screen_canvas.winfo_height()
        if cw == 0 or ch == 0: return

        self.dispatch_command_packet(self.target_ip, {
            "action": "remote_mouse_click",
            "pct_x": event.x / cw,
            "pct_y": event.y / ch
        })

    def forward_keyboard_stroke(self, event):
        key_char = event.char
        key_sym = event.keysym.lower()

        if key_sym in ["return", "enter"]: key_char = "\n"
        elif key_sym == "backspace": key_char = "\b"
        elif key_sym == "space": key_char = " "
        elif len(key_sym) > 1: key_char = f"[{key_sym}]"

        if not key_char: return
        self.dispatch_command_packet(self.target_ip, {
            "action": "remote_key_strike",
            "key": key_char
        })

    def close_session(self):
        self.is_streaming = False
        if self.stream_socket:
            try: self.stream_socket.close()
            except: pass
        self.safe_destroy_window()

    def safe_destroy_window(self):
        try: self.window.destroy()
        except: pass


class LANMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MATRIX // CORE NETWORK MONITOR")
        self.root.geometry("1200x850") 
        self.root.configure(bg="#020617") 

        self.active_remote_ip = None
        self.active_session = None

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#0b1329", foreground="#00f5ff", rowheight=28, fieldbackground="#0b1329", font=("Consolas", 9))
        style.configure("Treeview.Heading", background="#1c2541", foreground="#39ff14", font=("Consolas", 9, "bold"))

        self.left_frame = tk.Frame(root, bg="#0b1329", width=280, bd=1, relief=tk.SOLID)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.left_frame.pack_propagate(False)

        tk.Label(self.left_frame, text="[ DISCOVERED ENDPOINTS ]", font=("Consolas", 11, "bold"), fg="#39ff14", bg="#0b1329", pady=20).pack(fill=tk.X)
        self.device_listbox = tk.Listbox(self.left_frame, bg="#020617", fg="#00f5ff", font=("Consolas", 10), selectbackground="#1e3a8a", selectforeground="#39ff14")
        self.device_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.device_listbox.bind('<<ListboxSelect>>', self.on_device_select)

        self.right_frame = tk.Frame(root, bg="#020617", padx=20, pady=20)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.lbl_node_title = tk.Label(self.right_frame, text="// ENDPOINT_MONITOR : STANDBY", font=("Consolas", 14, "bold"), fg="#00f5ff", bg="#020617")
        self.lbl_node_title.pack(anchor="w", pady=(0, 15))

        self.specs_frame = tk.Frame(self.right_frame, bg="#0b1329", padx=10, pady=10, highlightbackground="#1e293b", highlightthickness=1)
        self.specs_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.specs_labels = {}
        for idx, field in enumerate(["IP Address", "Device Name", "Operating System", "Memory (RAM)", "Processor"]):
            f = tk.Frame(self.specs_frame, bg="#0b1329")
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=f"{field:.<20}", font=("Consolas", 10), fg="#64748b", bg="#0b1329", anchor="w").pack(side=tk.LEFT)
            lbl_val = tk.Label(f, text="-", font=("Consolas", 10), fg="#00f5ff", bg="#0b1329", anchor="w")
            lbl_val.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.specs_labels[field] = lbl_val

        self.menu_bar = tk.Frame(self.right_frame, bg="#020617")
        self.menu_bar.pack(fill=tk.X, pady=(5, 10))

        self.btn_history = tk.Button(self.menu_bar, text="[ VIEW BROWSING LOGS ]", font=("Consolas", 10, "bold"), bg="#1c2541", fg="#39ff14", bd=1, relief=tk.FLAT, padx=15, pady=6, command=lambda: self.switch_view("history"))
        self.btn_history.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_hardware = tk.Button(self.menu_bar, text="[ VIEW CONNECTED DEVICES ]", font=("Consolas", 10, "bold"), bg="#0b1329", fg="#00f5ff", bd=1, relief=tk.FLAT, padx=15, pady=6, command=lambda: self.switch_view("hardware"))
        self.btn_hardware.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_remote = tk.Button(self.menu_bar, text="[ REMOTE CONNECTION ]", font=("Consolas", 10, "bold"), bg="#0b1329", fg="#00f5ff", bd=1, relief=tk.FLAT, padx=15, pady=6, command=lambda: self.switch_view("remote"))
        self.btn_remote.pack(side=tk.LEFT)

        self.view_container = tk.Frame(self.right_frame, bg="#0b1329", bd=1, relief=tk.SOLID)
        self.view_container.pack(fill=tk.BOTH, expand=True)

        self.history_frame = tk.Frame(self.view_container, bg="#0b1329", padx=10, pady=10)
        self.tree = ttk.Treeview(self.history_frame, columns=("URL", "Time"), show="headings")
        self.tree.heading("URL", text="[ LOCAL SYSTEM BROWSING HISTORY LOGS ]")
        self.tree.heading("Time", text="[ VISIT TIMESTAMP ]")
        self.tree.column("URL", width=500, anchor="w")
        self.tree.column("Time", width=180, anchor="w")
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.hardware_frame = tk.Frame(self.view_container, bg="#0b1329", padx=10, pady=10)
        self.hw_tree = ttk.Treeview(self.hardware_frame, columns=("Name", "Category", "Mfg", "ID"), show="headings")
        self.hw_tree.heading("Name", text="[ FILTERED USER PERIPHERALS ]")
        self.hw_tree.heading("Category", text="[ TYPE ]")
        self.hw_tree.heading("Mfg", text="[ CURRENT STATE ]")
        self.hw_tree.column("Name", width=380, anchor="w")
        self.hw_tree.column("Category", width=140, anchor="w")
        self.hw_tree.column("Mfg", width=160, anchor="w")
        self.hw_tree.heading("ID", text="")
        self.hw_tree.column("ID", width=0, minwidth=0, stretch=tk.NO)
        self.hw_tree.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        self.action_bar = tk.Frame(self.hardware_frame, bg="#0b1329", pady=5)
        self.action_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.btn_unblock = tk.Button(self.action_bar, text="[ UNBLOCK DEVICE ]", font=("Consolas", 10, "bold"), bg="#22c55e", fg="#ffffff", bd=0, padx=15, pady=6, command=lambda: self.send_hardware_directive("unblock_device"))
        self.btn_unblock.pack(side=tk.RIGHT, padx=5)
        self.btn_block = tk.Button(self.action_bar, text="[ BLOCK DEVICE ]", font=("Consolas", 10, "bold"), bg="#ef4444", fg="#ffffff", bd=0, padx=15, pady=6, command=lambda: self.send_hardware_directive("block_device"))
        self.btn_block.pack(side=tk.RIGHT)

        self.remote_frame = tk.Frame(self.view_container, bg="#020617", padx=15, pady=20)
        
        lbl_info = tk.Label(
            self.remote_frame, 
            text="[ SEPARATE ENGINE LAUNCHER ]\n\nClick the button below to initialize a distinct, independent graphical interface module to oversee keyboard tracking, mouse mapping, and desktop rendering.", 
            font=("Consolas", 10), fg="#64748b", bg="#020617", justify=tk.LEFT
        )
        lbl_info.pack(anchor="w", pady=(0, 20))

        self.btn_launch_gui = tk.Button(
            self.remote_frame, text="[ LAUNCH LIVE REMOTE CONTROL WINDOW ]", 
            font=("Consolas", 11, "bold"), bg="#22c55e", fg="#ffffff", bd=0, padx=20, pady=12, command=self.open_separate_live_window
        )
        self.btn_launch_gui.pack(anchor="w", pady=(0, 25))

        self.deploy_box = tk.LabelFrame(self.remote_frame, text=" Remote Package Installation Tools ", font=("Consolas", 10, "bold"), bg="#020617", fg="#3b82f6", padx=10, pady=15)
        self.deploy_box.pack(fill=tk.X, anchor="w")

        tk.Label(self.deploy_box, text="Installer Deployment Command:", font=("Consolas", 9), fg="#64748b", bg="#020617").pack(anchor="w", pady=(0, 5))
        
        self.cmd_input_frame = tk.Frame(self.deploy_box, bg="#020617")
        self.cmd_input_frame.pack(fill=tk.X)

        self.ent_deploy_cmd = tk.Entry(self.cmd_input_frame, font=("Consolas", 10), bg="#0b1329", fg="#00f5ff", insertbackground="#00f5ff", bd=1, relief=tk.SOLID)
        self.ent_deploy_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 10))
        self.ent_deploy_cmd.insert(0, r"C:\path\to\setup.exe /silent")

        self.btn_deploy = tk.Button(self.cmd_input_frame, text="[ RUN REMOTE INSTALL ]", font=("Consolas", 9, "bold"), bg="#3b82f6", fg="#ffffff", bd=0, padx=15, pady=6, command=self.trigger_remote_installation)
        self.btn_deploy.pack(side=tk.RIGHT)

        self.current_view = "history"
        self.history_frame.pack(fill=tk.BOTH, expand=True)

    def switch_view(self, target_view):
        self.current_view = target_view
        self.history_frame.pack_forget()
        self.hardware_frame.pack_forget()
        self.remote_frame.pack_forget()

        self.btn_history.config(bg="#0b1329", fg="#00f5ff")
        self.btn_hardware.config(bg="#0b1329", fg="#00f5ff")
        self.btn_remote.config(bg="#0b1329", fg="#00f5ff")

        if target_view == "history":
            self.history_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_history.config(bg="#1c2541", fg="#39ff14")
        elif target_view == "hardware":
            self.hardware_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_hardware.config(bg="#1c2541", fg="#39ff14")
        elif target_view == "remote":
            self.remote_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_remote.config(bg="#1c2541", fg="#39ff14")
        self.refresh_current_selection_data()

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
            if ip == selected_ip:
                self.device_listbox.selection_set(idx)
        if selected_ip:
            self.update_data_panes(selected_ip)

    def on_device_select(self, event):
        self.refresh_current_selection_data()

    def update_data_panes(self, ip):
        data = network_database.get(ip)
        if not data: return
        self.specs_labels["IP Address"].config(text=ip)
        self.specs_labels["Device Name"].config(text=data.get('hostname'))
        self.specs_labels["Operating System"].config(text=data.get('os'))
        self.specs_labels["Memory (RAM)"].config(text=data.get('ram'))
        self.specs_labels["Processor"].config(text=data.get('cpu'))
        self.lbl_node_title.config(text=f"// DATA FEED: SYSTEM_NODE_{ip}")
        self.active_remote_ip = ip

        if self.current_view == "history":
            for item in self.tree.get_children(): self.tree.delete(item)
            for item in data.get("history", []):
                self.tree.insert("", tk.END, values=(item.get('site'), item.get('ip')))
        elif self.current_view == "hardware":
            for item in self.hw_tree.get_children(): self.hw_tree.delete(item)
            for dev in data.get("devices", []):
                target_raw_id = dev.get("raw_id") if dev.get("raw_id") and dev.get("raw_id") != "None" else dev.get("name")
                self.hw_tree.insert("", tk.END, values=(dev.get("name"), dev.get("type"), dev.get("mfg"), target_raw_id))

    def open_separate_live_window(self):
        if not self.active_remote_ip:
            messagebox.showwarning("Target Unidentified", "Please select an active endpoint from the roster list first.")
            return

        if self.active_session and self.active_session.is_streaming:
            messagebox.showinfo("Session Active", "An active interaction session window is already open.")
            return

        self.active_session = RemoteSessionWindow(self.root, self.active_remote_ip, self.dispatch_command_packet)

    def dispatch_command_packet(self, target_ip, data_dict):
        def worker():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(3.0)
                    s.connect((target_ip, COMMAND_PORT))
                    s.sendall(json.dumps(data_dict).encode('utf-8'))
            except: pass
        threading.Thread(target=worker, daemon=True).start()

    def trigger_remote_installation(self):
        cmd = self.ent_deploy_cmd.get().strip()
        if not cmd or not self.active_remote_ip: return
        
        self.dispatch_command_packet(self.active_remote_ip, {
            "action": "execute_installer",
            "command": cmd
        })
        messagebox.showinfo("Deployment Action Sent", f"Installation string dispatched to node {self.active_remote_ip}")

    def send_hardware_directive(self, action_type):
        selected_node = self.device_listbox.curselection()
        selected_hw = self.hw_tree.selection()
        if not selected_node or not selected_hw: return

        node_txt = self.device_listbox.get(selected_node[0])
        agent_ip = node_txt.split(" // ")[1].split(" ")[0]
        hw_values = self.hw_tree.item(selected_hw[0], 'values')
        
        self.dispatch_command_packet(agent_ip, {
            "action": action_type,
            "device_type": hw_values[1],
            "device_name": hw_values[0],
            "raw_id": hw_values[3] if len(hw_values) > 3 else hw_values[0]
        })


if __name__ == "__main__":
    root = tk.Tk()
    app = LANMonitorGUI(root)
    threading.Thread(target=start_agent_listener, args=(app.refresh_device_list,), daemon=True).start()
    root.mainloop()