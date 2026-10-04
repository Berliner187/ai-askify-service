from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("askify_service", "0016_authuser_test_balance_survey_questions_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="model_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="apikeyusage",
            name="tokens_used",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="apikeyusage",
            name="model_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
