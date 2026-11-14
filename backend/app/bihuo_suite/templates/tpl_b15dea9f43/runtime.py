"""Business editorial: whole-scene iris, sliced vertical words, photo plane and stars."""
from pathlib import Path
import copy,hashlib,importlib.util,json,math,sys
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter,ImageChops
HERE=Path(__file__).resolve().parent
def load(name):
 key='_business_'+name+'_'+hashlib.sha256(str(HERE).encode()).hexdigest()[:8];s=importlib.util.spec_from_file_location(key,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);sys.modules[key]=m;s.loader.exec_module(m);return m
core=load('core');F=load('primitives');F.text_image=core.pilot.text_image
SAMPLES=[[120,950],[121,698],[122,484],[123,308],[124,172],[125,75],[126,9],[127,0],[129,0],[130,9],[131,75],[132,172],[133,308],[134,484],[135,698],[136,950]]
STARS=[[400,110],[702,122],[169,342],[896,296],[68,554],[953,571],[168,874],[613,1024],[333,1054],[911,842]]
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
 if tuple(size)!=(1080,1920)or not Path(source_path).is_file():raise ValueError('Actual portrait source/native1080 required')
 duration=float(resolved['duration']);f=core._style_fonts(fonts);rows=[];tokens=resolved.get('tokens')or[]
 for c in resolved.get('captions',[]):
  a,b=map(float,c.get('time',[c.get('start'),c.get('end')]))
  if not 0<=a<b<=duration+.05:raise ValueError('Invalid host FA caption bounds')
  ranges=[];offset=0
  for line in c.get('lines')or[dict(text=c['text'],emphasis_spans=[])]:
   if isinstance(line,dict):ranges.extend([[x+offset,y+offset]for x,y in line.get('emphasis_spans',[])]);offset+=len(line['text'])
   else:offset+=len(line)
  rows.append(dict(text=c['text'],frames=[math.ceil(a*25),math.ceil(b*25)],time=[a,b],emphasis_spans=ranges,lines=copy.deepcopy(c.get('lines')or[])))
 if not rows:raise ValueError('Actual complete FA captions required')
 opts=creative_options or{};features=resolved.get('features')or resolved.get('points')or[];iris_at=next((r['time'][1]for r in rows if r['time'][1]>=duration*.28),duration*.33);columns=[]
 # Real semantic emphasis anchors; character slices are visual phases, never invented FA.
 for r in rows:
  if r['time'][0]<iris_at:continue
  for a,b in r['emphasis_spans']:
   text=r['text'][a:b].strip('，。！？,.!?')
   if 1<=len(text)<=4:
    found=next((t for t in tokens if r['time'][0]-.05<=t['start_ms']/1000<r['time'][1] and str(t['text']).strip()and str(t['text'])in text),None);at=found['start_ms']/1000 if found else r['time'][0];columns.append(dict(text=text,start=at,end=min(r['time'][1]+.16,duration)))
  if len(columns)>=2:break
 columns=columns[:2];late_min=min([r['time'][0]for r in rows if r['time'][0]>iris_at]+[iris_at]);materials=[];ignored=[]
 for i,m in enumerate(resolved.get('materials',[])):
  span=m.get('spoken_span')or{};a=max(float(m['start']),float(span.get('start',m['start'])));b=min(float(m['end']),float(span.get('end',m['end'])),duration)
  if b<=late_min or a>=b:ignored.append(m['asset_id']);continue
  if not Path(m['path']).is_file()or(m.get('sha256')and core._sha(m['path'])!=m['sha256']):raise ValueError('Matched photo resource/SHA invalid')
  # Native late-photo mechanism starts on a complete clause; semantic bounds unchanged.
  visual=next((r['time'][0]for r in rows if max(a,late_min)<=r['time'][0]<b),max(a,late_min))
  materials.append(dict(asset_id=m['asset_id'],slot_id=str(i),path=m['path'],kind=m.get('kind','image'),start=a,end=b,visual_start=visual,spoken_span=span))
 card=opts.get('name_card')or opts.get('identity')or{};conclusion=resolved.get('conclusion')or{};stars_at=float((conclusion.get('first')or{}).get('start',resolved.get('quote_start')or duration*.84))
 return dict(schema='bihuo.business.production/1',template_id='tpl_b15dea9f43',mode='clean',source_path=str(source_path),source_sha256=core._sha(source_path),duration=duration,frames=max(round(duration*25),math.ceil(rows[-1]['time'][1]*25)),fps=25,size=list(size),ffmpeg=str(ffmpeg),fonts=dict(body=f['caption']),captions=rows,materials=materials,unused_asset_ids=ignored,title=core._text(opts.get('title'))or core._text(resolved.get('title')),support=core._text(opts.get('subtitle'))or core._text(resolved.get('subtitle')),support_suffix='',opening_end=float(resolved.get('opening_end')or 3),identity=dict(enabled=bool(card.get('enabled',False)),name=core._text(card.get('name')),description=core._text(card.get('description'))),iris_at=iris_at,columns=columns,stars_at=stars_at,star_count=10,tail_fade=[duration-.48,duration],limits=['Source author raw/fonts/curve and recovered photo hidden caption pixels unavailable.','Native photo mechanism is late; early asset IDs do not force a new native slot.','Room-video circle, no synthetic head alpha.'])
def _fittext(text,cfg,size,color,width,stroke=3):
 while size>=28:
  im=F.tile(text,cfg,size,color,stroke)
  if im.width<=width:return im
  size-=2
 raise ValueError('Text requires semantic replanning')
def _titles(cfg,n):
 out={k:F.blank()for k in['title_shadow','title_main','title_support']};t=n/25;end=cfg['opening_end'];q=F.ramp(t,.04,.36)*(1-F.ramp(t,max(.4,end-.36),end));sq=F.ramp(t,.84,1.08)*(1-F.ramp(t,max(1.1,end-.52),max(1.2,end-.32)))
 if cfg.get('reference_mode'):return F.titles(dict(cfg,mode='baseline'),n)
 if cfg['title']:
  im=_fittext(cfg['title'],cfg,110,'white',1020,5);out['title_main'].alpha_composite(im,((1080-im.width)//2,164));out['title_main']=F.fade(out['title_main'],q)
 if cfg['support']:
  im=_fittext(cfg['support'],cfg,90,(234,203,109,255),970);out['title_support'].alpha_composite(im,(94,342));out['title_support']=F.fade(out['title_support'],sq)
 for key in['title_main','title_support']:
  sh=Image.new('RGBA',(1080,1920),(0,0,0,255));sh.putalpha(out[key].getchannel('A').point(lambda z:round(z*.75)));out['title_shadow'].alpha_composite(ImageChops.offset(sh,5,6))
 return out
def _caps(cfg,n):
 out={k:F.blank()for k in['caption_shadow','caption_body','caption_emphasis']};r=next((r for r in cfg['captions']if r['frames'][0]<=n<r['frames'][1]),None)
 if not r:return out,{}
 text=r['text'];size=84;ranges=r['emphasis_spans'];full=F.tile(text,cfg,size,'white',3);cuts=[len(text)]
 if full.width>1044:
  target=len(text)//2;candidates=[b for a,b in ranges if 2<=b<len(text)-1];cut=min(candidates,key=lambda x:abs(x-target))if candidates else target;cuts=[cut,len(text)]
 start=0;y=1574 if len(cuts)==1 else 1508
 for end in cuts:
  segments=[];k=start
  for a,b in ranges:
   a=max(a,start);b=min(b,end)
   if a>=b:continue
   if k<a:segments.append((text[k:a],False))
   segments.append((text[a:b],True));k=b
  if k<end:segments.append((text[k:end],False))
  tiles=[(F.tile(s,cfg,size,(235,203,103,255)if mark else'white',3),mark)for s,mark in segments if s];width=sum(v.width for v,m in tiles)
  while width>1044 and size>42:
   size-=2;tiles=[(F.tile(s,cfg,size,(235,203,103,255)if mark else'white',3),mark)for s,mark in segments if s];width=sum(v.width for v,m in tiles)
  x=(1080-width)/2
  for im,mark in tiles:
   out['caption_emphasis'if mark else'caption_body'].alpha_composite(im,(round(x),y));shadow=Image.new('RGBA',im.size,(0,0,0,255));shadow.putalpha(im.getchannel('A').point(lambda z:round(z*.8)));out['caption_shadow'].alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)),(round(x+4),y+6));x+=im.width
  start=end;y+=size+20
 q=min(1,max(0,(n-r['frames'][0]+1)/8))
 if r.get('slide_entry'):
  p=core.pilot.ease(r['frames'][0],r['frames'][0]+14,n);dx=round(210*(1-p))
  for k,im in out.items():
   moved=F.blank();moved.alpha_composite(im,(dx,0));mask=Image.new('L',(1080,1920));ImageDraw.Draw(mask).rectangle((r.get('clip_left',30),0,1079,1919),fill=255);moved.putalpha(ImageChops.multiply(moved.getchannel('A'),mask));out[k]=moved
 return{k:F.fade(v,q)for k,v in out.items()},dict(text=text,frames=r['frames'],line_count=len(cuts))
@lru_cache(maxsize=1)
def _grid():
 im=Image.new('RGBA',(1080,1920),(9,11,15,255));d=ImageDraw.Draw(im)
 for x in range(-2000,3201,220):d.line((540,960,x,1920),fill=(45,49,58,170),width=2);d.line((540,960,x,0),fill=(45,49,58,170),width=2)
 for y in[80,340,550,710,830,900,1015,1080,1190,1350,1550,1800]:d.line((0,y,1080,y),fill=(45,49,58,170),width=2)
 return im
def _room(cfg,n,small):
 raw=core.media._sample(dict(path=cfg['source_path'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n,25).convert('RGB')
 if cfg.get('reference_mode'):
  a=np.array(raw);mask=np.zeros((1920,1080),np.uint8);mask[1520:1740,60:1030]=255
  if 238<=n<286:mask[100:780,:]=255
  a=cv2.inpaint(a,mask,3,cv2.INPAINT_TELEA);raw=Image.fromarray(a)
  if n>=323:raw=raw.crop((354,194,726,564)).resize((1080,1920),Image.Resampling.LANCZOS)
 if small>0:
  box=np.array([0,0,1080,1920])*(1-small)+np.array([354,194,372,370])*small
 else:box=[0,0,1080,1920]
 x,y,w,h=box;texture=core.media._fit(raw.convert("RGBA"),round(w),round(h),dict(fit='cover',anchor=[.5,.36])).resize((1080,1920),Image.Resampling.LANCZOS);rad=185*small
 key=dict(time=0,matrix=[[w/1080,0,x/2],[0,h/1920,y/2]],rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=rad/2,background_opacity=0)
 out=core.visual.render('V02',texture,n,dict(size=[1080,1920],fps=25,visual_keys=[key]))['presenter'];border=F.blank()
 if small:ImageDraw.Draw(border).rounded_rectangle((x,y,x+w,y+h),radius=rad,outline=(255,255,255,round(255*small)),width=4)
 return out,border
def _columns(cfg,n):
 out=F.blank();t=n/25
 for i,c in enumerate(cfg['columns']):
  if not c['start']<=t<c['end']:continue
  x=820 if i==0 else 74;y=132 if i==0 else 246;step=195 if i==0 else 180
  for j,ch in enumerate(c['text']):
   im=F.tile(ch,cfg,180,(235,203,103,255)if i==0 and j>0 else'white',4);p=F.ramp(t,c['start']+j*.04,c['start']+j*.04+.12);im=im.crop((0,0,im.width,max(1,round(im.height*p))));out.alpha_composite(im,(x,y+j*step))
  out=F.fade(out,1-F.ramp(t,c['end']-.28,c['end']))
 return out
def _photo(cfg,n):
 t=n/25;m=next((m for m in cfg['materials']if m['visual_start']<=t<m['end']+.08),None)
 if not m:return F.blank(),0,None
 q=core.pilot.ease(m['visual_start'],m['visual_start']+.48,t);exit=1-core.pilot.ease(m['end']-.48,m['end']+.08,t);raw=core.media._sample(dict(path=m['path'],type=m['kind'],start_frame=math.ceil(m['visual_start']*25),source_in=0,speed=1,end_policy='hold'),n,25).convert('RGBA');fill=core.media._fit(raw,964,992,dict(fit='cover')).filter(ImageFilter.GaussianBlur(18));fill.alpha_composite(core.media._fit(raw,964,992,dict(fit='contain')));mask=Image.new('L',fill.size);ImageDraw.Draw(mask).rounded_rectangle((0,0,963,991),radius=40,fill=255);fill.putalpha(mask)
 src=np.float32([[0,0],[963,0],[963,991],[0,991]]);target=np.float32([[54,608],[1018,608],[1018,1600],[54,1600]]);initial=np.float32([[-710,704],[120,616],[254,1590],[-540,1455]]);dst=initial*(1-q)+target*q;mat=cv2.getPerspectiveTransform(src,dst);arr=cv2.warpPerspective(np.array(fill),mat,(1080,1920),borderMode=cv2.BORDER_CONSTANT);return F.fade(Image.fromarray(arr),exit),min(1,q+.1)*exit,m['asset_id']
def _stars(cfg,n):
 t=n/25;s=core.pilot.ease(cfg['stars_at'],cfg['stars_at']+.28,t)*(1-core.pilot.ease(cfg['stars_at']+.68,cfg['stars_at']+.92,t));im=F.blank();d=ImageDraw.Draw(im)
 for i,(x,y)in enumerate(STARS[:cfg.get('star_count',10)]):
  r=(66 if i%3 else 88)*s;pts=[]
  tips=[np.array(v,float)for v in[(0,-1),(1,0),(0,1),(-1,0)]]
  for a,b in zip(tips,tips[1:]+tips[:1]):
   for u in np.linspace(0,1,12,endpoint=False):v=((1-u)**2*a+2*(1-u)*u*(a+b)*.16+u*u*b)*r;pts.append((x+v[0],y+v[1]))
  if s>0:d.polygon(pts,fill=(252,197,45,240)if i%2==0 else(70,205,224,240));d.line(pts+[pts[0]],fill=(25,31,35,255),width=max(1,round(s*4)));d.ellipse((x+12*s,y+10*s,x+19*s,y+17*s),fill='white')
 return im
def render_layers(cfg,n):
 photo,small,asset=_photo(cfg,n);t=n/25
 if cfg.get('reference_mode'):
  small=core.pilot.ease(323,335,n)*(1-core.pilot.ease(475,488,n))
 presenter,border=_room(cfg,n,small);roles=dict(background=_grid().copy(),presenter=presenter,presenter_border=border,material=photo);roles.update(_titles(cfg,n));roles['identity']=F.identity(cfg,n);roles['vertical_words']=_columns(cfg,n);cap,meta=_caps(cfg,n);roles.update(cap);roles['stars']=_stars(cfg,n)
 # Iris gates the WHOLE sharp scene, including typography, against its blurred composite.
 phase=(n if cfg.get('reference_mode')else n-round(cfg['iris_at']*25)+120);radius=None
 if 120<=phase<=136:
  radius=float(F.lerp([[a,[v]]for a,v in SAMPLES],phase)[0]);sharp=F.blank()
  for v in roles.values():sharp.alpha_composite(v)
  gate=Image.new('L',(1080,1920));ImageDraw.Draw(gate).ellipse((540-radius,884-radius,540+radius,884+radius),fill=255)
  roles['background']=sharp.filter(ImageFilter.GaussianBlur(42))
  for k in list(roles)[1:]:roles[k].putalpha(ImageChops.multiply(roles[k].getchannel('A'),gate))
 fade=core.pilot.ease(*cfg['tail_fade'],t);roles['whole_rgb_fade']=Image.new('RGBA',(1080,1920),(0,0,0,round(fade*255)))
 return roles,dict(frame=n,caption=meta,matched_asset_id=asset,room_circle=small,whole_composition_iris_radius=radius,native_head_alpha=False)
def composite(roles):
 out=F.blank()
 for v in roles.values():out.alpha_composite(v)
 return out.convert('RGB')
def render_mp4(cfg,output_dir):
 core.render_layers=render_layers;core.composite=composite;return core.render_mp4(cfg,output_dir)
