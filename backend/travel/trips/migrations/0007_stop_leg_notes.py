"""Private free-text notes on each stop and leg (item 14b); never copied into a public snapshot."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0006_route_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="leg",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="stop",
            name="notes",
            field=models.TextField(blank=True),
        ),
    ]
