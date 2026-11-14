"""Blue complete native recipe adapter, variable resolved input."""
from pathlib import Path
import sys,json,copy,math,hashlib,importlib,types,subprocess
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent;PKG='_blue_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if PKG not in sys.modules:
 p=types.ModuleType(PKG);p.__path__=[str(HOME)];sys.modules[PKG]=p
E=importlib.import_module(PKG+'.blue_engine');TEMPLATE_ID='fk-1102-brief-blue'
def _file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
 if tuple(size)!=(1080,1920) or not Path(source_path).is_file():raise ValueError('Blue requires1080x1920 and existing clean source')
 duration=float(resolved['duration']);count=round(duration*25)
 if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
 defaults={'body':'62383707c086-思源黑体_CN_Bold--62383707c086.otf','accent':'62383707c086-思源黑体_CN_Bold--62383707c086.otf','name':'fbecfacdfac3-抖音美好体_Bold--fbecfacdfac3.ttf'};ff={r:str(Path(fonts.get(r) or HOME/'fonts'/f).resolve()) for r,f in defaults.items()};ff['caption_body']=str(Path(fonts.get('caption_body') or ff['body']).resolve())
 if not all(Path(p).is_file() for p in ff.values()):raise ValueError('Font missing')
 options=creative_options or {};card=options.get('name_card') or options.get('identity') or {};name=str(card.get('name','') or '').strip();desc=str(card.get('description','') or '').strip();enabled=bool(card.get('enabled',True)) and bool(name or desc)
 title=str(options.get('title') or resolved.get('title') or '').strip();support=str(options.get('subtitle') or resolved.get('subtitle') or '').strip();lines=[x for x in [title,support] if x]
 if any(E.tile(x,ff['name'],48,E.BLUE,.17).width>700 for x in lines):raise ValueError('Blue header needs shorter one/two natural lines')
 captions=[];previous=-1
 for i,row in enumerate(resolved.get('captions',[])):
  a,b=map(float,row['time']);first=math.ceil(a*25);end=math.ceil(b*25)
  if not 0<=a<b<=duration+.04 or a<previous or end<=first:raise ValueError('Invalid or zero-frame native FA caption')
  previous=b;linguistic=copy.deepcopy(row.get('lines') or [dict(text=row['text'],emphasis_spans=[])])
  if len(linguistic)>2 or ''.join(v['text'] for v in linguistic)!=row['text']:raise ValueError('One/two complete semantic caption lines required')
  for line in linguistic:line.setdefault('emphasis_spans',[])
  captions.append(dict(id=f'N{i+1:02}',text=row['text'],frames=[first,end],lines=linguistic,original_FA_seconds=[a,b],first_token_id=row.get('first_token_id'),last_token_id=row.get('last_token_id')))
 if not captions:raise ValueError('Full semantic captions required')
 size_=58
 while size_>=46:
  fit=True
  for c in captions:
   for line in c['lines']:
    parts=E.V.caption_parts(line);width=sum(E.tile(s,ff['accent'] if emphasis else ff['caption_body'],size_+10 if emphasis else size_,E.BLUE if emphasis else(255,255,255,255),.08 if emphasis else 0).width for s,emphasis in parts)+max(0,len(parts)-1)
    fit=fit and width<=1010
  if fit:break
  size_-=2
 if size_<46:raise ValueError('Caption needs semantic line break')
 mats=[];assignments=[]
 for m in sorted(resolved.get('materials',[]),key=lambda q:q['start']):
  if m.get('enabled') is False:continue
  if not m.get('asset_id') or not Path(m.get('path','')).is_file():raise ValueError('Actual matched asset ID/path required')
  if m.get('kind','image')!='image':raise ValueError('Current Blue picture profile requires images')
  if m.get('sha256') and _file_sha(m['path'])!=m['sha256']:raise ValueError('Material SHA changed')
  a=math.ceil(float(m['start'])*25);b=math.ceil(float(m['end'])*25)
  if not 0<=a<b<=count:raise ValueError('Material outside native source clock')
  row=dict(asset_id=m['asset_id'],path=str(Path(m['path']).resolve()),sha256=m.get('sha256'),frames=[a,b],first_token_id=m.get('first_token_id'),last_token_id=m.get('last_token_id'));mats.append(row);assignments.append(dict(row))
 opening=max(2,round(float(resolved.get('opening_end',2.51))*25))
 cfg=dict(mode='clean',source=str(Path(source_path).resolve()),duration=duration,frame_count=count,ffmpeg=str(ffmpeg),fonts=ff,warm0=False,identity=dict(enabled=enabled,name=name if enabled else '',description=desc if enabled else ''),identity_clock=[5,11,opening],header=dict(enabled=bool(lines),label='关于' if lines else '',lines=lines),header_entry=[5,12],header_exit=[max(1,opening-10),max(2,opening-4)],captions=captions,caption_size=size_,materials=mats,semantic_assignments=assignments,actual_image_asset_ids=list(dict.fromkeys(m['asset_id'] for m in mats)),unused_material_ids=[],fade_start=max(0,count-13),black_at=count-1,resolved_plan=copy.deepcopy(resolved),native_capabilities={'title':True,'subtitle':True,'name_card':True})
 # Same native primitive guard as real rendering; disabled fields do not consume layout.
 if enabled:E.identity(cfg,20)
 return cfg
def render_frame(cfg,n):
 if not 0<=n<cfg['frame_count']:raise ValueError('Frame outside scope')
 return E.render(cfg,n)

def render_mp4(cfg, output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    silent=out/'silent.mp4';final=out/'final.mp4';ff=cfg['ffmpeg']
    cmd=[ff,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
    try:
        for n in range(cfg['frame_count']):
            rgb,roles,_=render_frame(cfg,n);enc.stdin.write(rgb.tobytes())
    finally:enc.stdin.close()
    if enc.wait()!=0:raise RuntimeError('Blue encoding failed; see encode.log')
    # One encode from the actual input sound; no time remap or video-speed change.
    mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)]
    subprocess.run(mux,check=True)
    _json(out/'compiled-input.json',cfg)
    _json(out/'render-receipt.json',{'template_id':TEMPLATE_ID,'final_sha256':_file_sha(final),'source_sha256':_file_sha(cfg['source']),'frames':cfg['frame_count'],'fps':25,'size':[1080,1920],'whole_decode':'host validates','encode_command':cmd,'audio_command':mux,'inference_calls':0,'FA_calls':0,'audio':'Original source audio without retiming; AAC192k one encode','unused_material_ids':cfg['unused_material_ids']})
    return final
