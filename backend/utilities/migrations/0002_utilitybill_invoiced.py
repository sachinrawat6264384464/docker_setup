# Generated manually on 2026-06-19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("utilities", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="utilitybill",
            name="invoiced",
            field=models.BooleanField(default=False),
        ),
    ]
