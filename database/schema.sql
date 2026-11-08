CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS login_locks (
    username VARCHAR(100) PRIMARY KEY,
    failed_count INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash VARCHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS meetings (
    id UUID PRIMARY KEY,
    meeting_name VARCHAR(255) NOT NULL,
    date DATE NOT NULL,
    start_time TIME,
    end_time TIME,
    source_type VARCHAR(20) NOT NULL DEFAULT 'audio',
    audio_path TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'uploaded',
    error_message TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS meetings_owner_date_idx
    ON meetings (created_by, date DESC, start_time DESC NULLS LAST, created_at DESC);

CREATE TABLE IF NOT EXISTS meeting_transcripts (
    meeting_id UUID PRIMARY KEY
        REFERENCES meetings(id)
        ON DELETE CASCADE,
    transcript JSONB NOT NULL,
    model_name VARCHAR(200),
    proofread JSONB,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meeting_summaries (
    meeting_id UUID PRIMARY KEY
        REFERENCES meetings(id)
        ON DELETE CASCADE,
    reports JSONB NOT NULL DEFAULT '[]',
    discussions JSONB NOT NULL DEFAULT '[]',
    decisions JSONB NOT NULL DEFAULT '[]',
    action_items JSONB NOT NULL DEFAULT '[]',
    next_meeting JSONB NOT NULL DEFAULT '{"date":null,"time":null,"status":"not_mentioned"}',
    review_notes JSONB NOT NULL DEFAULT '[]',
    headline TEXT,
    model_name VARCHAR(100),
    language VARCHAR(8) NOT NULL DEFAULT 'zh',
    typo_suggestions JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_terms (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    term VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, term)
);

CREATE INDEX IF NOT EXISTS user_terms_user_idx ON user_terms (user_id, created_at);

-- 連線帳號擁有這些表。沒有 FORCE 時，擁有者會繞過政策。
-- app.user_id：這次請求的使用者。app.system = on：只給啟動時收回中斷的會議。
CREATE OR REPLACE FUNCTION public.app_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION public.app_is_system() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT current_setting('app.system', true) = 'on'
$$;

ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS meetings_owner ON meetings;
CREATE POLICY meetings_owner ON meetings
    FOR ALL
    USING (public.app_is_system() OR created_by = public.app_user_id())
    WITH CHECK (public.app_is_system() OR created_by = public.app_user_id());

ALTER TABLE meeting_transcripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_transcripts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS transcripts_owner ON meeting_transcripts;
CREATE POLICY transcripts_owner ON meeting_transcripts
    FOR ALL
    USING (
        public.app_is_system()
        OR EXISTS (SELECT 1 FROM meetings m WHERE m.id = meeting_transcripts.meeting_id)
    )
    WITH CHECK (
        public.app_is_system()
        OR EXISTS (SELECT 1 FROM meetings m WHERE m.id = meeting_transcripts.meeting_id)
    );

ALTER TABLE meeting_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_summaries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS summaries_owner ON meeting_summaries;
CREATE POLICY summaries_owner ON meeting_summaries
    FOR ALL
    USING (
        public.app_is_system()
        OR EXISTS (SELECT 1 FROM meetings m WHERE m.id = meeting_summaries.meeting_id)
    )
    WITH CHECK (
        public.app_is_system()
        OR EXISTS (SELECT 1 FROM meetings m WHERE m.id = meeting_summaries.meeting_id)
    );

ALTER TABLE user_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_terms FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS terms_owner ON user_terms;
CREATE POLICY terms_owner ON user_terms
    FOR ALL
    USING (public.app_is_system() OR user_id = public.app_user_id())
    WITH CHECK (public.app_is_system() OR user_id = public.app_user_id());
