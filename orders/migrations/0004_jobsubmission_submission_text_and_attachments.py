from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import orders.models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_remove_tasksubjectarea_jobs_unique_subject_per_category_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobsubmission',
            name='submission_text',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='jobsubmission',
            name='assignment',
            field=models.FileField(blank=True, null=True, upload_to=orders.models.assignment_upload_path),
        ),
        migrations.AlterField(
            model_name='jobsubmission',
            name='ai_report',
            field=models.FileField(blank=True, null=True, upload_to=orders.models.ai_report_upload_path),
        ),
        migrations.AlterField(
            model_name='jobsubmission',
            name='plag_report',
            field=models.FileField(blank=True, null=True, upload_to=orders.models.plag_report_upload_path),
        ),
        migrations.CreateModel(
            name='JobSubmissionAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to=orders.models.delivery_attachment_upload_path)),
                ('uploaded_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='orders.jobsubmission')),
            ],
            options={
                'ordering': ['uploaded_at'],
            },
        ),
        migrations.AddIndex(
            model_name='jobsubmissionattachment',
            index=models.Index(fields=['submission'], name='orders_jobs_submiss_a9d2cc_idx'),
        ),
    ]
