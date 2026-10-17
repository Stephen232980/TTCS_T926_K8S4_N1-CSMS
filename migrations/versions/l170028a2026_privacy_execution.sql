CREATE TABLE privacy_policies (
 version varchar(100) PRIMARY KEY, document jsonb NOT NULL,
 approval_basis text NOT NULL, approved_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE privacy_jobs (
 id uuid PRIMARY KEY, request_id uuid NOT NULL UNIQUE REFERENCES privacy_requests(id) ON DELETE RESTRICT,
 status varchar(20) NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','processing','needs_review','completed')),
 checkpoint integer NOT NULL DEFAULT 0 CHECK(checkpoint BETWEEN 0 AND 3),
 last_error varchar(80), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE SCHEMA privacy_private;
REVOKE ALL ON SCHEMA privacy_private FROM PUBLIC;
CREATE TABLE privacy_private.subjects (
 job_id uuid PRIMARY KEY REFERENCES public.privacy_jobs(id),
 original_user_id uuid NOT NULL, subject_id uuid NOT NULL UNIQUE,
 original_email text NOT NULL
);
REVOKE ALL ON ALL TABLES IN SCHEMA privacy_private FROM PUBLIC;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='csms_privacy_executor') THEN
   CREATE ROLE csms_privacy_executor NOLOGIN;
 END IF;
END $$;
GRANT USAGE ON SCHEMA privacy_private TO csms_privacy_executor;
INSERT INTO privacy_policies(version,document,approval_basis) VALUES ('CSMS-PRIVACY-2026-01','{"version": "CSMS-PRIVACY-2026-01", "approval_basis": "project_owner_delegated_policy_selection", "mode": "unlink_original_account_preserve_financials", "identity": "redact_after_approved_request_and_financial_gates", "financial_minimum_years": 10, "financial_expiry": "manual_review_no_automatic_delete", "operational_history": "preserve_measurements_remove_original_identity_links", "pending_ocpp": "never_delete_by_age", "legal_hold": "blocks_privacy_execution", "sources": ["https://vanban.chinhphu.vn/default.aspx?docid=183198&pageid=27160", "https://vanban.bocongan.gov.vn/co-so-du-lieu-van-ban/luat-bao-ve-du-lieu-ca-nhan-1753688803"]}'::jsonb,'project_owner_delegated_policy_selection');

-- No app-controlled GUC can authorize a trigger bypass: current_user must be
-- the migration/function owner AND the active private job must match.
CREATE FUNCTION privacy_private.redaction_context() RETURNS boolean
LANGUAGE sql VOLATILE SET search_path = pg_catalog, public AS $$
 SELECT current_user = pg_get_userbyid((SELECT proowner FROM pg_proc
    WHERE proname='execute_stage' AND pronamespace=(SELECT oid FROM pg_namespace WHERE nspname='privacy_private')))
 AND EXISTS (SELECT 1 FROM public.privacy_jobs j JOIN privacy_private.subjects s ON s.job_id=j.id
    WHERE j.id::text=current_setting('csms.privacy_job',true) AND j.status='processing');
$$;
REVOKE ALL ON FUNCTION privacy_private.redaction_context() FROM PUBLIC;

CREATE FUNCTION privacy_private.check_gates(p_job uuid) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE uid uuid; req public.privacy_requests; held boolean;
BEGIN
 SELECT r.* INTO req FROM public.privacy_requests r JOIN public.privacy_jobs j ON j.request_id=r.id WHERE j.id=p_job;
 IF req.id IS NULL OR req.status<>'approved' OR NOT EXISTS(SELECT 1 FROM public.privacy_policies WHERE version=req.policy_version) THEN
  RAISE EXCEPTION 'policy_or_approval_required';
 END IF;
 uid:=req.user_id;
 PERFORM 1 FROM public.users WHERE id=uid FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.users WHERE id=uid AND status IN ('active','pending_deletion')) THEN RAISE EXCEPTION 'subject_not_active'; END IF;
 IF EXISTS(SELECT 1 FROM public.user_roles ur JOIN public.roles r ON r.id=ur.role_id WHERE ur.user_id=uid AND r.code<>'driver')
 OR EXISTS(SELECT 1 FROM public.stations WHERE owner_id=uid) THEN RAISE EXCEPTION 'non_driver_obligations'; END IF;
 -- These locks serialize with wallet writers; the FK write fence below blocks
 -- new session/booking/topup creation racing the user freeze.
 PERFORM 1 FROM public.wallets WHERE driver_id=uid FOR UPDATE;
 IF EXISTS(SELECT 1 FROM public.wallets WHERE driver_id=uid AND balance_vnd<>0) THEN RAISE EXCEPTION 'wallet_refund_or_debt_required'; END IF;
 IF EXISTS(SELECT 1 FROM public.charging_sessions WHERE driver_id=uid AND
   (ended_at IS NULL OR settlement_completed_at IS NULL OR connector_released_at IS NULL)) THEN RAISE EXCEPTION 'charging_or_cable_open'; END IF;
 IF EXISTS(SELECT 1 FROM public.driver_start_requests WHERE driver_id=uid AND status IN ('Pending','Accepted')) THEN RAISE EXCEPTION 'remote_start_open'; END IF;
 IF EXISTS(SELECT 1 FROM public.reservations WHERE driver_id=uid AND
   (status IN ('pending','uncertain','active','cancel_pending','expiry_release_pending') OR fee_decision IN ('pending','review'))) THEN RAISE EXCEPTION 'reservation_or_fee_open'; END IF;
 IF EXISTS(SELECT 1 FROM public.wallet_topups WHERE driver_id=uid AND status IN ('pending','needs_review')) THEN RAISE EXCEPTION 'topup_open'; END IF;
 SELECT COALESCE((data->>'hold')::boolean,false) INTO held FROM public.audit_logs
  WHERE object_type='user' AND object_id=uid::text AND action='privacy.legal_hold' ORDER BY occurred_at DESC,id DESC LIMIT 1;
 IF COALESCE(held,false) THEN RAISE EXCEPTION 'legal_hold'; END IF;
 IF EXISTS(SELECT 1 FROM public.wallet_topups t JOIN public.users u ON u.id=t.driver_id WHERE t.driver_id=uid AND
    (position(uid::text in t.order_id)>0 OR position(lower(u.email) in lower(COALESCE(t.gateway_transaction_id,'')))>0)) THEN RAISE EXCEPTION 'financial_reference_requires_review'; END IF;
END $$;
REVOKE ALL ON FUNCTION privacy_private.check_gates(uuid) FROM PUBLIC;

CREATE FUNCTION privacy_private.redact_text(value text, needle text) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE found integer;
BEGIN
 IF value IS NULL OR needle IS NULL OR needle='' THEN RETURN value; END IF;
 found:=position(lower(needle) in lower(value));
 WHILE found>0 LOOP
  value:=overlay(value placing '[redacted]' from found for length(needle));
  found:=position(lower(needle) in lower(value));
 END LOOP;
 RETURN value;
END $$;
REVOKE ALL ON FUNCTION privacy_private.redact_text(text,text) FROM PUBLIC;

CREATE FUNCTION privacy_private.scrub(value jsonb, uid text, mail text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE output jsonb; k text; v jsonb; str text;
BEGIN
 CASE jsonb_typeof(value)
 WHEN 'object' THEN
  output:='{}'; FOR k,v IN SELECT * FROM jsonb_each(value) LOOP
    output:=output || jsonb_build_object(privacy_private.redact_text(privacy_private.redact_text(k,uid),mail),privacy_private.scrub(v,uid,mail)); END LOOP;
 WHEN 'array' THEN
  output:='[]'; FOR v IN SELECT * FROM jsonb_array_elements(value) LOOP output:=output || jsonb_build_array(privacy_private.scrub(v,uid,mail)); END LOOP;
 WHEN 'string' THEN
  str:=value#>>'{}';
  output:=to_jsonb(privacy_private.redact_text(privacy_private.redact_text(str,uid),mail));
 ELSE output:=value;
 END CASE;
 RETURN output;
END $$;
REVOKE ALL ON FUNCTION privacy_private.scrub(jsonb,text,text) FROM PUBLIC;

-- Replace statement-only UPDATE guards with per-row, column-allowlisted guards.
-- DELETE/TRUNCATE remain unconditionally forbidden, including for the executor.
-- Reject ordinary UPDATE statements even when they match no rows. The row
-- guard below still validates every changed column during privileged redaction.
CREATE FUNCTION privacy_private.guard_redaction_statement() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF current_user=pg_get_userbyid((SELECT proowner FROM pg_proc WHERE proname='execute_stage' AND pronamespace=(SELECT oid FROM pg_namespace WHERE nspname='privacy_private'))) THEN
  IF privacy_private.redaction_context() THEN RETURN NULL; END IF;
 END IF;
 CASE TG_TABLE_NAME
 WHEN 'invoices' THEN RAISE EXCEPTION 'invoice evidence is append-only';
 WHEN 'wallet_ledger','wallet_audits' THEN RAISE EXCEPTION 'wallet ledger is append-only';
 WHEN 'audit_logs' THEN RAISE EXCEPTION 'audit log is append-only';
 ELSE RAISE EXCEPTION 'control audit is append-only';
 END CASE;
END $$;
REVOKE ALL ON FUNCTION privacy_private.guard_redaction_statement() FROM PUBLIC;
CREATE TRIGGER privacy_update_guard BEFORE UPDATE ON invoices FOR EACH STATEMENT EXECUTE FUNCTION privacy_private.guard_redaction_statement();
CREATE TRIGGER privacy_update_guard BEFORE UPDATE ON wallet_ledger FOR EACH STATEMENT EXECUTE FUNCTION privacy_private.guard_redaction_statement();
CREATE TRIGGER privacy_update_guard BEFORE UPDATE ON wallet_audits FOR EACH STATEMENT EXECUTE FUNCTION privacy_private.guard_redaction_statement();
CREATE TRIGGER privacy_update_guard BEFORE UPDATE ON audit_logs FOR EACH STATEMENT EXECUTE FUNCTION privacy_private.guard_redaction_statement();
CREATE TRIGGER privacy_update_guard BEFORE UPDATE ON ocpp_control_requests FOR EACH STATEMENT EXECUTE FUNCTION privacy_private.guard_redaction_statement();

CREATE FUNCTION privacy_private.guard_redaction() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE allowed text[]; uid uuid; sid uuid; email text;
BEGIN
 IF TG_OP<>'UPDATE' OR current_user<>pg_get_userbyid((SELECT proowner FROM pg_proc WHERE proname='execute_stage' AND pronamespace=(SELECT oid FROM pg_namespace WHERE nspname='privacy_private'))) THEN RAISE EXCEPTION 'evidence is append-only'; END IF;
 IF NOT privacy_private.redaction_context() THEN RAISE EXCEPTION 'evidence is append-only'; END IF;
 SELECT original_user_id,subject_id,original_email INTO uid,sid,email FROM privacy_private.subjects
 WHERE job_id::text=current_setting('csms.privacy_job',true);
 CASE TG_TABLE_NAME
 WHEN 'invoices' THEN
  allowed:=ARRAY['driver_id'];
  IF OLD.driver_id<>uid OR NEW.driver_id<>sid THEN RAISE EXCEPTION 'invalid invoice redaction'; END IF;
 WHEN 'wallet_ledger' THEN
  allowed:=ARRAY['actor_id'];
  IF OLD.actor_id IS DISTINCT FROM uid OR NEW.actor_id IS DISTINCT FROM sid THEN RAISE EXCEPTION 'invalid ledger redaction'; END IF;
 WHEN 'wallet_audits' THEN
  allowed:=ARRAY['actor_id','reason'];
 WHEN 'audit_logs' THEN
  allowed:=ARRAY['actor_id','object_id','data'];
 WHEN 'ocpp_control_requests' THEN
  allowed:=ARRAY['actor_id','actor_email','payload'];
 ELSE RAISE EXCEPTION 'table not allowlisted';
 END CASE;
 IF (to_jsonb(OLD)-allowed) IS DISTINCT FROM (to_jsonb(NEW)-allowed) THEN RAISE EXCEPTION 'financial invariant mutation forbidden'; END IF;
 IF TG_TABLE_NAME IN ('wallet_audits','audit_logs','ocpp_control_requests') THEN
  IF (to_jsonb(NEW)->>'actor_id') IS DISTINCT FROM (CASE WHEN to_jsonb(OLD)->>'actor_id'=uid::text THEN sid::text ELSE to_jsonb(OLD)->>'actor_id' END) THEN RAISE EXCEPTION 'invalid actor redaction'; END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION privacy_private.guard_redaction() FROM PUBLIC;
DROP TRIGGER immutable_invoices ON invoices;
CREATE TRIGGER immutable_invoices BEFORE UPDATE ON invoices FOR EACH ROW EXECUTE FUNCTION privacy_private.guard_redaction();
CREATE TRIGGER immutable_invoices_delete BEFORE DELETE OR TRUNCATE ON invoices FOR EACH STATEMENT EXECUTE FUNCTION reject_invoice_mutation();
DROP TRIGGER immutable_wallet_ledger ON wallet_ledger;
CREATE TRIGGER immutable_wallet_ledger BEFORE UPDATE ON wallet_ledger FOR EACH ROW EXECUTE FUNCTION privacy_private.guard_redaction();
CREATE TRIGGER immutable_wallet_ledger_delete BEFORE DELETE OR TRUNCATE ON wallet_ledger FOR EACH STATEMENT EXECUTE FUNCTION reject_wallet_ledger_mutation();
DROP TRIGGER immutable_wallet_audits ON wallet_audits;
CREATE TRIGGER immutable_wallet_audits BEFORE UPDATE ON wallet_audits FOR EACH ROW EXECUTE FUNCTION privacy_private.guard_redaction();
CREATE TRIGGER immutable_wallet_audits_delete BEFORE DELETE OR TRUNCATE ON wallet_audits FOR EACH STATEMENT EXECUTE FUNCTION reject_wallet_ledger_mutation();
DROP TRIGGER immutable_audit_logs ON audit_logs;
CREATE TRIGGER immutable_audit_logs BEFORE UPDATE ON audit_logs FOR EACH ROW EXECUTE FUNCTION privacy_private.guard_redaction();
CREATE TRIGGER immutable_audit_logs_delete BEFORE DELETE OR TRUNCATE ON audit_logs FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_log_mutation();
DROP TRIGGER immutable_control_audit ON ocpp_control_requests;
CREATE TRIGGER immutable_control_audit BEFORE UPDATE ON ocpp_control_requests FOR EACH ROW EXECUTE FUNCTION privacy_private.guard_redaction();
CREATE TRIGGER immutable_control_audit_delete BEFORE DELETE OR TRUNCATE ON ocpp_control_requests FOR EACH STATEMENT EXECUTE FUNCTION reject_control_audit_mutation();

CREATE FUNCTION privacy_private.reject_frozen_driver_write() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE st text; owner_name text;
BEGIN
 -- Only the private stage function runs with a valid job context. All normal
 -- writes, including raw SQL callers, serialize with its row lock.
 IF current_user=pg_get_userbyid((SELECT proowner FROM pg_proc WHERE proname='execute_stage' AND pronamespace=(SELECT oid FROM pg_namespace WHERE nspname='privacy_private'))) AND current_setting('csms.privacy_job',true) IS NOT NULL THEN IF privacy_private.redaction_context() THEN RETURN NEW; END IF; END IF;
 SELECT status INTO st FROM public.users WHERE id=NEW.driver_id FOR UPDATE;
 IF st IN ('pending_deletion','anonymized') THEN RAISE EXCEPTION 'driver privacy freeze'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION privacy_private.reject_frozen_driver_write() FROM PUBLIC;
CREATE TRIGGER privacy_driver_fence BEFORE INSERT OR UPDATE OF driver_id ON charging_cards FOR EACH ROW EXECUTE FUNCTION privacy_private.reject_frozen_driver_write();
CREATE TRIGGER privacy_driver_fence BEFORE INSERT OR UPDATE OF driver_id ON charging_sessions FOR EACH ROW EXECUTE FUNCTION privacy_private.reject_frozen_driver_write();
CREATE TRIGGER privacy_driver_fence BEFORE INSERT OR UPDATE OF driver_id ON driver_start_requests FOR EACH ROW EXECUTE FUNCTION privacy_private.reject_frozen_driver_write();
CREATE TRIGGER privacy_driver_fence BEFORE INSERT OR UPDATE OF driver_id ON reservations FOR EACH ROW EXECUTE FUNCTION privacy_private.reject_frozen_driver_write();
CREATE TRIGGER privacy_driver_fence BEFORE INSERT OR UPDATE OF driver_id ON wallet_topups FOR EACH ROW EXECUTE FUNCTION privacy_private.reject_frozen_driver_write();
CREATE TRIGGER privacy_driver_fence BEFORE INSERT OR UPDATE OF driver_id ON wallets FOR EACH ROW EXECUTE FUNCTION privacy_private.reject_frozen_driver_write();

CREATE FUNCTION privacy_private.execute_stage(p_job uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE j public.privacy_jobs; req public.privacy_requests; vault privacy_private.subjects;
 uid uuid; sid uuid; mail text; tag text; item record;
BEGIN
 SELECT * INTO j FROM public.privacy_jobs WHERE id=p_job FOR UPDATE;
 IF j.id IS NULL THEN RAISE EXCEPTION 'job_not_found'; END IF;
 IF j.checkpoint=3 THEN RETURN 3; END IF;
 IF j.status='needs_review' THEN RAISE EXCEPTION 'job_requires_review'; END IF;
 UPDATE public.privacy_jobs SET status='processing' WHERE id=j.id;
 SELECT * INTO req FROM public.privacy_requests WHERE id=j.request_id FOR UPDATE;
 uid:=req.user_id;
 IF j.checkpoint<2 THEN PERFORM privacy_private.check_gates(p_job); END IF;
 IF j.checkpoint=0 THEN
   sid:=gen_random_uuid();
   INSERT INTO privacy_private.subjects(job_id,original_user_id,subject_id,original_email)
     SELECT j.id,uid,sid,email FROM public.users WHERE id=uid;
   UPDATE public.users SET status='pending_deletion',updated_at=clock_timestamp() WHERE id=uid;
   UPDATE public.sessions SET revoked_at=COALESCE(revoked_at,clock_timestamp()),ip_address=NULL,user_agent=NULL WHERE user_id=uid;
   UPDATE public.charging_cards SET status='revoked' WHERE driver_id=uid;
   UPDATE public.privacy_jobs SET status='processing',checkpoint=1,updated_at=clock_timestamp() WHERE id=j.id;
   RETURN 1;
 END IF;
 SELECT * INTO vault FROM privacy_private.subjects WHERE job_id=j.id;
 sid:=vault.subject_id; mail:=vault.original_email;
 PERFORM set_config('csms.privacy_job',j.id::text,true);
 IF j.checkpoint=1 THEN
   IF EXISTS(SELECT 1 FROM public.users WHERE id=sid AND (status<>'anonymized' OR email<>'retained_'||sid::text||'@deleted.local')) THEN RAISE EXCEPTION 'subject_collision'; END IF;
   INSERT INTO public.users(id,email,password_hash,status,created_at,updated_at) VALUES(sid,'retained_'||sid::text||'@deleted.local','DISABLED_PRIVACY_SUBJECT','anonymized',timestamptz '1970-01-01 00:00:00+00',timestamptz '1970-01-01 00:00:00+00') ON CONFLICT(id) DO NOTHING;
   -- Preserve every document/session/ledger ID, amount, rate and timestamp.
   UPDATE public.invoices SET driver_id=sid WHERE driver_id=uid;
   UPDATE public.wallets SET driver_id=sid,status='locked' WHERE driver_id=uid;
   UPDATE public.wallet_topups SET driver_id=sid,reason=privacy_private.redact_text(privacy_private.redact_text(reason,uid::text),mail) WHERE driver_id=uid;
   UPDATE public.charging_sessions SET driver_id=sid,tag_tail='----' WHERE driver_id=uid;
   UPDATE public.reservations SET driver_id=sid WHERE driver_id=uid;
   UPDATE public.driver_start_requests SET driver_id=sid WHERE driver_id=uid;
   UPDATE public.charging_cards SET driver_id=sid,tag_hash=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-',''),tag_tail='----',status='revoked' WHERE driver_id=uid;
   -- Raw virtual tags must not survive in operational JSON or on the card.
   FOR tag IN SELECT id_tag FROM public.id_tags WHERE driver_id=uid LOOP
    UPDATE public.ocpp_control_requests SET payload=privacy_private.scrub(payload,tag,mail)
      WHERE payload::text LIKE '%'||tag||'%';
    UPDATE public.charging_session_events SET details=privacy_private.scrub(details,tag,mail)
      WHERE details::text LIKE '%'||tag||'%';
    UPDATE public.charging_pending_messages SET payload=privacy_private.scrub(payload,tag,mail) WHERE position(tag in payload::text)>0;
   END LOOP;
   DELETE FROM public.id_tags WHERE driver_id=uid;
   UPDATE public.charging_cards SET issuer_id=sid WHERE issuer_id=uid;
   UPDATE public.charging_sessions SET closed_by=sid WHERE closed_by=uid;
   UPDATE public.operational_alerts SET acknowledged_by=CASE WHEN acknowledged_by=uid THEN sid ELSE acknowledged_by END,
     closed_by=CASE WHEN closed_by=uid THEN sid ELSE closed_by END,details=privacy_private.scrub(details,uid::text,mail),
     close_reason=privacy_private.redact_text(privacy_private.redact_text(close_reason,uid::text),mail)
     WHERE acknowledged_by=uid OR closed_by=uid OR position(lower(mail) in lower(details::text))>0 OR position(uid::text in details::text)>0;
   UPDATE public.ocpp_configuration_intents SET actor_id=CASE WHEN actor_id=uid THEN sid ELSE actor_id END,
     reset_actor_id=CASE WHEN reset_actor_id=uid THEN sid ELSE reset_actor_id END WHERE actor_id=uid OR reset_actor_id=uid;
   UPDATE public.reconciliation_runs SET created_by=sid WHERE created_by=uid;
   DELETE FROM public.station_create_idempotency WHERE actor_id=uid;
   UPDATE public.wallet_ledger SET actor_id=sid WHERE actor_id=uid;
   UPDATE public.wallet_audits SET actor_id=CASE WHEN actor_id=uid THEN sid ELSE actor_id END,
     reason=privacy_private.redact_text(privacy_private.redact_text(reason,uid::text),mail)
     WHERE actor_id=uid OR position(uid::text in reason)>0 OR position(lower(mail) in lower(reason))>0;
   UPDATE public.audit_logs SET actor_id=CASE WHEN actor_id=uid THEN sid ELSE actor_id END,
     object_id=replace(replace(object_id,uid::text,'[redacted]'),mail,'[redacted]'),
     data=privacy_private.scrub(data,uid::text,mail)
     WHERE actor_id=uid OR object_id=uid::text OR position(uid::text in data::text)>0 OR position(lower(mail) in lower(data::text))>0;
   UPDATE public.ocpp_control_requests SET actor_id=CASE WHEN actor_id=uid THEN sid ELSE actor_id END,
     actor_email=CASE WHEN actor_id=uid OR lower(actor_email)=lower(mail) THEN '[redacted]' ELSE actor_email END,
     payload=privacy_private.scrub(payload,uid::text,mail)
     WHERE actor_id=uid OR lower(actor_email)=lower(mail) OR position(uid::text in payload::text)>0 OR position(lower(mail) in lower(payload::text))>0;
   UPDATE public.account_audits SET actor_id=CASE WHEN actor_id=uid THEN sid ELSE actor_id END,
     target_id=CASE WHEN target_id=uid THEN sid ELSE target_id END,
     before_state=privacy_private.scrub(before_state,uid::text,mail),after_state=privacy_private.scrub(after_state,uid::text,mail)
     WHERE actor_id=uid OR target_id=uid OR position(lower(mail) in lower(after_state::text))>0 OR position(lower(mail) in lower(COALESCE(before_state::text,'')))>0;
   UPDATE public.charging_session_events SET actor_id=CASE WHEN actor_id=uid THEN sid ELSE actor_id END,
     details=privacy_private.scrub(details,uid::text,mail) WHERE actor_id=uid OR position(uid::text in details::text)>0 OR position(lower(mail) in lower(details::text))>0;
   DELETE FROM public.user_roles WHERE user_id=uid;
   DELETE FROM public.sessions WHERE user_id=uid;
   UPDATE public.privacy_requests SET reason='[processed]',decision_reason=privacy_private.redact_text(privacy_private.redact_text(decision_reason,uid::text),mail) WHERE user_id=uid;
   UPDATE public.users SET email='deleted_'||gen_random_uuid()::text||'@deleted.local',password_hash='DISABLED_PRIVACY_SUBJECT',
     status='anonymized',failed_login_count=0,locked_until=NULL,updated_at=clock_timestamp() WHERE id=uid;
   UPDATE public.privacy_jobs SET checkpoint=2,updated_at=clock_timestamp(),last_error=NULL WHERE id=j.id;
   UPDATE privacy_private.subjects SET original_email='[redacted]' WHERE job_id=j.id;
   RETURN 2;
 END IF;
 -- Drop the temporary original-ID -> financial-subject bridge. Neither the
 -- request nor the audit receipt records the replacement subject ID.
 DELETE FROM privacy_private.subjects WHERE job_id=j.id;
 INSERT INTO public.audit_logs(id,action,object_type,object_id,data,permission)
 VALUES(gen_random_uuid(),'privacy.request_completed','privacy_request',req.id::text,jsonb_build_object('policy_version',req.policy_version,'financial_values_preserved',true),'system.privacy.execute');
 UPDATE public.privacy_jobs SET status='completed',checkpoint=3,updated_at=clock_timestamp(),last_error=NULL WHERE id=j.id;
 RETURN 3;
END $$;
REVOKE ALL ON FUNCTION privacy_private.execute_stage(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION privacy_private.execute_stage(uuid) TO csms_privacy_executor;

GRANT SELECT ON public.privacy_jobs TO csms_privacy_executor;
GRANT UPDATE(status,last_error,updated_at) ON public.privacy_jobs TO csms_privacy_executor;
