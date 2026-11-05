"""覓聲 Colab 一鍵啟動：複製程式 → 安裝（裝過就跳過）→ 放模擬會議 → 啟動後端 → 開臨時網址。

由 colab_run.ipynb 的「一鍵執行」cell 用 exec() 執行，所以這裡定義的變數
（SOURCE_DIR、PROJECT_DIR、LOG_DIR、ENV…）之後的 cell 都可以直接用。

notebook 可以在 exec 之前設定：
  RUN_ALL_SOURCE = 專案來源資料夾（雲端硬碟或 GitHub 下載的位置）
  RUN_STEPS      = 只跑某幾段，例如 {'setup'}；不設 = 全部跑
"""
import glob, hashlib, json, os, re, shutil, subprocess, sys, time, urllib.request

# ===== 選項（要調整改這裡）=====
USE_TUNNEL = True      # 開 Cloudflare 臨時網址（VS Code 必須開，瀏覽器版 Colab 可關）
FORCE_SETUP = False    # True = 不管有沒有裝過都重新安裝
SEED_DEMO = True       # 放入 10 場模擬會議給 demo 帳號（每次重放，不會重複）
PROJECT_NAMES = ('Taiwanese_Meeting_Assistant', 'test2')   # 雲端硬碟上可能的專案資料夾名稱
GITHUB_REPO = 'https://github.com/henry19990130/Taiwanese_Meeting_Assistant.git'
PROJECT_DIR = '/content/Taiwanese_Meeting_Assistant'      # Colab 本機執行位置

ALL_STEPS = ('setup', 'seed', 'backend', 'tunnel')
_steps = globals().pop('RUN_STEPS', None)
STEPS = set(_steps) if _steps else set(ALL_STEPS)

T0 = time.time()


def step(title):
    print(f"\n{'=' * 60}\n{title}　（已執行 {time.time() - T0:.0f} 秒）\n{'=' * 60}", flush=True)


def sh(cmd, cwd=None, env=None):
    """執行指令並即時印出輸出（取代 ! 寫法，VS Code 也能用）。"""
    p = subprocess.Popen(cmd, shell=isinstance(cmd, str), cwd=cwd, env=env, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in p.stdout:
        print(line, end='', flush=True)
    return p.wait()


def find_source():
    """找專案來源：notebook 指定的 → 雲端硬碟 → GitHub。"""
    given = globals().get('RUN_ALL_SOURCE')
    if given and os.path.exists(os.path.join(given, 'setup_colab.sh')):
        return given
    found = []
    try:
        from google.colab import drive
        if not os.path.isdir('/content/drive/MyDrive'):
            drive.mount('/content/drive')
        for name in PROJECT_NAMES:
            pats = ['/content/drive/MyDrive/' + '*/' * d + name + '/setup_colab.sh' for d in range(0, 3)]
            pats += ['/content/drive/Othercomputers/' + '*/' * d + name + '/setup_colab.sh' for d in range(1, 5)]
            found += [os.path.dirname(p) for pat in pats for p in glob.glob(pat)]
    except Exception as exc:
        print('⚠️ 無法掛載雲端硬碟（', type(exc).__name__, exc, '）→ 改從 GitHub 下載')
    if found:
        found = sorted(set(found), key=newest_code_mtime)
        if len(found) > 1:
            print('⚠️ 找到不只一份專案，使用程式碼最新的那一份（建議刪掉舊的）：')
            for f in found:
                print('   ', '👉' if f == found[-1] else '  ', f)
        return found[-1]
    return clone_github()


def clone_github():
    dst = '/content/_src_github'
    if os.path.isdir(os.path.join(dst, '.git')):
        code = sh(['git', '-C', dst, 'fetch', '-q', '--depth', '1', 'origin', 'main'])
        if code == 0:
            sh(['git', '-C', dst, 'reset', '-q', '--hard', 'FETCH_HEAD'])
    else:
        if sh(['git', 'clone', '-q', '--depth', '1', GITHUB_REPO, dst]) != 0:
            raise RuntimeError('❌ 雲端硬碟找不到專案，GitHub 也下載失敗')
    print('ℹ️ 使用 GitHub 上 main 分支的程式（電腦上還沒 push 的修改不會包含在內）')
    return dst


def newest_code_mtime(d):
    times = [os.path.getmtime(p) for sub in ('backend/app', 'frontend', 'scripts')
             for p in glob.glob(os.path.join(d, sub, '**', '*.*'), recursive=True)]
    return max(times, default=os.path.getmtime(os.path.join(d, 'setup_colab.sh')))


TEXT_SUFFIXES = ('.sh', '.py', '.sql', '.txt', '.env', '.example')


def to_lf(path):
    """Windows 換行（\\r\\n）轉 Linux 換行。bash 讀到 \\r 會把它當成值的一部分
    （例如模型名稱變成 'qwen3.8:27b\\r'、密碼多一個看不見的字元）。"""
    with open(path, 'rb') as f:
        data = f.read()
    if b'\r\n' in data:
        with open(path, 'wb') as f:
            f.write(data.replace(b'\r\n', b'\n'))


def read_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def sync_code():
    """把來源的最新程式複製到 PROJECT_DIR（不動 log、上傳的音檔）。
    .env 每次依來源重建：有 .env 用 .env，沒有就用 .env.example。
    node_modules 與 Vite 快取不複製；頁面用已經建好的 frontend/dist。"""
    shutil.copytree(SOURCE_DIR, PROJECT_DIR, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
                        '.git', '.tmp.driveupload', 'logs', 'audio',
                        '__pycache__', '*.pyc', '.env',
                        'node_modules', '.vite'))
    for name in ('.env', '.env.example'):
        src = os.path.join(SOURCE_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(PROJECT_DIR, '.env'))
            break
    for root, _dirs, files in os.walk(PROJECT_DIR):
        if '/frontend/img' in root:
            continue
        for fn in files:
            if fn.endswith(TEXT_SUFFIXES) or fn == '.env':
                to_lf(os.path.join(root, fn))
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.join(BACKEND_DIR, 'storage', 'audio'), exist_ok=True)


# ---------------------------------------------------------------------------
step('① 找到專案、複製最新程式')
try:
    import google.colab  # noqa: F401
except ModuleNotFoundError:
    raise RuntimeError('現在是在「你自己的電腦」上執行，不是在 Colab。\n'
                       '請點 notebook 右上角的核心名稱 → Select Another Kernel → Colab → 連線到 GPU 伺服器，再執行一次。') from None

SOURCE_DIR = find_source()
RUN_ALL_SOURCE = SOURCE_DIR
BACKEND_DIR = os.path.join(PROJECT_DIR, 'backend')
LOG_DIR = os.path.join(PROJECT_DIR, 'logs')
sync_code()
os.chdir(PROJECT_DIR)
ENV = read_env(os.path.join(PROJECT_DIR, '.env'))
DEMO_USER = ENV.get('DEMO_USERNAME') or 'demo'
DEMO_PASS = ENV.get('DEMO_PASSWORD') or 'demo1234demo1234demo1234'

if not os.environ.get('HF_TOKEN') and ENV.get('HF_TOKEN'):
    os.environ['HF_TOKEN'] = ENV['HF_TOKEN']
if not os.environ.get('HF_TOKEN'):
    try:
        from google.colab import userdata
        _tok = userdata.get('HF_TOKEN')
        if _tok:
            os.environ['HF_TOKEN'] = _tok
            print('✅ 已讀取 Colab 金鑰 HF_TOKEN（客語模型可下載）')
    except Exception:
        print('ℹ️ 沒有 HF_TOKEN：中文／台語／英文可用；客語模型需要先在 .env 加 HF_TOKEN=... 才能下載\n'
              '   （VS Code 的 Colab 擴充讀不到 Colab 金鑰，請寫在 .env）')
print('✅ 專案來源：', SOURCE_DIR)
print('✅ 執行位置：', PROJECT_DIR)


# ---------------------------------------------------------------------------
def setup_fingerprint():
    h = hashlib.sha256()
    for rel in ('setup_colab.sh', 'backend/requirements.txt', 'database/schema.sql'):
        p = os.path.join(PROJECT_DIR, rel)
        if os.path.exists(p):
            h.update(open(p, 'rb').read())
    return h.hexdigest()


def services_running():
    pg = shutil.which('pg_isready') is not None and \
        subprocess.run(['pg_isready', '-h', 'localhost'], capture_output=True).returncode == 0
    try:
        urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3)
        ollama = True
    except Exception:
        ollama = False
    return pg, ollama


if 'setup' in STEPS:
    step('② 安裝環境')
    SETUP = os.path.join(PROJECT_DIR, 'setup_colab.sh')
    MARKER = '/content/.setup_done_meetsum'
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
        env_report = os.path.join(LOG_DIR, 'env_check.txt')
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

if 'seed' in STEPS and SEED_DEMO:
    step('③ 放入模擬會議')
    if sh([sys.executable, '../scripts/seed_demo_meetings.py', '--user', DEMO_USER], cwd=BACKEND_DIR) != 0:
        print('⚠️ 模擬會議沒有放成功（不影響其他功能），看上面訊息')


# ---------------------------------------------------------------------------
if 'backend' in STEPS:
    step('④ 啟動後端')
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
    print(f'✅ 後端已啟動（帳號 {DEMO_USER} / 密碼 {DEMO_PASS}）')
    print(f"   LLM：{health.get('llm_model')}　溫度 {health.get('llm_temperature')}　seed {health.get('llm_seed')}"
          f"　思考 {health.get('llm_think')}　上下文 {health.get('llm_num_ctx')}")

    if 'iframe' in STEPS:   # 只有瀏覽器版 Colab 看得到
        try:
            import warnings
            from google.colab import output
            output.serve_kernel_port_as_iframe(8000, height=900)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                output.serve_kernel_port_as_window(8000)
        except Exception as e:
            print('   （無法在這裡顯示網頁：', e, '）')


# ---------------------------------------------------------------------------
PUBLIC_URL = globals().get('PUBLIC_URL')
if 'tunnel' in STEPS and USE_TUNNEL:
    step('⑤ 開臨時網址')
    print('⚠️ 隱私提醒：資料會經過 Cloudflare，只能用公開的測試音檔；測完請執行「結束」那一段關閉。')
    PUBLIC_URL = None
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
if 'tunnel' in STEPS and PUBLIC_URL:
    print('👉 用瀏覽器打開：', PUBLIC_URL)
    print(f'   帳號 {DEMO_USER} / 密碼 {DEMO_PASS}')
    print('   ※ 若顯示「無法連上這個網站」：等 30 秒後重新整理；仍不行，在 Windows 命令提示字元執行')
    print('     ipconfig /flushdns 再重新整理（電腦記住了「查不到」的結果）')
    print('   ※ 每次重跑都會換新網址，舊網址會失效')
elif 'backend' in STEPS and not USE_TUNNEL:
    print('後端在 port 8000 執行中（瀏覽器版 Colab 可執行第 3 段在下方顯示網頁）')
