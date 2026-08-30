#!/usr/bin/env python3
import os
import signal
import socket
import subprocess
import sys
import time

# Launcher v10.5 — não se auto-mata, mata apenas filhos antigos
DIR = os.path.dirname(os.path.abspath(__file__))
# O launcher shell pode usar /usr/bin/python3 com PYTHONPATH quando um venv
# copiado está corrompido. Os filhos precisam usar exatamente o mesmo Python.
VENV_PYTHON = sys.executable

UDP_PORT_UI = 50134
MY_PID = os.getpid()

def kill_others(pattern):
    """Mata processos que combinam com o padrão, mas não o próprio PID."""
    try:
        out = subprocess.check_output(["pgrep", "-f", pattern], text=True).strip()
        for pid_str in out.splitlines():
            pid = int(pid_str.strip())
            if pid != MY_PID:
                os.kill(pid, signal.SIGTERM)
    except (subprocess.CalledProcessError, ProcessLookupError):
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
    children = []

    def cleanup():
        for proc in children:
            if proc.poll() is None:
                proc.terminate()
        for proc in children:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def handle_signal(signum, _frame):
        cleanup()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print("[launcher] Varrendo instâncias antigas...", flush=True)
    kill_others("porco_listener.py")
    kill_others("porco_ui.py")
    # Mata outros launchers (mas não nós mesmos)
    kill_others("porco_translator.py")
    time.sleep(0.5)

    if not wait_port_free(UDP_PORT_UI):
        print(f"[launcher] Aviso: porta {UDP_PORT_UI} ainda ocupada.", flush=True)

    print("[launcher] Iniciando listener...", flush=True)
    listener_proc = subprocess.Popen(
        [VENV_PYTHON, os.path.join(DIR, "porco_listener.py")],
        start_new_session=True,
    )
    children.append(listener_proc)
    time.sleep(0.5)

    print("[launcher] Iniciando UI...", flush=True)
    ui_proc = subprocess.Popen(
        [VENV_PYTHON, os.path.join(DIR, "porco_ui.py")],
        start_new_session=True,
    )
    children.append(ui_proc)
    try:
        while ui_proc.poll() is None:
            if listener_proc.poll() is not None:
                print(
                    f"[launcher] Listener encerrou com código {listener_proc.returncode}.",
                    flush=True,
                )
                ui_proc.terminate()
                break
            time.sleep(0.25)
    finally:
        cleanup()

if __name__ == "__main__":
    main()
