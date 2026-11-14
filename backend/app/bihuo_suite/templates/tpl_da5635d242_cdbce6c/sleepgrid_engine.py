"""Local Sleepgrid first-two adapter; source-only recovery and clean input separated."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import json,math
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter
H=Path(__file__).resolve().parent
C=H
from .vendor.apple_minimal import visual as V,media as M
from .vendor.apple_minimal.pilot import font,text_image
SIZE=(1080,1920)
MAIN='material-fe4af16e-0970-4b90-9ec2-ca29a175f736'
ROLES=['background','material_blur','material_clear','material_text','presenter_glow','presenter','topic','identity','caption_shadow','caption','leading_overlap']
def blank():return Image.new('RGBA',SIZE)
def ramp(n,a,b):return max(0.,min(1.,(n-a)/(b-a))) if b>a else float(n>=b)
def interp(n,keys):
 for (a,x),(b,y) in zip(keys,keys[1:]):
  if n<=b:return x+(y-x)*ramp(n,a,b)
 return keys[-1][1]
def op(im,q):
 if q>=1:return im
 im=im.copy();im.putalpha(im.getchannel('A').point(lambda a:round(a*max(0,q))));return im
@lru_cache(maxsize=1)
def recovery():return json.loads((H/'data/recovery.json').read_text('utf-8'))
@lru_cache(maxsize=1)
def poses():return {r['frame']:r for r in json.loads((H/'data/poster-poses.json').read_text('utf-8'))['rows']}
@lru_cache(maxsize=20)
def load(p):return Image.open(p).convert('RGBA')
@lru_cache(maxsize=1)
def grid():
 im=Image.new('RGBA',SIZE,(0,0,2,255));d=ImageDraw.Draw(im)
 used=[]
 for x0,y0,x1,y1 in json.loads((H/'data/grid-lines.json').read_text('utf-8'))['lines']:
  if abs(y1-y0)<3:
   y=round((y0+y1)/2)
   if any(abs(y-v)<5 for v in used):continue
   used.append(y);d.line((0,y,1079,y),fill=(65,65,67,255),width=1)
  else:
   vx=x1-x0;vy=y1-y0;points=[]
   for x in [0,1079]:
    if vx:
     y=y0+(x-x0)*vy/vx
     if 0<=y<=1919:points.append((x,y))
   for y in [0,1919]:
    x=x0+(y-y0)*vx/vy
    if 0<=x<=1079:points.append((x,y))
   if len(points)>=2:d.line(points[0]+points[-1],fill=(65,65,67,255),width=2)
 arr=np.array(im);fade=np.clip((np.abs(np.arange(1920)-960)-240)/400,0,1);arr[:,:,:3]=(arr[:,:,:3]*fade[:,None,None]).astype(np.uint8);im=Image.fromarray(arr)
 return im
def _old_match(cfg):
 if cfg['mode']=='baseline':return {'id':'source-sleep-poster','time':[79/25,217/25]}
 if cfg.get('material_disabled'):return None
 return next((m for m in cfg['materials'] if m['id']==MAIN and m['semantic']=='main-image-check' and Path(m['path']).is_file()),None)
def has_scene(cfg):return bool(match(cfg) or (not cfg.get('material_disabled') and any(str(t).strip() for t in cfg.get('material_texts',[]))))
def _old_native_frame(n,cfg):
 if cfg['mode']=='baseline':return n
 # Entry keyed to originalFA3.15. Drift/exit mapped to material speaking stage,
 # never shift originalFA/audio. Tiny leading prelude only after word6.97.
 if n<71:return n
 if n<=100:return n
 return interp(n,[(100,100),(145,150),(174,207),(184,216)])
def _old_person_box(cfg,n):
 if cfg['mode']=='new' and not has_scene(cfg):return [0,0,1080,1920]
 f=native_frame(n,cfg);rows=recovery()['presenter_frames'];a=int(min(216,max(0,math.floor(f))));b=min(216,a+1);q=f-a
 return [round(x+(y-x)*q) for x,y in zip(rows[a]['xyxy'],rows[b]['xyxy'])]
def source_pose(f):
 a=max(79,min(216,int(math.floor(f))));b=min(216,a+1);q=max(0,min(1,f-a));aa=poses()[a]['affine'];bb=poses()[b]['affine']
 x=np.array(aa)*(1-q)+np.array(bb)*q;s=float(x[0,0]);return np.array([[s,0,x[0,2]],[0,s,x[1,2]-530*s]],np.float32)
@lru_cache(maxsize=12)
def material_atlas(mode,path,texts,body):
 if mode=='baseline':return load(str(C/'source-recovery/poster-atlas-v2.png'))
 if path:
  image=load(path);back=M._fit(image,1080,1920,{'fit':'cover','anchor':[.5,.5]}).filter(ImageFilter.GaussianBlur(50));sharp=M._fit(image,1080,810,{'fit':'contain','anchor':[.5,.5]});bg=Image.new('RGBA',SIZE,(8,15,23,255));bg.alpha_composite(back);bg.alpha_composite(Image.new('RGBA',(1080,810),(8,15,23,255)),(0,555));bg.alpha_composite(sharp,(0,555));return bg
 im=Image.new('RGBA',SIZE,(7,18,30,255));d=ImageDraw.Draw(im);d.rectangle((0,555,1080,1365),fill=(15,34,52,255));return im
def material_layers(cfg,n,out):
 f=native_frame(n,cfg)
 if not has_scene(cfg) or f<79 or f>=217:return
 mat=match(cfg);texts=tuple(str(t).strip() for t in cfg.get('material_texts',[]) if str(t).strip());path=mat.get('path','') if mat else ''
 atlas=material_atlas(cfg['mode'],path,texts,cfg['fonts']['body']);basealpha=Image.new('L',SIZE);ImageDraw.Draw(basealpha).rounded_rectangle((0,0,1079,1919),radius=18,fill=255)
 top=basealpha.copy();ImageDraw.Draw(top).rectangle((0,555,1079,1364),fill=0);clear=Image.new('L',SIZE);ImageDraw.Draw(clear).rectangle((0,555,1079,1364),fill=255)
 entry=interp(f,[(79,.35),(80,.65),(81,.85),(82,.97),(83,1)])
 backq=entry*interp(f,[(79,1),(207,1),(208,.70),(209,.47),(210,.25),(211,.12),(212,.05),(213,.02),(214,.01),(215,.005),(216,.001)])
 clearq=entry*interp(f,[(79,1),(208,1),(209,.75),(210,.55),(211,.40),(212,.28),(213,.18),(214,.10),(215,.055),(216,.025)])
 m=source_pose(f)
 for role,alpha,q in [('material_blur',top,backq),('material_clear',clear,clearq)]:
  texture=atlas.copy();texture.putalpha(alpha);warped=cv2.warpAffine(np.asarray(texture),m,SIZE,flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT);out[role]=op(Image.fromarray(warped),q)
 if texts:
  layer=blank();y=665
  for i,t in enumerate(texts):
   im,_,_=text_image(t,cfg['fonts']['body'],min(88,760/max(1,len(t))),(255,255,255,255));layer.alpha_composite(im,(round((1080-im.width)/2),y));y+=145
  out['material_text']=op(Image.fromarray(cv2.warpAffine(np.asarray(layer),m,SIZE,flags=cv2.INTER_CUBIC)),clearq)
@lru_cache(maxsize=160)
def wordart(text,path,size,color,stroke=1):return text_image(text,path,size,color,stroke,(0,0,0,220))[0]
@lru_cache(maxsize=256)
def glyph(text,path,size,color):return text_image(text,path,size,color,1,(0,0,0,220))
def _old_caption_data(cfg,n):
 if cfg['mode']=='baseline':
  texts=['为什么你明明','睡够了8小时','白天还是很困','真正影响精力的','不只是睡眠时长','还有睡眠节律'];starts=[13,35,72,119,158,203];ends=[34,70,114,157,201,237];em=['','','很困','','睡眠时长','睡眠节律']
  for i,(a,b) in enumerate(zip(starts,ends)):
   if a<=n<b or (n==0 and i==0):return texts[i],[(texts[i].find(em[i]),len(texts[i]))] if em[i] else [],1 if n==0 else min(1,(n-a+1)/8)
  return None
 for c in cfg['captions']:
  a,b=c['time'];t=n/25
  if a<=t<b:
   spans=[];cursor=0
   for line in c['lines']:
    spans.extend([(x+cursor,y+cursor) for x,y in line.get('emphasis_spans',[])]);cursor+=len(line['text'])
   return c['text'],spans,min(1,(t-a+.04)/.24)
 return None
def _old_caption(cfg,n,out):
 data=caption_data(cfg,n)
 if not data or cfg.get('caption_disabled'):return
 text,spans,q=data;size=cfg.get('body_size',90);path=cfg['fonts']['body'];face=font(path,size);maxw=960
 # Wrap at glyph boundaries without moving milliseconds. Each line same pointsize.
 lines=[];s='';offset=0
 for j,ch in enumerate(text):
  if s and face.getlength(s+ch)>maxw:lines.append((s,offset));offset=j;s=''
  s+=ch
 if s:lines.append((s,offset))
 # Native ordinary ink begins1576; extra line grows upward to preserve safe bottom.
 y=1576-max(0,len(lines)-1)*104
 for line,start in lines:
  widths=[face.getlength(ch) for ch in line];x=(1080-sum(widths))/2;linebox=face.getbbox(line,anchor='ls',stroke_width=1);baseline=y-linebox[1]
  for j,ch in enumerate(line):
   color=(255,218,64,255) if any(a<=start+j<b for a,b in spans) else (255,255,255,255)
   im,b,pad=glyph(ch,path,size,color);out['caption'].alpha_composite(im,(round(x+b[0]-pad),round(baseline+b[1]-pad)));x+=widths[j]
  y+=104
 out['caption']=op(out['caption'],q);a=out['caption'].getchannel('A');shadow=blank();shadow.putalpha(a.filter(ImageFilter.GaussianBlur(2)).point(lambda v:round(v*.65)));out['caption_shadow'].alpha_composite(shadow,(2,3))
def _old_title_identity(cfg,n,out):
 if cfg['mode']=='baseline':q=1 if n==0 else (ramp(n,1,9)*(1-ramp(n,70,79)))
 else:q=ramp(n,1,9)*(1-ramp(n,64,76))
 topic=str(cfg.get('topic','')).strip()
 if topic and q>0:
  image=wordart(topic,cfg['fonts']['title'],cfg.get('topic_size',110),(255,255,255,255),8);image=image.transform((image.width+40,image.height),Image.Transform.AFFINE,(1,.16,-20,0,1,0),Image.Resampling.BICUBIC);b=image.getchannel('A').getbbox();out['topic'].alpha_composite(op(image,q),(round((1080-(b[2]-b[0]))/2-b[0]),164-b[1]))
 ident=cfg.get('identity',{});name=str(ident.get('name','')).strip();desc=str(ident.get('description','')).strip()
 if not ident.get('enabled',True) or not(name or desc):return
 q=1 if n==0 else ramp(n,1,9)*(1-ramp(n,66,71))
 if q<=0:return
 local=Image.new('RGBA',(700,220));d=ImageDraw.Draw(local);y=0
 for text,size,fill,bg in [(name,58,(0,0,0,255),(255,222,0,255)),(desc,36,(255,255,255,255),(0,0,0,255))]:
  if not text:continue
  im=wordart(text,cfg['fonts']['identity'] if text==name else cfg['fonts']['body'],size,fill,0);b=im.getchannel('A').getbbox();w=b[2]-b[0]+24;h=76 if text==name else 56;d.rectangle((0,y,w,y+h),fill=bg);local.alpha_composite(im,(12-b[0],y+(h-(b[3]-b[1]))//2-b[1]));y+=h+7
 # Native early text is locally clipped/revealed independently of top title.
 if 1<n<9:
  w=local.getchannel('A').getbbox()[2];cut=round(w*(1-ramp(n,2,9)));a=local.getchannel('A');ImageDraw.Draw(a).rectangle((0,0,cut,220),fill=0);local.putalpha(a)
 out['identity'].alpha_composite(op(local,q),(76,903))
def _old_render_layers(raw,n,cfg):
 out={r:blank() for r in ROLES};out['background']=grid().copy();material_layers(cfg,n,out)
 box=person_box(cfg,n);x0,y0,x1,y1=box;w=x1-x0;h=y1-y0
 if cfg['mode']=='baseline':frame=load(str(C/'source-recovery/presenter'/f'{n:04}.png'))
 else:frame=M._fit(raw.convert('RGBA'),w,h,{'fit':'cover','anchor':[.5,.35]})
 rad=round(18*ramp(1080-w,0,776));mask=Image.new('L',SIZE);ImageDraw.Draw(mask).rounded_rectangle(tuple(box),radius=rad,fill=255)
 if w<1070:
  glow=blank();glow.putalpha(mask.filter(ImageFilter.GaussianBlur(24)).point(lambda a:round(min(255,a*2.5)*ramp(1080-w,0,600))));white=Image.new('RGBA',SIZE,(255,255,255,0));white.putalpha(glow.getchannel('A'));out['presenter_glow']=white
 # Reuse actual pinned V02 sampler. Input crop is native own window, no face avoidance crop.
 cfgv={'size':[1080,1920],'fps':25,'stage_color':[0,0,2],'visual_keys':[{'time':0,'matrix':[[w/1080,0,x0/2],[0,h/1920,y0/2]],'rect':[x0/2,y0/2,x1/2,y1/2],'radius':rad/2,'background_opacity':0}]}
 out['presenter']=V.render('V02',frame,n,cfgv)['presenter'];title_identity(cfg,n,out);caption(cfg,n,out)
 f=native_frame(n,cfg)
 if f>=214 and (cfg['mode']=='baseline' or has_scene(cfg)):
  width=interp(f,[(214,9),(215,44),(216,112)]);m=Image.new('L',SIZE);ImageDraw.Draw(m).polygon([(0,0),(width,0),(0,min(1920,width*5))],fill=255)
  if cfg['mode']=='baseline':tex=load(str(C/'source-recovery'/f'leading-texture-{min(216,round(f))}.png'));layer=blank();layer.alpha_composite(tex,(0,0))
  else:layer=M._fit(raw.convert('RGBA'),1080,1920,{'fit':'cover'}).filter(ImageFilter.GaussianBlur(24))
  layer.putalpha(m);out['leading_overlap']=layer
 return out
def composite(layers):
 im=Image.new('RGBA',SIZE,(0,0,0,255))
 for r in ROLES:im.alpha_composite(layers[r])
 return im.convert('RGB')

def _ease(a,b,n):q=ramp(n,a,b);return 1-(1-q)**3
def _asset(cfg,n,tail=True):
 stages=cfg['materials']+([] if cfg['materials'] else cfg.get('text_cards',[]))
 current=next((m for m in stages if m['start']<=n<m['end']),None)
 return current if current else next((m for m in stages if tail and m['end']<=n<m['end']+12),None)
def match(cfg):
 if cfg['mode']=='baseline':return {'id':'source-sleep-poster','time':[79/25,217/25]}
 m=cfg.get('_active_material')
 return dict(m,time=[m['start']/25,m['end']/25]) if m else None
def native_frame(n,cfg):
 if cfg['mode']=='baseline':return n
 m=cfg.get('_active_material')
 if not m:return 70
 return float(interp(n,[(m['start'],79),(m['start']+7,93),(max(m['start']+8,m['end']-7),207),(m['end'],217)]))
def person_box(cfg,n):
 large=np.array([64,230,1016,1652.])
 if cfg['mode']=='baseline':
  if n<=216:return _old_person_box(cfg,n)
  if n<239:q=_ease(217,238,n);return (np.array([64,1046,368,1450.])*(1-q)+large*q).tolist()
  if n<303:return large.tolist()
  q=_ease(303,325,n);return (large*(1-q)+np.array([354,1200,726,1572.])*q).tolist()
 m=_asset(cfg,n)
 if not m:return [0,0,1080,1920] if not cfg['materials'] else large.tolist()
 target=np.array([64,1046,368,1450.]) if m['stage']==0 else np.array([354,1200,726,1572.])
 q=_ease(m['start']-7,m['start']+14,n)*(1-_ease(m['end'],m['end']+12,n));return (large*(1-q)+target*q).tolist()
def caption_data(cfg,n):
 if cfg['mode']!='baseline':return _old_caption_data(cfg,n)
 clock=json.loads((H/'data/caption-clock.json').read_text(encoding='utf-8'))
 for i,r in enumerate(clock['channels']['zh']):
  a,b=r['visible_frame_range']
  if a<=n<b or n==0 and i==0:
   text=r['source_visible_text'];accent=next((w for w in ['睡眠时长','睡眠节律','很困'] if w in text),'');return text,[(text.index(accent),text.index(accent)+len(accent))] if accent else [],1 if n==0 else min(1,(n-a+1)/8)
 return None
def caption(cfg,n,out):
 if cfg['mode']=='baseline':
  rows=json.loads((H/'data/caption-clock.json').read_text(encoding='utf-8'))['channels']['zh'];row=next((r for r in rows if r['visible_frame_range'][0]<=n<r['visible_frame_range'][1] and r.get('per_character_first_visible_frames')),None)
  if row:
   text=row['source_visible_text'];firsts=row['per_character_first_visible_frames'];cursor=n<row.get('cursor',{}).get('underscore_visible',[0,0])[1]
  else:return _old_caption(cfg,n,out)
 else:
  row=next((r for r in cfg['captions'] if r.get('progressive') and r['time'][0]<=n/25<r['time'][1]),None)
  if not row:return _old_caption(cfg,n,out)
  text=row['text'];firsts=row['glyph_firsts'];cursor=True
 size=cfg.get('body_size',90);path=cfg['fonts']['body'];face=font(path,size);adv=[face.getlength(ch) for ch in text];x=(1080-sum(adv))/2;baseline=1660;count=0
 for i,(ch,step,first) in enumerate(zip(text,adv,firsts)):
  if n>=first:
   im,b,pad=glyph(ch,path,size,(255,255,255,255));out['caption'].alpha_composite(im,(round(x+b[0]-pad),round(baseline+b[1]-pad)));count=i+1
  x+=step
 if cursor and count:
  xx=(1080-sum(adv))/2+sum(adv[:count]);ImageDraw.Draw(out['caption']).rectangle((round(xx+2),1664,round(xx+size*.55),1668),fill='white')
 a=out['caption'].getchannel('A');shadow=blank();shadow.putalpha(a.filter(ImageFilter.GaussianBlur(2)).point(lambda v:round(v*.65)));out['caption_shadow'].alpha_composite(shadow,(2,3))

def render_layers(raw,n,cfg):
 global C
 if cfg['mode']=='baseline' and n<=216:
  C=Path(cfg['source_cache_root']);return _old_render_layers(raw,n,cfg)
 out={r:blank() for r in ROLES};out['background']=grid().copy();local=dict(cfg);m=_asset(cfg,n)
 if m and m['stage']==0 and n<m['end']:
  local['_active_material']=m
  if m.get('text'):local['material_texts']=[m['text']]
  material_layers(local,n,out)
 elif m and m['stage']>0 and n<m['end']:
  q=_ease(m['start'],m['start']+15,n)*(1-_ease(m['end']-8,m['end'],n));box=[54,154,1026,1150];im=load(m['path']);back=M._fit(im,972,996,{'fit':'cover'}).filter(ImageFilter.GaussianBlur(40));sharp=M._fit(im,972,728,{'fit':'contain'});card=Image.new('RGBA',(972,996),(5,8,12,255));card.alpha_composite(back);card.alpha_composite(sharp,(0,134));a=Image.new('L',card.size);ImageDraw.Draw(a).rounded_rectangle((0,0,971,995),radius=24,fill=255);card.putalpha(a);out['material_clear'].alpha_composite(op(card,q),(54,154))
 box=person_box(local,n);x,y,x2,y2=box;w=x2-x;hh=y2-y
 if cfg['mode']=='baseline':
  crop=raw.crop(tuple(round(v) for v in box));arr=np.asarray(crop).copy();mask=np.zeros(arr.shape[:2],np.uint8)
  if caption_data(cfg,n):
   aa=max(0,1500-round(y));bb=min(arr.shape[0],1740-round(y));mask[aa:bb]=255
  if mask.any():
   before=arr.copy();arr=cv2.inpaint(arr,mask,3,cv2.INPAINT_TELEA)
   if cfg.get('repair_dir') and n in [217,225,238,250,302,320,350,475]:
    d=Path(cfg['repair_dir']);d.mkdir(parents=True,exist_ok=True);Image.fromarray(mask).save(d/f'f{n:04}-mask.png');Image.fromarray(np.abs(before.astype(int)-arr.astype(int)).astype(np.uint8)).save(d/f'f{n:04}-diff.png')
  frame=Image.fromarray(arr)
 else:frame=M._fit(raw.convert('RGBA'),round(w),round(hh),{'fit':'cover','anchor':[.5,.35]})
 circle=(cfg['mode']=='baseline' and n>=321) or (cfg['mode']!='baseline' and m and m['stage']>0)
 radius=min(w,hh)/2 if circle else 24
 key=dict(time=0,matrix=[[w/1080,0,x/2],[0,hh/1920,y/2]],rect=[x/2,y/2,x2/2,y2/2],radius=radius/2,background_opacity=0)
 out['presenter']=V.render('V02',frame,n,dict(size=list(SIZE),fps=25,visual_keys=[key]))['presenter']
 if w<1050:
  ma=Image.new('L',SIZE);ImageDraw.Draw(ma).rounded_rectangle(tuple(box),radius=radius,fill=255);halo=Image.new('RGBA',SIZE,'white');halo.putalpha(ma.filter(ImageFilter.GaussianBlur(24)));out['presenter_glow']=halo
 title_identity(cfg,n,out);caption(cfg,n,out)
 wipe_start=214 if cfg['mode']=='baseline' else cfg['materials'][0]['end'] if cfg['materials'] else 10**9
 phase=n-wipe_start
 if 0<=phase<12:
  # Shared whole content is occluded by the enlarged blurred room-person band.
  texture=M._fit(raw.convert('RGBA'),1404,2496,{'fit':'cover'}).filter(ImageFilter.GaussianBlur(30));layer=blank();layer.alpha_composite(texture,(-162,-288));mask=Image.new('L',SIZE);d=ImageDraw.Draw(mask)
  if phase<=6:
   edge=9+(phase/6)**2*2500;d.polygon([(0,0),(edge,0),(edge-900,1920),(0,1920)],fill=255)
  else:
   edge=(phase-6)/6*2600;d.polygon([(edge-900,0),(1080,0),(1080,1920),(edge-1900,1920)],fill=255)
  layer.putalpha(mask);out['leading_overlap']=layer
 if n>=cfg.get('fade_start',10**9):
  q=max(0,min(1,(cfg['black_at']-n)/max(1,cfg['black_at']-cfg['fade_start'])))
  for key,im in out.items():
   if cfg['mode']=='baseline' and key=='presenter':continue
   a=np.asarray(im).copy();a[:,:,:3]=np.round(a[:,:,:3]*q).astype(np.uint8);out[key]=Image.fromarray(a)
 if n>=cfg.get('black_at',10**9):out={k:blank() for k in out}
 return out


def title_identity(cfg,n,out):
 phase=n if cfg['mode']=='baseline' else n*76/max(1,cfg.get('opening_end_frame',76))
 return _old_title_identity(cfg,phase,out)

_source_caption=caption
def caption(cfg,n,out):
 if cfg['mode']=='baseline':return _source_caption(cfg,n,out)
 row=next((r for r in cfg['captions'] if r['time'][0]<=n/25<r['time'][1]),None)
 if not row:return
 size=cfg['body_size'];path=cfg['fonts']['body'];face=font(path,size);lines=row['lines'];offset=0;q=min(1,(n/25-row['time'][0]+.04)/.24)
 for li,line in enumerate(lines):
  text=line['text'];adv=[face.getlength(ch) for ch in text];xx=(1080-sum(adv))/2;top=1576-(len(lines)-1-li)*104;bb=face.getbbox(text,anchor='ls',stroke_width=1);baseline=top-bb[1];cursorx=None
  for i,(ch,step) in enumerate(zip(text,adv)):
   visible=not row.get('progressive') or n>=row['glyph_firsts'][offset+i]
   if visible:
    color=(255,218,64,255) if any(a<=i<b for a,b in line.get('emphasis_spans',[])) else (255,255,255,255);im,b,pad=glyph(ch,path,size,color);out['caption'].alpha_composite(im,(round(xx+b[0]-pad),round(baseline+b[1]-pad)));cursorx=xx+step
   xx+=step
  if cursorx is not None and row.get('progressive'):ImageDraw.Draw(out['caption']).rectangle((round(cursorx+2),round(baseline+4),round(cursorx+size*.55),round(baseline+8)),fill='white')
  offset+=len(text)
 if not row.get('progressive'):out['caption']=op(out['caption'],q)
 a=out['caption'].getchannel('A');shadow=blank();shadow.putalpha(a.filter(ImageFilter.GaussianBlur(2)).point(lambda v:round(v*.65)));out['caption_shadow'].alpha_composite(shadow,(2,3))
