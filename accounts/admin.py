from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.utils import timezone

from core.audit import audit

from .models import User


class AdminUserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "full_name", "phone")

    def clean_password2(self):
        if self.cleaned_data.get("password1") != self.cleaned_data.get("password2"):
            raise forms.ValidationError("Passwords don't match")
        return self.cleaned_data["password2"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class AdminUserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField()

    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    list_display = ("email", "full_name", "masked_phone", "is_verified", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "full_name", "phone")
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "last_login", "accepted_terms_at", "suspended_at")
    actions = ["suspend_users", "reactivate_users", "mark_verified"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "email_verified_at", "accepted_terms_at")}),
        ("Status", {"fields": ("is_active", "suspended_at", "suspended_reason")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "full_name", "phone", "password1", "password2")}),)

    @admin.display(boolean=True)
    def is_verified(self, obj):
        return obj.is_verified

    @admin.action(description="Suspend selected accounts")
    def suspend_users(self, request, queryset):
        count = 0
        for user in queryset.exclude(pk=request.user.pk).filter(is_active=True):
            user.is_active = False
            user.suspended_at = timezone.now()
            user.suspended_reason = user.suspended_reason or "Suspended by administrator"
            user.save(update_fields=["is_active", "suspended_at", "suspended_reason"])
            audit("account.suspended", request=request, target=user)
            count += 1
        self.message_user(request, f"Suspended {count} account(s).", messages.WARNING)

    @admin.action(description="Reactivate selected accounts")
    def reactivate_users(self, request, queryset):
        for user in queryset.filter(is_active=False):
            user.is_active = True
            user.suspended_at = None
            user.suspended_reason = ""
            user.save(update_fields=["is_active", "suspended_at", "suspended_reason"])
            audit("account.reactivated", request=request, target=user)
        self.message_user(request, "Accounts reactivated.")

    @admin.action(description="Mark email as verified")
    def mark_verified(self, request, queryset):
        for user in queryset.filter(email_verified_at__isnull=True):
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
            audit("account.verified_by_admin", request=request, target=user)
