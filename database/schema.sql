CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meeting_transcripts (
    meeting_id UUID PRIMARY KEY
        REFERENCES meetings(id)
        ON DELETE CASCADE,
    transcript JSONB NOT NULL,
    model_name VARCHAR(200),
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
    next_meeting JSONB NOT NULL DEFAULT
        '{"date":null,"time":null,"status":"not_mentioned"}',
    review_notes JSONB NOT NULL DEFAULT '[]',
    headline TEXT,
    model_name VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) NOT NULL DEFAULT 'audio';
ALTER TABLE meetings ALTER COLUMN audio_path DROP NOT NULL;
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS headline TEXT;
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS language VARCHAR(8) NOT NULL DEFAULT 'zh';
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS typo_suggestions JSONB NOT NULL DEFAULT '[]';

ALTER TABLE meeting_transcripts ADD COLUMN IF NOT EXISTS proofread JSONB;
ALTER TABLE meeting_transcripts ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE meeting_transcripts ALTER COLUMN confirmed_at SET DEFAULT NULL;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id);

CREATE TABLE IF NOT EXISTS user_terms (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    term VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, term)
);
CREATE INDEX IF NOT EXISTS user_terms_user_idx ON user_terms (user_id, created_at);

CREATE TABLE IF NOT EXISTS login_locks (
    username VARCHAR(32) PRIMARY KEY,
    failed_count INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ
);
