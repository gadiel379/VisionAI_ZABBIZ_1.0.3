from ultralytics import YOLO
import time


print("Cargando modelo YOLO...")


inicio = time.time()

model = YOLO("yolov8n.pt")


fin = time.time()


print(
    "Modelo cargado en:",
    round(fin - inicio, 2),
    "segundos"
)


print("YOLO listo")
