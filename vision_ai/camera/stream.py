import threading
import time


class CameraStream:

    def __init__(self, camera):

        self.camera = camera
        self.frame = None
        self.running = False
        self.thread = None


    def start(self):

        self.running = True

        self.thread = threading.Thread(
            target=self.update,
            daemon=True
        )

        self.thread.start()

        return self


    def update(self):

        while self.running:

            frame = self.camera.read()

            if frame is not None:
                self.frame = frame

            time.sleep(0.001)


    def read(self):

        return self.frame


    def stop(self):

        self.running = False

        if self.thread:
            self.thread.join()
