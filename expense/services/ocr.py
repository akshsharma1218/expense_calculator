import numpy as np
import os

os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"

from paddleocr import PaddleOCR
from PIL import Image


class OCRService:

    _ocr = None

    @classmethod
    def get_ocr(cls):
        if cls._ocr is None:
            cls._ocr = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                enable_mkldnn=False,
            )
        return cls._ocr
    
    @classmethod
    def extract_text(cls, image_file):

        image = Image.open(image_file).convert("RGB")
        image_np = np.array(image)

        results = cls.get_ocr().predict(image_np)

        lines = []

        for result in results:
            rec_texts = result.get("rec_texts", [])

            for text in rec_texts:
                text = text.strip()
                if text:
                    lines.append(text)

        return "\n".join(lines)