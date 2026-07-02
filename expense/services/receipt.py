from .base import ServiceError
from .gemini import GeminiService
from .ocr import OCRService


class ReceiptService:

    @staticmethod
    def extract(
        *,
        receipt,
    ):

        text = OCRService.extract_text(receipt)
        if not text:
            raise ServiceError(
                "Could not read receipt."
            )
        payload = GeminiService.parse_receipt(
            text,
        )
        return payload