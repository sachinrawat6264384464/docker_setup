# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0002_addonrequest_tenantaddongrant"),
    ]

    operations = [
        migrations.AddField(
            model_name="addonrequest",
            name="quantity",
            field=models.IntegerField(default=1),
        ),
    ]
