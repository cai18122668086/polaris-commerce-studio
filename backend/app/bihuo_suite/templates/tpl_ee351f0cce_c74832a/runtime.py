"""Qingci full suite: real FA glyph clocks and optional semantic media."""
from pathlib import Path
import copy,hashlib,importlib,json,math,subprocess,sys,types
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent
PKG='_qingci_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if PKG not in sys.modules:
 p=types.ModuleType(PKG);p.__path__=[str(HOME)];sys.modules[PKG]=p
E=importlib.import_module(PKG+'.qingci_engine')
TEMPLATE_ID='tpl_ee351f0cce_c74832a'
def _file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
 if tuple(size)!=(1080,1920):raise ValueError('Qingci supports1080x1920')
 if not Path(source_path).is_file():raise ValueError('Clean source missing')
 duration=float(resolved['duration']);count=round(duration*25)
 if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
 options=creative_options or {};card=options.get('name_card') or options.get('identity') or {}
 name=str(card.get('name','') or '').strip();desc=str(card.get('description','') or '').strip();enabled=bool(card.get('enabled',True)) and bool(name or desc)
 if len(name)>4:raise ValueError('Qingci vertical name allows4 glyphs')
 fontmap={key:str(Path(fonts.get(key) or fonts.get('caption' if key=='body' else 'bold') or HOME/'fonts'/fn).resolve()) for key,fn in [('body','simkai.ttf'),('title','msyhbd.ttc')]}
 if not all(Path(v).is_file() for v in fontmap.values()):raise ValueError('Font missing')
 if E.font(fontmap['body'],40).getlength(desc)>1080-(205 if name else 98)-30:raise ValueError('Identity description exceeds reading area')
 title=str(options.get('title') or resolved.get('title') or '').strip();support=str(options.get('subtitle') or resolved.get('subtitle') or '').strip()
 if E.font(fontmap['title'],100).getlength(title)>=1000:raise ValueError('Shorter Qingci title required')
 if E.font(fontmap['title'],24).getlength(support)>940:raise ValueError('Shorter support required')
 opening=max(2,round(float(resolved.get('opening_end',min(duration*.2,3)))*25))
 tokens=resolved.get('tokens')
 if not isinstance(tokens,list) or not tokens:raise ValueError('Qingci progressive caption requires original FA tokens, never evenly divided cue milliseconds')
 positions={t['id']:i for i,t in enumerate(tokens)};captions=[];expected=0
 for index,row in enumerate(resolved.get('captions',[])):
  a=positions[row['first_token_id']];b=positions[row['last_token_id']]
  if a!=expected or b<a:raise ValueError('Full caption token coverage must be once in source order')
  selected=tokens[a:b+1];expected=b+1;text=''.join(t['text'] for t in selected)
  if ''.join(text.split())!=''.join(str(row['text']).split()):raise ValueError('Caption text differs from its bound FA tokens')
  firsts=[float(t['start_ms'])/40 for t in selected for _ in t['text']]
  start=selected[0]['start_ms']/40;end=selected[-1]['end_ms']/40
  if not 0<=start<end<=duration*25+1 or math.ceil(end)-1<math.ceil(start):raise ValueError('Zero-frame or invalid cue; merge upstream without moving FA')
  lines=row.get('lines') or [dict(text=row['text'],emphasis_spans=[])]
  if ''.join(x['text'] for x in lines)!=text:raise ValueError('Planned lines must retain exact FA token text')
  breaks=[];spans=[];cursor=0
  for line in lines:
   spans.extend([[cursor+x,cursor+y] for x,y in line.get('emphasis_spans',[])])
   cursor+=len(line['text']);breaks.append(cursor)
  if len(lines)>2:raise ValueError('Qingci supports up to2 planned lines')
  captions.append(dict(id=f'N{index+1:02}',text=text,range=[start,end],glyph_firsts=firsts,emphasis_spans=spans,line_breaks=breaks[:-1],FA_tokens=selected))
 if expected!=len(tokens) or not captions:raise ValueError('Captions miss end of full FA transcript')
 style=dict(body_size=76,emphasis_size=90,glyph_entry_frames=5)
 # Respect the planner's linguistic lines; fit natural glyph advances as a unit.
 for body in range(76,49,-2):
  style.update(body_size=body,emphasis_size=body+14);fits=True
  for row in captions:
   cuts=[0]+row['line_breaks']+[len(row['text'])]
   widths=[sum(E.font(fontmap['body'],body+14 if any(x<=i<y for x,y in row['emphasis_spans']) else body).getlength(row['text'][i]) for i in range(a,b)) for a,b in zip(cuts,cuts[1:])]
   fits=fits and max(widths)<=1035
  if fits:break
 if not fits:raise ValueError('Caption needs semantic line break or shorter planned phrase')
 materials=[]
 for i,m in enumerate(sorted(resolved.get('materials',[]),key=lambda v:v['start'])):
  if m.get('enabled') is False:continue
  if not m.get('asset_id') or not Path(m.get('path','')).is_file():raise ValueError('Matched asset ID/path required')
  if m.get('sha256') and _file_sha(m['path'])!=m['sha256']:raise ValueError('Matched material SHA changed')
  start=round(float(m['start'])*25);end=round(float(m['end'])*25)
  if not 0<=start<end<=count:raise ValueError('Material interval outside source clock')
  kind=['street','night','book','window','city'][min(len(materials),4)]
  materials.append(dict(id=m['asset_id'],path=str(Path(m['path']).resolve()),sha256=m.get('sha256'),kind=kind,media_type=m.get('kind','image'),start=start,end=end))
 cfg=dict(mode='replacement',source=str(Path(source_path).resolve()),fonts=fontmap,title=title,support=support,name_card=dict(enabled=enabled,name=name if enabled else '',description=desc if enabled else ''),title_events=dict(entry=[2,9],exit=[max(1,opening-5),opening]),identity_events=dict(entry=[2,9],exit=[max(1,opening-5),opening+4]),captions=captions,caption_style=style,materials=materials,frame_count=count,duration=duration,fade_start=max(0,count-13),black_at=count-1,ffmpeg=str(ffmpeg),scopes={'full':[0,count]},actual_image_asset_ids=list(dict.fromkeys(m['id'] for m in materials)),unused_material_ids=[],template_id=TEMPLATE_ID,resolved_plan=copy.deepcopy(resolved))
 return cfg
def render_frame(cfg,n):
 if not 0<=n<cfg['frame_count']:raise ValueError('Frame outside scope')
 roles,meta=E.render_layers(cfg,n);return E.composite(roles),roles,meta
def render_mp4(cfg,output_dir):
 out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);silent=out/'silent.mp4';final=out/'final.mp4';ff=cfg.get('ffmpeg','ffmpeg')
 cmd=[ff,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
 enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
 try:
  for n in range(cfg['frame_count']):enc.stdin.write(render_frame(cfg,n)[0].tobytes())
 finally:enc.stdin.close()
 if enc.wait()!=0:raise RuntimeError('Qingci encode failed')
 mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)]
 subprocess.run(mux,check=True);_json(out/'compiled-input.json',cfg)
 _json(out/'render-receipt.json',dict(template_id=TEMPLATE_ID,final_sha256=_file_sha(final),source_sha256=_file_sha(cfg['source']),frames=cfg['frame_count'],size=[1080,1920],fps=25,encode_command=cmd,audio_command=mux,actual_image_asset_ids=cfg.get('actual_image_asset_ids',[]),FA_calls=0,model_calls=0,whole_decode='host validates'))
 return final
