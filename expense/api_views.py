from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import (
    TransactionService,
    ServiceError,
    ReceiptService,
)
from django.shortcuts import (
    render,
    redirect,
)
from .serializers import TransactionCreateSerializer
from django.contrib.auth.decorators import login_required
from .forms import ReceiptUploadForm
from django.contrib import messages


@login_required
def receipt_upload(request):

    if request.method == "POST":

        form = ReceiptUploadForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():

            try:

                payload = ReceiptService.extract(
                    receipt=form.cleaned_data["receipt"],
                )

                request.session["transaction_initial"] = {
                    "form": {
                        "amount": payload["amount"],
                        "transaction_date": payload["transaction_date"],
                        "description": payload["description"],
                    },
                    "items": payload["items"],
                }

                return redirect("transaction-create")

            except ServiceError as exc:

                messages.error(
                    request,
                    str(exc),
                )

    else:

        form = ReceiptUploadForm()

    return render(
        request,
        "expense/transaction/upload_form.html",
        {
            "form": form,
        },
    )

class TransactionCreateAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        serializer = TransactionCreateSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(
            raise_exception=True,
        )

        try:

            txn = TransactionService.create_transaction(
                user=request.user,
                **serializer.validated_data,
            )

        except ServiceError as exc:

            return Response(
                {
                    "detail": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "id": txn.id,
                "message": "Transaction created.",
            },
            status=status.HTTP_201_CREATED,
        )