#!/usr/bin/env python3
import subprocess, os, sys, time, socket

# Launcher v10.5 — não se auto-mata, mata apenas filhos antigos
DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(DIR, "..", "venv", "bin", "python3")

if not os.path.exists(VENV_PYTHON):
    print(f"[ERRO] Python do venv não encontrado em: {VENV_PYTHON}", flush=True)
    sys.exit(1)

UDP_PORT_UI = 50134
MY_PID = os.getpid()

def kill_others(pattern):
    """Mata processos que combinam com o padrão, mas não o próprio PID."""
    try:
        out = subprocess.check_output(["pgrep", "-f", pattern], text=True).strip()
        for pid_str in out.splitlines():
            pid = int(pid_str.strip())
            if pid != MY_PID:
                subprocess.call(["kill", "-9", str(pid)])
    except subprocess.CalledProcessError:
        pass  # nenhum processo encontrado

def wait_port_free(port, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("", port))
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False

def main():
    print("[launcher] Varrendo instâncias antigas...", flush=True)
    kill_others("porco_listener.py")
    kill_others("porco_ui.py")
    # Mata outros launchers (mas não nós mesmos)
    kill_others("porco_translator.py")
    time.sleep(1.0)

    if not wait_port_free(UDP_PORT_UI):
        print(f"[launcher] Aviso: porta {UDP_PORT_UI} ainda ocupada.", flush=True)

    print("[launcher] Iniciando listener...", flush=True)
    subprocess.Popen([VENV_PYTHON, os.path.join(DIR, "porco_listener.py")])
    time.sleep(0.5)

    print("[launcher] Iniciando UI...", flush=True)
    ui_proc = subprocess.Popen([VENV_PYTHON, os.path.join(DIR, "porco_ui.py")])
    ui_proc.wait()

if __name__ == "__main__":
    main()
