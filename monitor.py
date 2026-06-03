import socket
import threading
import json
import tkinter as tk
from tkinter import ttk, messagebox

AGENT_PORT = 5005      
COMMAND_PORT = 6006    

network_database = {}

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
            data = client_sock.recv(65536).decode('utf-8') 
            if data:
                network_database[client_ip] = json.loads(data)
                update_callback()
            client_sock.close()
        except Exception as e:
            print(f"[-] Data packet drop error: {e}")

class LANMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MATRIX // CORE NETWORK MONITOR")
        self.root.geometry("1150x740") 
        self.root.configure(bg="#020617") 

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

        self.btn_history = tk.Button(
            self.menu_bar, text="[ VIEW BROWSING LOGS ]", font=("Consolas", 10, "bold"),
            bg="#1c2541", fg="#39ff14", activebackground="#39ff14", activeforeground="#020617",
            bd=1, relief=tk.FLAT, padx=15, pady=6, command=lambda: self.switch_view("history")
        )
        self.btn_history.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_hardware = tk.Button(
            self.menu_bar, text="[ VIEW CONNECTED DEVICES ]", font=("Consolas", 10, "bold"),
            bg="#0b1329", fg="#00f5ff", activebackground="#00f5ff", activeforeground="#020617",
            bd=1, relief=tk.FLAT, padx=15, pady=6, command=lambda: self.switch_view("hardware")
        )
        self.btn_hardware.pack(side=tk.LEFT)

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

        # Added Unblock control button next to block button
        self.btn_unblock = tk.Button(
            self.action_bar, text="[ UNBLOCK SELECTED DEVICE ]", font=("Consolas", 10, "bold"),
            bg="#22c55e", fg="#ffffff", activebackground="#15803d", activeforeground="#ffffff",
            bd=0, padx=15, pady=6, command=lambda: self.send_hardware_directive("unblock_device")
        )
        self.btn_unblock.pack(side=tk.RIGHT, padx=5)

        self.btn_block = tk.Button(
            self.action_bar, text="[ HARD-BLOCK SELECTED ]", font=("Consolas", 10, "bold"),
            bg="#ef4444", fg="#ffffff", activebackground="#b91c1c", activeforeground="#ffffff",
            bd=0, padx=15, pady=6, command=lambda: self.send_hardware_directive("block_device")
        )
        self.btn_block.pack(side=tk.RIGHT)

        self.current_view = "history"
        self.history_frame.pack(fill=tk.BOTH, expand=True)

    def switch_view(self, target_view):
        self.current_view = target_view
        if target_view == "history":
            self.hardware_frame.pack_forget()
            self.history_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_history.config(bg="#1c2541", fg="#39ff14")
            self.btn_hardware.config(bg="#0b1329", fg="#00f5ff")
        else:
            self.history_frame.pack_forget()
            self.hardware_frame.pack(fill=tk.BOTH, expand=True)
            self.btn_history.config(bg="#0b1329", fg="#00f5ff")
            self.btn_hardware.config(bg="#1c2541", fg="#39ff14")
            
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
        selection = self.device_listbox.curselection()
        if not selection: return
        selected_txt = self.device_listbox.get(selection[0])
        ip = selected_txt.split(" // ")[1].split(" ")[0]
        self.update_data_panes(ip)

    def update_data_panes(self, ip):
        data = network_database.get(ip)
        if not data: return
        
        self.specs_labels["IP Address"].config(text=ip)
        self.specs_labels["Device Name"].config(text=data.get('hostname'))
        self.specs_labels["Operating System"].config(text=data.get('os'))
        self.specs_labels["Memory (RAM)"].config(text=data.get('ram'))
        self.specs_labels["Processor"].config(text=data.get('cpu'))
        self.lbl_node_title.config(text=f"// DATA FEED: SYSTEM_NODE_{ip}")

        if self.current_view == "history":
            for item in self.tree.get_children(): self.tree.delete(item)
            for item in data.get("history", []):
                self.tree.insert("", tk.END, values=(item.get('site'), item.get('ip')))
        else:
            for item in self.hw_tree.get_children(): self.hw_tree.delete(item)
            for dev in data.get("devices", []):
                target_raw_id = dev.get("raw_id") if dev.get("raw_id") and dev.get("raw_id") != "None" else dev.get("name")
                self.hw_tree.insert("", tk.END, values=(dev.get("name"), dev.get("type"), dev.get("mfg"), target_raw_id))

    def send_hardware_directive(self, action_type):
        selected_node = self.device_listbox.curselection()
        if not selected_node:
            messagebox.showwarning("Selection Missing", "Please select a target client node from the left explorer bar first.")
            return

        selected_hw = self.hw_tree.selection()
        if not selected_hw:
            messagebox.showwarning("Device Missing", "Please select a specific peripheral from the display list.")
            return

        node_txt = self.device_listbox.get(selected_node[0])
        agent_ip = node_txt.split(" // ")[1].split(" ")[0]
        hw_values = self.hw_tree.item(selected_hw[0], 'values')
        
        dev_name = hw_values[0]
        dev_type = hw_values[1]
        raw_id = hw_values[3] if len(hw_values) > 3 else dev_name

        action_word = "RE-ENABLE" if action_type == "unblock_device" else "DISABLE"
        confirm = messagebox.askyesno("Confirm Directive Intervention", f"Are you sure you want to request a status shift to {action_word}?\n\nTarget Host: {agent_ip}\nDevice: {dev_name}")
        if not confirm:
            return

        command_packet = {
            "action": action_type,
            "device_type": dev_type,
            "device_name": dev_name,
            "raw_id": raw_id
        }

        def dispatch_worker():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(3.0)
                    s.connect((agent_ip, COMMAND_PORT))
                    s.sendall(json.dumps(command_packet).encode('utf-8'))
                    response = s.recv(1024).decode('utf-8')
                
                if "SUCCESS" in response:
                    messagebox.showinfo("Directive Complete", f"Successfully updated device status layout parameters.")
                else:
                    messagebox.showerror("Execution Refused", f"Agent responded with error:\n{response}")
            except Exception as e:
                messagebox.showerror("Network Timeout", f"Failed to deliver command packet to agent at {agent_ip}.\nError: {e}")

        threading.Thread(target=dispatch_worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = LANMonitorGUI(root)
    threading.Thread(target=start_agent_listener, args=(app.refresh_device_list,), daemon=True).start()
    root.mainloop()