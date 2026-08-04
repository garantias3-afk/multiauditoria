"""CORRIDA VIVA — Slot 1 Live Dispatch with Exception Instrumentation (v2)
Shorter timeouts, per-dispatch flush, lower token budget.
"""
import sys, os, json, time, uuid, urllib.request, urllib.error, urllib.parse, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scripts.exception_taxonomy import classify_from_signal, CLASSES, UNMAPPED

# Load .env manually
env_map = {}
with open('/Users/mariano/Shared/.env', 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, _, v = line.partition('=')
            env_map[k.strip()] = v.strip()
os.environ.update(env_map)

# Artifact
with open(ROOT / "scripts" / "exception_taxonomy.py", 'r') as f:
    ART = f.read()
print("Artifact: exception_taxonomy.py ({} bytes)".format(len(ART.encode())), flush=True)

PROMPT = "Audit this Python file for bugs, exception handling issues, and technical debt. Respond in JSON: {\"veredict\":\"clean|debt\",\"summary\":\"...\"}\n\n"
FULL_MSG = PROMPT + ART

OUT_DIR = Path('/Users/mariano/Intercambio/CORRIDA_VIVA_2026-08-02')
jsonl_path = OUT_DIR / 'exceptions_vivo.jsonl'
dispatch_path = OUT_DIR / 'dispatch_log.json'
commands_path = OUT_DIR / 'COMMANDS_RUN.txt'

ROUTES = [
    ('gemini_aistudio_3_5_flash', 'gemini', 'gemini-3.5-flash'),
    ('vertex_gemini_2_5_pro', 'vertex_adc', 'gemini-2.5-pro'),
    ('deepseek_v4_flash', 'deepseek', 'deepseek-v4-flash'),
    ('openrouter_nemotron_free', 'openrouter', 'nvidia/nemotron-3-ultra-550b-a55b:free'),
    ('openrouter_gemma_4_26b_free', 'openrouter', 'google/gemma-4-26b-a4b-it:free'),
    ('openrouter_nemotron_nano_omni_30b_free', 'openrouter', 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free'),
    ('nvidia_nemotron_ultra_direct', 'nvidia', 'nvidia/nemotron-3-ultra-550b-a55b'),
]

exc_records = []
dispatch_records = []
cmd_lines = []
TIMEOUT = 30

def do_req(url, body_dict, headers, timeout=TIMEOUT):
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            elapsed = int((time.time() - start) * 1000)
            return {'ok': True, 'http': resp.status, 'latency_ms': elapsed,
                    'model': data.get('model', data.get('modelVersion', ''))}
    except urllib.error.HTTPError as e:
        elapsed = int((time.time() - start) * 1000)
        return {'ok': False, 'http': e.code, 'latency_ms': elapsed,
                'error': e.read().decode('utf-8', 'replace')[:300]}
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        return {'ok': False, 'http': None, 'latency_ms': elapsed,
                'error': str(e)[:300]}

def flush():
    with open(jsonl_path, 'w') as f:
        for r in exc_records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with open(dispatch_path, 'w') as f:
        json.dump(dispatch_records, f, indent=2, ensure_ascii=False)
    with open(commands_path, 'w') as f:
        for line in cmd_lines:
            f.write(line + '\n')

for route_id, family, model in ROUTES:
    cmd = "python3 dispatch_slot1_vivo.py --route={} --family={}".format(route_id, family)
    cmd_lines.append(cmd)
    print("[{}] {} ... ".format(route_id, family), end='', flush=True)

    if family == 'gemini':
        kv = os.environ.get('GOOGLE_AI_STUDIO_API_KEY', '')
        mname = 'models/' + model
        url = 'https://generativelanguage.googleapis.com/v1beta/' + mname + ':generateContent?key=' + kv
        result = do_req(url,
            {'contents': [{'parts': [{'text': FULL_MSG}]}],
             'generationConfig': {'maxOutputTokens': 512, 'temperature': 0.1}},
            {'Content-Type': 'application/json'})

    elif family == 'vertex_adc':
        tok = subprocess.run(['gcloud', 'auth', 'application-default', 'print-access-token'],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        proj = env_map.get('GOOGLE_VERTEX_PROJECT', '')
        url = ('https://us-central1-aiplatform.googleapis.com/v1/projects/{}/'
               'locations/us-central1/publishers/google/models/{}:generateContent'
               .format(urllib.parse.quote(proj), urllib.parse.quote(model)))
        result = do_req(url,
            {'contents': [{'role': 'user', 'parts': [{'text': FULL_MSG}]}],
             'generationConfig': {'maxOutputTokens': 512, 'temperature': 0.1}},
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tok})

    elif family == 'openrouter':
        kv = os.environ.get('OPENROUTER_API_KEY', '')
        result = do_req('https://openrouter.ai/api/v1/chat/completions',
            {'model': model, 'messages': [{'role': 'user', 'content': FULL_MSG}],
             'max_tokens': 512, 'temperature': 0.1},
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + kv,
             'HTTP-Referer': 'https://chatgpt.local/camino-a',
             'X-Title': 'Camino A Live'})

    elif family == 'deepseek':
        kv = os.environ.get('DEEPSEEK_API_KEY', '')
        result = do_req('https://api.deepseek.com/chat/completions',
            {'model': model, 'messages': [{'role': 'user', 'content': FULL_MSG}],
             'max_tokens': 512, 'temperature': 0.1},
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + kv})

    elif family == 'nvidia':
        kv = os.environ.get('NVIDIA_API_KEY', '')
        result = do_req('https://integrate.api.nvidia.com/v1/chat/completions',
            {'model': model, 'messages': [{'role': 'user', 'content': FULL_MSG}],
             'max_tokens': 512, 'temperature': 0.1},
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + kv})
    else:
        result = {'ok': False, 'http': None, 'latency_ms': 0, 'error': 'unknown family'}

    d_entry = {'route_id': route_id, 'family': family, 'model': model,
                'ok': result.get('ok'), 'http': result.get('http'),
                'latency_ms': result.get('latency_ms')}
    dispatch_records.append(d_entry)

    if result.get('ok'):
        print("OK http={} lat={}ms".format(result['http'], result['latency_ms']), flush=True)
    else:
        http_s = str(result.get('http') or 'None')
        print("FAIL http={} lat={}ms".format(http_s, result.get('latency_ms')), flush=True)
        err = result.get('error', '')
        http_code = result.get('http')
        signal = 'http_{}'.format(http_code) if http_code else err[:200]
        cls = classify_from_signal(signal, fase='despacho')
        reg = {
            'clase': cls.clase,
            'exception_id': str(uuid.uuid4()),
            'excerpt': err[:512],
            'excerpt_bytes': min(len(err.encode('utf-8')), 512),
            'expected': 'la invocacion del proveedor devuelve (ok, contenido)',
            'fase': 'despacho',
            'found': 'NO_CONSTA',
            'handler_tried': '',
            'puesto': 'auditores',
            'raw_condition': cls.raw_condition,
            'resolution': 'NONE',
            'route_id': route_id,
            'slot': '1',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        exc_records.append(reg)
        print("  -> clase={} raw={}".format(
            cls.clase, cls.raw_condition[:60] if cls.raw_condition else '-'), flush=True)

    flush()
    time.sleep(0.3)

ok_n = sum(1 for d in dispatch_records if d['ok'])
print("\nSUMMARY: {}/{} OK, {}/{} FAIL".format(
    ok_n, len(dispatch_records), len(dispatch_records) - ok_n, len(dispatch_records)), flush=True)
if exc_records:
    ccounts = {}
    for r in exc_records:
        ccounts[r['clase']] = ccounts.get(r['clase'], 0) + 1
    print("Exception classes observed:", flush=True)
    for c in sorted(ccounts):
        print("  {}: {}".format(c, ccounts[c]), flush=True)
else:
    print("No exceptions observed in this dispatch.", flush=True)
print("DONE", flush=True)
