from .base import BaseService, ServiceError
from .gemini import GeminiService


class ReceiptService(BaseService):

    @staticmethod
    def extract(
        *,
        receipt,
    ):
        ReceiptService._log_info(
            "Receipt extraction started",
            upload_filename=getattr(receipt, "name", None),
            size=getattr(receipt, "size", None),
        )

        try:
            from .ocr import OCRService
        except ImportError as exc:
            raise ServiceError(
                "Receipt OCR is not included in the lightweight EC2 micro deployment."
            ) from exc

        text = OCRService.extract_text(receipt)
        if not text:
            ReceiptService._log_warning(
                "Receipt extraction failed: no text",
                upload_filename=getattr(receipt, "name", None),
            )
            raise ServiceError(
                "Could not read receipt."
            )
        payload = GeminiService.parse_receipt(
            text,
        )
        ReceiptService._log_info(
            "Receipt extraction completed",
            upload_filename=getattr(receipt, "name", None),
            item_count=len(payload.get("items", [])),
        )
        return payload
