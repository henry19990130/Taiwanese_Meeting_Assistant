import glob, hashlib, json, os, re, shutil, subprocess, sys, time, urllib.request

USE_TUNNEL = True
FORCE_SETUP = False

T0 = time.time()


def step(title):
    print(f"\n{'=' * 60}\n{title}　（已執行 {time.time() - T0:.0f} 秒）\n{'=' * 60}", flush=True)


def sh(cmd, cwd=None):
    p = subprocess.Popen(cmd, shell=isinstance(cmd, str), cwd=cwd, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in p.stdout:
        print(line, end='', flush=True)
    return p.wait()


step('① 掛載雲端硬碟、複製最新程式')
try:
    from google.colab import drive
except ModuleNotFoundError:
    raise RuntimeError('現在是在「你自己的電腦」上執行，不是在 Colab。\n'
                       '請點 notebook 右上角的核心名稱 → Select Another Kernel → Colab → 連線到 GPU 伺服器，再執行一次。') from None

drive.mount('/content/drive')

PROJECT_NAME = 'test2'
patterns = ['/content/drive/MyDrive/' + '*/' * d + PROJECT_NAME + '/setup_colab.sh' for d in range(0, 3)]
patterns += ['/content/drive/Othercomputers/' + '*/' * d + PROJECT_NAME + '/setup_colab.sh' for d in range(1, 5)]
found = sorted({os.path.dirname(p) for pat in patterns for p in glob.glob(pat)})
if not found:
    raise FileNotFoundError(f'在「我的雲端硬碟」和「電腦」裡都找不到 {PROJECT_NAME} 資料夾（裡面要有 setup_colab.sh），'
                            f'請確認資料夾已改名為 {PROJECT_NAME} 並同步完成')


def newest_code_mtime(d):
    times = [os.path.getmtime(p) for sub in ('backend/app', 'frontend', 'scripts')
             for p in glob.glob(os.path.join(d, sub, '**', '*.*'), recursive=True)]
    return max(times, default=os.path.getmtime(os.path.join(d, 'setup_colab.sh')))


found.sort(key=newest_code_mtime)
SOURCE_DIR = found[-1]
if len(found) > 1:
    print(f'⚠️ 找到不只一份 {PROJECT_NAME}，使用程式碼最新的那一份（建議刪掉舊的）：')
    for f in found:
        print('   ', '👉' if f == SOURCE_DIR else '  ', f)

PROJECT_DIR = '/content/' + PROJECT_NAME
BACKEND_DIR = os.path.join(PROJECT_DIR, 'backend')
LOG_DIR = os.path.join(PROJECT_DIR, 'logs')


def sync_code():
    shutil.copytree(SOURCE_DIR, PROJECT_DIR, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('logs', 'audio', '__pycache__', '*.pyc', '.env'))
    for name in ('.env', '.env.example'):
        src = os.path.join(SOURCE_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(PROJECT_DIR, '.env'))
            break
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.join(BACKEND_DIR, 'storage', 'audio'), exist_ok=True)


sync_code()
os.chdir(PROJECT_DIR)

if not os.environ.get('HF_TOKEN'):
    try:
        from google.colab import userdata
        _tok = userdata.get('HF_TOKEN')
        if _tok:
            os.environ['HF_TOKEN'] = _tok
            print('✅ 已讀取 Colab 金鑰 HF_TOKEN（客語模型可下載）')
    except Exception:
        print('ℹ️ 沒有 Colab 金鑰 HF_TOKEN：中文／台語／英文可用；客語模型需要先設定才能下載')
print('✅ 專案來源：', SOURCE_DIR)
print('✅ 執行位置：', PROJECT_DIR)

step('② 安裝環境')
SETUP = os.path.join(PROJECT_DIR, 'setup_colab.sh')
MARKER = '/content/.setup_done_' + PROJECT_NAME


def setup_fingerprint():
    h = hashlib.sha256()
    for rel in ('setup_colab.sh', 'backend/requirements.txt', 'database/schema.sql'):
        p = os.path.join(PROJECT_DIR, rel)
        if os.path.exists(p):
            h.update(open(p, 'rb').read().replace(b'\r\n', b'\n'))
    return h.hexdigest()


def services_running():
    pg = subprocess.run(['pg_isready', '-h', 'localhost'], capture_output=True).returncode == 0
    try:
        urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3)
        ollama = True
    except Exception:
        ollama = False
    return pg, ollama


fp = setup_fingerprint()
done_fp = open(MARKER).read().strip() if os.path.exists(MARKER) else ''
pg_ok, ollama_ok = services_running() if done_fp else (False, False)

if not FORCE_SETUP and done_fp == fp and pg_ok and ollama_ok:
    print('✅ 已經安裝過，而且資料庫、Ollama 都在執行 → 跳過安裝')
else:
    if done_fp and done_fp != fp:
        print('安裝腳本或套件清單有改過 → 重新安裝')
    elif done_fp:
        print(f'服務沒有在執行（資料庫 {"✅" if pg_ok else "❌"}、Ollama {"✅" if ollama_ok else "❌"}）→ 重新執行安裝來啟動')
    else:
        print('第一次執行 → 完整安裝（約 10～20 分鐘，主要是下載模型）')
    with open(SETUP, 'rb') as f:
        data = f.read()
    with open(SETUP, 'wb') as f:
        f.write(data.replace(b'\r\n', b'\n'))
    env_report = os.path.join(PROJECT_DIR, 'logs', 'env_check.txt')
    if os.path.exists(env_report):
        os.remove(env_report)
    code = sh(['bash', SETUP])
    if code != 0:
        if os.path.exists(env_report):
            print('\n' + open(env_report, encoding='utf-8').read())
            raise RuntimeError('❌ 環境檢查有項目失敗，請把上面「環境檢查結果」整段貼給我')
        raise RuntimeError(f'❌ 安裝失敗（代碼 {code}），請把上面最後幾十行貼出來')
    with open(MARKER, 'w') as f:
        f.write(fp)
    print('✅ 安裝完成')

step('③ 啟動後端')
subprocess.run(['pkill', '-f', 'uvicorn app[.]main'])
time.sleep(1)
server = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000'],
    cwd=BACKEND_DIR, stdout=open(os.path.join(LOG_DIR, 'backend.log'), 'w'), stderr=subprocess.STDOUT,
)
print('等待後端啟動', end='', flush=True)
health = None
for _ in range(90):
    if server.poll() is not None:
        break
    try:
        health = json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2))
        break
    except Exception:
        print('.', end='', flush=True)
        time.sleep(1)
print()
if not health:
    with open(os.path.join(LOG_DIR, 'backend.log'), encoding='utf-8', errors='replace') as f:
        print(''.join(f.readlines()[-30:]))
    raise RuntimeError('❌ 後端沒有啟動成功，上面是 log 最後 30 行')
print('✅ 後端已啟動（帳號 demo / 密碼 demo1234）')
print(f"   LLM：{health.get('llm_model')}　溫度 {health.get('llm_temperature')}　seed {health.get('llm_seed')}"
      f"　思考 {health.get('llm_think')}　上下文 {health.get('llm_num_ctx')}")

PUBLIC_URL = None
if USE_TUNNEL:
    step('⑤ 開臨時網址')
    print('⚠️ 隱私提醒：資料會經過 Cloudflare，只能用公開的測試音檔；測完請執行第 6 段關閉。')
    CLOUDFLARED = '/usr/local/bin/cloudflared'
    if not os.path.exists(CLOUDFLARED):
        urllib.request.urlretrieve(
            'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64',
            CLOUDFLARED)
        os.chmod(CLOUDFLARED, 0o755)
    subprocess.run(['pkill', '-f', 'cloudflared[ ]tunnel'])
    TUNNEL_LOG = '/content/tunnel.log'
    tunnel = subprocess.Popen([CLOUDFLARED, 'tunnel', '--url', 'http://127.0.0.1:8000', '--no-autoupdate'],
                              stdout=open(TUNNEL_LOG, 'w'), stderr=subprocess.STDOUT)

    url = None
    for _ in range(60):
        time.sleep(1)
        text = open(TUNNEL_LOG).read()
        m = re.search(r'https://[-a-z0-9]+\.trycloudflare\.com', text)
        url = m.group(0) if m else None
        if url and 'Registered tunnel connection' in text:
            break
    if url:
        print('網址已建立，確認外部連得到', end='', flush=True)
        for _ in range(45):
            try:
                urllib.request.urlopen(url + '/api/v1/health', timeout=5)
                PUBLIC_URL = url
                break
            except Exception:
                print('.', end='', flush=True)
                time.sleep(2)
        print()
    if PUBLIC_URL:
        print('✅ 臨時網址已可使用')
    else:
        print('❌ 臨時網址沒有建立成功，cloudflared log 最後幾行：')
        print(open(TUNNEL_LOG).read()[-1500:])

step('完成')
if PUBLIC_URL:
    print('👉 用瀏覽器打開：', PUBLIC_URL)
    print('   帳號 demo / 密碼 demo1234')
    print('   ※ 若顯示「無法連上這個網站」：等 30 秒後重新整理；仍不行，在 Windows 命令提示字元執行')
    print('     ipconfig /flushdns 再重新整理（電腦記住了「查不到」的結果）')
    print('   ※ 每次重跑都會換新網址，舊網址會失效')
elif not USE_TUNNEL:
    print('後端在 port 8000 執行中（瀏覽器版 Colab 可執行第 3 段在下方顯示網頁）')
