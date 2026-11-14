"""Callable Qingbai full composition; Chinese/English responsibilities stay separate."""
from pathlib import Path
import hashlib,importlib,json,math,subprocess,sys,types,copy
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent;PKG='_qingbai_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if PKG not in sys.modules:
 p=types.ModuleType(PKG);p.__path__=[str(HOME)];sys.modules[PKG]=p
E=importlib.import_module(PKG+'.qingbai_engine');TEMPLATE_ID='fk-1112-qingbai-bilingual'
def _file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
 if tuple(size)!=(1080,1920) or not Path(source_path).is_file():raise ValueError('Qingbai requires1080x1920 and existing clean source')
 duration=float(resolved['duration']);count=round(duration*25)
 if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
 options=creative_options or {};card=options.get('name_card') or options.get('identity') or {};name=str(card.get('name','') or '').strip();desc=str(card.get('description','') or '').strip();enabled=bool(card.get('enabled',True)) and bool(name or desc)
 ff={role:str(Path(fonts.get(role) or fonts.get('caption' if role=='body' else 'bold') or HOME/'fonts'/fn).resolve()) for role,fn in [('body','msyhbd.ttc'),('title','msyhbd.ttc'),('english','arial.ttf')]}
 if not all(Path(x).is_file() for x in ff.values()):raise ValueError('Font missing')
 if any(E.text_run(t,ff['body'],s,(10,20,20,255)).width>250 for t,s in [(name,72),(desc,42)] if t):raise ValueError('Qingbai identity needs shorter supplied fields')
 title=str(options.get('title') or resolved.get('title') or '').strip();support=str(options.get('subtitle') or resolved.get('subtitle') or '').strip()
 if E.font(ff['title'],48).getlength(title)>950 or E.font(ff['title'],24).getlength(support)>950:raise ValueError('Title/support exceeds style reading area')
 captions=[];previous=-1
 for i,row in enumerate(resolved.get('captions',[])):
  a,b=map(float,row['time']);first=a*25;clear=b*25
  if not 0<=a<b<=duration+.04 or first<previous or math.ceil(clear)-1<math.ceil(first):raise ValueError('Invalid or zero-frame real caption clock')
  previous=clear;lines=copy.deepcopy(row.get('lines') or [dict(text=row['text'],emphasis_spans=[])])
  if len(lines)>2 or ''.join(x['text'] for x in lines)!=row['text']:raise ValueError('One or two complete planned lines required')
  for line in lines:
   line.setdefault('emphasis_spans',[])
   if any(not 0<=x<y<=len(line['text']) for x,y in line['emphasis_spans']):raise ValueError('Invalid emphasis')
  captions.append(dict(id=f'N{i+1:02}',text=row['text'],range=[first,clear],lines=lines,archived_semantic_spans=[],first_token_id=row.get('first_token_id'),last_token_id=row.get('last_token_id')))
 if not captions:raise ValueError('Full semantic captions required')
 body=64
 while body>=48:
  if all(sum(E.text_run(t,ff['body'],body+12 if yes else body,(255,255,255,255)).width for t,yes in E.V.caption_parts(line))<=1040 for c in captions for line in c['lines']):break
  body-=2
 if body<48:raise ValueError('Caption needs semantic line break')
 mats=[]
 for m in sorted(resolved.get('materials',[]),key=lambda q:q['start']):
  if m.get('enabled') is False:continue
  if not m.get('asset_id') or not Path(m.get('path','')).is_file():raise ValueError('Actual matched asset ID/path required')
  if m.get('sha256') and _file_sha(m['path'])!=m['sha256']:raise ValueError('Material SHA changed')
  if len(mats)>=4:raise ValueError('Current Qingbai four semantic media stages exceeded; plan fewer matched stages')
  start=round(float(m['start'])*25);end=round(float(m['end'])*25)
  if not 0<=start<end<=count:raise ValueError('Material clock outside source')
  if m.get('kind','image')!='image':raise ValueError('Qingbai current fit profile requires image assets')
  mats.append(dict(id=m['asset_id'],path=str(Path(m['path']).resolve()),semantic_segment=len(mats),start=start,end=end,media_type='image',sha256=m.get('sha256')))
 opening=max(2,round(float(resolved.get('opening_end',min(2.5,duration*.2)))*25));first=mats[0]['start'] if mats else opening;firstend=mats[0]['end'] if mats else opening+1;second=mats[1]['start'] if len(mats)>1 else count+25
 events=dict(book_entry=[first,first+11],person_shrink=[first,first+19],book_exit=[max(first+1,firstend-10),firstend],person_raise=[second-5,second+16],glow_start=second+2,food_entry=[second,second+17])
 return dict(mode='replacement',source=str(Path(source_path).resolve()),duration=duration,frame_count=count,ffmpeg=str(ffmpeg),fonts=ff,title=title,title_emphasis=[],support=support,name_card=dict(enabled=enabled,name=name if enabled else '',description=desc if enabled else ''),title_events=dict(main_entry=[2,10],support_entry=[4,12],exit=[max(1,opening-5),opening]),identity_events=dict(entry=[2,9],exit=[max(1,opening-5),opening]),captions=captions,caption_size=body,english_enabled=False,english_track='No confirmed translated track supplied; omitted',materials=mats,selected_asset_ids=[m['id'] for m in mats],actual_image_asset_ids=list(dict.fromkeys(m['id'] for m in mats)),unused_material_ids=[],events=events,fade_start=max(0,count-14),black_at=count-1,scopes={'full':[0,count]},resolved_plan=copy.deepcopy(resolved))
def render_frame(cfg,n):
 if not 0<=n<cfg['frame_count']:raise ValueError('Frame outside scope')
 roles,meta,_=E.render_layers(cfg,n);return E.composite(roles),roles,meta
def render_mp4(cfg,output_dir):
 out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);silent=out/'silent.mp4';final=out/'final.mp4';ff=cfg.get('ffmpeg','ffmpeg')
 cmd=[ff,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
 enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
 try:
  for n in range(cfg['frame_count']):enc.stdin.write(render_frame(cfg,n)[0].tobytes())
 finally:enc.stdin.close()
 if enc.wait()!=0:raise RuntimeError('Qingbai encode failed')
 mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)];subprocess.run(mux,check=True)
 _json(out/'compiled-input.json',cfg);_json(out/'render-receipt.json',dict(template_id=TEMPLATE_ID,final_sha256=_file_sha(final),source_sha256=_file_sha(cfg['source']),frames=cfg['frame_count'],size=[1080,1920],fps=25,encode_command=cmd,audio_command=mux,FA_calls=0,model_calls=0,whole_decode='host validates'))
 return final
