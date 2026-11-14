"""Full Sleepgrid website adapter: original room window, diagonal return, circle/poster."""
from pathlib import Path
import json,hashlib,importlib,math,subprocess,sys,types,copy
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent;PKG='_sleepgrid_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if PKG not in sys.modules:
 p=types.ModuleType(PKG);p.__path__=[str(HOME)];sys.modules[PKG]=p
E=importlib.import_module(PKG+'.sleepgrid_engine');TEMPLATE_ID='tpl_da5635d242_cdbce6c'
def _file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
 if tuple(size)!=(1080,1920) or not Path(source_path).is_file():raise ValueError('Sleepgrid requires1080x1920 and existing clean source')
 duration=float(resolved['duration']);count=round(duration*25)
 if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
 options=creative_options or {};card=options.get('name_card') or options.get('identity') or {};name=str(card.get('name','') or '').strip();desc=str(card.get('description','') or '').strip();enabled=bool(card.get('enabled',True)) and bool(name or desc)
 default={'body':'simsun.ttc','title':'msyhbd.ttc','identity':'Ma_Shan_Zheng_Regular--dc5c09e97580.ttf'};ff={r:str(Path(fonts.get(r) or HOME/'fonts'/f).resolve()) for r,f in default.items()}
 if not all(Path(p).is_file() for p in ff.values()):raise ValueError('Font missing')
 title=str(options.get('title') or resolved.get('title') or '').strip()
 if E.font(ff['title'],110).getlength(title)>940:raise ValueError('Sleepgrid opening topic needs shorter wording')
 if E.font(ff['identity'],58).getlength(name)>650 or E.font(ff['body'],36).getlength(desc)>650:raise ValueError('Identity exceeds badge width')
 captions=[];previous=-1;tokens=resolved.get('tokens',[]);positions={t['id']:i for i,t in enumerate(tokens)}
 for i,row in enumerate(resolved.get('captions',[])):
  a,b=map(float,row['time'])
  if not 0<=a<b<=duration+.04 or a<previous or math.ceil(b*25)-1<math.ceil(a*25):raise ValueError('Invalid native caption clock')
  previous=b;lines=copy.deepcopy(row.get('lines') or [dict(text=row['text'],emphasis_spans=[])])
  if len(lines)>2 or ''.join(v['text'] for v in lines)!=row['text']:raise ValueError('One or two complete semantic lines required')
  for line in lines:line.setdefault('emphasis_spans',[])
  captions.append(dict(text=row['text'],time=[a,b],lines=lines,first_token_id=row.get('first_token_id'),last_token_id=row.get('last_token_id')))
 if not captions:raise ValueError('Full captions required')
 body=82
 while body>=50 and any(E.font(ff['body'],body).getlength(line['text'])>960 for c in captions for line in c['lines']):body-=2
 if body<50:raise ValueError('Caption needs semantic line break')
 materials=[]
 for m in sorted(resolved.get('materials',[]),key=lambda q:q['start']):
  if m.get('enabled') is False:continue
  if not m.get('asset_id') or not Path(m.get('path','')).is_file():raise ValueError('Actual matched material ID/path required')
  if m.get('kind','image')!='image':raise ValueError('Current Sleepgrid poster profile requires image')
  if m.get('sha256') and _file_sha(m['path'])!=m['sha256']:raise ValueError('Material SHA changed')
  a=round(float(m['start'])*25);b=round(float(m['end'])*25)
  if not 0<=a<b<=count:raise ValueError('Material outside source clock')
  materials.append(dict(id=m['asset_id'],path=str(Path(m['path']).resolve()),start=a,end=b,stage=len(materials),semantic='actual-matched-semantic-segment'))
 if materials:
  progressive=next((c for c in captions if c['time'][0]*25>=materials[0]['end']),None)
  if progressive:
   if not tokens or progressive['first_token_id'] not in positions or progressive['last_token_id'] not in positions:raise ValueError('Typewriter requires real FA tokens, not divided cue times')
   a=positions[progressive['first_token_id']];b=positions[progressive['last_token_id']];selected=tokens[a:b+1]
   if ''.join(t['text'] for t in selected)!=progressive['text']:raise ValueError('Typewriter text differs from FA token span')
   progressive['glyph_firsts']=[t['start_ms']/40 for t in selected for _ in t['text']];progressive['progressive']=True
 return dict(mode='new',source=str(Path(source_path).resolve()),duration=duration,frame_count=count,ffmpeg=str(ffmpeg),fonts=ff,body_size=body,topic=title,topic_size=110,opening_end_frame=max(2,round(float(resolved.get('opening_end',2.51))*25)),identity=dict(enabled=enabled,name=name if enabled else '',description=desc if enabled else ''),captions=captions,materials=materials,text_cards=[dict(id='text-stage-'+str(i),path='',text=x['text'],start=round(float(x['start'])*25),end=round(float(x['end'])*25),stage=0) for i,x in enumerate(resolved.get('points',[])+resolved.get('features',[])) if x.get('text') and float(x['end'])>float(x['start'])],material_texts=[x['text'] for x in resolved.get('points',[]) if x.get('text')],fade_start=max(0,count-13),black_at=count-1,actual_image_asset_ids=list(dict.fromkeys(m['id'] for m in materials)),unused_material_ids=[],resolved_plan=copy.deepcopy(resolved))
def render_frame(cfg,n):
 if not 0<=n<cfg['frame_count']:raise ValueError('Frame outside scope')
 raw=E.M._sample(dict(path=cfg['source'],start_frame=0,source_in=0,end_policy='hold'),n,25).convert('RGB');roles=E.render_layers(raw,n,cfg);return E.composite(roles),roles,{}

def render_mp4(cfg, output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    silent=out/'silent.mp4';final=out/'final.mp4';ff=cfg['ffmpeg']
    cmd=[ff,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
    try:
        for n in range(cfg['frame_count']):
            rgb,roles,_=render_frame(cfg,n);enc.stdin.write(rgb.tobytes())
    finally:enc.stdin.close()
    if enc.wait()!=0:raise RuntimeError('Sleepgrid encoding failed; see encode.log')
    # One encode from the actual input sound; no time remap or video-speed change.
    mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)]
    subprocess.run(mux,check=True)
    _json(out/'compiled-input.json',cfg)
    _json(out/'render-receipt.json',{'template_id':TEMPLATE_ID,'final_sha256':_file_sha(final),'source_sha256':_file_sha(cfg['source']),'frames':cfg['frame_count'],'fps':25,'size':[1080,1920],'whole_decode':'host validates','encode_command':cmd,'audio_command':mux,'inference_calls':0,'FA_calls':0,'audio':'Original source audio without retiming; AAC192k one encode','unused_material_ids':cfg['unused_material_ids']})
    return final
