# Generated manually on 2026-06-19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0002_alter_maintenancerequest_assigned_to_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="maintenancerequest",
            name="request_type",
            field=models.CharField(
                choices=[("common", "Common Area"), ("personal", "Personal Unit")],
                default="personal",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="maintenancerequest",
            name="is_chargeable",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="maintenancerequest",
            name="invoiced",
            field=models.BooleanField(default=False),
        ),
    ]
