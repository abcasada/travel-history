from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0005_route_attribution"),
    ]

    operations = [
        migrations.AddField(
            model_name="route",
            name="sources",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
