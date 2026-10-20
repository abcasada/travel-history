from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"
    VIEWER = "viewer", "Viewer"


class UserManager(BaseUserManager):
    def create_user(self, email: str, display_name: str = "", **extra) -> "User":
        user = self.model(email=self.normalize_email(email), display_name=display_name, **extra)
        user.set_unusable_password()  # logins are OIDC only
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """A login. Identity comes from the OIDC provider, keyed by (issuer, subject); the email is
    informational and never used to link accounts. A user links to at most one Person."""

    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    oidc_issuer = models.CharField(max_length=255, blank=True)
    oidc_sub = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    privacy_notice_ack_at = models.DateTimeField(null=True, blank=True)
    onboarding_done_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["oidc_issuer", "oidc_sub"],
                condition=~models.Q(oidc_sub=""),
                name="user_unique_oidc_identity",
            )
        ]

    def __str__(self) -> str:
        return self.display_name or self.email

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN
