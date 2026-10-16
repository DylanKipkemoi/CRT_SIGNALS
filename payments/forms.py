from django import forms

from accounts.validators import normalize_kenyan_phone


class PaymentForm(forms.Form):
    phone = forms.CharField(label="M-Pesa phone number", max_length=16,
                            widget=forms.TextInput(attrs={"placeholder": "0712345678", "autocomplete": "tel"}))

    def clean_phone(self):
        return normalize_kenyan_phone(self.cleaned_data["phone"])
