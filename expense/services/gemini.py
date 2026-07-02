from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel

class ReceiptItem(BaseModel):
    name: str
    quantity: float
    unit_price: float


class Receipt(BaseModel):
    amount: float
    transaction_date: str | None
    description: str
    items: list[ReceiptItem]

client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
)


PROMPT = """
You are an expense receipt parser.

Extract the following from the OCR text:

- amount
- transaction_date
- description
- items

Rules:
- Return ONLY valid JSON.
- amount = final paid amount (Grand Total/Total/Amount Paid).
- transaction_date = purchase date in dd-mm-yyyy format.
- description = short generic description of the purchase.
- Extract all purchased items with name, quantity, unit_price and total_price.
- Use generic item names.
- If quantity is missing, use 1.
- Create separate items for taxes (GST, CGST, SGST, IGST, VAT, etc.) using name "tax".
- Create separate items for delivery charges using name "delivery".
- Create separate items for other charges (service charge, packaging, convenience fee, platform fee, handling charge, etc.).
- Ignore invoice number, receipt number, payment method, cashier, card details, transaction IDs and QR codes.
- Do not invent items that are not present in the receipt.

Return ONLY this JSON:

{
  "amount": 0,
  "transaction_date": "dd-mm-yyyy",
  "description": "",
  "items": [
    {
      "name": "",
      "quantity": 1,
      "unit_price": 0,
    }
  ]
}
"""

class GeminiService:

    @staticmethod
    def parse_receipt(text):

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=f"""
              {PROMPT}

              OCR TEXT

              {text}
              """,
              config=types.GenerateContentConfig(
              temperature=1.0,
              response_mime_type="application/json",
              response_schema=Receipt,  
              candidate_count=1,
          ),
        )

        return response.parsed.model_dump()