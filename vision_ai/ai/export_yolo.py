from ultralytics import YOLO


print("Cargando YOLOv8n...")


model = YOLO("yolov8n.pt")


print("Exportando a ONNX...")


model.export(
    format="onnx",
    imgsz=416
)


print("Exportación terminada")
