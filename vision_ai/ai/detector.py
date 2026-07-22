from ultralytics import YOLO


class Detector:

    def __init__(self):

        print("=" * 40)
        print("Inicializando Detector IA")

        self.model = YOLO("ai/models/yolov8n.onnx")

        print("Modelo cargado")
        print("=" * 40)

    def detect(self, frame):

        resultados = self.model(
            frame,
            imgsz=416,
            verbose=False,
            conf=0.50
        )

        detecciones = []

        for r in resultados:

            for box in r.boxes:

                x1, y1, x2, y2 = box.xyxy[0].tolist()

                detecciones.append({

                    "label": self.model.names[int(box.cls)],

                    "confidence": float(box.conf),

                    "bbox": [
                        int(x1),
                        int(y1),
                        int(x2),
                        int(y2)
                    ]
                })

        return detecciones
