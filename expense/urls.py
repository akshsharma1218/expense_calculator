from django.urls import path

from . import views


urlpatterns = [
    path(
        "transactions/export/",
        views.transaction_export,
        name="transaction-export",
    ),
    path(
        "transactions/template/",
        views.transaction_template_download,
        name="transaction-template",
    ),
    path(
        "accounts/template/",
        views.account_template_download,
        name="account-template",
    ),
    path(
        "accounts/upload/",
        views.account_upload,
        name="account-upload",
    ),
]

urlpatterns += [
    path('health/', views.health_check, name='health-check'),
    path(
        "signup/",
        views.signup,
        name="signup",
    ),
    # Dashboard
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),

    # Accounts
    path(
        "accounts/",
        views.account_list,
        name="account-list",
    ),

    path(
        "accounts/create/",
        views.account_create,
        name="account-create",
    ),
    path(
        "favorites/",
        views.favorite_list,
        name="favorite-list",
    ),
    
    # Transfer
    path(
        "transfers/",
        views.transfer_list,
        name="transfer-list",
    ),

    path(
        "transfers/create/",
        views.transfer_create,
        name="transfer-create",
    ),

    path(
        "transfers/<uuid:pk>/edit/",
        views.transfer_update,
        name="transfer-update",
    ),

    path(
        "transfers/<uuid:pk>/delete/",
        views.transfer_delete,
        name="transfer-delete",
    ),

    # Transactions
    path(
        "transactions/",
        views.transaction_list,
        name="transaction-list",
    ),

    path(
        "transactions/create/",
        views.transaction_create,
        name="transaction-create",
    ),

    path(
        "transactions/<uuid:pk>/edit/",
        views.transaction_update,
        name="transaction-update",
    ),
    path(
        "transactions/<uuid:pk>/split/",
        views.transaction_split,
        name="transaction-split",
    ),
    path(
        "api/transactions/<uuid:pk>/split/",
        views.transaction_split_api,
        name="transaction-split-api",
    ),

    path(
        "transactions/<uuid:pk>/delete/",
        views.transaction_delete,
        name="transaction-delete",
    ),

    path(
        "transactions/receipt-upload/",
        views.receipt_upload,
        name="receipt-upload",
    ),

    path(
        "transactions/text-input/",
        views.text_transaction_input,
        name="text-transaction-input",
    ),

    path(
        "transactions/transactions-upload/",
        views.transactions_upload,
        name="transactions-upload",
    ),

    # Budgets
    path(
        "budgets/",
        views.budget_list,
        name="budget-list",
    ),

    path(
        "budgets/create/",
        views.budget_create,
        name="budget-create",
    ),

    path(
        "budgets/<uuid:pk>/",
        views.budget_detail,
        name="budget-detail",
    ),

    path(
        "budgets/<uuid:pk>/edit/",
        views.budget_update,
        name="budget-update",
    ),

    path(
        "budgets/<uuid:pk>/delete/",
        views.budget_delete,
        name="budget-delete",
    ),

    # Groups
    path(
        "groups/",
        views.group_list,
        name="group-list",
    ),

    path(
        "groups/create/",
        views.group_create,
        name="group-create",
    ),

    path(
        "groups/<uuid:pk>/",
        views.group_detail,
        name="group-detail",
    ),

    path(
        "groups/<uuid:pk>/settle/",
        views.settlement_create,
        name="group-settlement",
    ),

    path(
        "groups/invitations/",
        views.invitation_list,
        name="group-invitations",
    ),

    path(
        "groups/invitations/<uuid:pk>/accept/",
        views.invitation_accept,
        name="group-invitation-accept",
    ),

    path(
        "groups/invitations/<uuid:pk>/decline/",
        views.invitation_decline,
        name="group-invitation-decline",
    ),

    # Reports
    path(
        "reports/monthly/",
        views.monthly_report,
        name="monthly-report",
    ),

    path(
        "reports/category/",
        views.category_report,
        name="category-report",
    ),
    
    # Category
    path(
        "categories/",
        views.category_list,
        name="category-list",
    ),

    path(
        "categories/create/",
        views.category_create,
        name="category-create",
    ),

    path(
        "categories/<uuid:pk>/edit/",
        views.category_update,
        name="category-update",
    ),

    path(
        "categories/<uuid:pk>/delete/",
        views.category_delete,
        name="category-delete",
    ),

    # Merchant
    path(
        "merchants/",
        views.merchant_list,
        name="merchant-list",
    ),

    path(
        "merchants/create/",
        views.merchant_create,
        name="merchant-create",
    ),

    path(
        "merchants/<uuid:pk>/edit/",
        views.merchant_update,
        name="merchant-update",
    ),

    path(
        "merchants/<uuid:pk>/delete/",
        views.merchant_delete,
        name="merchant-delete",
    ),
]