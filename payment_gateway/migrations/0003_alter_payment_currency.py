from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payment_gateway', '0002_alter_payment_amount_alter_payment_authorization_url_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='currency',
            field=models.CharField(default='USD', max_length=3),
        ),
    ]
