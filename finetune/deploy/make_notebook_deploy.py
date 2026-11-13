"""產生 deploy_summary_ollama.ipynb：把摘要 LoRA 合併進 Qwen3.8-27B → 匯入 Ollama → 用正式系統的呼叫方式實測。"""
import base64
import gzip
import json
from pathlib import Path

H = Path(__file__).resolve().parent
EMBED = {n: (H / n).read_text(encoding="utf-8") for n in ["merge_lora.py", "ollama_eval.py", "eval_sum.py", "lm_utils.py", "train_lora.py"]}
DATA = {n: base64.b64encode(gzip.compress((H / n).read_bytes())).decode() for n in ["sft_train.jsonl", "sft_dev.jsonl"]}
TEST = base64.b64encode(gzip.compress((H / "test8.jsonl").read_bytes())).decode()
HF_REPORT = (H / "hf_sum_report.json").read_text(encoding="utf-8")

cells = []
md = lambda s: cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip()})
code = lambda s: cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip()})

md("""
# 覓聲 MeetSum — 把摘要微調版放進 Ollama
1. 下載原始權重 → 2. 重新訓練摘要 LoRA（和上次相同的資料與設定，約 31 分）→ 3. 把 LoRA 加回原始權重 → 4. 匯入 Ollama（模型名稱 `meetsum-summary`）
→ 5. 用覓聲正式的呼叫方式（/api/chat、format=json）比較原版與微調版 → 6. 下載結果。不需要雲端硬碟。原版 qwen3.8:27b 不動。
""")
code(r'''
# 0. 環境：程式與測試資料都內嵌在 notebook 裡；安裝並啟動 Ollama，背景下載 qwen3.8:27b
import os, sys, json, gzip, base64, subprocess, shutil, time, glob, hashlib
W = '/content/deploy'; os.makedirs(W, exist_ok=True)
for n, s in __EMBED__.items():
    open(f'{W}/{n}', 'w', encoding='utf-8').write(s)
os.makedirs(f'{W}/data', exist_ok=True)
for n, b in __DATA__.items():
    open(f'{W}/data/{n}', 'wb').write(gzip.decompress(base64.b64decode(b)))
open(f'{W}/test8.jsonl', 'wb').write(gzip.decompress(base64.b64decode(__TEST__)))
open(f'{W}/hf_sum_report.json', 'w', encoding='utf-8').write(__HF__)
print('測試會議', sum(1 for _ in open(f'{W}/test8.jsonl', encoding='utf-8')), '場')
print(subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv'], capture_output=True, text=True).stdout)
def sh(cmd, check=True):
    print('$', cmd, flush=True)
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in p.stdout:
        print(line, end='', flush=True)
    p.wait()
    if check and p.returncode != 0:
        raise RuntimeError(f'失敗 exit {p.returncode}: {cmd}')
    return p.returncode
if shutil.which('ollama') is None:
    sh('apt-get install -y -qq zstd pciutils lshw > /content/apt.log 2>&1', check=False)
    sh('curl -fsSL https://ollama.com/install.sh | sh > /content/ollama_install.log 2>&1 || (tail -20 /content/ollama_install.log; false)')
sh(f'{sys.executable} -m pip uninstall -y -q torchao', check=False)
sh(f'{sys.executable} -m pip install -q -U transformers peft accelerate bitsandbytes flash-linear-attention', check=False)
os.environ['OLLAMA_KEEP_ALIVE'] = '24h'
if subprocess.run('curl -sf http://127.0.0.1:11434/api/version', shell=True).returncode != 0:
    subprocess.Popen('nohup ollama serve > /content/ollama.log 2>&1 &', shell=True)
    time.sleep(5)
print(subprocess.run('ollama --version', shell=True, capture_output=True, text=True).stdout)
PULL = subprocess.Popen('ollama pull qwen3.8:27b > /content/ollama_pull.log 2>&1', shell=True)
print('qwen3.8:27b 背景下載中')
''')
code(r'''
# 1. 下載原始權重（約 54GB）
BASE = '/content/hf/Qwen3.8-27B'
if not os.path.exists(f'{BASE}/model.safetensors.index.json'):
    from huggingface_hub import snapshot_download
    snapshot_download('Qwen/Qwen3.8-27B', local_dir=BASE, max_workers=16)
print('完成', sh(f'du -sh {BASE}', check=False))
''')
code(r'''
# 2. 重新訓練摘要 LoRA（和上次完全相同的資料與設定；只算回答段的 loss，顯示卡記憶體峰值約 52GB）
ADAPTER = f'{W}/run/final'
if not os.path.exists(f'{ADAPTER}/adapter_model.safetensors'):
    sh(f'{sys.executable} {W}/train_lora.py --base {BASE} --data {W}/data --out {W}/run --max-len 16384 --load-4bit '
       f'--epochs 3 --grad-accum 4 --save-steps 5 --dev-limit 3 --max-train 0')
print(open(f'{W}/run/train_args.json').read())
''')
code(r'''
# 3. 把 LoRA 加回原始權重（檔名、張量名稱、格式和官方完全一樣）
MERGED = '/content/merged'
if not os.path.exists(f'{MERGED}/model.safetensors.index.json'):
    sh(f'{sys.executable} {W}/merge_lora.py --base {BASE} --adapter {ADAPTER} --out {MERGED}')
sh(f'du -sh {MERGED}; df -h /content | tail -1', check=False)
''')
code(r'''
# 4. 匯入 Ollama（模型名稱 meetsum-summary）：沿用原版的 Modelfile（對話樣板、參數），只換掉權重
NAME = 'meetsum-summary'
PULL.wait()
print('下載結果：', (open('/content/ollama_pull.log', errors='replace').read()[-300:].replace('\r', '\n').strip().splitlines() or [''])[-1], '（exit', PULL.returncode, '）')
show = subprocess.run('ollama show qwen3.8:27b', shell=True, capture_output=True, text=True).stdout
print(show)
import re
q = (re.search(r'quantization\s+(\S+)', show) or [None, 'Q4_K_M'])[1]
QUANT = {'Q4_K_M': 'q4_K_M', 'Q4_K_S': 'q4_K_S', 'Q8_0': 'q8_0'}.get(q.upper(), 'q4_K_M')
base_mf = subprocess.run('ollama show qwen3.8:27b --modelfile', shell=True, capture_output=True, text=True).stdout
def quick_test(model):
    import requests
    r = requests.post('http://127.0.0.1:11434/api/chat', json={'model': model, 'stream': False, 'format': 'json', 'think': False,
        'messages': [{'role': 'user', 'content': '用 JSON 回答：{"ok": true, "word": "測試"}'}], 'options': {'temperature': 0}}, timeout=900)
    print('快速測試', model, r.status_code, r.text[:300])
    return r.status_code == 200 and '"ok"' in r.text
def make(from_path):
    mf = re.sub(r'^FROM .*$', f'FROM {from_path}', base_mf, count=1, flags=re.M)
    mf = re.sub(r'^ADAPTER .*$\n?', '', mf, flags=re.M)
    open(f'{W}/Modelfile', 'w').write(mf)
    return sh(f'cd {W} && ollama create {NAME} --quantize {QUANT} -f Modelfile', check=False) == 0
ROUTE = None
# 做法 A：讓 Ollama 自己讀合併好的 safetensors 並量化成和原版相同的格式
if make(MERGED) and quick_test(NAME):
    ROUTE = 'A'
else:
    print('--- 做法 A 沒成功，Ollama 紀錄最後 60 行 ---')
    print(''.join(open('/content/ollama.log', errors='replace').readlines()[-60:]))
    # 做法 B：llama.cpp 轉 GGUF（bf16）→ 量化 → 匯入
    LC = '/content/llama.cpp'
    if not os.path.exists(LC):
        sh(f'git clone -q --depth 1 https://github.com/ggml-org/llama.cpp {LC}')
    sh(f'{sys.executable} -m pip install -q -r {LC}/requirements/requirements-convert_hf_to_gguf.txt', check=False)
    sh(f'cd {LC} && cmake -B build -DGGML_CUDA=OFF -DLLAMA_CURL=OFF > /dev/null && cmake --build build --target llama-quantize -j 12 > /dev/null')
    sh(f'{sys.executable} {LC}/convert_hf_to_gguf.py {MERGED} --outfile /content/merged-bf16.gguf --outtype bf16')
    sh(f'{LC}/build/bin/llama-quantize /content/merged-bf16.gguf /content/meetsum-summary-{q}.gguf {q.upper()}')
    os.remove('/content/merged-bf16.gguf')
    if make(f'/content/meetsum-summary-{q}.gguf') and quick_test(NAME):
        ROUTE = 'B'
if ROUTE is None:
    print(''.join(open('/content/ollama.log', errors='replace').readlines()[-80:]))
    raise RuntimeError('兩種做法都沒辦法讓 Ollama 正常執行，請看上面的紀錄')
print('✅ 匯入成功，做法', ROUTE, '，量化格式', QUANT)
sh('ollama list', check=False)
''')
code(r'''
# 5. 用覓聲正式的呼叫方式實測（8 場：中文 5、英文 3）
#    原版 = qwen3.8:27b + 思考模式（目前 .env 的設定）；微調版 = meetsum-summary + 不思考（訓練時的設定）
EV = f'{W}/eval'
sh(f'{sys.executable} {W}/ollama_eval.py --data {W}/test8.jsonl --model {NAME} --tag ft_ollama --think false --out {EV}')
sh('ollama stop meetsum-summary', check=False)
sh(f'{sys.executable} {W}/ollama_eval.py --data {W}/test8.jsonl --model qwen3.8:27b --tag base_ollama --think true --out {EV}')
B = json.load(open(f'{EV}/base_ollama.report.json')); F = json.load(open(f'{EV}/ft_ollama.report.json'))
HF = json.load(open(f'{W}/hf_sum_report.json'))
names = {'json_ok': 'JSON 合法', 'quote_ok': '引用正確', 'count_diff': '項目數差距（越小越好）', 'topic_f1': '議題吻合',
         'action_f1': '待辦吻合', 'text_sim': '文字相似度', 'headline_sim': '一句話總結相似度'}
for grp in ['all', 'zh', 'en']:
    print(f'\n== {grp}（{B[grp]["n"]} 場）       原版Ollama  微調Ollama  （參考：微調HF）')
    for k, label in names.items():
        print(f'{label:<14} {B[grp][k]!s:>10} {F[grp][k]!s:>10}   {HF["ft"][grp][k]!s:>8}')
print('\n平均每場秒數：原版', B['avg_secs'], '／微調版', F['avg_secs'])
''')
code(r'''
# 6. 結果打包下載（Ollama 模型檔太大，留在這台主機；要長期保存再另外處理）
import zipfile
mf = subprocess.run(f'ollama show {NAME} --modelfile', shell=True, capture_output=True, text=True).stdout
open(f'{EV}/Modelfile.txt', 'w').write(mf)
Z = '/content/meetsum_summary_ollama_eval.zip'
with zipfile.ZipFile(Z, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in glob.glob(f'{EV}/*'):
        z.write(f, os.path.basename(f))
    for f in [f'{W}/run/train_log.json', f'{W}/run/train_args.json', f'{ADAPTER}/adapter_config.json']:
        if os.path.exists(f):
            z.write(f, 'run/' + os.path.basename(f))
print('===REPORT_BASE==='); print(json.dumps(B, ensure_ascii=False))
print('===REPORT_FT==='); print(json.dumps(F, ensure_ascii=False))
print('===END===')
from google.colab import files
files.download(Z)
''')
code(r'''
# 7. 關機（確認上面都完成之後才執行）
from google.colab import runtime
runtime.unassign()
''')

src = json.dumps(EMBED, ensure_ascii=False)
for c in cells:
    if c["cell_type"] == "code":
        c["source"] = c["source"].replace("__EMBED__", repr(EMBED)).replace("__TEST__", repr(TEST)).replace("__HF__", repr(HF_REPORT)).replace("__DATA__", repr(DATA))
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"gpuType": "A100", "machine_shape": "hm"},
      "kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 0}
(H / "deploy_summary_ollama.ipynb").write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print("寫出", H / "deploy_summary_ollama.ipynb")
