"""Trip spreadsheet import (work-order item 14c-1, docs/design/trip-sheet.md §28.11): stop and leg
sheet keys, stop time precision and batch, and the own-only tables `tripsheetrecord` (parsed tabs,
append-only except the commit's outcome) and `tripsheetlink` (key -> trip, outlives the trip)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


# Raw history of their owner (permissions.md §6.3): only the owner reads or changes them, never
# the Admin; writing needs a role that may import. A record or link may point only at the
# owner's own batch, trip and record, so a key can never stand for someone else's trip. The
# helpers run once per statement (InitPlan), as in history migration 0007.
SQL = """
ALTER TABLE trips_tripsheetrecord ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON trips_tripsheetrecord FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND (SELECT app.is_family()))
  WITH CHECK (owner_id = app.user_id() AND (SELECT app.can_create())
              AND EXISTS (SELECT 1 FROM history_importbatch b
                           WHERE b.id = import_batch_id AND b.owner_id = app.user_id())
              AND (trip_id IS NULL OR EXISTS (SELECT 1 FROM trips_trip t
                                               WHERE t.id = trip_id
                                                 AND t.owner_id = app.user_id())));

ALTER TABLE trips_tripsheetlink ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON trips_tripsheetlink FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND (SELECT app.is_family()))
  WITH CHECK (owner_id = app.user_id() AND (SELECT app.can_create())
              AND (trip_id IS NULL OR EXISTS (SELECT 1 FROM trips_trip t
                                               WHERE t.id = trip_id
                                                 AND t.owner_id = app.user_id()))
              AND (last_record_id IS NULL OR EXISTS (SELECT 1 FROM trips_tripsheetrecord r
                                                      WHERE r.id = last_record_id
                                                        AND r.owner_id = app.user_id())));

-- What the worker parsed is raw history: only the commit's outcome may be filled in later
-- (and trip_id cleared by the foreign key when the trip is deleted).
CREATE FUNCTION app.guard_tripsheetrecord_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'outcome' - 'trip_id' - 'committed_at')
     IS DISTINCT FROM
     (to_jsonb(OLD) - 'outcome' - 'trip_id' - 'committed_at') THEN
    RAISE EXCEPTION 'trip sheet records are append-only; only the outcome may change'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tripsheetrecord_outcome_only BEFORE UPDATE ON trips_tripsheetrecord
FOR EACH ROW EXECUTE FUNCTION app.guard_tripsheetrecord_update();
"""

REVERSE = """
DROP TRIGGER IF EXISTS tripsheetrecord_outcome_only ON trips_tripsheetrecord;
DROP FUNCTION IF EXISTS app.guard_tripsheetrecord_update();
DROP POLICY IF EXISTS own_all ON trips_tripsheetlink;
ALTER TABLE trips_tripsheetlink DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_all ON trips_tripsheetrecord;
ALTER TABLE trips_tripsheetrecord DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0014_trip_sheet'),
        ('trips', '0007_stop_leg_notes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='leg',
            name='sheet_key',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='stop',
            name='import_batch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DB_SET_NULL, related_name='+', to='history.importbatch'),
        ),
        migrations.AddField(
            model_name='stop',
            name='sheet_key',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='stop',
            name='time_precision',
            field=models.CharField(choices=[('exact', 'Exact'), ('day', 'Day'), ('month', 'Month'), ('year', 'Year'), ('approximate', 'Approximate')], default='exact', max_length=16),
        ),
        migrations.AlterField(
            model_name='trip',
            name='source',
            field=models.CharField(choices=[('manual', 'Manual'), ('detected', 'Detected'), ('flight_import', 'Flight import'), ('merged', 'Merged'), ('sheet_import', 'Spreadsheet import')], default='manual', max_length=16),
        ),
        migrations.CreateModel(
            name='TripSheetRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tab_name', models.CharField(max_length=255)),
                ('position', models.PositiveSmallIntegerField()),
                ('key', models.CharField(max_length=100)),
                ('content', models.JSONField(default=dict)),
                ('content_hash', models.CharField(max_length=64)),
                ('issues', models.JSONField(default=list)),
                ('blocked', models.BooleanField(default=False)),
                ('outcome', models.CharField(blank=True, choices=[('', 'Not committed'), ('created', 'New trip'), ('updated', 'Updated'), ('identical', 'Identical'), ('review', 'Sent to review (edited in the app)'), ('skipped', 'Skipped')], max_length=16)),
                ('committed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('import_batch', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='trip_sheet_records', to='history.importbatch')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('trip', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DB_SET_NULL, related_name='+', to='trips.trip')),
            ],
            options={
                'ordering': ['import_batch', 'position'],
            },
        ),
        migrations.CreateModel(
            name='TripSheetLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100)),
                ('applied_hash', models.CharField(blank=True, max_length=64)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('trip', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DB_SET_NULL, related_name='+', to='trips.trip')),
                ('last_record', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DB_SET_NULL, related_name='+', to='trips.tripsheetrecord')),
            ],
        ),
        migrations.AddConstraint(
            model_name='tripsheetrecord',
            constraint=models.UniqueConstraint(fields=('import_batch', 'position'), name='tripsheetrecord_unique_tab'),
        ),
        migrations.AddConstraint(
            model_name='tripsheetlink',
            constraint=models.UniqueConstraint(fields=('owner', 'key'), name='tripsheetlink_unique_key'),
        ),
        migrations.RunSQL(SQL, REVERSE),
    ]
