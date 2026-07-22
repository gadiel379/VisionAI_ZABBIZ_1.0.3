import cv2

cap = cv2.VideoCapture("/dev/video0")

if not cap.isOpened():
    print("No se pudo abrir la cámara")
    exit()

while True:
    ret, frame = cap.read()

    if not ret:
        print("No llegó imagen")
        break

    print(frame.shape)

cap.release()
