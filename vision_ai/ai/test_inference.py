from ultralytics import YOLO
import numpy as np
import time


print("Cargando YOLO...")

model = YOLO("yolov8n.pt")


# Crear imagen simulada 640x360
frame = np.zeros(
    (360,640,3),
    dtype=np.uint8
)


print("Iniciando pruebas...")


# Calentamiento del modelo
model(frame, verbose=False)


tiempos = []


for i in range(10):

    inicio = time.time()

    resultado = model(
        frame,
        verbose=False
    )

    fin = time.time()


    tiempo = (fin - inicio) * 1000

    tiempos.append(tiempo)


    print(
        "Inferencia",
        i+1,
        ":",
        round(tiempo,2),
        "ms"
    )


promedio = sum(tiempos)/len(tiempos)


print("-----------------------")
print(
    "Promedio:",
    round(promedio,2),
    "ms"
)

print(
    "FPS estimado:",
    round(1000/promedio,2)
)
