"""Silver website adapter. Deterministic resolved-plan input, zero model calls."""
from pathlib import Path
import copy,hashlib,importlib,json,math,subprocess,sys,types
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent
_PACKAGE='_silver_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if _PACKAGE not in sys.modules:
    _p=types.ModuleType(_PACKAGE);_p.__path__=[str(HOME)];sys.modules[_PACKAGE]=_p
E=importlib.import_module(_PACKAGE+'.silver_engine')
TEMPLATE_ID='tpl_dc421f64d0'
def _file_sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
    if tuple(size)!=(1080,1920):raise ValueError('Silver supports 1080x1920')
    if not Path(source_path).is_file():raise ValueError('Clean source is missing')
    duration=float(resolved['duration']);count=round(duration*25)
    if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
    cfg=json.loads((HOME/'data/defaults.json').read_text(encoding='utf-8'))
    for key in ['caption','title']:
        default=HOME/cfg['fonts'][key]
        cfg['fonts'][key]=str(Path(fonts.get(key) or fonts.get('body' if key=='caption' else 'bold') or default).resolve())
        if not Path(cfg['fonts'][key]).is_file():raise ValueError('Font missing: '+key)
    cfg['fonts'].pop('alternative',None)
    options=creative_options or {};identity=options.get('identity') or options.get('name_card') or options.get('person_card') or {}
    name=str(identity.get('name',options.get('name','')) or '').strip()
    desc=str(identity.get('description',options.get('description','')) or '').strip()
    enabled=bool(identity.get('enabled',options.get('identity_enabled',True))) and bool(name or desc)
    if len(name)>10 or len(desc)>32:raise ValueError('Identity exceeds Silver reading area')
    cfg['identity']={'enabled':enabled,'name':name if enabled else '', 'description':desc if enabled else ''}
    cfg['source']=str(Path(source_path).resolve());cfg['mode']='replacement'
    cfg['title']=str(options.get('title') or resolved.get('title') or '').strip()
    cfg['title_size']=126
    while cfg['title'] and E.font(cfg['fonts']['title'],cfg['title_size']).getlength(cfg['title'])>980 and cfg['title_size']>54:cfg['title_size']-=2
    if cfg['title'] and E.font(cfg['fonts']['title'],cfg['title_size']).getlength(cfg['title'])>980:raise ValueError('Title needs shorter wording')
    opening=float(resolved.get('opening_end',min(2.5,duration*.2)))
    title_end=min(count,max(2,round(opening*25)))
    cfg['title_exit']=[max(1,title_end-5),title_end];cfg['identity_exit']=cfg['title_exit'][:]
    rows=resolved.get('captions')
    if not isinstance(rows,list) or not rows:raise ValueError('Full semantic captions with native FA times required')
    captions=[];prior=-1
    for i,row in enumerate(rows):
        a,b=map(float,row['time']);first=round(a*25);gone=round(b*25)
        if not 0<=a<b<=duration+.04 or first<prior or gone<=first:raise ValueError('Invalid or zero-frame FA cue; merge upstream without shifting audio')
        prior=gone
        text=str(row.get('text','')).rstrip('，。！？；：,!?;:')
        line_specs=row.get('lines') or [{'text':text,'emphasis_spans':[]}]
        lines=[]
        for line in line_specs:
            line=copy.deepcopy(line);line['text']=str(line['text']).rstrip('，。！？；：,!?;:');line.setdefault('emphasis_spans',[])
            if not line['text']:raise ValueError('Empty caption line')
            if any(not 0<=x<y<=len(line['text']) for x,y in line['emphasis_spans']):raise ValueError('Invalid emphasis span')
            lines.append(line)
        if not 1<=len(lines)<=2:raise ValueError('Silver accepts one or two planned caption lines')
        c=dict(text='\n'.join(x['text'] for x in lines),lines=lines,original_text=row['text'],first=first,settle=min(first+3,gone-1),gone=gone,exit=gone,split=None,entry_mode='whole-phrase-brightness-entry',exit_mode='whole-phrase-direct-clear',emphasis_spans=lines[0]['emphasis_spans'],first_token_id=row.get('first_token_id'),last_token_id=row.get('last_token_id'),fa_interval_seconds=[a,b])
        captions.append(c)
    # The full-plan semantic chapter and conclusion roles select outgoing splits.
    # No fixed three-item, fixed cue ordinal, or source timestamp migration.
    split_starts={captions[0]['first']}
    split_starts.update(round(float(ch['time'])*25) for ch in resolved.get('chapters',[]))
    conclusion=resolved.get('conclusion') or {}
    if conclusion.get('first'):split_starts.add(round(float(conclusion['first']['start'])*25))
    for i,c in enumerate(captions):
        if i+1<len(captions) and any(c['first']<=v<c['gone'] for v in split_starts):
            following=captions[i+1]['first'];split=max(c['first']+1,following-6)
            if split>=c['gone']:
                c.update(split=split,exit=split,gone=following,exit_mode='semantic-complementary-split-tail')
    cfg['captions']=captions
    # Whole-frame -> close window follows the actual conclusion, or final chapter.
    # FA stays immutable; only visual placement and motion events derive from plan.
    handoff_seconds=(conclusion.get('first') or {}).get('start')
    if handoff_seconds is None:
        chapters=resolved.get('chapters',[]);handoff_seconds=chapters[-1]['time'] if chapters else max(opening,duration*.68)
    cfg['handoff']=min(count-2,max(title_end,round(float(handoff_seconds)*25)-5))
    cfg['window_settled']=cfg['handoff']+29
    final_seconds=(conclusion.get('second') or {}).get('start')
    cfg['outer_start']=max(cfg['handoff']+30,round(float(final_seconds)*25)+5 if final_seconds is not None else count-52)
    cfg['fade_start']=max(cfg['outer_start']+17,count-13);cfg['black_at']=count-1
    # Clamp to the actual visual tail without changing any caption/FA boundary.
    cfg['fade_start']=min(count-2,cfg['fade_start']);cfg['outer_start']=min(cfg['outer_start'],cfg['fade_start']-17)
    cfg.update(duration=duration,frame_count=count,ffmpeg=str(ffmpeg),template_id=TEMPLATE_ID,scopes={'full':[0,count]},resolved_plan=copy.deepcopy(resolved),actual_image_asset_ids=[],unused_material_ids=[x['asset_id'] for x in resolved.get('materials',[])],native_picture_slots=0)
    # Real glyph width validation, including planned two-line text.
    for c in captions:E.whole_line(cfg,c)
    return cfg
def render_frame(cfg,n):
    if not 0<=n<cfg['frame_count']:raise ValueError('Frame outside compiled scope')
    roles,meta=E.render_layers(cfg,n)
    return E.composite(roles),roles,meta
def render_mp4(cfg, output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    silent=out/'silent.mp4';final=out/'final.mp4';ff=cfg['ffmpeg']
    cmd=[ff,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
    try:
        for n in range(cfg['frame_count']):
            rgb,roles,_=render_frame(cfg,n);enc.stdin.write(rgb.tobytes())
    finally:enc.stdin.close()
    if enc.wait()!=0:raise RuntimeError('Silver encoding failed; see encode.log')
    # One encode from the actual input sound; no time remap or video-speed change.
    mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)]
    subprocess.run(mux,check=True)
    _json(out/'compiled-input.json',cfg)
    _json(out/'render-receipt.json',{'template_id':TEMPLATE_ID,'final_sha256':_file_sha(final),'source_sha256':_file_sha(cfg['source']),'frames':cfg['frame_count'],'fps':25,'size':[1080,1920],'whole_decode':'host validates','encode_command':cmd,'audio_command':mux,'inference_calls':0,'FA_calls':0,'audio':'Original source audio without retiming; AAC192k one encode','native_picture_slots':0,'unused_material_ids':cfg['unused_material_ids']})
    return final
