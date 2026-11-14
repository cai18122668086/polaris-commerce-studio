"""Yuanfeng native text UI: serif captions, list, yellow rule, typed browser, steps."""
from pathlib import Path
import copy,hashlib,importlib.util,json,math,sys
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter,ImageOps
HERE=Path(__file__).resolve().parent
def _load(name,file):
 key='_yuanfeng_'+name+'_'+hashlib.sha256(str(HERE).encode()).hexdigest()[:8];s=importlib.util.spec_from_file_location(key,HERE/file);m=importlib.util.module_from_spec(s);sys.modules[key]=m;s.loader.exec_module(m);return m
core=_load('core','core.py');F=_load('shapes','primitives.py');F.text_image=core.pilot.text_image;F.font=core.pilot.font;F.V=core.visual;F.T=F;F.word_tile=lru_cache(maxsize=512)(F.word_tile)
def _clean(text):return str(text or '').strip(' ，。！？,.!?')
def _events(tokens,text,first=None,last=None):
 items=tokens
 if first is not None:
  index={t['id']:i for i,t in enumerate(tokens)}
  if first not in index or last not in index:raise ValueError('Host FA token anchors missing')
  items=tokens[index[first]:index[last]+1]
 result=[dict(glyph=ch,start=t['start_ms']/1000,end=t['end_ms']/1000,token_id=t['id'])for t in items for ch in t['text']if ch not in' ，。！？,.!?']
 target=_clean(text)
 if ''.join(e['glyph']for e in result)!=target:raise ValueError('Typed text does not match real FA token text')
 return result
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
 if tuple(size)!=(1080,1920)or not Path(source_path).is_file():raise ValueError('Actual native portrait source required')
 duration=float(resolved['duration']);tokens=resolved.get('tokens',[]);rows=[];positions={v['id']:i for i,v in enumerate(tokens)};f=core._style_fonts(fonts);captions=resolved.get('captions',[])
 for c in captions:
  a,b=map(float,c.get('time',[c.get('start'),c.get('end')]))
  if not 0<=a<b<=duration+.05:raise ValueError('Caption outside actual FA duration')
  line=c.get('lines')or[dict(text=c['text'],emphasis_spans=[])];text=c['text'];ranges=[];offset=0
  for v in line:
   if isinstance(v,dict):ranges.extend([[a+offset,b+offset]for a,b in v.get('emphasis_spans',[])]);offset+=len(v['text'])
   else:offset+=len(v)
  rows.append(dict(text=text,frames=[math.ceil(a*25),math.ceil(b*25)],time=[a,b],lines=copy.deepcopy(line),emphasis_spans=ranges))
 if not rows:raise ValueError('Complete host FA captions required')
 opt=creative_options or{};title=core._text(opt.get('title'))or core._text(resolved.get('title'));opening_end=float(resolved.get('opening_end')or min(duration*.16,3));points=copy.deepcopy(resolved.get('points')or[]);features=copy.deepcopy(resolved.get('features')or[])
 if not points:
  for m in resolved.get('materials',[]):
   text=next((c['text'][a:b]for c in rows if float(m['start'])-.1<=c['time'][0]<float(m['end'])for a,b in c['emphasis_spans']),None)
   if text:points.append(dict(text=text,start=float(m['start']),end=float(m['end'])))
 if len(points)>4 or len(features)>4:raise ValueError('Yuanfeng supports at most4 readable list/step nodes; host replan required')
 theme=None
 for c in captions:
  if c['time'][0]<duration*.25:continue
  spans=c.get('emphasis_token_spans')or[]
  if spans:
   a,b=[positions.get(spans[0][k])for k in['first_token_id','last_token_id']]
   if a is not None and b is not None:
    ts=tokens[a:b+1];text=_clean(''.join(t['text']for t in ts));theme=dict(text=text,events=_events(ts,text),small='',start=ts[0]['start_ms']/1000-.12,end=c['time'][1]+.32);break
 if theme is None:theme=dict(text='',events=[],small='',start=duration*.27,end=duration*.36)
 chosen=[c for c in captions if c['time'][0]>=theme['end']-.1][:2];browser_lines=[]
 for c in chosen:browser_lines.append(dict(text=_clean(c['text']),events=_events(tokens,c['text'],c['first_token_id'],c['last_token_id']),start=c['time'][0]))
 browser_start=browser_lines[0]['start']-.12 if browser_lines else duration*.42;browser_end=chosen[-1]['time'][1]+.24 if chosen else duration*.56
 if not features:
  features=[dict(text=_clean(c['text']),start=c['time'][0],end=c['time'][1])for c in captions if c['time'][0]>=max(browser_end,duration*.65)][:4]
 steps_start=features[0]['start']-.24 if features else browser_end;card=opt.get('name_card')or opt.get('identity')or{}
 return dict(schema='bihuo.yuanfeng.production/1',template_id='fk-1021-news-yuanfeng',source_path=str(source_path),source_sha256=core._sha(source_path),duration=duration,frames=max(round(duration*25),math.ceil(rows[-1]['time'][1]*25)),fps=25,size=list(size),ffmpeg=str(ffmpeg),fonts=dict(body=f['caption'],row=fonts.get('row')or f['caption'],heading=f['title']),mode='clean',captions=rows,title=title,initial_items=points,opening_end=opening_end,theme=theme,browser=dict(start=browser_start,end=browser_end,lines=browser_lines),steps=dict(start=steps_start,title=title,items=features),identity=dict(enabled=bool(card.get('enabled',False)),name=core._text(card.get('name')),description=core._text(card.get('description'))),caption_body_size=68,caption_emphasis_size=80,tail_fade=[max(0,duration-.48),duration],reference_mode=False,unused_material_ids=[m.get('asset_id')for m in resolved.get('materials',[])],limits=['Native0 picture slots: material semantics inform text topics but no arbitrary uploaded image is drawn.','TextUI progressive births use true token starts; native-source observed typography retains separate visual clock.','Author font/glow/type timing curves unknown; original serif/calligraphic profile is preserved as candidate.'])
@lru_cache(maxsize=1)
def background():
 yy=np.arange(1920)[:,None,None]/1919;a=np.array([28,10,66])*(1-yy)+np.array([62,23,111])*yy;arr=np.broadcast_to(a,(1920,1080,3)).copy().astype(np.uint8);arr[:,::60]=[65,35,107];arr[::60,:]=[65,35,107];return Image.fromarray(arr).convert('RGBA')
def _pose(cfg,n):
 t=n/25;first=np.array([129,710,951,1402]);large=np.array([98,480,983,1365]);small=np.array([263,968,817,1705]);opening_end=cfg['opening_end'];q=core.pilot.ease(opening_end,opening_end+.68,t)if cfg['initial_items']or cfg['title']else 1;box=first*(1-q)+large*q
 if t>=cfg['browser']['start']-.08:q=core.pilot.ease(cfg['browser']['start']-.08,cfg['browser']['start']+.44,t);box=large*(1-q)+small*q
 return [round(v)for v in box]
def _person(cfg,n,box):
 raw=core.media._sample(dict(path=cfg['source_path'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n,25).convert('RGB');x,y,z,w=box
 if cfg.get('reference_mode'):
  ar=np.asarray(raw).copy();mask=np.zeros((1920,1080),np.uint8);mask[1540:1730,50:1030]=255;ar=cv2.inpaint(ar,mask,3,cv2.INPAINT_TELEA);texture=Image.fromarray(ar).crop((x+4,y+4,z-4,w-4)).resize((1080,1920),Image.Resampling.LANCZOS)
 else:texture=ImageOps.fit(raw,(z-x,w-y),method=Image.Resampling.LANCZOS).resize((1080,1920),Image.Resampling.LANCZOS)
 key=dict(time=0,matrix=[[(z-x)/1080,0,x/2],[0,(w-y)/1920,y/2]],rect=[v/2 for v in box],radius=10,background_opacity=0);person=core.visual.render('V02',texture,0,dict(size=[1080,1920],fps=25,visual_keys=[key]))['presenter'];border=F.blank();ImageDraw.Draw(border).rounded_rectangle((x-2,y-2,z+2,w+2),radius=22,outline=(100,225,246,255),width=4);mask=Image.new('L',(1080,1920));ImageDraw.Draw(mask).rounded_rectangle((x-4,y-4,z+4,w+4),radius=22,outline=255,width=11);glow=Image.new('RGBA',(1080,1920),(30,212,255,0));glow.putalpha(mask.filter(ImageFilter.GaussianBlur(13)).point(lambda a:min(255,round(a*2.5))));return dict(presenter_glow=glow,presenter_border=border,presenter=person)
def _put(out,text,path,point,x,y,color):
 if not text:return
 im=F.tile(text,path,point,color);out.alpha_composite(im,(round(x),round(y)))
def _fit(text,path,point,width):
 while point>22 and core.pilot.font(path,point).getlength(text)>width:point-=1
 if core.pilot.font(path,point).getlength(text)>width:raise ValueError('TextUI needs shorter semantic host phrase')
 return point
def _typed(out,row,path,point,x,y,color,t):
 text=row['text'];point=_fit(text,path,point,820);x=float(x)
 for event in row['events']:
  if t>=event['start']:_put(out,event['glyph'],path,point,x,y,color)
  x+=core.pilot.font(path,point).getlength(event['glyph'])
def _ui(cfg,n):
 t=n/25;out={k:F.blank()for k in['list_plate','list_heading','list_rows','topic_rule','topic_glyphs','browser_plate','browser_text','steps_plate','steps_text']};q=core.pilot.ease(0,.44,t)*(1-core.pilot.ease(cfg['opening_end']-.1,cfg['opening_end']+.24,t));items=cfg['initial_items']
 if (items or cfg['title'])and q>0:
  ImageDraw.Draw(out['list_plate']).rounded_rectangle((72,200,1008,691),radius=42,fill=(250,250,247,255));_put(out['list_heading'],cfg['title'],cfg['fonts']['heading'],_fit(cfg['title'],cfg['fonts']['heading'],52,818),128,258,(15,15,15,255))
  for i,row in enumerate(items):
   reveal=min(cfg['opening_end']-.2,.24+i*.42);current=t>=reveal;yy=365+i*96
   if i<len(items)-1:ImageDraw.Draw(out['list_plate']).line((128,yy+74,946,yy+74),fill=(149,149,145,255),width=2)
   if current:_put(out['list_rows'],row['text'],cfg['fonts']['row'],_fit(row['text'],cfg['fonts']['row'],38,818),128,yy,(153,104,56,255)if i==min(len(items)-1,max(0,int((t-.24)/.42)))else(20,20,20,255))
  for key in['list_plate','list_heading','list_rows']:out[key]=F.fade(out[key],q)
 theme=cfg['theme'];q=core.pilot.ease(theme['start'],theme['start']+.12,t)*(1-core.pilot.ease(theme['end']-.48,theme['end'],t))
 if theme['text']and q>0:
  ImageDraw.Draw(out['topic_rule']).rectangle((125,325,138,443),fill=(255,217,0,255));_typed(out['topic_glyphs'],theme,cfg['fonts']['row'],144,175,325,(255,255,255,255),t)
  if theme.get('small'):_put(out['topic_glyphs'],theme['small'],cfg['fonts']['row'],64,850,390,(255,255,255,255))
  out['topic_rule']=F.fade(out['topic_rule'],q);out['topic_glyphs']=F.fade(out['topic_glyphs'],q)
 browser=cfg['browser'];q=core.pilot.ease(browser['start'],browser['start']+.16,t)*(1-core.pilot.ease(browser['end']-.16,browser['end'],t))
 if browser['lines']and q>0:
  d=ImageDraw.Draw(out['browser_plate']);d.rounded_rectangle((72,370,1008,751),radius=42,fill=(250,250,247,255));d.line((72,482,1008,482),fill=(175,175,171,255),width=2)
  for x in[128,166,204]:d.ellipse((x,414,x+18,432),fill=(153,104,56,255))
  for i,row in enumerate(browser['lines']):_typed(out['browser_text'],row,cfg['fonts']['row'],60,128,532+i*98,(20,20,20,255)if i==0 else(153,104,56,255),t)
  out['browser_plate']=F.fade(out['browser_plate'],q);out['browser_text']=F.fade(out['browser_text'],q)
 steps=cfg['steps'];q=core.pilot.ease(steps['start'],steps['start']+.24,t)
 if (steps['items']or steps['title'])and q>0:
  d=ImageDraw.Draw(out['steps_plate']);d.rounded_rectangle((72,389,1008,732),radius=42,fill=(250,250,247,255));_put(out['steps_text'],steps['title'],cfg['fonts']['heading'],_fit(steps['title'],cfg['fonts']['heading'],52,818),128,431,(15,15,15,255));items=steps['items'];count=len(items);gap=828/max(1,count)
  for i,row in enumerate(items):
   x=128+i*gap;active=t>=float(row['start']);color=(153,104,56,255)if active and(i==count-1 or t<float(items[i+1]['start']))else(20,20,20,255)
   if active:_put(out['steps_text'],str(i+1),cfg['fonts']['row'],36,x,536,color);_put(out['steps_text'],row['text'],cfg['fonts']['row'],_fit(row['text'],cfg['fonts']['row'],36,gap-20),x,610,color)
   if i<count-1 and t>=float(items[i+1]['start']):d.line((x+gap-40,563,x+gap-18,563),fill=(153,104,56,255),width=3);d.line((x+gap-24,557,x+gap-18,563,x+gap-24,569),fill=(153,104,56,255),width=3)
  out['steps_plate']=F.fade(out['steps_plate'],q);out['steps_text']=F.fade(out['steps_text'],q)
 return out
def _captions(cfg,n):
 row=next((r for r in cfg['captions']if r['frames'][0]<=n<r['frames'][1]),None)
 if not row or len(row.get('lines',[]))<=1:return F.captions(cfg,n)[0]
 result={k:F.blank()for k in['caption_shadow','caption_body','caption_emphasis']};lines=row['lines']
 for i,line in enumerate(lines):
  cue=dict(row,text=line['text'],emphasis_spans=line.get('emphasis_spans',[]));local=dict(cfg,captions=[cue]);roles,_=F.captions(local,n)
  for k,im in roles.items():result[k].alpha_composite(im,(0,round(-(len(lines)-1)*44+i*88)))
 return result
def _identity(cfg,n):
 out=F.blank();r=cfg['identity'];t=n/25
 if not r['enabled']or not(r['name']or r['description'])or t>=cfg['opening_end']+.2:return out
 y=1261
 for text,point,bg,fg in[(r['name'],48,(247,206,66,255),(12,12,12,255)),(r['description'],29,(20,20,20,160),(255,255,255,255))]:
  if not text:continue
  tile=F.tile(text,cfg['fonts']['row'],point,fg)
  if tile.width>860:raise ValueError('Optional identity too wide')
  ImageDraw.Draw(out).rectangle((76,y,76+tile.width+12,y+tile.height+10),fill=bg);out.alpha_composite(tile,(82,y+5));y+=tile.height+17
 return out
def render_layers(cfg,n):
 box=_pose(cfg,n);ui=_ui(cfg,n);person=_person(cfg,n,box);plates={k:ui.pop(k)for k in['list_plate','browser_plate','steps_plate']};roles=dict(background=background().copy(),**plates,**person,**ui,identity=_identity(cfg,n),**_captions(cfg,n));roles['whole_scene_black']=Image.new('RGBA',(1080,1920),(0,0,0,round(255*core.pilot.ease(*cfg['tail_fade'],n/25))));return roles,dict(frame=n,presenter_box=box,native_picture_slots=0,initial_rows=len(cfg['initial_items']),steps=len(cfg['steps']['items']),typed_from_true_FA=not cfg.get('reference_mode'))
def composite(roles):
 out=F.blank()
 for im in roles.values():out.alpha_composite(im)
 return out.convert('RGB')
core.render_layers=render_layers;core.composite=composite
def render_mp4(cfg,output_dir):return core.render_mp4(cfg,output_dir)
