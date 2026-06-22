# Generated manually on 2026-06-19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0002_paymentgateway_charges_enabled_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="billing_month",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoice",
            name="billing_year",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
