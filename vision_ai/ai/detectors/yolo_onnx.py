import cv2
import numpy as np
import onnxruntime as ort


class YOLOONNX:

    def __init__(self, model_path):

        print("Cargando ONNX optimizado...")


        opciones = ort.SessionOptions()


        # Optimización del grafo
        opciones.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )


        # Usar todos los núcleos de Raspberry Pi 4
        opciones.intra_op_num_threads = 4
        opciones.inter_op_num_threads = 4


        self.session = ort.InferenceSession(
            model_path,
            sess_options=opciones,
            providers=[
                "CPUExecutionProvider"
            ]
        )


        self.input_name = (
            self.session
            .get_inputs()[0]
            .name
        )


        print("ONNX optimizado listo")


    def detect(self, frame):

        img = cv2.resize(
            frame,
            (416,416)
        )


        img = cv2.cvtColor(
            img,
            cv2.COLOR_BGR2RGB
        )


        img = img.astype(
            np.float32
        ) / 255.0


        img = np.transpose(
            img,
            (2,0,1)
        )


        img = np.expand_dims(
            img,
            axis=0
        )


        resultado = self.session.run(
            None,
            {
                self.input_name: img
            }
        )


        return resultado
