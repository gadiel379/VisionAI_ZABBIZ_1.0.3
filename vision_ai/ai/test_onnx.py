from ai.detectors import Detector
import numpy as np
import time
import os


# Buscar automáticamente el modelo desde la raíz del proyecto

ruta_modelo = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "yolov8n.onnx"
)


print("Modelo:", ruta_modelo)


modelo = Detector(
)


# Frame de prueba 416x416
frame = np.zeros(
    (416,416,3),
    dtype=np.uint8
)


print("Calentando modelo...")

# calentamiento
modelo.detect(frame)


print("Iniciando pruebas...")


tiempos = []


for i in range(10):

    inicio = time.time()

    salida = modelo.detect(frame)

    fin = time.time()


    ms = (fin - inicio) * 1000

    tiempos.append(ms)


    print(
        "Inferencia",
        i + 1,
        ":",
        round(ms,2),
        "ms"
    )


promedio = sum(tiempos) / len(tiempos)


print("----------------")
print(
    "Promedio:",
    round(promedio,2),
    "ms"
)


print(
    "FPS:",
    round(1000 / promedio,2)
)
