detector = YOLODetector()

resultado = detector.detect(frame)

if resultado:
    evento()
