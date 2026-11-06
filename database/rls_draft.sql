-- 草稿，不要套到現有資料庫，setup_colab.sh 也不會執行這份檔案。
-- 應用程式目前還沒有 SET LOCAL app.user_id。直接啟用後，會議查詢會變成空的。
-- 連線帳號是資料表擁有者，所以要 FORCE，否則擁有者會繞過政策。

ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meetings_owner ON meetings;
CREATE POLICY meetings_owner ON meetings
    FOR ALL
    USING (created_by = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (created_by = NULLIF(current_setting('app.user_id', true), '')::uuid);
