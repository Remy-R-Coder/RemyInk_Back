from django.db import migrations


def sync_legacy_payout_schema(apps, schema_editor):
    table_name = "pay_freelancer_payout"
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    existing_columns = {col.name for col in description}

    statements = []
    if "fee_amount" not in existing_columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN fee_amount decimal DEFAULT 0.00"
        )
    if "reference" not in existing_columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN reference varchar(255)"
        )
    if "retry_count" not in existing_columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN retry_count integer DEFAULT 0"
        )
    if "last_retry_at" not in existing_columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN last_retry_at datetime"
        )
    if "processed_at" not in existing_columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN processed_at datetime"
        )

    for sql in statements:
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ("pay_freelancer", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(sync_legacy_payout_schema, migrations.RunPython.noop),
    ]

