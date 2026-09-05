from django.db import migrations


# ANALYTICS VIEW: scheme_analytics_view — per-scheme application counts
# broken down by status, using GROUP BY + FILTER (a real aggregate query).
CREATE_ANALYTICS_VIEW = """
CREATE OR REPLACE VIEW scheme_analytics_view AS
SELECT
    s.id AS scheme_id,
    s.name AS scheme_name,
    s.category AS scheme_category,
    COUNT(a.id) AS total_applications,
    COUNT(*) FILTER (WHERE a.status = 'approved') AS approved_count,
    COUNT(*) FILTER (WHERE a.status = 'rejected') AS rejected_count,
    COUNT(*) FILTER (WHERE a.status = 'pending') AS pending_count
FROM core_scheme s
LEFT JOIN core_application a ON a.scheme_id = s.id
GROUP BY s.id, s.name, s.category
ORDER BY total_applications DESC;
"""

DROP_ANALYTICS_VIEW = "DROP VIEW IF EXISTS scheme_analytics_view;"


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_gap_procedure'),
    ]

    operations = [
        migrations.RunSQL(CREATE_ANALYTICS_VIEW, reverse_sql=DROP_ANALYTICS_VIEW),
    ]