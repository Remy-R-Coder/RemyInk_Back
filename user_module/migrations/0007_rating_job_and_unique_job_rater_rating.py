from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_jobsubmission_submission_text_and_attachments'),
        ('user_module', '0006_alter_freelancerprofile_subjects'),
    ]

    operations = [
        migrations.AddField(
            model_name='rating',
            name='job',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ratings', to='orders.job'),
        ),
        migrations.AddConstraint(
            model_name='rating',
            constraint=models.UniqueConstraint(condition=models.Q(('job__isnull', False)), fields=('job', 'rater'), name='unique_job_rater_rating'),
        ),
    ]
