import os
import signal
import subprocess
import time

try:
    # Find master uvicorn process
    master_pids = subprocess.check_output(["pgrep", "-f", "uvicorn main:app"]).decode().strip().split()
    print("Found uvicorn master PIDs:", master_pids)
    
    for master_pid_str in master_pids:
        master_pid = int(master_pid_str)
        if master_pid == os.getpid():
            continue

        # Find child workers spawned by master uvicorn process
        try:
            worker_pids = subprocess.check_output(["pgrep", "-P", str(master_pid)]).decode().strip().split()
        except subprocess.CalledProcessError:
            worker_pids = []

        print(f"Master PID {master_pid} has child worker PIDs: {worker_pids}")
        for w_pid_str in worker_pids:
            w_pid = int(w_pid_str)
            print(f"Terminating child worker {w_pid} to trigger fresh respawn with updated code...")
            try:
                os.kill(w_pid, signal.SIGTERM)
            except Exception as e:
                print(f"Error terminating worker {w_pid}: {e}")

        # Also signal master process with SIGHUP
        try:
            os.kill(master_pid, signal.SIGHUP)
        except Exception as e:
            print(f"Error signaling master {master_pid}: {e}")

    print("Uvicorn worker reload completed successfully. Master process has respawned fresh workers.")
except Exception as exc:
    print(f"Error during uvicorn reload: {exc}")

