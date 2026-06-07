import os
import sys
import time
import ctypes
import subprocess

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def force_elevate():
    """Relaunches the current script as administrator if not already elevated."""
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
    except Exception:
        pass
    sys.exit(0)

def clear_process_lock(process_name, timeout=5):
    """
    Attempts to gracefully wait for a process to release file locks, 
    falling back to a system termination call if it persists.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Check if process is still running using tasklist
        cmd = f'tasklist /FI "IMAGENAME eq {process_name}" /NH'
        output = subprocess.check_output(cmd, shell=True).decode(errors='ignore')
        if process_name.lower() not in output.lower():
            return True
        time.sleep(0.5)
    
    # Force kill if it fails to exit gracefully within the timeout window
    subprocess.run(f'taskkill /F /IM {process_name}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)

def main():
    # Enforce administrative context for system file operations
    if not is_admin():
        force_elevate()

    # Define standard naming layout (assumed to be in the same working directory)
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    old_file_name = "agent.exe"
    new_file_name = "agent1.exe"

    old_file_path = os.path.join(base_dir, old_file_name)
    new_file_path = os.path.join(base_dir, new_file_name)

    # 1. Ensure the running agent has relinquished its handles
    clear_process_lock(old_file_name)

    # 2. Execute File Replacement Operation
    if os.path.exists(new_file_path):
        try:
            # Remove or archive old binary to clear the path
            if os.path.exists(old_file_path):
                os.remove(old_file_path)
            
            # Rename the staged version to the primary identifier
            os.rename(new_file_path, old_file_path)
        except Exception as e:
            # Log failure internally or attempt fallback recovery if necessary
            sys.exit(1)
    else:
        # Abort if the new update binary payload is missing
        sys.exit(1)

    # 3. Relaunch New Binary under Elevated Privileges
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", old_file_path, None, base_dir, 1
        )
    except Exception:
        # Fallback to standard process creation if ShellExecute fails
        subprocess.Popen([old_file_path], cwd=base_dir, shell=True)

    # 4. Immediate Self-Termination
    sys.exit(0)

if __name__ == "__main__":
    main()