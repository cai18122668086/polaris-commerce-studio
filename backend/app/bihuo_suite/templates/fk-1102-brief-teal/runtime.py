"""Teal complete native recipe adapter, resolved semantics and native FA input."""
from pathlib import Path
import sys,json,math,copy,hashlib,importlib,types,subprocess
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent;PKG='_teal_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if PKG not in sys.modules:
 p=types.ModuleType(PKG);p.__path__=[str(HOME)];sys.modules[PKG]=p
E=importlib.import_module(PKG+'.full_engine');TEMPLATE_ID='fk-1102-brief-teal'
def _file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
 if tuple(size)!=(1080,1920) or not Path(source_path).is_file():raise ValueError('Teal requires1080x1920 and existing clean source')
 duration=float(resolved['duration']);count=round(duration*25)
 if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
 defaults={'bold':'62383707c086-思源黑体_CN_Bold--62383707c086.otf','body':'9c62ceb174d7-Noto_Sans_SC_Medium--9c62ceb174d7.otf'};ff={r:str(Path(fonts.get(r) or HOME/'fonts'/f).resolve()) for r,f in defaults.items()};ff['caption']=str(Path(fonts.get('caption') or ff['bold']).resolve())
 if not all(Path(p).is_file() for p in ff.values()):raise ValueError('Font missing')
 card=(creative_options or {}).get('name_card') or (creative_options or {}).get('identity') or {};name=str(card.get('name','') or '').strip();desc=str(card.get('description','') or '').strip();enabled=bool(card.get('enabled',True)) and bool(name or desc)
 if enabled and (E.B.ink(name,ff['bold'],84,(0,0,0,255)).width>430 or E.B.ink(desc,ff['body'],52,(0,0,0,255)).width>430):raise ValueError('Shorter Teal identity required')
 captions=[];previous=-1
 for row in resolved.get('captions',[]):
  a,b=map(float,row['time'])
  if not 0<=a<b<=duration+.04 or a<previous or math.ceil(b*25)-1<math.ceil(a*25):raise ValueError('Invalid or zero-frame native caption')
  previous=b;c=copy.deepcopy(row);c['near']=min(a+.32,(math.ceil(b*25)-1)/25);c['lines']=c.get('lines') or [dict(text=c['text'],emphasis_spans=[])]
  if len(c['lines'])>2 or ''.join(x['text'] for x in c['lines'])!=c['text']:raise ValueError('Full one/two semantic caption lines required')
  captions.append(c)
 if not captions:raise ValueError('Full semantic captions required')
 csize=58
 while csize>=46 and any(sum(E.B.font(ff['caption'],csize+10 if emph else csize).getlength(text) for text,emph in E.B.V.caption_parts(line))>990 for c in captions for line in c['lines']):csize-=2
 if csize<46:raise ValueError('Caption needs semantic line break')
 conclusion=resolved.get('conclusion') or {};split=float((conclusion.get('first') or {}).get('start',duration*.68))
 points=[x for x in resolved.get('points',[]) if str(x.get('text','')).strip() and x.get('enabled',True)];features=[x for x in resolved.get('features',[]) if str(x.get('text','')).strip() and x.get('enabled',True)]
 early_features=[x for x in features if float(x['start'])<split];late_features=[x for x in features if float(x['start'])>=split]
 if len(points)>4 or len(early_features)>4 or len(late_features)>4:raise ValueError('Teal supports4 natural rows/pills per stage; explicit paging needed')
 mats=[];opening_end=float(resolved.get('opening_end',min(2.5,duration*.2)))
 for m in sorted(resolved.get('materials',[]),key=lambda q:q['start']):
  if m.get('enabled') is False:continue
  if not m.get('asset_id') or not Path(m.get('path','')).is_file():raise ValueError('Actual asset ID/path required')
  if m.get('kind','image')!='image':raise ValueError('Current Teal card profile requires image')
  if m.get('sha256') and _file_sha(m['path'])!=m['sha256']:raise ValueError('Material SHA changed')
  a,b=float(m['start']),float(m['end'])
  if not 0<=a<b<=duration+.04:raise ValueError('Material outside source clock')
  role=m.get('scene_role')
  if role not in ['opening','first-card','second-card']:
   if a>=split and late_features:role='second-card'
   elif points and any(float(p['start'])<b and a<float(p['end']) for p in points):role='first-card'
   elif a>=duration*.35 and a<split:role='first-card'
   else:role='opening'
  mats.append(dict(id=m['asset_id'],path=str(Path(m['path']).resolve()),sha256=m.get('sha256'),start=a,end=b,scene_role=role))
 first_image=next((m for m in mats if m['scene_role']=='first-card'),None)
 def nearby_label(at):
  rows=[x for x in resolved.get('chapters',[]) if float(x['time'])<=at+.1]
  return rows[-1]['text'] if rows else next((c['text'].rstrip('，。') for c in captions if c['time'][0]<=at<c['time'][1]),'内容要点')
 if not points and first_image:
  selected=[c for c in captions if first_image['start']<=c['time'][0]<first_image['end']];points=[dict(text=c['text'],start=c['time'][0],end=c['time'][1]) for c in selected[1:5]]
 first_start=first_image['start'] if first_image else max(0,float(points[0]['start'])-.16) if points else duration+2
 first_end=max([float(x['end']) for x in points]+[m['end'] for m in mats if m['scene_role']=='first-card']+[-1]) if points or first_image else duration+3
 info=dict(enabled=bool(points or first_image),start=first_start,end=first_end,label=nearby_label(first_start) if points or first_image else '',items=[dict(text=x['text'],start=float(x['start']),near=min(float(x['start'])+.28,float(x['end']))) for x in points])
 final_start=float((conclusion.get('first') or {}).get('start',late_features[0]['start'] if late_features else duration+2));last_row=max([float(x['end']) for x in late_features]+[final_start]);following=next((c['time'][0] for c in captions if c['time'][0]>=last_row+.01),min(duration,last_row+.4));second_end=max(final_start+.1,following)
 second=dict(enabled=bool(late_features),start=final_start,near=final_start+.2,label_at=final_start+.32,label=next((c['text'].rstrip('，。') for c in captions if abs(c['time'][0]-final_start)<.05),nearby_label(final_start)),items=[dict(text=x['text'],start=float(x['start']),near=min(float(x['start'])+.28,float(x['end']))) for x in late_features],end=second_end,clear=second_end+.32)
 pills=[dict(text=x['text'],start=float(x['start']),near=float(x['start'])+.2,active_end=split-.01) for x in early_features];pills_end=min(split-.01,max([float(x['end'])+.13 for x in early_features]+[0]))
 for row in points+late_features:
  if E.B.ink(row['text'],ff['bold'],30,(0,0,0,255)).width>700:raise ValueError('Card row exceeds native reading width')
 for row in pills:
  if E.B.ink(row['text'],ff['bold'],32,(0,0,0,255)).width>900:raise ValueError('Pill label exceeds native width')
 if E.B.ink(info['label'],ff['bold'],26,(0,0,0,255)).width>650 or E.B.ink(second['label'],ff['bold'],26,(0,0,0,255)).width>650:raise ValueError('Shorter information label required')
 return dict(mode='new',source=str(Path(source_path).resolve()),duration=duration,frame_count=count,ffmpeg=str(ffmpeg),fonts=ff,caption_size=csize,captions=captions,identity=dict(enabled=enabled,name=name if enabled else '',description=desc if enabled else ''),identity_exit=[max(.08,opening_end+.16),max(.12,opening_end+.52)],materials=mats,information=info,return_start=first_end+.8 if info['enabled'] else 0,second_information=second,second_person=dict(shrink=[max(0,final_start-.16),final_start+.48],**{'return':[second['clear']+.12,second['clear']+.92]}),pills=pills,pills_exit=[max(0,pills_end-.28),pills_end],actual_image_asset_ids=list(dict.fromkeys(m['id'] for m in mats)),unused_material_ids=[],resolved_plan=copy.deepcopy(resolved),native_capabilities={'title':False,'subtitle':False,'name_card':True})
def render_frame(cfg,n):
 if not 0<=n<cfg['frame_count']:raise ValueError('Frame outside scope')
 raw=E.B.M._sample(dict(path=cfg['source'],start_frame=0,end_policy='hold'),n,25).convert('RGBA');raw=raw if raw.size==(1080,1920) else E.B.M._fit(raw.convert('RGBA'),1080,1920,dict(fit='cover',anchor=[.5,.5])).convert('RGBA');roles=E.render_layers(raw,n/25,cfg);return E.composite(roles),roles,{}

def render_mp4(cfg, output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    silent=out/'silent.mp4';final=out/'final.mp4';ff=cfg['ffmpeg']
    cmd=[ff,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
    try:
        for n in range(cfg['frame_count']):
            rgb,roles,_=render_frame(cfg,n);enc.stdin.write(rgb.tobytes())
    finally:enc.stdin.close()
    if enc.wait()!=0:raise RuntimeError('Teal encoding failed; see encode.log')
    # One encode from the actual input sound; no time remap or video-speed change.
    mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)]
    subprocess.run(mux,check=True)
    _json(out/'compiled-input.json',cfg)
    _json(out/'render-receipt.json',{'template_id':TEMPLATE_ID,'final_sha256':_file_sha(final),'source_sha256':_file_sha(cfg['source']),'frames':cfg['frame_count'],'fps':25,'size':[1080,1920],'whole_decode':'host validates','encode_command':cmd,'audio_command':mux,'inference_calls':0,'FA_calls':0,'audio':'Original source audio without retiming; AAC192k one encode','unused_material_ids':cfg['unused_material_ids']})
    return final
