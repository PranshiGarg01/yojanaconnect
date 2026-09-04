from django.db import migrations


# SECOND STORED PROCEDURE: explain_eligibility_gap(citizen_id, scheme_id)
# Returns WHY a citizen doesn't qualify, not just a flat no.
CREATE_GAP_PROCEDURE = """
CREATE OR REPLACE FUNCTION explain_eligibility_gap(p_citizen_id INTEGER, p_scheme_id INTEGER)
RETURNS TEXT[] AS $$
DECLARE
    v_income NUMERIC;
    v_age INTEGER;
    v_category VARCHAR;
    v_reasons TEXT[] := ARRAY[]::TEXT[];
    crit RECORD;
BEGIN
    SELECT income, age, category INTO v_income, v_age, v_category
    FROM core_citizenprofile WHERE user_id = p_citizen_id;

    IF NOT FOUND THEN
        RETURN ARRAY['No citizen profile found.'];
    END IF;

    FOR crit IN SELECT * FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id LOOP
        IF crit.min_income IS NOT NULL AND v_income < crit.min_income THEN
            v_reasons := array_append(v_reasons, format('Your income (Rs %s) is below the required minimum of Rs %s', v_income, crit.min_income));
        END IF;
        IF crit.max_income IS NOT NULL AND v_income > crit.max_income THEN
            v_reasons := array_append(v_reasons, format('Your income (Rs %s) exceeds the limit of Rs %s by Rs %s', v_income, crit.max_income, v_income - crit.max_income));
        END IF;
        IF crit.min_age IS NOT NULL AND v_age < crit.min_age THEN
            v_reasons := array_append(v_reasons, format('You are %s years short of the minimum age of %s', crit.min_age - v_age, crit.min_age));
        END IF;
        IF crit.max_age IS NOT NULL AND v_age > crit.max_age THEN
            v_reasons := array_append(v_reasons, format('You exceed the maximum age of %s by %s years', crit.max_age, v_age - crit.max_age));
        END IF;
        IF crit.category_required IS NOT NULL AND crit.category_required <> v_category THEN
            v_reasons := array_append(v_reasons, format('This scheme requires category "%s", your profile has "%s"', crit.category_required, v_category));
        END IF;
    END LOOP;

    RETURN v_reasons;
END;
$$ LANGUAGE plpgsql;
"""

DROP_GAP_PROCEDURE = "DROP FUNCTION IF EXISTS explain_eligibility_gap(INTEGER, INTEGER);"


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_db_procedures'),
    ]

    operations = [
        migrations.RunSQL(CREATE_GAP_PROCEDURE, reverse_sql=DROP_GAP_PROCEDURE),
    ]