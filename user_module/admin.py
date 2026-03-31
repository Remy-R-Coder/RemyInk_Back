from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.utils.html import format_html

from .models import (
    User, FreelancerProfile, Admin, Freelancer, Client, 
    Role, RoleIDCounter, Rating
)
from pay_freelancer.models import Payout, PayoutLog


@admin.register(User)
class MyUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'role', 'is_active', 'current_balance', 'pending_balance')
    search_fields = ('username', 'email')
    list_filter = ('role', 'is_active')
    readonly_fields = ('date_joined', 'last_login', 'current_balance', 'pending_balance', 'total_earnings')
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Personal Info', {'fields': ('phone', 'role')}),
        ('Balance Information', {'fields': ('current_balance', 'pending_balance', 'total_earnings')}),
        ('Status', {'fields': ('is_active', 'is_staff', 'is_superuser', 'warnings', 'suspended_until')}),
        ('Permissions', {'fields': ('groups', 'user_permissions')}),
        ('Important Dates', {'fields': ('date_joined', 'last_login')}),
    )


class RoleScopedAdminMixin:
    role = None

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(role=self.role)


class FreelancerCreationForm(forms.ModelForm):
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Password confirmation"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "phone", "password", "password2")

    def clean_password2(self):
        if self.cleaned_data.get("password") != self.cleaned_data.get("password2"):
            raise forms.ValidationError(_("Passwords don't match."))
        return self.cleaned_data["password2"]

    def save(self, commit=True):
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password"]
        phone = self.cleaned_data.get("phone")
        user, _ = User.objects.create_freelancer(email=email, phone=phone)
        user.set_password(password)
        if commit:
            user.save()
        self.instance = user
        return self.instance

    def save_m2m(self):
        """
        Required by Django Admin when using custom save logic 
        in a ModelForm with related many-to-many fields.
        """
        pass


class AdminCreationForm(forms.ModelForm):
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Password confirmation"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("username", "email", "password", "password2")

    def clean_password2(self):
        if self.cleaned_data.get("password") != self.cleaned_data.get("password2"):
            raise forms.ValidationError(_("Passwords don't match."))
        return self.cleaned_data["password2"]

    def save(self, commit=True):
        return User.objects.create_superuser(
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            username=self.cleaned_data['username']
        )


class ClientCreationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email", "phone", "is_active")

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_("This email is already in use."))
        return email

    def save(self, commit=True):
        return User.objects.create_client(
            email=self.cleaned_data['email'],
            phone=self.cleaned_data.get('phone'),
            activate=self.cleaned_data.get('is_active')
        )[0]


def suspend_users(modeladmin, request, queryset):
    queryset.update(suspended_until=timezone.now() + timezone.timedelta(days=30))


def unsuspend_users(modeladmin, request, queryset):
    queryset.update(suspended_until=None)


def reset_warnings(modeladmin, request, queryset):
    queryset.update(warnings=0)


@admin.register(FreelancerProfile)
class FreelancerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'rating', 'completed_jobs', 'is_available', 'has_payout_method', 'created_at')
    search_fields = ('user__username', 'user__email', 'mpesa_number')
    list_filter = ('is_available', 'payout_preference', 'rating')
    readonly_fields = ('created_at', 'updated_at', 'rating', 'completed_jobs')
    filter_horizontal = ('categories', 'subjects')
    
    fieldsets = (
        (None, {'fields': ('user',)}),
        ('Profile Information', {'fields': ('bio', 'hourly_rate', 'experience_years')}),
        ('Availability', {'fields': ('is_available', 'max_jobs_concurrent')}),
        ('Skills', {'fields': ('categories', 'subjects')}),
        ('Payout Information', {'fields': ('payout_preference', 'mpesa_number')}),
        ('Stats', {'fields': ('rating', 'completed_jobs', 'created_at', 'updated_at')}),
    )


@admin.register(Freelancer)
class FreelancerAdmin(RoleScopedAdminMixin, admin.ModelAdmin):
    role = Role.FREELANCER
    list_display = ('username', 'email', 'current_balance', 'available_for_payout', 'is_active', 'is_suspended', 'warnings')
    search_fields = ('username', 'email', 'phone')
    list_filter = ('is_active', 'warnings', 'date_joined')
    ordering = ('username',)
    actions = [suspend_users, unsuspend_users, reset_warnings]
    readonly_fields = ('current_balance', 'pending_balance', 'total_earnings', 'date_joined', 'last_login')

    def get_form(self, request, obj=None, **kwargs):
        if obj:
            return super().get_form(request, obj, **kwargs)
        kwargs['form'] = FreelancerCreationForm
        return super().get_form(request, obj, **kwargs)

    def response_add(self, request, obj, post_url_continue=None):
        if "_addanother" not in request.POST and "_continue" not in request.POST:
            url = reverse("admin:user_module_freelancer_change", args=[obj.pk])
            return HttpResponseRedirect(url)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if "_continue" not in request.POST:
            url = reverse("admin:user_module_freelancer_changelist")
            return HttpResponseRedirect(url)
        return super().response_change(request, obj)


@admin.register(Client)
class ClientAdmin(RoleScopedAdminMixin, admin.ModelAdmin):
    role = Role.CLIENT
    list_display = ('username', 'email', 'phone', 'is_active', 'warnings', 'date_joined', 'last_login')
    search_fields = ('username', 'email', 'phone')
    list_filter = ('is_active', 'warnings', 'date_joined')
    ordering = ('-date_joined',)
    readonly_fields = ('username', 'date_joined', 'last_login', 'current_balance', 'pending_balance', 'total_earnings')
    actions = [suspend_users, unsuspend_users, reset_warnings]

    def get_form(self, request, obj=None, **kwargs):
        if obj:
            return super().get_form(request, obj, **kwargs)
        kwargs['form'] = ClientCreationForm
        return super().get_form(request, obj, **kwargs)


@admin.register(Admin)
class AdminAdmin(RoleScopedAdminMixin, BaseUserAdmin):
    role = Role.ADMIN
    add_form = AdminCreationForm
    list_display = ('username', 'email', 'is_superuser', 'last_login')
    search_fields = ('username', 'email')
    ordering = ('username',)
    actions = [suspend_users, unsuspend_users, reset_warnings]

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password', 'is_superuser', 'is_active')}),
        ('Permissions', {'fields': ('groups', 'user_permissions')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',), 
            'fields': ('username', 'email', 'password', 'password2'),
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        if obj:
            return super().get_form(request, obj, **kwargs)
        kwargs['form'] = self.add_form
        return super().get_form(request, obj, **kwargs)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('rater', 'rated_user', 'score', 'created_at')
    list_filter = ('score', 'created_at')
    search_fields = ('rater__username', 'rater__email', 'rated_user__username', 'rated_user__email')
    readonly_fields = ('created_at',)
    
    fieldsets = (
        (None, {'fields': ('rater', 'rated_user', 'score', 'review')}),
        ('Timestamps', {'fields': ('created_at',)}),
    )


@admin.register(RoleIDCounter)
class RoleIDCounterAdmin(admin.ModelAdmin):
    list_display = ('role', 'next_id')
    list_editable = ('next_id',)
    readonly_fields = ('role',)
    
    def has_add_permission(self, request):
        return False