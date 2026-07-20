import cv2

class Camera:

    def __init__(self, device, width, height, fps):

        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)

        # Solicitar MJPG
        self.cap.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*'MJPG')
         )

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,height)
        self.cap.set(cv2.CAP_PROP_FPS,fps)

    def read(self):

        ok, frame = self.cap.read()

        if not ok:
            return None

        return frame

    def release(self):
        self.cap.release()
