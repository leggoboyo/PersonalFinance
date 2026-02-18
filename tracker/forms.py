from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Account, Expense


class CustomUserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["account", "title", "amount", "category", "transaction_type", "date"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = Account.objects.filter(
                user=user, is_active=True
            )

        for name, field in self.fields.items():
            if name == "transaction_type":
                field.widget.attrs.update({"class": "form-select"})
            else:
                field.widget.attrs.update({"class": "form-control"})


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ["name", "institution", "account_type", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in {"account_type"}:
                field.widget.attrs.update({"class": "form-select"})
            elif name == "is_active":
                field.widget.attrs.update({"class": "form-check-input"})
            else:
                field.widget.attrs.update({"class": "form-control"})


class CSVImportForm(forms.Form):
    account = forms.ModelChoiceField(queryset=Account.objects.none(), required=False)
    csv_file = forms.FileField(
        help_text="Expected columns: date,title,amount,category,transaction_type,account"
    )
    has_header = forms.BooleanField(initial=True, required=False)
    allow_duplicate_statement = forms.BooleanField(
        initial=False,
        required=False,
        help_text="Disabled by default. Enable only if you intentionally need to re-import the same file.",
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = Account.objects.filter(user=user)
        self.fields["account"].widget.attrs.update({"class": "form-select"})
        self.fields["csv_file"].widget.attrs.update({"class": "form-control"})
        self.fields["has_header"].widget.attrs.update({"class": "form-check-input"})
        self.fields["allow_duplicate_statement"].widget.attrs.update(
            {"class": "form-check-input"}
        )


class PDFImportForm(forms.Form):
    account = forms.ModelChoiceField(queryset=Account.objects.none(), required=True)
    pdf_file = forms.FileField(help_text="Upload your monthly statement PDF.")
    statement_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Optional statement end date (improves year inference for dates like 12/31).",
    )
    allow_duplicate_statement = forms.BooleanField(
        initial=False,
        required=False,
        help_text="Disabled by default. Enable only if you intentionally need to re-import the same file.",
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = Account.objects.filter(user=user)
        self.fields["account"].widget.attrs.update({"class": "form-select"})
        self.fields["pdf_file"].widget.attrs.update(
            {"class": "form-control", "accept": "application/pdf"}
        )
        self.fields["statement_date"].widget.attrs.update({"class": "form-control"})
        self.fields["allow_duplicate_statement"].widget.attrs.update(
            {"class": "form-check-input"}
        )
