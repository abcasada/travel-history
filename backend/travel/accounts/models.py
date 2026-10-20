from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

from travel.core.choices import DeviceClass


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
    person = models.OneToOneField(
        "accounts.Person", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="user"
    )
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


class Person(models.Model):
    """Anyone who travels, with or without a login. The managing user of a person is its linked
    user if there is one, otherwise `created_by`."""

    class Visibility(models.TextChoices):
        FAMILY = "family", "Family"
        PRIVATE = "private", "Private"

    display_name = models.CharField(max_length=150)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.DO_NOTHING, related_name="persons_created"
    )
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.FAMILY
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.display_name


class UserPreference(models.Model):
    """Per-user settings, optionally per device class (e.g. split-pane width on desktop)."""

    user = models.ForeignKey(User, on_delete=models.DB_CASCADE, related_name="preferences")
    key = models.CharField(max_length=64)
    device_class = models.CharField(
        max_length=16, choices=DeviceClass.choices, default=DeviceClass.ANY
    )
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key", "device_class"], name="userpref_unique_key"
            )
        ]

    def __str__(self) -> str:
        return f"{self.key}[{self.device_class}]"


class DeviceToken(models.Model):
    """Write-only credential for a location tracker. Only the SHA-256 of the token is stored."""

    class Kind(models.TextChoices):
        OWNTRACKS = "owntracks", "OwnTracks"
        OVERLAND = "overland", "Overland"
        GPSLOGGER = "gpslogger", "GPSLogger"
        COLOTA = "colota", "Colota"
        GENERIC = "generic", "Generic"

    user = models.ForeignKey(User, on_delete=models.DB_CASCADE, related_name="device_tokens")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    token_prefix = models.CharField(max_length=12)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    points_received = models.BigIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.name} ({self.token_prefix}…)"


class AccessRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    name = models.CharField(max_length=150)
    email = models.EmailField()
    relationship = models.CharField(max_length=150)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    ip_hash = models.CharField(max_length=64, blank=True)
    turnstile_ok = models.BooleanField(default=False)
    invite = models.ForeignKey(
        "accounts.Invite", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    idp_user_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} <{self.email}> ({self.status})"


class AllowlistEntry(models.Model):
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    created_by = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="+")
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="allowlist_unique_email_ci")]

    def __str__(self) -> str:
        return self.email


class Invite(models.Model):
    """Personal invite link / QR code that pre-fills the request form. Token stored hashed."""

    token_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    relationship = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    created_by = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="+")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"invite for {self.name or self.email or '?'}"


class PushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.DB_CASCADE, related_name="push_subscriptions")
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True)
    failures = models.PositiveIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"push for {self.user_id}"


class PublicProfile(models.Model):
    """A user's public profile page. Off until its owner enables it."""

    user = models.OneToOneField(User, on_delete=models.DB_CASCADE, related_name="public_profile")
    slug = models.SlugField(max_length=64, unique=True)
    enabled = models.BooleanField(default=False)
    display_name = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True)
    avatar = models.ForeignKey(
        "media.Media", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.slug


class IntegrationSetting(models.Model):
    """Per-user external integration (Immich later). Credentials are Fernet-encrypted and never
    returned to clients."""

    class Provider(models.TextChoices):
        IMMICH = "immich", "Immich"

    user = models.ForeignKey(User, on_delete=models.DB_CASCADE, related_name="integrations")
    provider = models.CharField(max_length=16, choices=Provider.choices)
    base_url = models.URLField()
    credential_encrypted = models.TextField(blank=True)
    enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=64, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "provider"], name="integration_unique")
        ]

    def __str__(self) -> str:
        return f"{self.provider} for {self.user_id}"


class AuditLog(models.Model):
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    at = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["at"], name="auditlog_at_idx")]

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d} {self.action}"
