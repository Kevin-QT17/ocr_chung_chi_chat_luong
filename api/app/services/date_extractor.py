"""Run 7D date extraction rules for certificate/recognition documents.

Returns issue_date, valid_from, expiry_date, decision_date in ISO YYYY-MM-DD,
plus heuristic confidence and evidence text. Rules are intentionally conservative
and exclude generic laboratory/test-report dates.
"""
import re
from datetime import date
from dateutil.relativedelta import relativedelta
from unidecode import unidecode

DATE_FIELDS=['issue_date','valid_from','expiry_date','decision_date']
GT_FIELDS=['gt_issue_date','gt_valid_from','gt_expiry_date','gt_decision_date']

# Common OCR-normalization for relevant date keywords.
def norm(s):
    s = unidecode(str(s or '')).lower()
    s = s.replace('|',' ')
    # OCR often reads digit 1 as [ or ] inside dates.
    s = re.sub(r'(?<=\d)[\[\]](?=\s*(?:thang|[./-]))', '1', s)
    s = re.sub(r'(?<=\bthang\s)[\[\]](?=\d)', '1', s)
    # character-level common OCR variants in words handled by token substitutions below
    s = re.sub(r'\s+', ' ', s)
    # token aliases (safe only as standalone-ish words)
    reps = {
        r'\bng[od][yy]\b':'ngay', r'\bngdy\b':'ngay', r'\bngoy\b':'ngay', r'\bng[a@]y\b':'ngay',
        r'\bthong\b':'thang', r'\bthhng\b':'thang', r'\bihang\b':'thang', r'\bthung\b':'thang', r'\bthong\b':'thang',
        r'\bndm\b':'nam', r'\bnbm\b':'nam', r'\bnfm\b':'nam', r'\bnom\b':'nam',
        r'\bdote\b':'date', r'\befccuve\b':'effective', r'\beffecuve\b':'effective', r'\beffective\b':'effective',
        r'\bcertficote\b':'certificate', r'\bcertificote\b':'certificate',
        r'\bquyet\s+djnh\b':'quyet dinh', r'\bquyet\s+dlnh\b':'quyet dinh',
        r'\bgia\s+iri\b':'gia tri', r'\bgia\s+uri\b':'gia tri', r'\bgia\s+ti\b':'gia tri', r'\bgid\s+tri\b':'gia tri', r'\bcogia\b':'co gia', r'\bc6\s+gia\b':'co gia',
        r'\bketu\b':'ke tu', r'\bketir\b':'ke tu', r'\btir\b':'tu',
        r'\bngoy\b':'ngay', r'\b0l\b':'01',
    }
    for a,b in reps.items(): s=re.sub(a,b,s)
    s=re.sub(r'\s+',' ',s).strip()
    s=re.sub(r'\bco\s+gia\s+(?:iri|uri|ti)\b','co gia tri',s)
    return s

def valid_date(y,m,d):
    try: return date(int(y),int(m),int(d))
    except: return None

def iso(d): return d.isoformat() if d else None

# Parse date-like occurrences from normalized OCR with positions.
def parse_occurrences(text):
    t=norm(text)
    occ=[]
    def add(dt,st,en,matched,kind):
        if dt and 2000 <= dt.year <= 2035:
            occ.append({'date':iso(dt),'start':st,'end':en,'matched':matched,'kind':kind})
    # Numeric dd/mm/yyyy etc
    for m in re.finditer(r'(?<!\d)([0-3]?\d)\s*[./-]\s*([01]?\d)\s*[./-]\s*((?:20)\d{2})(?!\d)', t):
        d,mo,y=map(int,m.groups()); add(valid_date(y,mo,d),m.start(),m.end(),m.group(),'numeric')
    # OCR-corrupt direct issue like 16706/2020 -> 16/06/2020 (one stray digit between day/month)
    for m in re.finditer(r'(?<!\d)([0-3]\d)\d([01]\d)\s*/\s*((?:20)\d{2})(?!\d)', t):
        d,mo,y=map(int,m.groups()); add(valid_date(y,mo,d),m.start(),m.end(),m.group(),'ocr_numeric')
    # Vietnamese textual with ngay
    for m in re.finditer(r'\bngay\s*([0-4]?\d)\s*(?:thang\s*)?([01]?\d)\s*(?:nam\s*)?((?:20)\d{2})\b', t):
        d,mo,y=map(int,m.groups())
        if d>31 and 40<=d<=49: d-=30  # 43 -> 13 observed OCR confusion
        add(valid_date(y,mo,d),m.start(),m.end(),m.group(),'vi_text')
    # variant: ngay DD thang MM nam YYYY allowing separators/noise and explicit words
    for m in re.finditer(r'\bngay\s*([0-4]?\d)\s*[^0-9a-z]{0,4}\s*thang\s*([01]?\d)\s*[^0-9a-z]{0,4}\s*nam\s*((?:20)\d{2})\b',t):
        d,mo,y=map(int,m.groups())
        if d>31 and 40<=d<=49: d-=30
        add(valid_date(y,mo,d),m.start(),m.end(),m.group(),'vi_text2')
    # no 'ngay', but DD thang MM nam YYYY in certificate/decision vicinity
    for m in re.finditer(r'(?<!\d)([0-4]?\d)\s*thang\s*([01]?\d)\s*nam\s*((?:20)\d{2})\b',t):
        d,mo,y=map(int,m.groups())
        if d>31 and 40<=d<=49: d-=30
        add(valid_date(y,mo,d),m.start(),m.end(),m.group(),'vi_text_no_ngay')
    # English Month DD YYYY / DD Month YYYY
    months={'jan':1,'january':1,'feb':2,'february':2,'mar':3,'march':3,'apr':4,'april':4,'may':5,'jun':6,'june':6,'jul':7,'july':7,'aug':8,'august':8,'sep':9,'sept':9,'september':9,'oct':10,'october':10,'nov':11,'november':11,'dec':12,'december':12}
    monpat='|'.join(sorted(months,key=len,reverse=True))
    for m in re.finditer(rf'\b({monpat})\s+([0-3]?\d)(?:st|nd|rd|th)?\s*,?\s*((?:20)\d{{2}})\b',t):
        mo=months[m.group(1)]; d=int(m.group(2)); y=int(m.group(3)); add(valid_date(y,mo,d),m.start(),m.end(),m.group(),'en_text')
    for m in re.finditer(rf'\b([0-3]?\d)(?:st|nd|rd|th)?\s+({monpat})\s*,?\s*((?:20)\d{{2}})\b',t):
        d=int(m.group(1)); mo=months[m.group(2)]; y=int(m.group(3)); add(valid_date(y,mo,d),m.start(),m.end(),m.group(),'en_text')
    # dedupe by (date, near-pos)
    occ=sorted(occ,key=lambda x:(x['start'],x['end']-x['start']))
    out=[]
    for o in occ:
        if any(abs(o['start']-q['start'])<4 and o['date']==q['date'] for q in out): continue
        out.append(o)
    return t,out

def context(t,o,left=130,right=130):
    return t[max(0,o['start']-left):min(len(t),o['end']+right)]

def nearest_occ(occ, pos, maxdist=180, prefer_after=True):
    cand=[]
    for o in occ:
        dist = o['start']-pos
        if abs(dist)<=maxdist:
            penalty=abs(dist) + (0 if (dist>=0 if prefer_after else dist<=0) else 30)
            cand.append((penalty,o))
    return min(cand,key=lambda x:x[0])[1] if cand else None

def first_date_after_phrase(t,occ,patterns,maxdist=180):
    best=None
    for pat in patterns:
        for m in re.finditer(pat,t):
            o=nearest_occ(occ,m.end(),maxdist=maxdist,prefer_after=True)
            if o:
                d=o['start']-m.end()
                if d>=-10 and (best is None or abs(d)<best[0]): best=(abs(d),o,pat)
    return best[1] if best else None

def date_near_phrase(t,occ,patterns,maxdist=170):
    best=None
    for pat in patterns:
        for m in re.finditer(pat,t):
            for o in occ:
                # distance between intervals
                dist=min(abs(o['start']-m.end()),abs(m.start()-o['end']))
                if dist<=maxdist and (best is None or dist<best[0]): best=(dist,o,pat)
    return best[1] if best else None

def add_months(date_str,months):
    y,m,d=map(int,date_str.split('-'))
    return (date(y,m,d)+relativedelta(months=months)).isoformat()

def extract(text):
    t,occ=parse_occurrences(text)
    res={k:None for k in DATE_FIELDS}
    conf={k:0.0 for k in DATE_FIELDS}
    ev={k:'' for k in DATE_FIELDS}
    flags=[]

    # Ignore laboratory report dates as certificate dates, except explicit nested certificate issue references.
    lab_report = any(x in t for x in ['test report','phieu ket qua thu nghiem','phieu ket qua kiem nghiem','ket qua thu nghiem'])

    def setv(k,o,c,e):
        if o and (res[k] is None or c>conf[k]):
            res[k]=o['date']; conf[k]=c; ev[k]=e or context(t,o)

    # Direct issue date: must be very close to explicit 'ngay cap'/issue label; don't accept lab 'date of issue' as issue.
    for pats,c in [([r'\bngay\s+cap\b',r'\bngaycap\b'],0.98),([r'\bdate\s+of\s+issue\b',r'\bissue\s+date\b'],0.95)]:
        o=date_near_phrase(t,occ,pats,100)
        if o:
            ctx=context(t,o,160,160)
            if not (lab_report and ('date of issue' in ctx or 'ngay tra ket qua' in ctx)):
                setv('issue_date',o,c,ctx)

    # Special OCR-corrupt GMP issue date if not parsed, e.g. "ngay cap: 16706/2020".
    if res['issue_date'] is None:
        m=re.search(r'ngay\s+cap\s*:?\s*([0-3]\d)\D?\d?([01]\d)\s*/\s*((?:20)\d{2})',t)
        if m:
            dt=valid_date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
            if dt:
                res['issue_date']=dt.isoformat(); conf['issue_date']=0.92; ev['issue_date']=t[max(0,m.start()-100):m.end()+100]

    # Valid-from / expiry direct pair on certificate.
    # Find occurrences around "co gia tri tu ngay" and use next two dates.
    for pat in [r'co\s+gia\s+tri\s+tu\s+ngay',r'certificate\s+is\s+valid\s+from',r'\bvalid\s+from\b']:
        for m in re.finditer(pat,t):
            after=[o for o in occ if o['start']>=m.end()-10 and o['start']<=m.end()+220]
            if after:
                setv('valid_from',after[0],0.98,context(t,after[0],160,180))
                if len(after)>=2:
                    setv('expiry_date',after[1],0.98,context(t,after[1],180,160))

    # Effective date / Ngay hieu luc.
    for pat in [r'\beffective\s+date\b',r'\bef+\w*\s+date\b',r'ngay\s+hieu\s+luc',r'ngoy\s+hieu\s+luc']:
        o=first_date_after_phrase(t,occ,[pat],100)
        if o: setv('valid_from',o,0.98,context(t,o,120,160))

    # Expiry direct labels.
    expiry_pats=[r'\bexpiry\s+date\b',r'\bexpir\w*\s+date\b',r'ngay\s+(?:ket\s+thuc|het\s+han)',r'co\s+gia\s+tri\s+(?:den|den\s+het)\s+ngay',r'giay\s+chung\s+nhan\s+co\s+gia\s+tri\s+(?:den|den\s+het)\s+ngay']
    o=first_date_after_phrase(t,occ,expiry_pats,130)
    if o: setv('expiry_date',o,0.98,context(t,o,180,120))

    # Decision date: phrase then nearby/next date.
    dec_pats=[r'quyet\s*[^a-z0-9]{0,3}\s*dinh(?:\s+so)?',r'ban\s+hanh\s+kem\s+theo\s+quyet\s+dinh']
    o=first_date_after_phrase(t,occ,dec_pats,130)
    if o:
        # Don't let a later expiry date stand in for a missing/garbled decision date.
        prior=t[max(0,o['start']-180):o['start']]
        if 'co gia tri den' not in prior and 'co gia tri' not in prior[-55:]:
            setv('decision_date',o,0.97,context(t,o,180,130))

    # Certificate / recognition context.
    cert_like = any(k in t for k in ['giay chung nhan','chung nhan','certificate','san pham ocop','ocop','san pham cong nghiep nong thon tieu bieu'])
    registration = 'giay tiep nhan dang ky ban cong bo san pham' in t or 'giay tiep nhan dang ky ban cong bo' in t

    # Location/signing date fallback on certificate/registration, excluding lab reports.
    if not lab_report:
        # date near a city/province header or before issuer/signature block
        loc_patterns=[r'(?:ha noi|quang tri|trieu phong|dong hoi)[,;]?\s*ngay',r'\bngay\s+[0-4]?\d.{0,35}(?:chu tich|bo truong|cuc truong|uy ban)']
        lo=date_near_phrase(t,occ,loc_patterns,60)
        if lo and cert_like and res['issue_date'] is None:
            setv('issue_date',lo,0.86,context(t,lo,180,180))
        if lo and registration and res['issue_date'] is None:
            setv('issue_date',lo,0.86,context(t,lo,180,180))

    # Recognition cert: decision date semantically acts as issue/signing date.
    recognition = ('ocop' in t or 'san pham cong nghiep nong thon' in t)
    if recognition and res['decision_date'] and res['issue_date'] is None:
        res['issue_date']=res['decision_date']; conf['issue_date']=0.92; ev['issue_date']='FALLBACK from decision/signing date: '+ev['decision_date']
    if recognition and res['decision_date'] is None and res['issue_date'] is not None and re.search(r'quyet\s*[^a-z0-9]{0,3}\s*dinh',t):
        res['decision_date']=res['issue_date']; conf['decision_date']=0.88; ev['decision_date']='FALLBACK from certificate signing/issue date'

    # If explicit certificate validity-to is present and we found a location/decision issue, okay.
    # Derive expiry for explicit N-month validity from signing/decision/issue date.
    dur=None
    m=re.search(r'(?:co\s+gia\s+tri|valid)[^\d]{0,20}(\d{1,3})\s*thang[^.]{0,100}(?:ke\s+tu|(?:[a-z]\s+)?tu)\s+ngay\s+ky\s+ban\s+hanh',t)
    if not m:
        m=re.search(r'co\s+gia\s+tri\s*(\d{1,3})\s*thang',t)
    if m:
        dur=int(m.group(1))
        if 1<=dur<=120:
            base=res['decision_date'] or res['issue_date'] or res['valid_from']
            if base and res['expiry_date'] is None:
                res['expiry_date']=add_months(base,dur); conf['expiry_date']=0.90; ev['expiry_date']=f'DERIVED {dur} months from {base}'

    # Registration doc with embedded GMP "ngay cap" should keep nested GMP issue over document header date.
    # Already direct issue has higher confidence than location fallback.

    # Prevent generic report dates from becoming issue based only on certificate disclaimer text.
    if lab_report:
        # retain only direct nested certificate issue; clear all other fields
        if conf['issue_date'] < 0.95:
            res['issue_date']=None; conf['issue_date']=0; ev['issue_date']=''
        res['valid_from']=None; conf['valid_from']=0; ev['valid_from']=''
        res['expiry_date']=None; conf['expiry_date']=0; ev['expiry_date']=''
        res['decision_date']=None; conf['decision_date']=0; ev['decision_date']=''

    return {**res, **{k+'_confidence':round(conf[k],3) for k in DATE_FIELDS}, **{k+'_evidence':ev[k] for k in DATE_FIELDS}}

