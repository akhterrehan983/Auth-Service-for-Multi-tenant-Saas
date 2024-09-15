from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)


class Organization(models.Model):
    name = models.CharField(max_length=255, null=False)
    status = models.IntegerField(default=0, null=False)
    personal = models.BooleanField(default=False, null=True)
    settings = models.JSONField(default=dict, null=True)
    created_at = models.DateTimeField(null=True, auto_now_add=True)
    updated_at = models.DateTimeField(null=True, auto_now=True)

    def __str__(self):
        return f"{self.id} - {self.name}"


# Define the custom UserManager
class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if not extra_fields.get("is_staff"):
            raise ValueError("Superuser must have is_staff=True.")
        if not extra_fields.get("is_superuser"):
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


# Updated User model without username but with 'is_staff' and 'is_superuser'
class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, null=False)
    password = models.CharField(max_length=255, null=False)
    profile = models.JSONField(default=dict, null=False)
    status = models.IntegerField(default=0, null=False)
    settings = models.JSONField(default=dict, null=True)
    created_at = models.DateTimeField(null=True, auto_now_add=True)
    updated_at = models.DateTimeField(null=True, auto_now=True)
    is_staff = models.BooleanField(
        default=False
    )  # Added to support Django admin and auth checks
    is_superuser = models.BooleanField(
        default=False
    )  # Added to support Django admin and auth checks

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # No additional fields required for superuser creation

    objects = UserManager()

    def __str__(self):
        return f"{self.id} - {self.email}"

    def has_perm(self, perm, obj=None):
        # This method is required for Django's admin. You might want to adjust its behavior to fit your needs.
        return self.is_superuser

    def has_module_perms(self, app_label):
        # This method is also required for Django's admin.
        return self.is_superuser


class Role(models.Model):
    name = models.CharField(max_length=255, null=False)
    description = models.TextField(null=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="roles"
    )

    def __str__(self):
        return f"{self.id} - {self.name}"


class Member(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="members")
    status = models.IntegerField(default=0, null=False)
    settings = models.JSONField(default=dict, null=True)
    created_at = models.DateTimeField(null=True, auto_now_add=True)
    updated_at = models.DateTimeField(null=True, auto_now=True)

    def __str__(self):
        return f"{self.id} - {self.user.email} - {self.role.name} at {self.organization.name}"
