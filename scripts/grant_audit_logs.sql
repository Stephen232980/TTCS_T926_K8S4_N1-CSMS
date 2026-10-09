-- Run as migration owner with -v app_role=<existing-runtime-role>.
-- Runtime role must not own the table or inherit migration-owner privileges.
\set ON_ERROR_STOP on
BEGIN;
GRANT USAGE ON SCHEMA public TO :"app_role";
REVOKE ALL ON TABLE public.audit_logs FROM :"app_role";
GRANT SELECT, INSERT ON TABLE public.audit_logs TO :"app_role";
COMMIT;
