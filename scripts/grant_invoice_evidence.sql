-- Run as migration owner: psql -v app_role=<existing-runtime-role> -f this-file
\set ON_ERROR_STOP on
BEGIN;
GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT SELECT, INSERT ON TABLE public.invoices, public.invoice_lines TO :"app_role";
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON TABLE public.invoices, public.invoice_lines FROM :"app_role";
COMMIT;
