CREATE TABLE driver_notifications (
 id uuid PRIMARY KEY, driver_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 session_id integer NOT NULL REFERENCES charging_sessions(id) ON DELETE RESTRICT,
 event_type varchar(20) NOT NULL CONSTRAINT ck_driver_notification_event CHECK(event_type IN ('stop','idle','invoice')),
 event_id varchar(100) NOT NULL, title varchar(200) NOT NULL, message text NOT NULL,
 occurred_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), read_at timestamptz,
 email_status varchar(20) NOT NULL DEFAULT 'pending' CONSTRAINT ck_driver_notification_email CHECK(email_status IN ('pending','sending','sent')),
 attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, lease_token uuid,
 CONSTRAINT uq_driver_notification_event UNIQUE(driver_id,event_type,event_id)
);
CREATE INDEX ix_driver_notifications_driver_id ON driver_notifications(driver_id);
CREATE INDEX ix_driver_notifications_due ON driver_notifications(next_attempt_at) WHERE email_status <> 'sent';
-- The retained notification text links identity with a charging location/time.
-- Purge it together with S-57's freeze, before financial identity is unlinked.
CREATE FUNCTION purge_driver_notifications() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status IN ('pending_deletion','anonymized') THEN DELETE FROM driver_notifications WHERE driver_id=NEW.id; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER privacy_driver_notifications BEFORE UPDATE OF status ON users FOR EACH ROW EXECUTE FUNCTION purge_driver_notifications();
