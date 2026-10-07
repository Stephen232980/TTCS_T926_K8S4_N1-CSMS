-- Run as the migration owner with psql -v app_role=<existing-runtime-role>.
-- The role must already exist. Quoted psql identifiers prevent SQL injection.
\set ON_ERROR_STOP on
BEGIN;
GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT SELECT, INSERT ON TABLE public.wallet_ledger TO :"app_role";
GRANT USAGE ON SEQUENCE public.wallet_ledger_id_seq TO :"app_role";
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON TABLE public.wallet_ledger FROM :"app_role";
COMMIT;
