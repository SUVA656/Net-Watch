import socket
import threading
import json
import tkinter as tk
from tkinter import ttk

# Port configuration
AGENT_PORT = 5005  

# Global network storage map
network_database = {}

# ==========================================
# CENTRALIZED NETWORK LISTENER ENGINE
# ==========================================
def start_agent_listener(update_callback):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    server_socket.bind(('0.0.0.0', AGENT_PORT))
    server_socket.listen(10)
    print(f"[*] CORE ACTIVE: Monitoring network socket interface on port {AGENT_PORT}...")

    while True:
        try:
            client_sock, client_addr = server_socket.accept()
            client_ip = client_addr[0]
            
            # Read streaming telemetry byte payload (increased buffer for safe transmission)
            data = client_sock.recv(32768).decode('utf-8')
            if data:
                network_database[client_ip] = json.loads(data)
                print(f"[+] INCOMING NODE INGESTED: Payload verified from {client_ip}")
                update_callback()
            client_sock.close()
        except Exception as e:
            print(f"[-] Data packet drop / transmission error: {e}")

# ==========================================
# GUI CONTROL TERMINAL INTERFACE
# ==========================================
class LANMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MATRIX // CORE NETWORK MONITOR")
        self.root.geometry("1050x680")
        self.root.configure(bg="#020617") 

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#0b1329", foreground="#00f5ff", rowheight=28, fieldbackground="#0b1329", font=("Consolas", 9))
        style.configure("Treeview.Heading", background="#1c2541", foreground="#39ff14", font=("Consolas", 9, "bold"))

        # Left Column Node Explorer
        self.left_frame = tk.Frame(root, bg="#0b1329", width=280, bd=1, relief=tk.SOLID)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.left_frame.pack_propagate(False)

        tk.Label(self.left_frame, text="[ DISCOVERED ENDPOINTS ]", font=("Consolas", 11, "bold"), fg="#39ff14", bg="#0b1329", pady=20).pack(fill=tk.X)
        self.device_listbox = tk.Listbox(self.left_frame, bg="#020617", fg="#00f5ff", font=("Consolas", 10), selectbackground="#1e3a8a", selectforeground="#39ff14")
        self.device_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.device_listbox.bind('<<ListboxSelect>>', self.on_device_select)

        # Right Column Target Telemetry Pane
        self.right_frame = tk.Frame(root, bg="#020617", padx=20, pady=20)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.lbl_node_title = tk.Label(self.right_frame, text="// ENDPOINT_MONITOR : STANDBY", font=("Consolas", 14, "bold"), fg="#00f5ff", bg="#020617")
        self.lbl_node_title.pack(anchor="w", pady=(0, 15))

        # Hardware Info Panel
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

        # Logs Viewer Panel
        self.logs_frame = tk.Frame(self.right_frame, bg="#0b1329", padx=10, pady=10)
        self.logs_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(self.logs_frame, columns=("URL", "Time"), show="headings")
        self.tree.heading("URL", text="[ LOCAL SYSTEM BROWSING HISTORY LOGS ]")
        self.tree.heading("Time", text="[ RECORDED VISIT TIMESTAMP ]")
        self.tree.column("URL", width=550, anchor="w")
        self.tree.column("Time", width=180, anchor="w")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def refresh_device_list(self):
        self.root.after(0, self._update_ui)

    def _update_ui(self):
        # Save current selection to restore it after refresh
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

        # Force UI update on the data panels if the viewed device changed data
        if selected_ip:
            self.update_data_panes(selected_ip)

    def on_device_select(self, event):
        selection = self.device_listbox.curselection()
        if not selection: return
        
        selected_txt = self.device_listbox.get(selection[0])
        ip = selected_txt.split(" // ")[1].split(" ")[0]
        self.update_data_panes(ip)

    def update_data_panes(self, ip):
        data = network_database.get(ip)
        if data:
            self.lbl_node_title.config(text=f"// DATA FEED: SYSTEM_NODE_{ip}")
            self.specs_labels["IP Address"].config(text=ip)
            self.specs_labels["Device Name"].config(text=data.get('hostname'))
            self.specs_labels["Operating System"].config(text=data.get('os'))
            self.specs_labels["Memory (RAM)"].config(text=data.get('ram'))
            self.specs_labels["Processor"].config(text=data.get('cpu'))

            for item in self.tree.get_children(): self.tree.delete(item)
            for item in data.get("history", []):
                self.tree.insert("", tk.END, values=(item.get('site'), item.get('ip')))

if __name__ == "__main__":
    root = tk.Tk()
    app = LANMonitorGUI(root)
    threading.Thread(target=start_agent_listener, args=(app.refresh_device_list,), daemon=True).start()
    root.mainloop()
