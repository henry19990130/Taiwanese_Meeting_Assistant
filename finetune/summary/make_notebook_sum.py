"""產生 finetune_summary.ipynb：程式與訓練資料全部內嵌，不依賴雲端硬碟。"""
import base64
import gzip
import json
from pathlib import Path

H = Path(__file__).resolve().parent
TYPO = H.parent / "typo"
FILES = {"lm_utils.py": TYPO / "lm_utils.py", "train_lora.py": TYPO / "train_lora.py", "eval_sum.py": H / "eval_sum.py"}
EMBED = {k: v.read_text(encoding="utf-8") for k, v in FILES.items()}
DATA = {n: base64.b64encode(gzip.compress((H / "data" / n).read_bytes())).decode()
        for n in ["sft_train.jsonl", "sft_dev.jsonl", "sft_test.jsonl"]}

cells = []
md = lambda s: cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip()})
code = lambda s: cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip()})

md("""
# 覓聲 MeetSum — 重點摘要 LoRA 微調
訓練答案 = Claude 依覓聲摘要規則寫的會議摘要。原版 qwen3.8:27b 不動。
從上到下依序執行；最後一格「關機」請確認結果都看到了再執行。
""")
code(r'''
# 0. 環境與檔案（程式、訓練資料都內嵌在 notebook 裡）
import os, sys, json, gzip, base64, subprocess, shutil
W = '/content/sum_ft'; os.makedirs(f'{W}/data', exist_ok=True); os.makedirs(f'{W}/out', exist_ok=True)
for n, s in __EMBED__.items():
    open(f'{W}/{n}', 'w', encoding='utf-8').write(s)
for n, b in __DATA__.items():
    open(f'{W}/data/{n}', 'wb').write(gzip.decompress(base64.b64decode(b)))
for n in ['sft_train.jsonl', 'sft_dev.jsonl', 'sft_test.jsonl']:
    print(n, sum(1 for _ in open(f'{W}/data/{n}', encoding='utf-8')), '筆')
print(subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv'], capture_output=True, text=True).stdout)
GPU_GB = int(subprocess.run(['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader,nounits'], capture_output=True, text=True).stdout.split()[0]) // 1024
subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', '-q', 'torchao'])
r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-U', 'transformers', 'peft', 'accelerate', 'bitsandbytes', 'flash-linear-attention'], capture_output=True, text=True)
print('套件安裝', '完成' if r.returncode == 0 else r.stderr[-2000:])
def run(cmd):
    print('$', ' '.join(cmd), flush=True)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        for line in p.stdout:
            print(line, end='', flush=True)
        p.wait()
    except KeyboardInterrupt:
        p.kill(); p.wait(); raise
    if p.returncode != 0:
        raise RuntimeError(f'失敗 exit {p.returncode}')
'''.replace("__EMBED__", repr(EMBED)).replace("__DATA__", repr(DATA)))
code(r'''
# 1. 下載原始權重（約 54GB，20–30 分鐘）
BASE = '/content/hf/Qwen3.8-27B'
if not os.path.exists(f'{BASE}/model.safetensors.index.json'):
    from huggingface_hub import snapshot_download
    snapshot_download('Qwen/Qwen3.8-27B', local_dir=BASE, max_workers=16)
print('完成')
''')
code(r'''
# 2. 訓練 LoRA（摘要的輸入很長，用 4-bit 載入原始權重以節省顯示卡記憶體）
if not os.path.exists(f'{W}/out/run/final/adapter_model.safetensors'):
    run([sys.executable, f'{W}/train_lora.py', '--base', BASE, '--data', f'{W}/data', '--out', f'{W}/out/run',
         '--max-len', '16384', '--load-4bit', '--epochs', '3', '--grad-accum', '4', '--save-steps', '10',
         '--dev-limit', '3', '--max-train', '0'])
print(open(f'{W}/out/run/train_args.json').read())
''')
code(r'''
# 3. 評測：同一份權重，不掛 LoRA（原版）vs 掛 LoRA（微調版），和 Claude 寫的參考摘要比較
run([sys.executable, f'{W}/eval_sum.py', '--data', f'{W}/data', '--base', BASE, '--adapter', f'{W}/out/run/final',
     '--out', f'{W}/out/eval', '--batch-size', '4', '--load-4bit'])
rep = json.load(open(f'{W}/out/eval/sum_report.json', encoding='utf-8'))
names = {'json_ok': 'JSON 合法', 'quote_ok': '引用正確', 'count_diff': '項目數差距（越小越好）', 'topic_f1': '議題吻合',
         'action_f1': '待辦吻合', 'text_sim': '文字相似度', 'headline_sim': '一句話總結相似度'}
for grp in ['all', 'zh', 'en']:
    print(f'\n== {grp}（{rep["base"][grp]["n"]} 場）')
    for k, label in names.items():
        print(f'{label:<16} 原版 {rep["base"][grp][k]}   微調版 {rep["ft"][grp][k]}')
''')
code(r'''
# 4. 存檔：結果與 LoRA 盡量複製到雲端硬碟（雲端硬碟空間不夠也不影響上面已印出的結果）
try:
    from google.colab import drive
    if not os.path.isdir('/content/drive/MyDrive'):
        drive.mount('/content/drive')
    dst = '/content/drive/MyDrive/MeetSum_summary_ft'
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(f'{W}/out/eval', f'{dst}/eval', dirs_exist_ok=True)
    shutil.copytree(f'{W}/out/run/final', f'{dst}/lora_final', dirs_exist_ok=True)
    for f in ['train_log.json', 'train_args.json']:
        shutil.copy(f'{W}/out/run/{f}', dst)
    drive.flush_and_unmount()
    print('✅ 已存到雲端硬碟 MeetSum_summary_ft/')
except Exception as e:
    print('⚠️ 存雲端硬碟失敗：', e)
''')
code(r'''
# 5. 關機（確認上面結果都看到之後才執行）
from google.colab import runtime
runtime.unassign()
''')

nb = {"cells": cells, "metadata": {"accelerator": "GPU", "kernelspec": {"display_name": "Python 3", "name": "python3"},
                                    "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 0}
json.dump(nb, open(H / "finetune_summary.ipynb", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已產生 finetune_summary.ipynb", round((H / "finetune_summary.ipynb").stat().st_size / 1e6, 2), "MB")
