"""摘要微調：產生輸入、驗證我寫的摘要。"""
import json, sys, re
sys.path.insert(0, '/mnt/user-data/uploads/Taiwanese_Meeting_Assistant/backend')
from app.services.summary_prompt import build_user_message, OUTPUT_EXAMPLE
D = '/mnt/user-data/uploads/MeetSum_finetune/data2'

def meetings():
    out = {}
    for lang in ['zh', 'en']:
        for split in ['train', 'dev', 'test']:
            for line in open(f'{D}/meetings_{lang}_{split}.jsonl', encoding='utf-8'):
                m = json.loads(line); m['split'] = split; out[m['meeting_id']] = m
    return out

def transcript(m, max_segs=None):
    segs = m['segments'][:max_segs] if max_segs else m['segments']
    return {"segments": [{"segment_id": s['segment_id'], "start_ms": int(s['start']*1000), "end_ms": int(s['end']*1000),
                          "text": s['ref'] if m['lang'] == 'zh' else s['ref'].lower().capitalize()} for s in segs]}

KEYS = {"headline", "meeting_content", "review_notes"}
MC = {"reports", "discussions", "decisions", "action_items", "next_meeting"}

def validate(mid, path, max_segs=None):
    m = meetings()[mid]; t = transcript(m, max_segs)
    text = {s['segment_id']: s['text'] for s in t['segments']}
    j = json.load(open(path, encoding='utf-8'))
    errs = []
    if set(j) != KEYS: errs.append(f'top keys {set(j)}')
    mc = j.get('meeting_content', {})
    if set(mc) != MC: errs.append(f'mc keys {set(mc)}')
    ids = set()
    for cat in ['reports', 'discussions', 'decisions', 'action_items']:
        for it in mc.get(cat, []):
            ids.add(it['id'])
            if not it.get('evidence'): errs.append(f"{it['id']} no evidence")
            for e in it.get('evidence', []):
                if e['segment_id'] not in text: errs.append(f"{it['id']} bad sid {e['segment_id']}")
                elif e['quote'] not in text[e['segment_id']]: errs.append(f"{it['id']} quote not in {e['segment_id']}: {e['quote'][:20]}")
    for cat in ['decisions', 'action_items']:
        for it in mc.get(cat, []):
            for r in it.get('related_ids', []):
                if r not in ids: errs.append(f"{it['id']} bad related {r}")
    return errs

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'show':
        mid = sys.argv[2]; n = int(sys.argv[3]) if len(sys.argv) > 3 else None
        print(build_user_message(transcript(meetings()[mid], n)))
    elif cmd == 'check':
        mid = sys.argv[2]; n = int(sys.argv[3]) if len(sys.argv) > 3 else None
        e = validate(mid, f"targets/{mid}.json", n); print("OK" if not e else e)
    elif cmd == 'list':
        for k, m in meetings().items():
            print(k, m['lang'], m['split'], len(m['segments']), sum(len(s['ref']) for s in m['segments']))
