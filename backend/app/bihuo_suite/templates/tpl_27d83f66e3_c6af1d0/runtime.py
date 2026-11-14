"""Orange full composition: actual glyph FA + optional image/information phases."""
from pathlib import Path
import sys,json,copy,math,hashlib,importlib,types,subprocess
sys.dont_write_bytecode=True
HOME=Path(__file__).resolve().parent;PKG='_orange_delivery_'+hashlib.sha256(str(HOME).encode()).hexdigest()[:12]
if PKG not in sys.modules:
 p=types.ModuleType(PKG);p.__path__=[str(HOME)];sys.modules[PKG]=p
E=importlib.import_module(PKG+'.orange_engine');TEMPLATE_ID='tpl_27d83f66e3_c6af1d0'
def _file_sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def _json(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def compile_request(resolved, *, source_path, fonts, creative_options, ffmpeg='ffmpeg', size=(1080,1920)):
 if tuple(size)!=(1080,1920) or not Path(source_path).is_file():raise ValueError('Orange requires1080x1920 and existing clean source')
 duration=float(resolved['duration']);count=round(duration*25)
 if not math.isfinite(duration) or duration<=0 or count<2:raise ValueError('Invalid duration')
 options=creative_options or {};card=options.get('name_card') or options.get('identity') or {};name=str(card.get('name','') or '').strip();desc=str(card.get('description','') or '').strip();enabled=bool(card.get('enabled',True)) and bool(name or desc)
 ff={r:str(Path(fonts.get(r) or fonts.get('caption' if r=='body' else 'bold') or HOME/'fonts'/f).resolve()) for r,f in [('body','simkai.ttf'),('title','msyhbd.ttc')]}
 if not all(Path(p).is_file() for p in ff.values()):raise ValueError('Font missing')
 if enabled and (E.ink(name,ff['body'],54,(255,255,255,255)).width>=290 or E.ink(desc,ff['body'],34,(255,255,255,255)).width>=290):raise ValueError('Shorter supplied identity required')
 title=str(options.get('title') or resolved.get('title') or '').strip();support=str(options.get('subtitle') or resolved.get('subtitle') or '').strip()
 if E.font(ff['title'],110).getlength(title)>925 or E.font(ff['title'],28).getlength(support)>860:raise ValueError('Shorter Orange title/support required')
 tokens=resolved.get('tokens',[])
 if not tokens:raise ValueError('Original FA tokens required for progressive glyphs')
 positions={t['id']:i for i,t in enumerate(tokens)};captions=[];expected=0
 for i,row in enumerate(resolved.get('captions',[])):
  a=positions[row['first_token_id']];b=positions[row['last_token_id']]
  if a!=expected or b<a:raise ValueError('Full caption FA coverage must be once in source order')
  selected=tokens[a:b+1];expected=b+1;text=''.join(t['text'] for t in selected);lines=row.get('lines') or [dict(text=row['text'],emphasis_spans=[])]
  if text!=row['text'] or ''.join(x['text'] for x in lines)!=text or len(lines)>2:raise ValueError('Complete linguistic lines must retain bound FA token text')
  start=selected[0]['start_ms']/40;end=selected[-1]['end_ms']/40
  if not 0<=start<end<=duration*25+1 or math.ceil(end)-1<math.ceil(start):raise ValueError('Zero-frame cue; merge upstream without moving FA')
  breaks=[];cursor=0
  for line in lines:cursor+=len(line['text']);breaks.append(cursor)
  captions.append(dict(id=f'N{i+1:02}',text=text,range=[start,end],glyph_firsts=[t['start_ms']/40 for t in selected for _ in t['text']],emphasis_spans=[],line_breaks=breaks[:-1],FA_tokens=selected))
 if not captions or expected!=len(tokens):raise ValueError('Captions miss full FA transcript')
 body=108
 while body>=58:
  if all(E.font(ff['body'],body).getlength(c['text'][a:b])<=1035 for c in captions for a,b in zip([0]+c['line_breaks'],c['line_breaks']+[len(c['text'])])):break
  body-=2
 if body<58:raise ValueError('Caption needs semantic line break')
 phases=[];materials=[]
 for m in sorted(resolved.get('materials',[]),key=lambda q:q['start']):
  if m.get('enabled') is False:continue
  if not m.get('asset_id') or not Path(m.get('path','')).is_file():raise ValueError('Actual matched material ID/path required')
  if m.get('kind','image')!='image':raise ValueError('Current Orange still-card profile requires images')
  if m.get('sha256') and _file_sha(m['path'])!=m['sha256']:raise ValueError('Material SHA changed')
  a=math.ceil(float(m['start'])*25);b=math.ceil(float(m['end'])*25)
  if not 0<=a<b<=count:raise ValueError('Material outside source clock')
  index=len(phases);materials.append(dict(id=m['asset_id'],path=str(Path(m['path']).resolve()),semantic_segment=index,sha256=m.get('sha256')))
  spoken=[c for c in resolved['captions'] if c['time'][0]<float(m['end']) and float(m['start'])<c['time'][1]]
  phases.append(dict(id='semantic-media-'+str(index),enabled=True,asset_id=m['asset_id'],note_title=spoken[0]['text'] if spoken else '',note_detail=spoken[1]['text'] if len(spoken)>1 else '',example='实际上传示例',background_entry=[max(0,a-7),max(1,a-1)],person_entry=[max(0,a-6),a+16],entry=[a,a+16],exit=[b,b+9],background_exit=[b,b+11]))
 # Actual meaningful text spans can survive missing pictures; no asset-count inference.
 for row in resolved.get('points',[])+resolved.get('features',[]):
  if not str(row.get('text','')).strip():continue
  a=math.ceil(float(row['start'])*25);b=math.ceil(float(row['end'])*25)
  if not 0<=a<b<=count:raise ValueError('Information span outside source clock')
  if any(p['entry'][0]<=a<p['exit'][1] for p in phases):continue
  index=len(phases);phases.append(dict(id='semantic-text-'+str(index),enabled=True,asset_id=None,note_title=row['text'],note_detail='',example='',background_entry=[a,a+6],person_entry=[max(0,a-13),max(1,a-1)] if index in [2,3] else [a,a+16],entry=[a,a+16],exit=[b,b+9],background_exit=[b,b+11]))
 for s in phases:
  for text in [s['note_title'],s['note_detail']]:
   if E.font(ff['title'],28).getlength(text)>560:raise ValueError('Information card needs shorter semantic wording')
 opening=max(2,round(float(resolved.get('opening_end',2.51))*25))
 return dict(mode='replacement',source=str(Path(source_path).resolve()),duration=duration,frame_count=count,ffmpeg=str(ffmpeg),fonts=ff,title=title,support=support,title_events=dict(entry=[4,12],exit=[max(1,opening-8),opening]),identity=dict(enabled=enabled,name=name if enabled else '',description=desc if enabled else '',entry=[3,9],exit=[max(1,opening-10),max(2,opening-4)]),captions=captions,body_size=body,caption_baseline=1640,caption_line_gap=124,phases=phases,materials=materials,selected_asset_ids=list(dict.fromkeys(m['id'] for m in materials)),actual_image_asset_ids=list(dict.fromkeys(m['id'] for m in materials)),unused_material_ids=[],fade_start=max(0,count-13),black_at=count-1,resolved_plan=copy.deepcopy(resolved))
def render_frame(cfg,n):
 if not 0<=n<cfg['frame_count']:raise ValueError('Frame outside scope')
 roles,meta,_=E.render_layers(cfg,n);return E.composite(roles),roles,meta

def render_mp4(cfg, output_dir):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    silent=out/'silent.mp4';final=out/'final.mp4';ff=cfg['ffmpeg']
    cmd=[ff,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-an','-c:v','libx264','-threads','3','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    enc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=(out/'encode.log').open('wb'))
    try:
        for n in range(cfg['frame_count']):
            rgb,roles,_=render_frame(cfg,n);enc.stdin.write(rgb.tobytes())
    finally:enc.stdin.close()
    if enc.wait()!=0:raise RuntimeError('Orange encoding failed; see encode.log')
    # One encode from the actual input sound; no time remap or video-speed change.
    mux=[ff,'-v','error','-y','-i',str(silent),'-i',cfg['source'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(cfg['duration']),'-movflags','+faststart',str(final)]
    subprocess.run(mux,check=True)
    _json(out/'compiled-input.json',cfg)
    _json(out/'render-receipt.json',{'template_id':TEMPLATE_ID,'final_sha256':_file_sha(final),'source_sha256':_file_sha(cfg['source']),'frames':cfg['frame_count'],'fps':25,'size':[1080,1920],'whole_decode':'host validates','encode_command':cmd,'audio_command':mux,'inference_calls':0,'FA_calls':0,'audio':'Original source audio without retiming; AAC192k one encode','unused_material_ids':cfg['unused_material_ids']})
    return final
