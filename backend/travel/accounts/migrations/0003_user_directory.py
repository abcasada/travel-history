"""Account privacy (D-72, D-76).

Family members used to read every column of every account row. Now:

- `accounts_user` rows are readable only by the account itself (while active, D-53), by the
  Admin, and by the narrow login context. Email, OIDC issuer and subject, role and timestamps
  stay there.
- Everyone in the family reads other accounts through `accounts_userdirectory`, a view with a
  fixed column list: id, display name, the linked person (the permission rules need it to find
  a person's managing user) and whether the account is active.

The view is owned by the owner role, so it reads the base table without its row policies;
`app.is_family()` limits it to signed-in, active accounts, and `security_barrier` keeps caller
conditions from being evaluated before that check. Grants live in travel/core/db_privileges.py.
"""

from django.db import migrations, models

FORWARD = r"""
DROP POLICY user_select ON accounts_user;
CREATE POLICY user_select ON accounts_user FOR SELECT TO travel_app
  USING ((id = app.user_id() AND app.is_family()) OR app.is_admin() OR app.ctx() = 'auth');

CREATE VIEW accounts_userdirectory WITH (security_barrier = true) AS
  SELECT id, display_name, person_id, is_active
    FROM accounts_user
   WHERE app.is_family();
COMMENT ON VIEW accounts_userdirectory IS
  'Family-visible account columns only (D-72, D-76). Never add identity or contact columns.';
"""

REVERSE = r"""
DROP VIEW accounts_userdirectory;
DROP POLICY user_select ON accounts_user;
CREATE POLICY user_select ON accounts_user FOR SELECT TO travel_app
  USING (id = app.user_id() OR app.is_family() OR app.ctx() = 'auth');
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"),
        ("core", "0002_row_level_security"),
    ]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.CreateModel(
            name="UserDirectory",
            fields=[
                ("id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("display_name", models.CharField(max_length=150)),
                ("person_id", models.BigIntegerField(null=True)),
                ("is_active", models.BooleanField()),
            ],
            options={"managed": False, "db_table": "accounts_userdirectory"},
        ),
    ]
