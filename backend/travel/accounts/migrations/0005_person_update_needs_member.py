"""People are edited by their managing user or the Admin, never by a Viewer (work-order item
21b, D-113; docs/design/permissions.md §6.3 'Person: edit').

Core migration 0002's `person_update` policy let any managing user update the row, so a Viewer
could rename their own linked person at the SQL level although the matrix says Viewers are
read-only. `PATCH /persons/{id}` (item 21b) is the first code path that edits people, so the
policy now agrees with `policy.can_edit_person`: the Admin, or a managing Member.
"""

from django.db import migrations

FORWARD = r"""
DROP POLICY person_update ON accounts_person;
CREATE POLICY person_update ON accounts_person FOR UPDATE TO travel_app
  USING (app.is_admin() OR (app.can_create() AND app.manages_person(id)))
  WITH CHECK (app.is_admin() OR (app.can_create() AND app.manages_person(id)));
"""

REVERSE = r"""
DROP POLICY person_update ON accounts_person;
CREATE POLICY person_update ON accounts_person FOR UPDATE TO travel_app
  USING (app.manages_person(id) OR app.is_admin())
  WITH CHECK (app.manages_person(id) OR app.is_admin());
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_device_token_guards"),
        ("core", "0002_row_level_security"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
