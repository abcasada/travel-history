"""Device tokens for tracker ingestion (work-order item 7, PLAN.md §9.1).

- `token_hash` must look like a hex SHA-256 digest, so no code path can store a raw token.
- A token's identity is fixed once created (owner, hash, display prefix, kind, creation time),
  and a revocation is final: `revoked_at` goes from empty to a time, never back or elsewhere.
  Only the name and the usage counters (`last_used_at`, `points_received`) may change.

Which rows a user may touch is unchanged (core migration 0002: own tokens; the `ingest`
context may look a token up by hash).
"""

from django.db import migrations, models

FORWARD = r"""
CREATE FUNCTION app.guard_device_token_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.token_hash IS DISTINCT FROM OLD.token_hash
     OR NEW.token_prefix IS DISTINCT FROM OLD.token_prefix
     OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'a device token''s identity is fixed' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
    RAISE EXCEPTION 'a revoked device token stays revoked' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER devicetoken_guard BEFORE UPDATE ON accounts_devicetoken
FOR EACH ROW EXECUTE FUNCTION app.guard_device_token_update();
"""

REVERSE = r"""
DROP TRIGGER IF EXISTS devicetoken_guard ON accounts_devicetoken;
DROP FUNCTION IF EXISTS app.guard_device_token_update();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_directory"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="devicetoken",
            constraint=models.CheckConstraint(
                condition=models.Q(("token_hash__regex", "^[0-9a-f]{64}$")),
                name="devicetoken_hash_is_sha256",
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
