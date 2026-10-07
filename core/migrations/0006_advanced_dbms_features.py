from django.db import migrations

CHECK_ELIGIBILITY_OR_LOGIC = """
CREATE OR REPLACE FUNCTION check_eligibility(p_citizen_id BIGINT, p_scheme_id BIGINT)
RETURNS BOOLEAN AS $$
DECLARE
    v_income NUMERIC;
    v_age INTEGER;
    v_category VARCHAR;
    v_gender VARCHAR;
    v_group_count INTEGER;
    v_passed_group BOOLEAN;
    grp_rec RECORD;
    crit RECORD;
BEGIN
    SELECT income, age, category, COALESCE(gender, 'other')
    INTO v_income, v_age, v_category, v_gender
    FROM core_citizenprofile WHERE user_id = p_citizen_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- If no criteria defined for the scheme, anyone qualifies
    SELECT COUNT(*) INTO v_group_count
    FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id;
    IF v_group_count = 0 THEN
        RETURN TRUE;
    END IF;

    -- Evaluate each distinct criteria_group (OR logic across groups)
    FOR grp_rec IN SELECT DISTINCT criteria_group FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id ORDER BY criteria_group LOOP
        v_passed_group := TRUE;
        -- Evaluate all conditions within this group (AND logic within group)
        FOR crit IN SELECT * FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id AND criteria_group = grp_rec.criteria_group LOOP
            IF crit.min_income IS NOT NULL AND v_income < crit.min_income THEN v_passed_group := FALSE; END IF;
            IF crit.max_income IS NOT NULL AND v_income > crit.max_income THEN v_passed_group := FALSE; END IF;
            IF crit.min_age IS NOT NULL AND v_age < crit.min_age THEN v_passed_group := FALSE; END IF;
            IF crit.max_age IS NOT NULL AND v_age > crit.max_age THEN v_passed_group := FALSE; END IF;
            IF crit.category_required IS NOT NULL AND crit.category_required <> v_category THEN v_passed_group := FALSE; END IF;
            IF crit.gender_required IS NOT NULL AND crit.gender_required <> v_gender THEN v_passed_group := FALSE; END IF;
        END LOOP;

        IF v_passed_group THEN
            RETURN TRUE; -- satisfied at least one criteria group
        END IF;
    END LOOP;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION check_eligibility(p_citizen_id INTEGER, p_scheme_id INTEGER)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN check_eligibility(p_citizen_id::BIGINT, p_scheme_id::BIGINT);
END;
$$ LANGUAGE plpgsql;
"""

EXPLAIN_GAP_OR_LOGIC = """
CREATE OR REPLACE FUNCTION explain_eligibility_gap(p_citizen_id BIGINT, p_scheme_id BIGINT)
RETURNS TEXT[] AS $$
DECLARE
    v_income NUMERIC;
    v_age INTEGER;
    v_category VARCHAR;
    v_gender VARCHAR;
    v_reasons TEXT[] := ARRAY[]::TEXT[];
    grp_reasons TEXT[];
    v_group_count INTEGER;
    v_distinct_groups INTEGER;
    grp_rec RECORD;
    crit RECORD;
BEGIN
    SELECT income, age, category, COALESCE(gender, 'other')
    INTO v_income, v_age, v_category, v_gender
    FROM core_citizenprofile WHERE user_id = p_citizen_id;

    IF NOT FOUND THEN
        RETURN ARRAY['No citizen profile found.'];
    END IF;

    SELECT COUNT(*), COUNT(DISTINCT criteria_group)
    INTO v_group_count, v_distinct_groups
    FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id;

    IF v_group_count = 0 THEN
        RETURN ARRAY[]::TEXT[];
    END IF;

    -- If eligible via check_eligibility, no gap
    IF check_eligibility(p_citizen_id, p_scheme_id) THEN
        RETURN ARRAY[]::TEXT[];
    END IF;

    FOR grp_rec IN SELECT DISTINCT criteria_group FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id ORDER BY criteria_group LOOP
        grp_reasons := ARRAY[]::TEXT[];
        FOR crit IN SELECT * FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id AND criteria_group = grp_rec.criteria_group LOOP
            IF crit.min_income IS NOT NULL AND v_income < crit.min_income THEN
                grp_reasons := array_append(grp_reasons, format('Your income (Rs %s) is below the required minimum of Rs %s', v_income, crit.min_income));
            END IF;
            IF crit.max_income IS NOT NULL AND v_income > crit.max_income THEN
                grp_reasons := array_append(grp_reasons, format('Your income (Rs %s) exceeds the limit of Rs %s by Rs %s', v_income, crit.max_income, v_income - crit.max_income));
            END IF;
            IF crit.min_age IS NOT NULL AND v_age < crit.min_age THEN
                grp_reasons := array_append(grp_reasons, format('You are %s years short of the minimum age of %s', crit.min_age - v_age, crit.min_age));
            END IF;
            IF crit.max_age IS NOT NULL AND v_age > crit.max_age THEN
                grp_reasons := array_append(grp_reasons, format('You exceed the maximum age of %s by %s years', crit.max_age, v_age - crit.max_age));
            END IF;
            IF crit.category_required IS NOT NULL AND crit.category_required <> v_category THEN
                grp_reasons := array_append(grp_reasons, format('This scheme requires category "%s", your profile has "%s"', crit.category_required, v_category));
            END IF;
            IF crit.gender_required IS NOT NULL AND crit.gender_required <> v_gender THEN
                grp_reasons := array_append(grp_reasons, format('This scheme requires gender "%s", your profile has "%s"', crit.gender_required, v_gender));
            END IF;
        END LOOP;

        IF v_distinct_groups > 1 THEN
            v_reasons := array_append(v_reasons, format('[Criteria Option %s]: %s', grp_rec.criteria_group, array_to_string(grp_reasons, '; ')));
        ELSE
            v_reasons := array_cat(v_reasons, grp_reasons);
        END IF;
    END LOOP;

    RETURN v_reasons;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION explain_eligibility_gap(p_citizen_id INTEGER, p_scheme_id INTEGER)
RETURNS TEXT[] AS $$
BEGIN
    RETURN explain_eligibility_gap(p_citizen_id::BIGINT, p_scheme_id::BIGINT);
END;
$$ LANGUAGE plpgsql;
"""

UPDATE_ELIGIBLE_VIEW = """
CREATE OR REPLACE VIEW eligible_schemes_view AS
SELECT cp.user_id AS citizen_user_id, s.id AS scheme_id, s.name AS scheme_name, s.category AS scheme_category
FROM core_citizenprofile cp
CROSS JOIN core_scheme s
WHERE s.is_active = TRUE
  AND (s.valid_until IS NULL OR s.valid_until >= CURRENT_DATE)
  AND check_eligibility(cp.user_id::BIGINT, s.id::BIGINT) = TRUE;
"""

CALCULATE_SCHEME_MATCH_SCORE = """
CREATE OR REPLACE FUNCTION calculate_scheme_match_score(p_citizen_id BIGINT, p_scheme_id BIGINT)
RETURNS TABLE(match_score INTEGER, limiting_factor TEXT) AS $$
DECLARE
    v_income NUMERIC;
    v_age INTEGER;
    v_category VARCHAR;
    v_gender VARCHAR;
    v_best_score INTEGER := 0;
    v_best_factor TEXT := 'Ineligible';
    grp_rec RECORD;
    crit RECORD;
    v_has_criteria BOOLEAN := FALSE;
    v_grp_score NUMERIC;
    v_crit_score NUMERIC;
    v_grp_factor TEXT;
    v_factor_score NUMERIC;
BEGIN
    SELECT income, age, category, COALESCE(gender, 'other')
    INTO v_income, v_age, v_category, v_gender
    FROM core_citizenprofile WHERE user_id = p_citizen_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT 0, 'No citizen profile'::TEXT;
        RETURN;
    END IF;

    FOR grp_rec IN SELECT DISTINCT criteria_group FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id LOOP
        v_has_criteria := TRUE;
        v_grp_score := 100;
        v_grp_factor := 'Fully Eligible';
        v_factor_score := 100;

        FOR crit IN SELECT * FROM core_eligibilitycriteria WHERE scheme_id = p_scheme_id AND criteria_group = grp_rec.criteria_group LOOP
            -- Income check
            IF crit.max_income IS NOT NULL THEN
                IF v_income <= crit.max_income THEN
                    v_crit_score := 100;
                ELSE
                    -- Partial credit within 50% excess band
                    IF (v_income - crit.max_income) <= (0.5 * crit.max_income) THEN
                        v_crit_score := GREATEST(0, ROUND(100 - ((v_income - crit.max_income) / (0.5 * crit.max_income)) * 100));
                    ELSE
                        v_crit_score := 0;
                    END IF;
                END IF;
                IF v_crit_score < v_factor_score THEN
                    v_factor_score := v_crit_score;
                    IF v_crit_score = 100 THEN
                        v_grp_factor := 'Fully Eligible';
                    ELSE
                        v_grp_factor := format('Income (exceeds limit by Rs %s)', v_income - crit.max_income);
                    END IF;
                END IF;
                v_grp_score := LEAST(v_grp_score, v_crit_score);
            END IF;

            -- Min income check
            IF crit.min_income IS NOT NULL THEN
                IF v_income >= crit.min_income THEN
                    v_crit_score := 100;
                ELSE
                    v_crit_score := GREATEST(0, ROUND((v_income / crit.min_income) * 100));
                END IF;
                IF v_crit_score < v_factor_score THEN
                    v_factor_score := v_crit_score;
                    v_grp_factor := format('Income (below min of Rs %s)', crit.min_income);
                END IF;
                v_grp_score := LEAST(v_grp_score, v_crit_score);
            END IF;

            -- Age checks
            IF crit.min_age IS NOT NULL THEN
                IF v_age >= crit.min_age THEN
                    v_crit_score := 100;
                ELSIF (crit.min_age - v_age) <= 5 THEN
                    v_crit_score := GREATEST(0, 100 - (crit.min_age - v_age) * 20);
                ELSE
                    v_crit_score := 0;
                END IF;
                IF v_crit_score < v_factor_score THEN
                    v_factor_score := v_crit_score;
                    v_grp_factor := format('Age (%s yrs short of min %s)', crit.min_age - v_age, crit.min_age);
                END IF;
                v_grp_score := LEAST(v_grp_score, v_crit_score);
            END IF;

            IF crit.max_age IS NOT NULL THEN
                IF v_age <= crit.max_age THEN
                    v_crit_score := 100;
                ELSIF (v_age - crit.max_age) <= 5 THEN
                    v_crit_score := GREATEST(0, 100 - (v_age - crit.max_age) * 20);
                ELSE
                    v_crit_score := 0;
                END IF;
                IF v_crit_score < v_factor_score THEN
                    v_factor_score := v_crit_score;
                    v_grp_factor := format('Age (exceeds max %s by %s yrs)', crit.max_age, v_age - crit.max_age);
                END IF;
                v_grp_score := LEAST(v_grp_score, v_crit_score);
            END IF;

            -- Category check
            IF crit.category_required IS NOT NULL THEN
                IF crit.category_required = v_category THEN
                    v_crit_score := 100;
                ELSE
                    v_crit_score := 0;
                END IF;
                IF v_crit_score < v_factor_score THEN
                    v_factor_score := v_crit_score;
                    v_grp_factor := format('Category (requires %s, profile has %s)', crit.category_required, v_category);
                END IF;
                v_grp_score := LEAST(v_grp_score, v_crit_score);
            END IF;

            -- Gender check
            IF crit.gender_required IS NOT NULL THEN
                IF crit.gender_required = v_gender THEN
                    v_crit_score := 100;
                ELSE
                    v_crit_score := 0;
                END IF;
                IF v_crit_score < v_factor_score THEN
                    v_factor_score := v_crit_score;
                    v_grp_factor := format('Gender (requires %s, profile has %s)', crit.gender_required, v_gender);
                END IF;
                v_grp_score := LEAST(v_grp_score, v_crit_score);
            END IF;
        END LOOP;

        IF v_grp_score > v_best_score THEN
            v_best_score := v_grp_score;
            v_best_factor := v_grp_factor;
        END IF;
    END LOOP;

    IF NOT v_has_criteria THEN
        v_best_score := 100;
        v_best_factor := 'Fully Eligible';
    END IF;

    IF v_best_score = 100 THEN
        v_best_factor := 'Fully Eligible';
    END IF;

    RETURN QUERY SELECT v_best_score::INTEGER, v_best_factor::TEXT;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION calculate_scheme_match_score(p_citizen_id INTEGER, p_scheme_id INTEGER)
RETURNS TABLE(match_score INTEGER, limiting_factor TEXT) AS $$
BEGIN
    RETURN QUERY SELECT * FROM calculate_scheme_match_score(p_citizen_id::BIGINT, p_scheme_id::BIGINT);
END;
$$ LANGUAGE plpgsql;
"""

CREATE_FTS_INDEX = """
CREATE INDEX IF NOT EXISTS core_scheme_fts_idx
ON core_scheme
USING GIN (to_tsvector('english', name || ' ' || description));
"""

CREATE_MATERIALIZED_VIEW = """
CREATE MATERIALIZED VIEW IF NOT EXISTS scheme_analytics_mview AS
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

CREATE UNIQUE INDEX IF NOT EXISTS scheme_analytics_mview_id_idx
ON scheme_analytics_mview (scheme_id);
"""

CREATE_RLS_POLICIES = """
ALTER TABLE core_application ENABLE ROW LEVEL SECURITY;
ALTER TABLE core_document ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rls_citizen_application ON core_application;
CREATE POLICY rls_citizen_application ON core_application
    FOR ALL
    USING (
        current_setting('app.is_officer', true) = 'true'
        OR citizen_id = NULLIF(current_setting('app.current_user_id', true), '')::INTEGER
        OR current_setting('app.current_user_id', true) IS NULL
    );

DROP POLICY IF EXISTS rls_citizen_document ON core_document;
CREATE POLICY rls_citizen_document ON core_document
    FOR ALL
    USING (
        current_setting('app.is_officer', true) = 'true'
        OR EXISTS (
            SELECT 1 FROM core_application a
            WHERE a.id = core_document.application_id
            AND a.citizen_id = NULLIF(current_setting('app.current_user_id', true), '')::INTEGER
        )
        OR current_setting('app.current_user_id', true) IS NULL
    );
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_scheme_expansion_dispute'),
    ]

    operations = [
        migrations.RunSQL(CHECK_ELIGIBILITY_OR_LOGIC, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(EXPLAIN_GAP_OR_LOGIC, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(UPDATE_ELIGIBLE_VIEW, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CALCULATE_SCHEME_MATCH_SCORE, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CREATE_FTS_INDEX, reverse_sql="DROP INDEX IF EXISTS core_scheme_fts_idx;"),
        migrations.RunSQL(CREATE_MATERIALIZED_VIEW, reverse_sql="DROP MATERIALIZED VIEW IF EXISTS scheme_analytics_mview;"),
        migrations.RunSQL(CREATE_RLS_POLICIES, reverse_sql=migrations.RunSQL.noop),
    ]
