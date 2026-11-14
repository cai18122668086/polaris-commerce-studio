"""Portable Copper full-suite runtime. Host supplies resolved transcript/media/fonts.

No fixed person, fixed transcript, model/provider or original finished pixels.
"""
from pathlib import Path
import copy,hashlib,importlib,importlib.util,json,math,subprocess,sys
from functools import lru_cache
import unicodedata
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageOps
HERE=Path(__file__).resolve().parent
PACKAGE='_bihuo_copper_pinned_v1'
if PACKAGE not in sys.modules:
 spec=importlib.util.spec_from_file_location(PACKAGE,HERE/'vendor/__init__.py',submodule_search_locations=[str(HERE/'vendor')]);module=importlib.util.module_from_spec(spec);sys.modules[PACKAGE]=module;spec.loader.exec_module(module)
pilot=importlib.import_module(PACKAGE+'.pilot');visual=importlib.import_module(PACKAGE+'.visual');media=importlib.import_module(PACKAGE+'.media')
def _sha(p):
 with Path(p).open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def _dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n','utf8')
def _blank():return Image.new('RGBA',(1080,1920))
def _text(t):return str(t or '').strip()
def _style_fonts(fonts):
 title=fonts.get('title')or fonts.get('main')or fonts.get('caption_bold');body=fonts.get('caption')or fonts.get('caption_bold')or fonts.get('body')or title
 if not title or not body or not Path(title).is_file()or not Path(body).is_file():raise ValueError('Existing host title/main and caption/body fonts required')
 return dict(title=str(title),caption=str(body))
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
 if tuple(size)!=(1080,1920):raise ValueError('Copper native1080x1920 required')
 if not Path(source_path).is_file():raise ValueError('Actual source video missing')
 duration=float(resolved['duration']);rows=[]
 if not math.isfinite(duration)or duration<=0:raise ValueError('Positive actual duration required')
 for i,c in enumerate(resolved.get('captions',[])):
  a,b=c.get('time',[c.get('start'),c.get('end')]);a=float(a);b=float(b)
  if not 0<=a<b<=duration+.05:raise ValueError('Caption outside actual source clock')
  text=_text(c.get('text'));lines=[_text(v.get('text')if isinstance(v,dict)else v)for v in c.get('lines',[])];lines=lines or[text]
  if text:rows.append(dict(id=f'caption-{i+1}',text=text,lines=lines,time=[a,b],tokens=[c.get('first_token_id'),c.get('last_token_id')],emphasis=copy.deepcopy(c.get('emphasis_token_spans',[]))))
 if not rows:raise ValueError('Host must resolve complete real FA caption rows')
 assets=[]
 for i,m in enumerate(resolved.get('materials',[])):
  span=m.get('spoken_span')or{};a=max(float(m['start']),float(span.get('start',m['start'])));b=min(float(m['end']),float(span.get('end',m['end'])),duration)
  if b<=a:continue
  path=m.get('path');kind=m.get('kind','image')
  if not path or not Path(path).is_file():raise ValueError('Matched material file missing')
  if m.get('sha256')and _sha(path)!=m['sha256']:raise ValueError('Matched material SHA mismatch')
  if kind not in['image','video']:raise ValueError('Copper supports real image/video material resources only')
  assets.append(dict(slot_id=f"{m.get('asset_id','asset')}-{i}",asset_id=m.get('asset_id'),path=str(path),kind=kind,sha256=_sha(path),start=a,end=b,spoken_span=copy.deepcopy(span),fit='contain'))
 opts=creative_options or{};identity=opts.get('name_card')or opts.get('identity')or{};name=_text(identity.get('name'));description=_text(identity.get('description'));enabled=bool(identity.get('enabled',False)and(name or description))
 title=_text(opts.get('title'))or _text(resolved.get('title'));opening_end=min(duration,float(resolved.get('opening_end')or min(2.5,duration*.15)))
 anchors=[float(c['time'])for c in resolved.get('chapters',[])if isinstance(c.get('time'),(int,float))and float(c['time'])>=duration*.45]
 candidates=[]
 for anchor in (anchors[:2]or[duration*.5,duration*.8]):
  row=next((r for r in rows if r['time'][0]>=anchor-.05),rows[-1])
  if row['id']not in candidates:candidates.append(row['id'])
 tokens=copy.deepcopy(resolved.get('tokens',[]));positions={v['id']:i for i,v in enumerate(tokens)}
 for row in rows:
  if row['id'] not in candidates:continue
  first,last=row['tokens']
  if first not in positions or last not in positions:raise ValueError('Actual host FA tokens required for Copper glyph rows')
  glyph_times=[]
  for token in tokens[positions[first]:positions[last]+1]:
   for char in token['text']:
    if not char.isspace()and not unicodedata.category(char).startswith('P'):glyph_times.append(dict(glyph=char,start=token['start_ms']/1000,end=token['end_ms']/1000,token_id=token['id']))
  row['glyph_times']=glyph_times
 cfg=dict(schema='bihuo.copper.production/1',template_id='tpl_d1772aff94',source_path=str(source_path),source_sha256=_sha(source_path),duration=duration,frames=max(round(duration*25),math.ceil(rows[-1]['time'][1]*25)),fps=25,size=list(size),fonts=_style_fonts(fonts),title=title,opening_end=opening_end,captions=rows,materials=assets,glyph_caption_ids=candidates,tokens=tokens,identity=dict(enabled=enabled,name=name,description=description),ffmpeg=str(ffmpeg),points=copy.deepcopy(resolved.get('points',[])),features=copy.deepcopy(resolved.get('features',[])),conclusion=copy.deepcopy(resolved.get('conclusion')),limits=['Author glyph angles/rest curves unknown; local12degree candidate retains stagger/whole-line distinction. Actual glyph birth clock uses host token starts, never equal division of a cue.','Only planned matched resource spans adopt upper-person/material layout; missing segments remain full oral scene.','Native Copper has no independent feature-card UI; complete caption rows retain all spoken content.'])
 return cfg
@lru_cache(maxsize=512)
def _ink(text,path,size,color,stroke=0,edge=(20,20,20,220)):
 im=pilot.text_image(text,path,size,color,stroke,edge)[0];box=im.getchannel('A').getbbox();return im.crop(box)if box else Image.new('RGBA',(1,1))
def _put(out,text,path,size,x,y,color,stroke=0,center=False,opacity=1):
 if not text:return
 im=_ink(text,path,size,tuple(color),stroke).copy()
 if opacity<1:im.putalpha(im.getchannel('A').point([round(v*max(0,opacity))for v in range(256)]))
 out.alpha_composite(im,(round(x-im.width/2)if center else round(x),round(y)))
def _lines(lines,path,size,width=1000):
 result=[]
 for text in lines:
  current=''
  for ch in text.strip('，。！？；,.!?;'):
   if current and pilot.font(path,size).getlength(current+ch)>width:result.append(current);current=ch
   else:current+=ch
  if current:result.append(current)
 if len(result)>2:raise ValueError('Caption requires host semantic replanning to at most2 natural lines')
 return result
def caption_layer(cfg,n):
 out=_blank();t=n/25;row=next((c for c in cfg['captions']if c['time'][0]<=t<c['time'][1]),None)
 if not row:return out
 path=cfg['fonts']['caption'];size=74;lines=_lines(row['lines'],path,size);animated=row['id']in cfg['glyph_caption_ids'];top=1600-(len(lines)-1)*43
 glyph_index=0
 for j,line in enumerate(lines):
  y=top+j*86;width=pilot.font(path,size).getlength(line);x=(1080-width)/2
  if animated:
   for i,ch in enumerate(line):
    if ch.isspace():x+=pilot.font(path,size).getlength(ch);continue
    punctuation=unicodedata.category(ch).startswith('P')
    if not row['glyph_times']:raise ValueError('Glyph row has no actual spoken FA tokens')
    event=row['glyph_times'][min(glyph_index if not punctuation else max(0,glyph_index-1),len(row['glyph_times'])-1)]
    if not punctuation:
     if ch!=event['glyph']:raise ValueError('Host glyph tokens do not match caption text')
     glyph_index+=1
    at=event['start'];q=pilot.ease(at,at+min(.14,max(.04,event['end']-at)),t);tile=_ink(ch,path,size,(255,255,255,255),2).copy();tile.putalpha(tile.getchannel('A').point([round(v*q)for v in range(256)]));tile=tile.rotate(-12*(1-q),resample=Image.Resampling.BICUBIC,expand=True);out.alpha_composite(tile,(round(x+(pilot.font(path,size).getlength(ch)-tile.width)/2),round(y+(size-tile.height)/2)));x+=pilot.font(path,size).getlength(ch)
  else:_put(out,line,path,size,540,y,(255,255,255,255),2,True,pilot.ease(row['time'][0]-.04,row['time'][0]+.24,t))
 return out
def render_layers(cfg,n):
 t=n/25;raw=media._sample(dict(path=cfg['source_path'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n,25).convert('RGB');raw=ImageOps.fit(raw,(1080,1920),method=Image.Resampling.LANCZOS);active=next((m for m in cfg['materials']if m['start']<=t<m['end']),None)
 bg=raw.filter(ImageFilter.GaussianBlur(30)).convert('RGBA');person=raw.convert('RGBA');picture=_blank();phase='oral-full'
 if active:
  x,y,w,h=292,246,496,320;texture=raw.filter(ImageFilter.GaussianBlur(24)).resize((w,h),Image.Resampling.LANCZOS).convert('RGBA')
  fit=ImageOps.contain(raw,(w,h),method=Image.Resampling.LANCZOS);texture.alpha_composite(fit.convert('RGBA'),((w-fit.width)//2,(h-fit.height)//2));canvas=Image.new('RGB',(1080,1920));canvas.paste(texture.convert('RGB'),(x,y));key=dict(time=0,matrix=[[1,0,0],[0,1,0]],rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=8,background_opacity=0);person=visual.render('V02',canvas,0,dict(size=[1080,1920],fps=25,visual_keys=[key],stage_color=[0,0,0]))['presenter']
  entry=dict(id=active['slot_id'],path=active['path'],type=active['kind'],start_frame=math.ceil(active['start']*25),source_in=0,speed=1,end_policy='hold',fit='contain',rect=[27,306.5,513,805],radius=10,entry_frames=4,entry_blur=4,audio='muted');picture=next(iter(media.render('V03',None,n,dict(size=[1080,1920],fps=25,media_entries=[entry])).values()));phase='upper-person-and-matched-material'
 headline=_blank();a=max(0,cfg['opening_end']-.24);q=pilot.ease(0,.28,t)*(1-pilot.ease(a,cfg['opening_end'],t))
 if cfg['title']and q>0:
  lines=_lines([cfg['title']],cfg['fonts']['title'],125,950)
  for j,line in enumerate(lines):_put(headline,line,cfg['fonts']['title'],125,540,117+j*132,(255,254,237,255),8,True,q)
 identity=_blank();card=cfg['identity']
 if card['enabled']:
  x=54
  for text,point,fill,ink in[(card['name'],38,(63,51,9,240),(255,254,237,255)),(card['description'],30,(255,254,237,240),(30,28,25,255))]:
   if not text:continue
   tile=_ink(text,cfg['fonts']['caption'],point,ink);w=tile.width+24
   if x+w>1026:raise ValueError('Optional identity exceeds reading width')
   box=Image.new('RGBA',(w,68));ImageDraw.Draw(box).rounded_rectangle((0,0,w-1,67),radius=18,fill=fill);box.alpha_composite(tile,(12,(68-tile.height)//2));identity.alpha_composite(box,(x,1760));x+=w+8
 return dict(background=bg,presenter=person,material=picture,headline=headline,caption=caption_layer(cfg,n),identity=identity),dict(frame=n,time=t,phase=phase,active_asset_id=active['asset_id']if active else None)
def composite(roles):
 out=_blank()
 for im in roles.values():out.alpha_composite(im)
 return out.convert('RGB')
def render_mp4(cfg,output_dir):
 out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);final=out/'final.mp4';digest=hashlib.sha256(json.dumps(cfg,ensure_ascii=False,sort_keys=True).encode()).hexdigest();receipt=out/'render-receipt.json'
 if final.exists():
  prior=json.loads(receipt.read_text('utf8'))if receipt.exists()else{}
  if prior.get('config_sha256')==digest and prior.get('final_sha256')==_sha(final):return final
  raise ValueError('Output exists for a different request; use a new directory')
 _dump(out/'input.json',cfg);ff=cfg.get('ffmpeg','ffmpeg');cmd=[ff,'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-i',cfg['source_path'],'-map','0:v:0','-map','1:a:0?','-t',str(cfg['frames']/25),'-c:v','libx264','-preset','veryfast','-threads','2','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',str(final)]
 with(out/'encode.log').open('wb')as log:
  process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
  try:
   for n in range(cfg['frames']):
    roles,meta=render_layers(cfg,n);rgb=composite(roles);process.stdin.write(rgb.tobytes())
  finally:process.stdin.close();code=process.wait();media.clear_cache()
  if code:raise RuntimeError('Copper encoder failed; see encode.log')
 _dump(receipt,dict(template_id=cfg['template_id'],config_sha256=digest,final_sha256=_sha(final),frames=cfg['frames'],fps=25,duration=cfg['frames']/25,host_decode_required=True,unretimed_source_audio=True,source_sha256=cfg['source_sha256'],complete_caption_rows=len(cfg['captions']),material_slots=len(cfg['materials']),encoder_command=cmd,source_raw_not_required=True));return final
