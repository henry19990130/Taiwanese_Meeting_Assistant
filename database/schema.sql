CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE, --vs login_locks.username VARCHAR(100), passwords.py USERNAME_RE 
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_locks (
    username VARCHAR(100) PRIMARY KEY, --vs users.username VARCHAR(100), passwords.py USERNAME_RE 
    failed_count INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ
);

ALTER TABLE login_locks ALTER COLUMN username TYPE VARCHAR(100);

ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(32);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash VARCHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- ============================================================
-- 會議主表：每場會議一列（上傳音檔或直接貼逐字稿）
-- 主要查詢：repositories/library.py——依 created_by 過濾、date/start_time 由新到舊排序
-- ============================================================
CREATE TABLE IF NOT EXISTS meetings (
    id UUID PRIMARY KEY,                               -- 由應用端（Python uuid4）產生，資料庫無預設值
    meeting_name VARCHAR(255) NOT NULL,                -- 顯示名稱；前端 maxlength=255（index.html:152）
    date DATE NOT NULL,                                -- 會議日期（牆上時間，無時區；跨午夜會議 end_time < start_time）
    start_time TIME,                                   -- 可空：transcript 來源可能沒有時間資訊
    end_time TIME,                                     -- 可空：同上
    source_type VARCHAR(20) NOT NULL DEFAULT 'audio',  -- 合法值 'audio'｜'transcript'，定義在 repositories/meetings.py SOURCE_TYPES
    audio_path TEXT,                                   -- 音檔路徑；source_type='transcript' 時為 NULL
    status VARCHAR(30) NOT NULL DEFAULT 'uploaded',    -- 狀態機：uploaded→transcribing→proofreading→summarizing→transcribed/completed/failed
    error_message TEXT,                                -- 失敗時存 JSON 字串 {stage, code, message}（repositories/meetings.py:55）
    created_by UUID REFERENCES users(id),              -- 擁有者；所有權限判斷的依據（access.py、_and_owner）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()      -- 無觸發器，由應用端每次 UPDATE 手動維護
);

-- ↓↓↓ 舊資料庫遷移區：全新資料庫的 CREATE 已包含以上欄位，以下皆為 no-op，不可刪 ↓↓↓
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) NOT NULL DEFAULT 'audio';
ALTER TABLE meetings ALTER COLUMN audio_path DROP NOT NULL;  -- 舊版曾 NOT NULL；開放 transcript 來源後放寬
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id);

-- 每個使用者的會議列表（library / assistant 六個端點都靠這個查詢）：owner 過濾 + 日期排序
-- 位置規則：必須在 created_by 的 ALTER 之後（全新資料庫靠上面才有的欄位）
-- NULLS LAST 與 library.py 的 ORDER BY 完全一致，缺了它 Postgres 會重新排序
CREATE INDEX IF NOT EXISTS meetings_owner_date_idx
    ON meetings (created_by, date DESC, start_time DESC NULLS LAST, created_at DESC);

CREATE TABLE IF NOT EXISTS meeting_transcripts (
    meeting_id UUID PRIMARY KEY
        REFERENCES meetings(id)
        ON DELETE CASCADE,
    transcript JSONB NOT NULL,
    model_name VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE meeting_transcripts ADD COLUMN IF NOT EXISTS proofread JSONB;
ALTER TABLE meeting_transcripts ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE meeting_transcripts ALTER COLUMN confirmed_at SET DEFAULT NULL;

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS headline TEXT;
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS language VARCHAR(8) NOT NULL DEFAULT 'zh';
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS typo_suggestions JSONB NOT NULL DEFAULT '[]';



-- ============================================================
-- 使用者自訂詞庫：ASR 與校對提示用的專有名詞（meeting_service.py term_strings 取用）
-- 上限：MAX_TERMS=200、MAX_TERM_LEN=30，定義在 repositories/terms.py
-- ============================================================
CREATE TABLE IF NOT EXISTS user_terms (
    id UUID PRIMARY KEY,                                    -- 應用端（Python uuid4）產生
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    term VARCHAR(30) NOT NULL,                              -- 大小寫視為不同詞（'Whisper' ≠ 'whisper'）；長度與 terms.py MAX_TERM_LEN 一致
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),          -- 同一批加入的詞 NOW() 相同，排序靠 term 破平手
    UNIQUE (user_id, term)                                  -- 同時是 ON CONFLICT (user_id, term) 判重的依據
);
-- 詞庫列表（terms.py:11）：WHERE user_id = %s ORDER BY created_at, term（舊→新）
-- UNIQUE (user_id, term) 已涵蓋 user_id 過濾與判重；此索引讓 created_at 排序免排序節點
CREATE INDEX IF NOT EXISTS user_terms_user_idx ON user_terms (user_id, created_at);

-- ↓↓↓ 舊資料庫遷移區（user_terms）：不可刪 ↓↓↓
ALTER TABLE user_terms ALTER COLUMN term TYPE VARCHAR(30);   -- 舊資料庫原為 VARCHAR(50)；需先確認無超過 30 字的資料