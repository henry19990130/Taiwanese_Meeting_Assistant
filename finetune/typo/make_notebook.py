"""產生 finetune_typo.ipynb（改 notebook 內容請改這支，再重新產生）。"""
import json
from pathlib import Path

SCRIPTS = ["ft_common.py", "lm_utils.py", "build_asr_data.py", "build_sft.py", "eval_typo.py", "train_lora.py", "export_ollama.py", "compare.py"]
EMBED = {n: Path(n).read_text(encoding="utf-8") for n in SCRIPTS}

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n")})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n")})


md("""
# 覓聲 MeetSum — 錯字校正 LoRA 微調（國語＋英文）

**做什麼**：讓 Qwen3.8-27B 更會抓語音辨識造成的同音／近音錯字。原本的 `qwen3.8:27b` 完全不動，
微調結果另存成 Ollama 模型 `qwen3.8-27b-typo`，評分比原版好才會接進系統。

**資料**：AISHELL-4（國語真實會議）、AMI（英文真實會議）用專案自己的 ASR 辨識，
和人工逐字稿比對出的同音錯字當標準答案；另加規則式同音字注入。沒有用任何大型語言模型產生答案。

**用法**：執行階段選 GPU（96 GB）→ 從上到下依序執行。每一步的結果都存在雲端硬碟 `MeetSum_finetune/`，
Colab 斷線後重新連線、從頭再按一次即可，做過的步驟會自動跳過。

⚠️ 全程約 6–8 小時，請保持這個分頁開著、電腦不要睡眠。
""")

code(r"""
# 0. 設定與檢查
import os, subprocess, sys, shutil, json, glob, time
BASE_TAG = 'qwen3.8:27b'                               # 正式系統用的 Ollama 模型
FT_TAG = 'qwen3.8-27b-typo'                            # 微調後的 Ollama 模型名稱
BASE_HF = 'Qwen/Qwen3.8-27B'                           # 訓練用的原始權重
BASE_HF_DIR = '/content/hf/Qwen3.8-27B'
SCALE = 1.0                                            # 會議數量倍率；想先試跑一小輪改成 0.1

try:
    from google.colab import drive
    if not os.path.isdir('/content/drive/MyDrive'):
        drive.mount('/content/drive')
    WORK = '/content/drive/MyDrive/MeetSum_finetune'   # 結果存雲端硬碟，斷線不會不見
except Exception as e:
    print('⚠️ 無法掛載雲端硬碟（', type(e).__name__, e, '）→ 結果先存在 Colab 本機，斷線會消失')
    WORK = '/content/MeetSum_finetune'
for d in ['data', 'results', 'run1', 'export', 'logs', 'code_override']:
    os.makedirs(f'{WORK}/{d}', exist_ok=True)
print('結果資料夾：', WORK)
DATA = f'{WORK}/data2'      # v2：單一麥克風聲道（v1 的 data/ 是 8 聲道平均，辨識太差，不使用）
os.makedirs(DATA, exist_ok=True)
print(subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv'], capture_output=True, text=True).stdout)
print('磁碟剩餘', shutil.disk_usage('/content').free // 2**30, 'GB')
GPU_GB = int(subprocess.run(['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
                            capture_output=True, text=True).stdout.split()[0]) // 1024

def run(cmd, log_name=None, env=None):
    # 執行指令，即時印出，並另存 log。執行前先套用雲端硬碟 code_override/ 裡的修正版程式（遠端修 bug 用）
    for f in glob.glob(f'{WORK}/code_override/*.py'):
        shutil.copy(f, f'{FT}/{os.path.basename(f)}')
        print('套用修正版：', os.path.basename(f))
    print('$', ' '.join(cmd), flush=True)
    logf = open(f'{WORK}/logs/{log_name}.log', 'a', encoding='utf-8') if log_name else None
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                         env={**os.environ, **(env or {})})
    try:
        for line in p.stdout:
            if 'it/s]' in line or 's/it]' in line:
                print(line.rstrip()[-160:], end='\r', flush=True)
            else:
                print(line, end='', flush=True)
            if logf:
                logf.write(line); logf.flush()
        p.wait()
    except KeyboardInterrupt:      # 按「中斷」時連子程序一起停掉，不留在背景占用 GPU
        p.kill(); p.wait()
        raise
    if p.returncode != 0:
        raise RuntimeError(f'失敗（exit {p.returncode}），詳見 {WORK}/logs/{log_name}.log')

def done(path):
    return os.path.exists(path)

# 停掉上一次中斷後可能殘留在背景的子程序
subprocess.run(['pkill', '-f', 'ft_typo/(build_asr_data|build_sft|eval_typo|train_lora|export_ollama).py'])

# 微調程式直接內嵌在 notebook 裡，寫到 /content/ft_typo（不依賴雲端硬碟同步）
FT = '/content/ft_typo'
os.makedirs(FT, exist_ok=True)
EMBED = __EMBED__
for name, src in EMBED.items():
    open(f'{FT}/{name}', 'w', encoding='utf-8').write(src)
print('微調程式：', ', '.join(EMBED))
""".replace("__EMBED__", repr(EMBED)))

md("## 1. 準備專案與正式環境（Ollama＋qwen3.8:27b＋ASR 模型）\n沿用 `run_all.py`，和平常 demo 的環境完全相同。")

code(r"""
NAMES = ('Taiwanese_Meeting_Assistant', 'test2')
REPO = 'https://github.com/henry19990130/Taiwanese_Meeting_Assistant.git'
cands = []
for n in NAMES if os.path.isdir('/content/drive') else []:
    pats = ['/content/drive/MyDrive/' + '*/' * d + n + '/run_all.py' for d in range(0, 3)]
    pats += ['/content/drive/Othercomputers/' + '*/' * d + n + '/run_all.py' for d in range(1, 5)]
    cands += [p for pat in pats for p in glob.glob(pat)]
if cands:
    RUN_ALL_SOURCE = os.path.dirname(max(set(cands), key=os.path.getmtime))
else:
    RUN_ALL_SOURCE = '/content/_src_github'
    if not os.path.isdir(RUN_ALL_SOURCE):
        subprocess.run(['git', 'clone', '-q', '--depth', '1', REPO, RUN_ALL_SOURCE], check=True)
print('專案來源：', RUN_ALL_SOURCE)
RUN_STEPS = {'sync', 'setup'}
exec(open(os.path.join(RUN_ALL_SOURCE, 'run_all.py'), encoding='utf-8').read())
PROJECT = '/content/Taiwanese_Meeting_Assistant'
os.environ['PROJECT_BACKEND'] = f'{PROJECT}/backend'
assert os.path.exists(f'{PROJECT}/backend/app/services/typo_service.py'), '專案程式沒有複製成功'
run([sys.executable, '-m', 'pip', 'install', '-q', 'pypinyin', 'jieba', 'jellyfish', 'pronouncing', 'opencc-python-reimplemented', 'librosa'])
""")

md("## 2. 產生資料：公開會議錄音 → 專案 ASR 辨識 → 和人工逐字稿比對\n約 40–70 分鐘。中斷後重跑會從還沒做的會議繼續。")

code(r"""
if not done(f'{DATA}/.asr_done'):
    run([sys.executable, f'{FT}/build_asr_data.py', '--out', DATA, '--scale', str(SCALE)], 'build_asr')
    open(f'{DATA}/.asr_done', 'w').close()
run([sys.executable, f'{FT}/build_sft.py', '--data', DATA], 'build_sft')
print(open(f'{DATA}/stats.json', encoding='utf-8').read())
""")

md("## 3. 原版 qwen3.8:27b 的基準分數（走正式系統的 Ollama 呼叫）")

code(r"""
if not done(f'{WORK}/results/base_ollama.json'):
    run([sys.executable, f'{FT}/eval_typo.py', '--data', DATA, '--backend', 'ollama', '--model', BASE_TAG,
         '--name', 'base_ollama', '--out', f'{WORK}/results'], 'eval_base')
r = json.load(open(f'{WORK}/results/base_ollama.json', encoding='utf-8'))
for k in ['zh', 'en']:
    if k in r: print(k, {x: r[k][x] for x in ['precision', 'recall', 'f0.5', 'false_alarm_rate_on_clean_chunks', 'error_rate']})
""")

md("## 4. 下載原始權重並訓練 LoRA\n訓練前先讓 Ollama 釋放顯示卡記憶體。checkpoint 存在雲端硬碟，斷線後重跑會接續。約 3–5 小時。")

code(r"""
subprocess.run('ollama ps | tail -n +2 | awk \'{print $1}\' | xargs -r -n1 ollama stop', shell=True)
run([sys.executable, '-m', 'pip', 'install', '-q', '-U', 'transformers', 'peft', 'accelerate', 'bitsandbytes'], 'pip_train')
r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'flash-linear-attention', 'causal-conv1d'], capture_output=True, text=True)
print('線性注意力加速套件：', '已安裝' if r.returncode == 0 else '安裝失敗，改用較慢的版本（結果相同）')
if not done(f'{WORK}/run1/final/adapter_model.safetensors'):
    if not done(f'{BASE_HF_DIR}/model.safetensors.index.json'):
        from huggingface_hub import snapshot_download
        snapshot_download(BASE_HF, local_dir=BASE_HF_DIR, max_workers=16)
    args = [sys.executable, f'{FT}/train_lora.py', '--base', BASE_HF_DIR, '--data', DATA, '--out', f'{WORK}/run1']
    if done(f'{WORK}/run1/.use_4bit'):
        args.append('--load-4bit')
    try:
        run(args, 'train')
    except RuntimeError:
        log = open(f'{WORK}/logs/train.log', encoding='utf-8').read()[-5000:]
        if 'out of memory' in log.lower() and '--load-4bit' not in args:
            print('⚠️ 顯示卡記憶體不夠（', GPU_GB, 'GB ）→ 改用 QLoRA（4-bit 載入原始權重）重新訓練')
            open(f'{WORK}/run1/.use_4bit', 'w').close()
            shutil.rmtree(f'{WORK}/run1/checkpoints', ignore_errors=True)
            run(args + ['--load-4bit'], 'train')
        else:
            raise
print(open(f'{WORK}/run1/train_args.json').read())
""")

md("## 5. 轉成 Ollama 模型 `qwen3.8-27b-typo`（原版不動）")

code(r"""
if not done(f'{WORK}/export/ollama_model.json'):
    if not done(f'{BASE_HF_DIR}/model.safetensors.index.json'):
        from huggingface_hub import snapshot_download
        snapshot_download(BASE_HF, local_dir=BASE_HF_DIR, max_workers=16)
    run([sys.executable, f'{FT}/export_ollama.py', '--base-hf', BASE_HF_DIR, '--adapter', f'{WORK}/run1/final',
         '--data', DATA, '--base-tag', BASE_TAG, '--name', FT_TAG, '--save', f'{WORK}/export'], 'export')
else:
    info = json.load(open(f'{WORK}/export/ollama_model.json', encoding='utf-8'))
    open(f'{WORK}/export/Modelfile', 'w').write(info['modelfile'])
    subprocess.run(['ollama', 'create', FT_TAG, '-f', 'Modelfile'], cwd=f'{WORK}/export', check=True)
print(subprocess.run(['ollama', 'list'], capture_output=True, text=True).stdout)
""")

md("## 6. 微調版的分數，和原版比較")

code(r"""
if not done(f'{WORK}/results/ft_ollama.json'):
    run([sys.executable, f'{FT}/eval_typo.py', '--data', DATA, '--backend', 'ollama', '--model', FT_TAG,
         '--name', 'ft_ollama', '--out', f'{WORK}/results'], 'eval_ft')
run([sys.executable, f'{FT}/compare.py', '--results', f'{WORK}/results', '--out', f'{WORK}/results/report.md'], 'compare')
print(open(f'{WORK}/results/report.md', encoding='utf-8').read())
""")

nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "G4"},
                                    "kernelspec": {"display_name": "Python 3", "name": "python3"},
                                    "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 0}
json.dump(nb, open("finetune_typo_v2.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已產生 finetune_typo_v2.ipynb，共", len(cells), "格")
