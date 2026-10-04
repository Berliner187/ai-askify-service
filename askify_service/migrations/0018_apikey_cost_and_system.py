from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("askify_service", "0017_apikey_model_apikeyusage_tokens"),
    ]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="cost_per_1m_tokens",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="apikey",
            name="is_system",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="apikey",
            name="key",
            field=models.TextField(blank=True, default=""),
        ),
    ]
