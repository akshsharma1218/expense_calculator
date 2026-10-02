from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel
from .base import BaseService, ServiceError


class TransactionItem(BaseModel):
    name: str
    quantity: float = 1
    unit_price: float


class TextTransaction(BaseModel):
    amount: float
    transaction_date: str
    description: str
    category: str
    items: list[TransactionItem] = []


client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
)

TEXT_PROMPT = """
You are an expense transaction analyzer.

Extract transaction details from natural language text. Examples:
- "spent 500 on groceries today"
- "paid 1200 for lunch with friends yesterday"
- "coffee this morning was 120"

Return ONLY this JSON:
{
  "amount": number,
  "transaction_date": "dd-mm-yyyy",
  "description": "brief description",
  "category": "Food|Travel|Shopping|Entertainment|Utilities|Other",
  "items": [{"name": "item", "quantity": 1, "unit_price": amount}]
}

Rules:
- amount = total transaction amount
- transaction_date = purchase date in dd-mm-yyyy format. If not specified, use today's date.
- description = short description
- category = best fit from list
- items = breakdown if mentioned, otherwise single item with the description as name
- quantity defaults to 1 if not mentioned
"""


class TextTransactionService(BaseService):

    @staticmethod
    def extract(*, text):
        TextTransactionService._log_info(
            "Text transaction extraction started",
            text_length=len(text),
        )

        if not text or len(text.strip()) < 5:
            raise ServiceError("Please provide more detail in the transaction description.")

        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=f"""
{TEXT_PROMPT}

USER TEXT: {text}
""",
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    response_mime_type="application/json",
                    response_schema=TextTransaction,
                ),
            )

            import json
            result_text = response.text
            parsed = json.loads(result_text)

            TextTransactionService._log_info(
                "Text transaction extraction completed",
                amount=parsed.get("amount"),
                category=parsed.get("category"),
            )

            return {
                "amount": float(parsed.get("amount", 0)),
                "transaction_date": parsed.get("transaction_date", ""),
                "description": parsed.get("description", ""),
                "category": parsed.get("category", "Other"),
                "items": [
                    {
                        "name": item.get("name", "Item"),
                        "quantity": float(item.get("quantity", 1)),
                        "unit_price": float(item.get("unit_price", 0)),
                        "total_price": float(item.get("quantity", 1)) * float(item.get("unit_price", 0)),
                    }
                    for item in parsed.get("items", [])
                ],
            }
        except Exception as exc:
            TextTransactionService._log_error(
                "Text transaction extraction error",
                exc_info=True,
            )
            raise ServiceError(f"Failed to parse transaction: {str(exc)}")
