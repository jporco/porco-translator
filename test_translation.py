import queue, time, sys, os
import numpy as np
import speech_recognition as sr
from deep_translator import GoogleTranslator
import subprocess
from porco_translator import AudioWorker, ProcessorWorker, get_best_audio_source

def test():
    print(">>> Iniciando Teste de Diagnóstico de Áudio e Tradução <<<")
    
    print("Iniciando testes (Google Web Speech + Google Translate)...")
    
    audio_queue = queue.Queue()
    source = get_best_audio_source()
    print(f"Selected source: {source}")
    
    audio_worker = AudioWorker(audio_queue, source)
    proc_worker = ProcessorWorker(audio_queue)
    
    def on_text(text):
        print(f"\n+++ TRADUÇÃO RETORNADA: '{text}' +++")
    
    proc_worker.new_segment.connect(on_text)
    
    print("Iniciando captura de áudio...")
    audio_worker.start()
    proc_worker.start()
    
    print("Por favor, reproduza algum áudio no sistema (ex: vídeo no YouTube). Capturando por 15 segundos...")
    start_time = time.time()
    try:
        while time.time() - start_time < 15:
            time.sleep(1)
            sys.stdout.write(".")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    
    print("\nEncerrando workers...")
    audio_worker.running = False
    proc_worker.running = False
    audio_worker.wait()
    proc_worker.wait()
    print("Teste finalizado.")

if __name__ == "__main__":
    test()
