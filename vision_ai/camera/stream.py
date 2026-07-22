import threading
import time


class CameraStream:

    def __init__(
        self,
        camera,
        frame_callback=None,
        state_callback=None,
        missing_frames_before_offline=3,
    ):

        self.camera = camera
        self.frame_callback = frame_callback
        self.state_callback = state_callback
        self.frame = None
        self.running = False
        self.thread = None
        self.online = False
        self.missing_frames = 0
        self.missing_frames_before_offline = max(
            1, int(missing_frames_before_offline)
        )


    def _set_online(self, online):

        online = bool(online)

        if self.online == online:
            return

        self.online = online

        if self.state_callback is not None:
            try:
                self.state_callback(online)
            except Exception as error:
                print(f"[CAMERA STREAM] Error en callback de estado: {error}")


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

            try:
                frame = self.camera.read()
            except Exception as error:
                # Ultima barrera de proteccion: una falla transitoria del
                # backend V4L2 nunca debe terminar el hilo de adquisicion.
                print(f"[CAMERA STREAM] Error de captura controlado: {error}")
                time.sleep(0.1)
                continue

            if not self.running:
                break

            if frame is not None:
                self.missing_frames = 0
                self.frame = frame
                self._set_online(True)
                if self.frame_callback is not None:
                    try:
                        self.frame_callback()
                    except Exception as error:
                        print(f"[CAMERA STREAM] Error en callback de frame: {error}")

            else:
                self.missing_frames += 1
                if self.missing_frames >= self.missing_frames_before_offline:
                    # Nunca mantener el ultimo frame como si siguiera siendo
                    # video actual. Esto tambien detiene la alimentacion HLS.
                    self.frame = None
                    self._set_online(False)

            time.sleep(0.001)


    def read(self):

        return self.frame


    def stop(self):

        self.running = False

        if self.thread:
            self.thread.join()

        self.frame = None
        self._set_online(False)
