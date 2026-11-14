"""Portable Milkblue full-script application. Host supplies the resolved FA plan."""
from __future__ import annotations
import hashlib, json, math, subprocess
from pathlib import Path
from .renderer import encode

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
    if tuple(size)!=(1080,1920): raise ValueError('Milkblue currently supports native 1080x1920 only')
    source=Path(source_path).resolve()
    if not source.is_file(): raise ValueError('Missing source video')
    ffprobe=str(Path(ffmpeg).with_name('ffprobe.exe' if str(ffmpeg).lower().endswith('.exe') else 'ffprobe')) if '/' in str(ffmpeg) or '\\' in str(ffmpeg) else 'ffprobe'
    probe=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-show_format','-of','json',str(source)]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    a,b=map(int,video['avg_frame_rate'].split('/')); native_fps=a/b
    frames=int(video.get('nb_frames') or round(float(video['duration'])*native_fps))
    count=round(frames/native_fps*25)
    duration=count/25
    captions=[]
    for row in resolved.get('captions',[]):
        start,end=map(float,row['time'])
        if not (0<=start<end<=duration+.12): raise ValueError('Caption clock outside source')
        text=str(row['text']).strip()
        if text: captions.append({**row,'text':text,'time':[start,end]})
    if not captions: raise ValueError('A full resolved caption plan is required')
    options=dict(creative_options or {})
    selected=options.get('selected_asset_ids')
    materials=[]
    for i,m in enumerate(resolved.get('materials',[])):
        if m.get('disabled') or m.get('enabled') is False: continue
        asset=m.get('asset_id',m.get('id'))
        if selected is not None and asset not in selected: continue
        if options.get('material_mode')=='none': continue
        span=m.get('spoken_span') or {}
        start=float(span.get('start',m.get('start',0)))
        end=float(span.get('end',m.get('end',start)))
        if not 0<=start<end<=duration+.12: raise ValueError('Invalid material semantic clock')
        path=Path(m.get('path',''))
        if not path.is_file(): continue
        expected=m.get('sha256')
        actual=digest(path)
        if expected and expected!=actual: raise ValueError('Material SHA mismatch')
        kind=m.get('kind',m.get('type','image'))
        if kind!='image': raise ValueError('Milkblue production currently accepts still images only')
        materials.append({'slot_id':str(m.get('slot_id',f'material-{i}')),'asset_id':asset,'path':str(path.resolve()),'sha256':actual,'start':start,'end':end,'spoken_text':span.get('text',m.get('spoken_text',''))})
    materials.sort(key=lambda x:x['start'])
    texts=[]
    if options.get('information_enabled',True):
        for kind in ['points','features']:
            for i,row in enumerate(resolved.get(kind,[]) or []):
                text=str(row.get('text','')).strip()
                if text and not row.get('disabled'): texts.append({'slot_id':f'{kind}-{i}','text':text,'start':float(row['start']),'end':float(row['end'])})
        for i,ch in enumerate(resolved.get('chapters',[]) or []):
            text=str(ch.get('text','')).strip(); t=float(ch.get('time',0))
            if text and not any(abs(t-m['start'])<.3 for m in materials):
                end=next((q['time'][1] for q in captions if q['time'][0]-.08<=t<q['time'][1]),min(t+1.5,duration))
                texts.append({'slot_id':f'chapter-{i}','text':text,'start':t,'end':end})
    font_path=next((fonts[k] for k in ['body','caption_bold','main','caption'] if fonts.get(k)),str(Path(__file__).parent/'fonts/body.otf'))
    if not Path(font_path).is_file(): raise ValueError('Missing host font')
    conclusion=resolved.get('conclusion') or {}
    final_start=min([float(v['start']) for v in conclusion.values() if isinstance(v,dict) and 'start' in v] or [float(resolved.get('quote_start',duration*.84))])
    late=[x for x in texts if x['start']>=max([m['end'] for m in materials] or [duration*.5])]
    # A real FA gap is preferred for the foreground compression/reopening handoff.
    gaps=[(a['time'][1],b['time'][0]) for a,b in zip(captions,captions[1:]) if b['time'][0]-a['time'][1]>=.28 and a['time'][1]<=final_start and a['time'][1]>=final_start-2]
    mask=list(gaps[-1]) if gaps and late else None
    if mask: mask=[mask[0]+.03,mask[1]-.03]
    cache=options.get('foreground_cache')
    head_start=min([x['start'] for x in late] or [duration])
    required=list(range(count)) if materials or texts else []
    alpha={}
    if required:
        if not cache or cache.get('source_sha256')!=digest(source):raise ValueError('Host source-bound foreground cache required')
        if cache.get('model_sha256')!='01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c':raise ValueError('Foreground model binding differs')
        for n in required:
            native=min(frames-1,int(n*native_fps/25));ref=cache.get('frames',{}).get(str(native),cache.get('frames',{}).get(native))
            if not ref or not Path(ref['path']).is_file() or digest(ref['path'])!=ref['sha256']:raise ValueError(f'Missing trusted alpha native {native}')
            alpha[str(n)]=ref
    return {'schema':'bihuo.milkblue-production/1','source_path':str(source),'source_sha256':digest(source),'fps':25,'native_fps':native_fps,'frames':count,'duration':duration,'audio_duration':probe.get('format',{}).get('duration'),'ffmpeg':str(ffmpeg),'size':list(size),'font':str(Path(font_path).resolve()),'font_sha256':digest(font_path),'captions':captions,'materials':materials,'text_items':texts,'final_start':final_start,'mask':mask,'creative_options':options,'native_identity_slots':1,'title':str(resolved.get('title','')).strip(),'subtitle':str(resolved.get('subtitle','')).strip(),'opening_end':float(resolved.get('opening_end') or min(2.5,duration*.15)),'identity_policy':'empty/disabled omit; independent name or description supported','title_policy':'independent whole-line opening title and support','foreground_alpha':alpha,'head_start':head_start,'tokens':resolved.get('tokens',[]),'conclusion':conclusion}

def render_mp4(cfg, output_dir):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    (out/'render-input.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),'utf8')
    final=encode(cfg,out)
    receipt={'schema':'bihuo.render-receipt/1','final_sha256':digest(final),'final':str(final),'frames':cfg['frames'],'fps':25,'source_sha256':cfg['source_sha256'],'font_sha256':cfg['font_sha256'],'material_slots':[{k:m[k] for k in ['slot_id','asset_id','sha256','start','end']} for m in cfg['materials']],'caption_count':len(cfg['captions']),'native_identity_slots':1,'limitations':['Native author raw and exact source curves unavailable; measured mechanisms are reconstructed.','Images use contain over blur padding to preserve embedded text.','Head foreground uses host source-bound native alpha; missing resources are rejected.']}
    (out/'render-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
    return final
