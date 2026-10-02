import os
import sys
import django

os.chdir('a:\\Project\\X\\expense_calculator')
sys.path.insert(0, 'a:\\Project\\X\\expense_calculator')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'expense_calculator.settings')
django.setup()

try:
    from expense.services.text_transaction import TextTransactionService
    print("✓ TextTransactionService imported successfully")
except Exception as e:
    print(f"✗ Error importing TextTransactionService: {e}")
    sys.exit(1)

try:
    from expense import views
    print("✓ expense.views imported successfully")
except Exception as e:
    print(f"✗ Error importing expense.views: {e}")
    sys.exit(1)

print("\nAll imports successful!")
