from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("visualizations/", views.visualizations, name="visualizations"),
    path("analytics/", views.analytics_hub, name="analytics_hub"),
    path("register/", views.register, name="register"),
    path("reports/", views.reports, name="reports"),
    path("expenses/", views.expense_list, name="expense_list"),
    path("expenses/add/", views.expense_create, name="expense_create"),
    path("expenses/<int:pk>/edit/", views.expense_update, name="expense_update"),
    path("expenses/<int:pk>/delete/", views.expense_delete, name="expense_delete"),
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/add/", views.account_create, name="account_create"),
    path("accounts/<int:pk>/edit/", views.account_update, name="account_update"),
    path("import/csv/", views.import_csv, name="import_csv"),
    path("import/pdf/", views.import_pdf, name="import_pdf"),
    path("import/pdf/preview/", views.import_pdf_preview, name="import_pdf_preview"),
    path("imports/history/", views.import_history, name="import_history"),
]
