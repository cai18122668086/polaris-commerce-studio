"""Full multimedia native composition with independent bilingual/source tracks."""
from pathlib import Path
import sys,json,math,copy,hashlib,importlib,subprocess,types
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent;PKG='_multimedia_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if PKG not in sys.modules:
 p=types.ModuleType(PKG);p.__path__=[str(HOME)];sys.modules[PKG]=p
E=importlib.import_module(PKG+'.multimedia_engine');TEMPLATE_ID='tpl_81019325e3_c6d9175'
def _file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
 if tuple(size)!=(1080,1920) or not Path(source_path).is_file():raise ValueError('Multimedia requires1080x1920 and existing clean source')
 duration=float(resolved['duration']);count=round(duration*25)
 if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
 default={'title':'fbecfacdfac3-抖音美好体_Bold--fbecfacdfac3.ttf','caption':'9c62ceb174d7-Noto_Sans_SC_Medium--9c62ceb174d7.otf','english':'9c62ceb174d7-Noto_Sans_SC_Medium--9c62ceb174d7.otf'};ff={r:str(Path(fonts.get(r) or fonts.get('body' if r=='caption' else r) or HOME/'fonts'/f).resolve()) for r,f in default.items()}
 if not all(Path(p).is_file() for p in ff.values()):raise ValueError('Font missing')
 title=str((creative_options or {}).get('title') or resolved.get('title') or '').strip()
 if E.font(ff['title'],124).getlength(title)>980:raise ValueError('Shorter multimedia title required')
 rows=[];previous=-1
 for i,c in enumerate(resolved.get('captions',[])):
  a,b=map(float,c['time']);first=math.ceil(a*25);end=math.ceil(b*25)
  if not 0<=a<b<=duration+.04 or a<previous or end<=first:raise ValueError('Invalid or zero-frame FA caption')
  previous=b;lines=copy.deepcopy(c.get('lines') or [dict(text=c['text'],emphasis_spans=[])])
  if len(lines)>2 or ''.join(line['text'] for line in lines)!=c['text']:raise ValueError('One or two complete semantic caption lines required')
  rows.append(dict(id=f'ZH{i+1:02}',text=c['text'],frames=[first,end],near=first,lines=lines,original_FA_seconds=[a,b],first_token_id=c.get('first_token_id'),last_token_id=c.get('last_token_id')))
 if not rows:raise ValueError('Full semantic captions required')
 size_=72
 while size_>=48 and any(E.ink(line['text'],ff['caption'],size_).width>1040 for c in rows for line in c['lines']):size_-=2
 if size_<48:raise ValueError('Caption needs semantic line break')
 mats=[]
 for m in sorted(resolved.get('materials',[]),key=lambda v:v['start']):
  if m.get('enabled') is False:continue
  if not m.get('asset_id') or not Path(m.get('path','')).is_file():raise ValueError('Actual material ID/path required')
  if m.get('kind','image')!='image':raise ValueError('Current multimedia poster profile requires images')
  if m.get('sha256') and _file_sha(m['path'])!=m['sha256']:raise ValueError('Material SHA changed')
  a=math.ceil(float(m['start'])*25);b=math.ceil(float(m['end'])*25)
  if not 0<=a<b<=count:raise ValueError('Material outside source clock')
  mats.append(dict(id=m['asset_id'],path=str(Path(m['path']).resolve()),start=a,end=b,stage=len(mats)))
 if mats:
  lead=next((i for i,c in enumerate(rows) if c['frames'][0]>=mats[0]['start']),None);last=next((i for i in range(len(rows)-1,-1,-1) if rows[i]['frames'][0]<mats[0]['end']),None)
  for i in {lead,last}:
   if i is not None and i+1<len(rows):
    first=rows[i+1]['frames'][0]-1;end=min(count,rows[i+1]['frames'][0]+16);rows[i]['split']=[first,end];rows[i]['frames'][1]=end
 return dict(mode='clean',source=str(Path(source_path).resolve()),duration=duration,frame_count=count,ffmpeg=str(ffmpeg),fonts=ff,title=title,identity={'enabled':False,'name':'','description':''},captions_zh=rows,captions_en=[],caption_size=size_,materials=mats,selected_asset_ids=[m['id'] for m in mats],actual_image_asset_ids=list(dict.fromkeys(m['id'] for m in mats)),unused_material_ids=[],opening_end_frame=max(2,round(float(resolved.get('opening_end',2.51))*25)),fade_start=max(0,count-13),black_at=count-1,resolved_plan=copy.deepcopy(resolved),native_capabilities={'title':True,'subtitle':False,'name_card':False})
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
    if enc.wait()!=0:raise RuntimeError('Multimedia encoding failed; see encode.log')
    # One encode from the actual input sound; no time remap or video-speed change.
    mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)]
    subprocess.run(mux,check=True)
    _json(out/'compiled-input.json',cfg)
    _json(out/'render-receipt.json',{'template_id':TEMPLATE_ID,'final_sha256':_file_sha(final),'source_sha256':_file_sha(cfg['source']),'frames':cfg['frame_count'],'fps':25,'size':[1080,1920],'whole_decode':'host validates','encode_command':cmd,'audio_command':mux,'inference_calls':0,'FA_calls':0,'audio':'Original source audio without retiming; AAC192k one encode','unused_material_ids':cfg['unused_material_ids']})
    return final
