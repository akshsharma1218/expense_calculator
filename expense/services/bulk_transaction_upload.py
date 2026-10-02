from decimal import Decimal, InvalidOperation
import csv
from datetime import datetime
from io import StringIO

from django.db import transaction as db_transaction
from django.db import models

from .transactions import TransactionService

from ..models import (
    Account,
    EntryType,
    Category,
    Merchant,
)
from .base import BaseService, ServiceError


class BulkTransactionUploadService(BaseService):
    """
    Optimized bulk transaction upload service.

    Improvements:
    - Single query for Accounts
    - Single query for Categories
    - Single query for Merchants
    - Bulk create missing Categories
    - Bulk create missing Merchants
    - Atomic upload with full rollback on error
    - Comprehensive validation before creation
    - Dictionary lookups instead of DB hits
    - User context for category/merchant creation
    - Detailed error reporting
    """

    BATCH_SIZE = 500
    MAX_FILE_SIZE = 10 * 1024 * 1024 

    @staticmethod
    def _parse_transaction_date(raw_value):
        value = (raw_value or "").strip()

        if not value:
            return None

        # Keep existing ISO support, then allow slash-based CSV dates.
        formats = [
            "%m/%d/%Y",
            "%m-%d-%Y",
        ]
        print(f"Attempting to parse date: {value}")
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue

        return None
    
    def extract_transactions(self, file):
        """Extract CSV rows with size validation."""
        self._log_info("Bulk CSV extraction started", upload_filename=getattr(file, "name", None))
        # Validate file size
        file.seek(0, 2)  # Seek to end
        size = file.tell()
        file.seek(0)  # Reset to beginning
        
        if size > self.MAX_FILE_SIZE:
            self._log_warning(
                "Bulk CSV rejected due to size",
                upload_filename=getattr(file, "name", None),
                size=size,
                max_size=self.MAX_FILE_SIZE,
            )
            raise ServiceError(
                f"File size exceeds {self.MAX_FILE_SIZE // (1024*1024)}MB limit"
            )
        
        decoded = file.read().decode("utf-8-sig")
        print(f"Decoded CSV content:\n{decoded[:500]}...")  # Print first 500 chars for debugging
        reader = csv.DictReader(StringIO(decoded))
        print(f"CSV headers: {reader.fieldnames}")  # Debugging output for headers
        if not reader.fieldnames:
            self._log_warning("Bulk CSV rejected due to missing headers")
            raise ServiceError("CSV file is empty or invalid format")
        reader.fieldnames = [(field or "").strip().lower() for field in reader.fieldnames]

        rows = []

        for index, row in enumerate(reader, start=2):
            row["_row"] = index
            print(f"Extracted row {index}: {row}")  # Debugging output for each row
            rows.append(row)

        return rows

    #####################################################################
    # Validation
    #####################################################################

    def validate_rows(self, rows):
        """Validate all rows before processing."""
        required = [
            "amount",
            "category",
            "transaction_date",
            "account",
        ]

        errors = []

        for row in rows:

            for field in required:

                if not row.get(field) or not row.get(field).strip():
                    errors.append(
                        f"Row {row['_row']}: Missing required field '{field}'"
                    )

            try:
                amount = Decimal(row["amount"])
                if not amount.is_finite() or amount == 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError):
                errors.append(
                    f"Row {row['_row']}: Invalid amount '{row['amount']}'. Must be a valid decimal."
                )

            category_type = (row.get("category_type") or "expense").strip().lower()
            if category_type not in Category.CategoryType.values:
                errors.append(f"Row {row['_row']}: Invalid category type '{category_type}'.")
            normal_side = (row.get("category_normal_side") or "").strip().lower()
            if normal_side and normal_side not in EntryType.values:
                errors.append(f"Row {row['_row']}: Invalid category normal side '{normal_side}'.")

            # Validate date format
            parsed_date = self._parse_transaction_date(row.get("transaction_date", ""))
            if not parsed_date:
                errors.append(
                    f"Row {row['_row']}: Invalid date format '{row.get('transaction_date')}'. Use MM/DD/YYYY or MM-DD-YYYY."
                )
            else:
                # Normalize for downstream service/model handling.
                row["transaction_date"] = parsed_date.isoformat()

            print(f"Row {row} validated successfully.")
        if errors:
            raise ServiceError(
                f"Validation failed with {len(errors)} error(s):\n"
                + "\n".join(errors[:10])  
                + (f"\n... and {len(errors) - 10} more errors" if len(errors) > 10 else "")
            )

    #####################################################################
    # Prefetch
    #####################################################################

    def load_accounts(self, rows, user):
        """Load and validate accounts from rows."""
        names = {
            r["account"].strip()
            for r in rows
            if r.get("account")
        }

        accounts = {
            a.name: a
            for a in Account.objects.filter(name__in=names, user = user)
        }

        missing = names - accounts.keys()

        if missing:
            raise ServiceError(
                f"Unknown Accounts: {', '.join(sorted(missing))}. "
                f"Please create these accounts first."
            )

        return accounts

    def load_categories(self, rows, user):
        """Load categories and auto-create missing ones with user context."""
        names = {
            r["category"].strip()
            for r in rows
            if r.get("category")
        }

        existing = {
            c.name: c
            for c in Category.objects.filter(
                models.Q(is_system=True) | models.Q(created_by=user),
                name__in=names
            )
        }

        missing = names - existing.keys()

        if missing:
            category_specs = {}
            for row in rows:
                name = (row.get("category") or "").strip()
                if name not in missing or name in category_specs:
                    continue
                category_type = (row.get("category_type") or "expense").strip().lower()
                normal_side = (row.get("category_normal_side") or "").strip().lower()
                if not normal_side:
                    normal_side = EntryType.CREDIT if category_type == Category.CategoryType.INCOME else EntryType.DEBIT
                category_specs[name] = (category_type, normal_side)

            new_categories = [
                Category(
                    name=name,
                    category_type=category_specs[name][0],
                    normal_side=category_specs[name][1],
                    created_by=user,
                    is_system=False,
                )
                for name in missing
            ]
            
            Category.objects.bulk_create(
                new_categories,
                ignore_conflicts=True
            )

            existing = {
                c.name: c
                for c in Category.objects.filter(
                    models.Q(is_system=True) | models.Q(created_by=user),
                    name__in=names
                )
            }

        return existing

    def load_merchants(self, rows, user):
        """Load merchants and auto-create missing ones with user context."""
        names = {
            r["merchant"].strip()
            for r in rows
            if r.get("merchant")
        }

        existing = {
            m.name: m
            for m in Merchant.objects.filter(
                models.Q(is_system=True) | models.Q(created_by=user),
                name__in=names
            )
        }

        missing = names - existing.keys()

        if missing:

            new_merchants = [
                Merchant(
                    name=name,
                    created_by=user,
                    is_system=False
                )
                for name in missing
            ]
            
            Merchant.objects.bulk_create(
                new_merchants,
                ignore_conflicts=True
            )

            existing = {
                m.name: m
                for m in Merchant.objects.filter(
                    models.Q(is_system=True) | models.Q(created_by=user),
                    name__in=names
                )
            }

        return existing

    #####################################################################
    # Item
    #####################################################################

    def create_item(self, amount):
        """Create transaction item."""
        item = {
            "name": "Item",
            "quantity": 1,
            "unit_price": amount,
            "total_price": amount,
        }

        return [item]

    #####################################################################
    # Upload
    #####################################################################

    @db_transaction.atomic
    def upload(self, user, file):
        """
        Atomically upload bulk transactions.
        
        Optimizations:
        - Single query per resource type (Account, Category, Merchant)
        - Dictionary lookups (O(1)) instead of repeated DB queries
        - Bulk create for missing categories/merchants
        - Row-by-row transaction creation for atomic safety
        - Full transaction rollback on any error
        - Fail fast on the first invalid row
        
        Args:
            user: The authenticated user
            file: CSV file object
            
        Returns:
            dict: Upload result with success status and count
            
        Raises:
            ServiceError: On validation or processing errors
        """

        self._log_info(
            "Bulk transaction upload started",
            user_id=getattr(user, "id", None),
            upload_filename=getattr(file, "name", None),
        )

        rows = self.extract_transactions(file)

        if not rows:
            self._log_warning(
                "Bulk upload failed: no rows",
                user_id=getattr(user, "id", None),
            )
            raise ServiceError("CSV contains no data. Please provide at least one transaction row.")

        self.validate_rows(rows)

        # Load all required resources with single queries
        account_cache = self.load_accounts(rows, user)
        category_cache = self.load_categories(rows, user)
        merchant_cache = self.load_merchants(rows, user)

        created = 0

        # Process transactions; any row failure aborts the whole batch.
        for row in rows:

            try:
                amount = Decimal(row["amount"])
                merchant_name = (row.get("merchant") or "").strip()
                self._log_info(
                    f"{user}, type(user): {type(user)}, user.id: {getattr(user, 'id', None)}, row: {row}"
                )
                TransactionService.create_transaction(
                    user=user,
                    account=account_cache[row["account"].strip()],
                    category=category_cache[row["category"].strip()],
                    merchant=merchant_cache.get(merchant_name),
                    amount=amount,
                    transaction_date=row["transaction_date"],
                    description=row.get("description", ""),
                    is_group_expense=False,
                    items=None,
                )
                created += 1
                
            except ServiceError as e:
                self._log_error(
                    f"Bulk upload row service error",
                    exc_info=True,
                    user_id=getattr(user, "id", None),
                    row=row.get("_row", "unknown"),
                    detail=str(e),
                )
                raise ServiceError(
                    f"Row {row.get('_row', 'unknown')}: {str(e)}"
                ) from e
            except Exception as e:
                self._log_error(
                    "Bulk upload row unexpected error",
                    exc_info=True,
                    user_id=getattr(user, "id", None),
                    row=row.get("_row", "unknown"),
                    detail=str(e),
                )
                raise ServiceError(
                    f"Row {row.get('_row', 'unknown')}: Unexpected error: {str(e)}"
                ) from e

        self._log_info(
            "Bulk transaction upload completed",
            user_id=getattr(user, "id", None),
            created=created,
            failed=0,
            total=created,
        )
        return {
            "success": True,
            "created": created,
            "failed": 0,
            "total": created,
            "errors": None,
        }
