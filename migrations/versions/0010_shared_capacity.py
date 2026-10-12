"""Shared expiring resource leases and persisted source/host cadence."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

GUARD = """
IF p_workspace::text IS DISTINCT FROM current_setting('app.workspace_id', true)
   OR workspace_role(p_workspace, current_setting('app.actor_id', true)) IS NULL THEN
  RAISE EXCEPTION 'Workspace membership required' USING ERRCODE='42501';
END IF;
PERFORM pg_advisory_xact_lock(74392301);
"""


def upgrade():
    op.execute("""
CREATE TABLE capacity_leases (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL,
 job_id uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('http','browser','model')),
 source text NOT NULL, host text NOT NULL, expires_at timestamptz NOT NULL,
 FOREIGN KEY(workspace_id,job_id) REFERENCES jobs(workspace_id,id)
);
CREATE INDEX capacity_active ON capacity_leases(expires_at);
CREATE TABLE capacity_cadence (
 scope text NOT NULL, name text NOT NULL, delay double precision NOT NULL DEFAULT 0,
 next_at timestamptz NOT NULL DEFAULT '-infinity', PRIMARY KEY(scope,name)
);
ALTER TABLE capacity_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE capacity_cadence ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON capacity_leases, capacity_cadence FROM PUBLIC, skriller_app;
""")
    op.execute(
        """
CREATE FUNCTION capacity_acquire(p_workspace uuid, p_job uuid, p_kind text,
 p_source text, p_host text, p_ttl integer, p_floor double precision)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE result uuid; cap integer;
BEGIN
"""
        + GUARD
        + """
IF p_kind NOT IN ('http','browser','model') OR p_ttl NOT BETWEEN 1 AND 120
 OR p_floor NOT BETWEEN 0 AND 86400 OR p_source !~ '^[a-z0-9_.-]{1,100}$'
 OR p_host !~ '^[a-z0-9_.:-]{1,253}$' THEN RAISE EXCEPTION 'Invalid capacity request'; END IF;
IF NOT EXISTS(SELECT 1 FROM jobs WHERE workspace_id=p_workspace AND id=p_job
 AND state IN ('queued','running')) THEN RAISE EXCEPTION 'Active scoped job required'; END IF;
DELETE FROM capacity_leases WHERE expires_at<=clock_timestamp();
cap := CASE p_kind WHEN 'http' THEN 8 WHEN 'browser' THEN 2 ELSE 1 END;
IF (SELECT count(*) FROM capacity_leases WHERE kind=p_kind)>=cap
 OR EXISTS(SELECT 1 FROM capacity_leases WHERE source=p_source OR host=p_host)
 OR (NOT EXISTS(SELECT 1 FROM capacity_leases WHERE workspace_id=p_workspace AND job_id=p_job)
 AND (SELECT count(DISTINCT job_id) FROM capacity_leases WHERE workspace_id=p_workspace)>=2)
 OR EXISTS(SELECT 1 FROM capacity_cadence WHERE ((scope='source' AND name=p_source)
 OR (scope='host' AND name=p_host)) AND next_at>clock_timestamp()) THEN RETURN NULL; END IF;
INSERT INTO capacity_leases(workspace_id,job_id,kind,source,host,expires_at)
 VALUES(p_workspace,p_job,p_kind,p_source,p_host,clock_timestamp()+make_interval(secs=>p_ttl))
 RETURNING id INTO result;
INSERT INTO capacity_cadence(scope,name,next_at) VALUES
 ('source',p_source,clock_timestamp()+make_interval(secs=>p_floor)),
 ('host',p_host,clock_timestamp()+make_interval(secs=>p_floor))
 ON CONFLICT(scope,name) DO UPDATE SET next_at=greatest(capacity_cadence.next_at,excluded.next_at);
RETURN result;
END $$;
REVOKE ALL ON FUNCTION capacity_acquire(uuid,uuid,text,text,text,integer,double precision) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION capacity_acquire(uuid,uuid,text,text,text,integer,double precision) TO skriller_app;
"""
    )
    op.execute(
        """
CREATE FUNCTION capacity_observe(p_workspace uuid, p_lease uuid)
RETURNS TABLE(source text, host text, delay double precision)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
"""
        + GUARD
        + """
RETURN QUERY SELECT l.source,l.host,coalesce(max(c.delay),0)
 FROM capacity_leases l LEFT JOIN capacity_cadence c ON
 (c.scope='source' AND c.name=l.source) OR (c.scope='host' AND c.name=l.host)
 WHERE l.workspace_id=p_workspace AND l.id=p_lease AND l.expires_at>clock_timestamp()
 GROUP BY l.source,l.host;
END $$;
REVOKE ALL ON FUNCTION capacity_observe(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION capacity_observe(uuid,uuid) TO skriller_app;
"""
    )
    op.execute(
        """
CREATE FUNCTION capacity_finish(p_workspace uuid, p_lease uuid, p_delay double precision)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE l capacity_leases%ROWTYPE;
BEGIN
"""
        + GUARD
        + """
IF p_delay NOT BETWEEN 0 AND 86400 THEN RAISE EXCEPTION 'Invalid cadence'; END IF;
DELETE FROM capacity_leases WHERE workspace_id=p_workspace AND id=p_lease
 AND expires_at>clock_timestamp() RETURNING * INTO l;
IF NOT FOUND THEN RETURN false; END IF;
IF p_delay>0 THEN
INSERT INTO capacity_cadence(scope,name,delay,next_at) VALUES
 ('source',l.source,p_delay,clock_timestamp()+make_interval(secs=>p_delay)),
 ('host',l.host,p_delay,clock_timestamp()+make_interval(secs=>p_delay))
 ON CONFLICT(scope,name) DO UPDATE SET delay=excluded.delay,
 next_at=greatest(capacity_cadence.next_at,excluded.next_at);
END IF;
RETURN true;
END $$;
REVOKE ALL ON FUNCTION capacity_finish(uuid,uuid,double precision) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION capacity_finish(uuid,uuid,double precision) TO skriller_app;
"""
    )


def downgrade():
    op.execute("DROP FUNCTION capacity_finish(uuid,uuid,double precision)")
    op.execute("DROP FUNCTION capacity_observe(uuid,uuid)")
    op.execute("DROP FUNCTION capacity_acquire(uuid,uuid,text,text,text,integer,double precision)")
    op.drop_table("capacity_cadence")
    op.drop_table("capacity_leases")
