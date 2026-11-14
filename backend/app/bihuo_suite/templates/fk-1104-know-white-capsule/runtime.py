"""Portable full-script compilers for the three established card/window suites."""
from pathlib import Path
import copy,hashlib,json,math,subprocess
from functools import lru_cache
import numpy as np
from PIL import Image
from .core import app_window_engine as top, app_bottom_full as bottom, capsule_engine as capsule
from .core.capsule_third import third_layers
from .core.library.visuals.capsule_list_v1 import CapsuleListV1,GEOMETRY,COLORS

HOME=Path(__file__).resolve().parent
META=json.loads((HOME/'data/template.json').read_text('utf-8'))

def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
    if tuple(size)!=(1080,1920):raise ValueError('This suite uses native1080x1920')
    if not Path(source_path).is_file():raise ValueError('Clean source file is missing')
    duration=float(resolved['duration'])
    if not math.isfinite(duration) or duration<2:raise ValueError('A complete opening needs at least2seconds of recorded speech')
    c=copy.deepcopy(META['defaults']);kind=META['kind'];options=creative_options or {}
    c.update(size=[1080,1920],fps=25,source=str(Path(source_path).resolve()),duration=duration,frames=round(duration*25),frame_count=round(duration*25),ffmpeg=str(ffmpeg),source_mode='clean-raw',source_warm_frame=False,mode='clean')
    c['fonts']={role:str(Path(fonts[role]).resolve())for role in META['font_roles']}
    if any(not Path(path).is_file()for path in c['fonts'].values()):raise ValueError('Template font is missing')
    title=str(options.get('title') or resolved.get('title') or '').strip()
    subtitle=str(options.get('subtitle') or resolved.get('subtitle') or '').strip()
    card=copy.deepcopy(options.get('name_card') or {})
    card=dict(enabled=bool(card.get('enabled',True)),name=str(card.get('name')or'').strip(),description=str(card.get('description')or'').strip())
    card['enabled']=card['enabled']and bool(card['name']or card['description']);c['name_card']=card
    opening=min(duration-.2,max(.4,float(resolved['opening_end'])))
    captions=copy.deepcopy(resolved['captions'])
    if not captions:raise ValueError('Complete measured speech captions are required')
    for row in captions:
        a,b=row['time']
        if not 0<=a<b<=duration+.04:raise ValueError('Caption outside measured source clock')
    c['captions']=captions
    materials=[]
    for m in resolved.get('materials',[]):
        if not Path(m['path']).is_file():raise ValueError('Assigned material file is missing')
        if m['kind']not in ['image','video']:raise ValueError('Unsupported material type')
        span=m.get('spoken_span')or{}
        start=max(opening,float(m['start']));end=min(duration,float(span.get('end',m['end'])))
        if end<=start:continue
        materials.append(dict(id=m['asset_id'],path=m['path'],sha256=m.get('sha256'),type=m['kind'],start=start,end=end,label=m.get('spoken_text',''),fit='contain'))
    c['materials']=materials;c['material_mode']='provided'if materials else'none'
    points=[dict(text=x['text'],at=float(x['start']),end=float(x['end']))for x in resolved.get('points',[])if x.get('text')]
    if len(points)>3:raise ValueError('This native list has3rows; prepare a shorter semantic set')
    features=[dict(text=x['text'],at=float(x['start']),end=float(x['end']))for x in resolved.get('features',[])if x.get('text')]
    conclusion=resolved.get('conclusion')or{};first=conclusion.get('first')or{};second=conclusion.get('second')or{}
    quote=float(resolved['quote_start'])if resolved.get('quote_start')is not None else None
    if kind=='capsule':
        summary=features[-1]if features and(quote is None or features[-1]['at']<quote)else{}
        c.update(opening_title=title,title=subtitle or title,items=[dict(text=x['text'],at=x['at'])for x in points],identity_times=[0,opening],card_times=[opening,opening+.24],card_exit=[quote if quote is not None else duration-.36,quote+.35 if quote is not None else duration],conclusion=dict(text=summary.get('text',''),at=float(summary.get('at',duration))))
        c['motion']['times']=[max(0,opening-.09),min(duration,opening+.655)]
        # Later focus rows keep the same source third-card mechanism.
        rows=[dict(text=x.get('text',''),at=float(x.get('start',duration))+(.4 if x is first else 0))for x in [first,second]if x.get('text')]
        start=(quote+.15)if rows and quote is not None else duration
        c['third']=dict(title=title,title_at=start,plate_at=start+.12,settle_at=start+.28,items=rows,tail_start=max(0,c['frames']-14),tail_end=c['frames']-1)
        c['_list_spec']=dict(schema='motion.capsule-list/1-candidate',size=[1080,1920],fps=25,enabled=True,title=c['title'],items=c['items'],conclusion=c['conclusion'],fonts={k:dict(path=c['fonts'][r],sha256=hashlib.sha256(Path(c['fonts'][r]).read_bytes()).hexdigest())for k,r in [('title','title'),('rows','title')]},events=dict(entry=c['card_times'],exit=c['card_exit'],row_reveal_seconds=.12,arrow_lead=[-.32,-.20]),conclusion_scale_keys=c['conclusion_scale_keys'],geometry=copy.deepcopy(GEOMETRY),colors=copy.deepcopy(COLORS),image_layout_intervals=[[m['start'],m['end']]for m in materials])
        CapsuleListV1(c['_list_spec'])
    else:
        c.update(header_title=title,header_support=subtitle,category='',chapters=[])
        scenes=c['chapters'];opening_scene=dict(at=0,nav=title,nav_support=subtitle,label=title,gray=subtitle,blue=title)
        if kind=='app-bottom'and(title or subtitle):
            opening_scene['quote']=dict(first=subtitle,second=title,first_at=.2,second_at=.44,compact_optional_roles=True)
        scenes.append(opening_scene)
        for pair in resolved.get('comparisons',[]):
            left,right=pair['left'],pair['right'];a=float(left['start']);b=float(right['start'])
            scene=dict(at=min(a,b),nav='',nav_support='',label='',gray='',blue='')
            if kind=='app-top':scene.update(contrast=[dict(label='',text=left['text'],at=a,reveal=.2),dict(label='',text=right['text'],at=max(a+.24,b),reveal=.24,emphasis=True)],connector_at=max(a+.48,b+.24))
            else:scene.update(contrast=[dict(label='',text=left['text'],support='',phase=[a,a+.24],emphasis=False),dict(label='',text=right['text'],support='',phase=[max(a+.24,b),max(a+.24,b)+.24],emphasis=True)],connector_phase=[max(a+.48,b+.24),max(a+.64,b+.4)])
            scenes.append(scene)
        if points:
            scenes.append(dict(at=opening,nav=title,nav_support='',label=title,gray='',blue='',items=[dict(text=x['text'],at=x['at'],enter_at=max(opening,x['at']-.08),clear_at=x['at']+.24)for x in points]))
        if quote is not None and(first or second):
            scenes.append(dict(at=quote,nav=title,nav_support='',label='',gray='',blue='',quote=dict(first=first.get('text',''),second=second.get('text',''),support='',first_at=float(first.get('start',quote)),second_at=float(second.get('start',quote)),compact_optional_roles=True)))
        scenes.sort(key=lambda x:x['at']);c['information_outro']=[max(0,c['frames']-14),c['frames']-4];c['global_fade']=[max(0,c['frames']-5),c['frames']-1]
    c['resolved_plan']=copy.deepcopy(resolved)
    return c

@lru_cache(maxsize=4)
def _list(spec_json):return CapsuleListV1(json.loads(spec_json))

def _capsule_card(cfg,t):
    return _list(json.dumps(cfg['_list_spec'],sort_keys=True)).render(t*25)['card']

def render_frame(cfg,n):
    t=n/25;kind=META['kind'];media=top.approved_media
    raw=media._sample(dict(path=cfg['source'],type='video',start_frame=0,source_in=0,end_policy='error'),n,25).convert('RGB')
    if kind=='app-top':roles=top.render_layers(raw,t,cfg);rgb=top.composite(roles)
    elif kind=='app-bottom':roles,_=bottom.render_layers(raw,t,cfg);rgb=bottom.composite(roles)
    else:
        roles=capsule.render_layers(raw,t,cfg);roles['information']=_capsule_card(cfg,t);third,_=third_layers(cfg,n);ordered={}
        for role,im in roles.items():
            if role=='presenter_border':ordered.update(third)
            ordered[role]=im
        roles=ordered;rgb=capsule.composite(roles)
    return rgb,roles

def render_mp4(cfg, output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);final=out/'final.mp4';log=(out/'encode.log').open('wb')
    command=[cfg['ffmpeg'],'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-t',str(cfg['duration']),'-c:v','libx264','-threads','2','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(final)]
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
    try:
        for n in range(cfg['frame_count']):process.stdin.write(render_frame(cfg,n)[0].tobytes())
    finally:process.stdin.close()
    if process.wait()!=0:raise RuntimeError('Suite encoder failed; see encode.log')
    log.close();receipt=dict(frames=cfg['frame_count'],fps=25,size=[1080,1920],final_sha256=hashlib.sha256(final.read_bytes()).hexdigest(),source_sha256=hashlib.sha256(Path(cfg['source']).read_bytes()).hexdigest(),source_audio_unretimed=True)
    (out/'render-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    return final
