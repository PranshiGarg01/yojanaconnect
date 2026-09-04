from django.db import migrations


# TRIGGER: automatically logs every Application status change (or creation)
# into StatusLog. Runs INSIDE Postgres — fires no matter how the status is
# changed, so it can't be silently skipped by forgetting to call a function.
CREATE_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION log_application_status_change() RETURNS TRIGGER AS $$
DECLARE
    v_user_id INTEGER;
    v_reason TEXT;
BEGIN
    v_user_id := NULLIF(current_setting('app.current_user_id', true), '')::INTEGER;
    v_reason := current_setting('app.reason', true);

    IF (TG_OP = 'INSERT') THEN
        INSERT INTO core_statuslog (application_id, old_status, new_status, changed_by_id, reason, changed_at)
        VALUES (NEW.id, NULL, NEW.status, v_user_id, COALESCE(NULLIF(v_reason, ''), 'Application submitted'), NOW());
        RETURN NEW;
    ELSIF (TG_OP = 'UPDATE') THEN
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            INSERT INTO core_statuslog (application_id, old_status, new_status, changed_by_id, reason, changed_at)
            VALUES (NEW.id, OLD.status, NEW.status, v_user_id, COALESCE(v_reason, ''), NOW());
        END IF;
        RETURN NEW;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER = """
DROP TRIGGER IF EXISTS trg_log_application_status ON core_application;
CREATE TRIGGER trg_log_application_status
AFTER INSERT OR UPDATE ON core_application
FOR EACH ROW EXECUTE FUNCTION log_application_status_change();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS trg_log_application_status ON core_application;
DROP FUNCTION IF EXISTS log_application_status_change();
"""


# STORED PROCEDURE: check_eligibility(citizen_id, scheme_id) -> BOOLEAN
CREATE_PROCEDURE = """
CREATE OR REPLACE FUNCTION check_eligibility(p_citizen_id INTEGER, p_scheme_id INTEGER)
RETURNS BOOLEAN AS $$
DECLARE
    v_income NUMERIC;
    v_age INTEGER;
    v_category VARCHAR;
    v_eligible BOOLEAN := TRUE;
    crit RECORD;
BEGIN
    SELECT income, age, category INTO v_income, v_age, v_category
    FROM core_citizenprofile WHERE user_id = p_citizen_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    FOR crit IN SELECT * FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id LOOP
        IF crit.min_income IS NOT NULL AND v_income < crit.min_income THEN v_eligible := FALSE; END IF;
        IF crit.max_income IS NOT NULL AND v_income > crit.max_income THEN v_eligible := FALSE; END IF;
        IF crit.min_age IS NOT NULL AND v_age < crit.min_age THEN v_eligible := FALSE; END IF;
        IF crit.max_age IS NOT NULL AND v_age > crit.max_age THEN v_eligible := FALSE; END IF;
        IF crit.category_required IS NOT NULL AND crit.category_required <> v_category THEN v_eligible := FALSE; END IF;
    END LOOP;

    RETURN v_eligible;
END;
$$ LANGUAGE plpgsql;
"""

DROP_PROCEDURE = "DROP FUNCTION IF EXISTS check_eligibility(INTEGER, INTEGER);"


# VIEW: eligible_schemes_view — precomputes which schemes each citizen qualifies for
CREATE_VIEW = """
CREATE OR REPLACE VIEW eligible_schemes_view AS
SELECT cp.user_id AS citizen_user_id, s.id AS scheme_id, s.name AS scheme_name, s.category AS scheme_category
FROM core_citizenprofile cp
JOIN core_scheme s ON s.is_active = TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM core_eligibilitycriteria ec
    WHERE ec.scheme_id = s.id
    AND (
        (ec.min_income IS NOT NULL AND cp.income < ec.min_income) OR
        (ec.max_income IS NOT NULL AND cp.income > ec.max_income) OR
        (ec.min_age IS NOT NULL AND cp.age < ec.min_age) OR
        (ec.max_age IS NOT NULL AND cp.age > ec.max_age) OR
        (ec.category_required IS NOT NULL AND ec.category_required <> cp.category)
    )
);
"""

DROP_VIEW = "DROP VIEW IF EXISTS eligible_schemes_view;"


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(CREATE_TRIGGER_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
        migrations.RunSQL(CREATE_PROCEDURE, reverse_sql=DROP_PROCEDURE),
        migrations.RunSQL(CREATE_VIEW, reverse_sql=DROP_VIEW),
    ]