"""Portable paper editorial with current/history gallery and meaningful text card."""
from pathlib import Path
import copy,hashlib,importlib.util,json,math,sys
from functools import lru_cache
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
HERE=Path(__file__).resolve().parent
def load(name):
 key='_paper_'+name+'_'+hashlib.sha256(str(HERE).encode()).hexdigest()[:8];s=importlib.util.spec_from_file_location(key,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);sys.modules[key]=m;s.loader.exec_module(m);return m
core=load('core');F=load('primitives');F.approved_visual=core.visual;F.approved_media=core.media;F.text_image=core.pilot.text_image;F.font=core.pilot.font;F.ease=core.pilot.ease
C=load('card')
for key in['blank','fade','out','ink','place']:setattr(C,key,getattr(F,key))
BIG=np.array([64,230,952,1422],float);SMALL=np.array([292,1149,498,376],float);CARD=np.array([302,963,476,534],float)
def compile_request(resolved,*,source_path,fonts,creative_options,ffmpeg='ffmpeg',size=(1080,1920)):
 if tuple(size)!=(1080,1920)or not Path(source_path).is_file():raise ValueError('Existing portrait video/native1080 required')
 duration=float(resolved['duration']);f=core._style_fonts(fonts);rows=[]
 for c in resolved.get('captions',[]):
  a,b=map(float,c.get('time',[c.get('start'),c.get('end')]))
  if not 0<=a<b<=duration+.05:raise ValueError('Invalid actual FA caption bounds')
  lines=copy.deepcopy(c.get('lines')or[dict(text=c['text'],emphasis_spans=[])])
  for line in lines:
   if not isinstance(line,dict):raise ValueError('Semantic line rows required')
  wrapped=[]
  for line in lines:
   if core.pilot.font(f['caption'],74).getlength(line['text'])<=970:wrapped.append(line);continue
   text=line['text'];spans=line.get('emphasis_spans',[]);candidates=[b for a,b in spans if 1<b<len(text)-1];cut=min(candidates,key=lambda x:abs(x-len(text)/2))if candidates else len(text)//2
   for u,v in[(0,cut),(cut,len(text))]:wrapped.append(dict(text=text[u:v],emphasis_spans=[[max(a,u)-u,min(b,v)-u]for a,b in spans if max(a,u)<min(b,v)]))
  if len(wrapped)>3:raise ValueError('Caption needs semantic replanning beyond3 natural lines')
  rows.append(dict(text=c['text'],time=[a,b],lines=wrapped))
 if not rows:raise ValueError('Actual complete FA captions required')
 mats=[]
 for m in resolved.get('materials',[]):
  span=m.get('spoken_span')or{};a=max(float(m['start']),float(span.get('start',m['start'])));b=min(float(m['end']),float(span.get('end',m['end'])),duration)
  if a>=b:continue
  if not Path(m['path']).is_file()or(m.get('sha256')and core._sha(m['path'])!=m['sha256']):raise ValueError('Actual matched picture/pathSHA invalid')
  mats.append(dict(id=m['asset_id'],path=m['path'],sha256=core._sha(m['path']),start=a,end=b,kind=m.get('kind','image'),fit='contain',spoken_span=span))
 mats.sort(key=lambda m:m['start'])
 if len(mats)>4:raise ValueError('Gallery supports current+3 history; use explicit paging above4 actual matches')
 opts=creative_options or{};ident=opts.get('name_card')or opts.get('identity')or{};identity=dict(name=core._text(ident.get('name')),description=core._text(ident.get('description')))if ident.get('enabled',False)else dict(name='',description='');items=[]
 features=resolved.get('features')or resolved.get('points')or[];last=max([m['end']for m in mats]+[float(resolved.get('opening_end')or 3)])
 for r in features:
  if core._text(r['text']):items.append(dict(text=r['text'],at=float(r['start'])))
 if not items:
  for r in rows:
   if r['time'][0]<max(last,duration*.6)or r['time'][0]>=float(((resolved.get('conclusion')or{}).get('first')or{}).get('start',duration)):continue
   phrases=[]
   for line in r['lines']:
    spans=line.get('emphasis_spans',[])
    if spans:phrases.append(line['text'][min(a for a,b in spans):max(b for a,b in spans)])
   text=''.join(phrases)
   if core._text(text)and text not in[x['text']for x in items]:items.append(dict(text=text,at=r['time'][0]))
 if len(items)>4:raise ValueError('More than4 meaningful text items requires explicit paging')
 con=resolved.get('conclusion')or{};first=con.get('first')or{};button=core._text(first.get('text'));at=min([i['at']for i in items]+[float(first.get('start')or duration*.8)]);card_title=core._text(opts.get('title'))or core._text(resolved.get('title'));card=dict(enabled=bool(items or button),title=card_title,items=items,button=button,entry=at,exit=[duration-.32,duration-.12],links=[max(at+.4,float(first.get('start')or duration*.8)-.6),float(first.get('start')or duration*.8)-.2],button_at=float(first.get('start')or at+.8))
 if card['links'][1]<=card['links'][0]:card['links']=[at+.2,at+.5]
 return dict(schema='bihuo.paper.production/1',template_id='fk-1017-share-paper',mode='clean',source_path=str(source_path),source_sha256=core._sha(source_path),duration=duration,frames=max(round(duration*25),math.ceil(rows[-1]['time'][1]*25)),fps=25,size=list(size),ffmpeg=str(ffmpeg),fonts=f,captions=rows,materials=mats,title=card_title,title_end=float(resolved.get('opening_end')or 3),identity=identity,raw_crop=[0,80,1080,1780],card=card,star_count=10,stars_at=max(last,at-.88),wipe_at=last+.09 if mats else None,tail_fade=[duration-.48,duration],limits=['Reference paper texture/font/easing remain reconstruction candidates.','Historical visual retention is previous teaching example, never extended FA/active spoken span.','Native original-room window, no person/head matte.'])
def active(cfg,t):
 mats=cfg['materials'];idx=max([-1]+[i for i,m in enumerate(mats)if m['start']<=t]);end=max([m['end']for m in mats]+[0])
 return(idx,mats[idx])if idx>=0 and t<end+.16 else(-1,None)
F.active=active
def card_active(cfg,t):
 c=cfg['card'];return c['enabled']and bool(c['items']or c['title']or c['button'])and c['entry']-.08<=t<c['exit'][1]
C.card_active=card_active
def _card(cfg,t):
 c=cfg['card']
 if c['items']:return C.card_layers(t,cfg)
 roles={r:F.blank()for r in['card','card-title','card-items','card-links','card-button','card-conclusion']}
 if not card_active(cfg,t):return roles
 q=F.out(c['entry']-.04,c['entry']+.32,t)*(1-F.out(*c['exit'],t));ImageDraw.Draw(roles['card']).rounded_rectangle((72,396,1008,716),radius=40,fill=(248,243,229,255));F.place(roles['card-title'],F.ink(c['title'],cfg['fonts']['title'],50,(22,21,17,255)),540,460)
 if c['button']:
  face=F.ink(c['button'],cfg['fonts']['title'],40,(22,21,17,255));F.place(roles['card-conclusion'],face,540,604,F.out(c['button_at']-.04,c['button_at']+.2,t))
 return{k:F.fade(v,q)for k,v in roles.items()}
def _pose(cfg,t):
 idx,m=active(cfg,t);mats=cfg['materials'];q=F.out(mats[0]['start']-.24,mats[0]['start']+.32,t)*(1-F.out(mats[-1]['end'],mats[-1]['end']+.24,t))if m else 0;box=BIG*(1-q)+SMALL*q
 c=cfg['card']
 if c['enabled']and(c['items']or c['title']or c['button']):cq=F.out(c['entry']-.08,c['entry']+.72,t)*(1-F.out(c['exit'][1]+.12,c['exit'][1]+1.12,t));box=box*(1-cq)+CARD*cq;q=max(q,cq)
 return box,q
@lru_cache(maxsize=1)
def _star_spec():return json.loads((HERE/'stars.json').read_text('utf8'))
def _stars(cfg,t):
 layer=F.blank();scale=F.out(cfg['stars_at'],cfg['stars_at']+.44,t)*(1-F.out(cfg['stars_at']+.60,cfg['stars_at']+1,t));d=ImageDraw.Draw(layer)
 if scale<=0:return layer
 for i,st in enumerate(_star_spec()[:cfg.get('star_count',10)]):
  x,y=st['estimated_center_xy'];roi=st['visible_roi_xyxy'];w,h=roi[2]-roi[0],roi[3]-roi[1];w=180 if st['id']in['S05','S06']else w;angle=math.radians([10,45,38,-15,35,20,12,43,43,10][i]);tips=[np.array(v,float)for v in[(0,-1),(1,0),(0,1),(-1,0)]];pts=[]
  for a,b in zip(tips,tips[1:]+tips[:1]):
   for u in np.linspace(0,1,20,endpoint=False):v=((1-u)**2*a+2*(1-u)*u*(a+b)*.16+u*u*b)*np.array([w/2,h/2])*scale;pts.append((x+v[0]*math.cos(angle)-v[1]*math.sin(angle),y+v[0]*math.sin(angle)+v[1]*math.cos(angle)))
  d.polygon(pts,fill=(255,194,49,230)if st['color']=='gold'else(74,184,208,230));d.line(pts+[pts[0]],fill=(161,103,25,240)if st['color']=='gold'else(36,121,137,235),width=max(1,round(6*scale)),joint='curve')
 return layer
def render_layers(cfg,n):
 t=n/25;raw=core.media._sample(dict(path=cfg['source_path'],type='video',start_frame=0,source_in=0,speed=1,end_policy='hold'),n,25).convert('RGBA');box,q=_pose(cfg,t);mat,current=F.gallery(t,cfg);bg=F.paper().copy();c=cfg['card']
 if t<cfg['title_end']or card_active(cfg,t):
  dark=raw.resize((1080,1920)).filter(ImageFilter.GaussianBlur(64));dark.alpha_composite(Image.new('RGBA',(1080,1920),(22,20,13,175)));dq=1-F.out(cfg['title_end']-.24,cfg['title_end'],t)if t<cfg['title_end']else F.out(c['entry']-.08,c['entry']+.28,t)*(1-F.out(*c['exit'],t));bg.alpha_composite(F.fade(dark,dq))
 if current:bg.alpha_composite(F.fade(F.blur_material(current['path']),q))
 x,y,w,h=box;texture=core.media._fit(raw.crop(tuple(cfg['raw_crop'])),round(w),round(h),dict(fit='cover',anchor=[.5,.35])).resize((1080,1920),Image.Resampling.LANCZOS);radius=20 if h>800 else 40;key=dict(time=0,matrix=[[w/1080,0,x/2],[0,h/1920,y/2]],rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=radius/2,background_opacity=0);pres=core.visual.render('V02',texture,n,dict(size=[1080,1920],fps=25,visual_keys=[key]))['presenter'];border=F.blank();ImageDraw.Draw(border).rounded_rectangle((x,y,x+w,y+h),radius=radius,outline=(255,255,255,235),width=2);pres.alpha_composite(border);halo=Image.new('RGBA',(1080,1920),'white');halo.putalpha(pres.getchannel('A').filter(ImageFilter.GaussianBlur(24)).point(lambda z:round(z*.9*q)));back,title,identity=F.title(t,cfg);shadow,caption=F.caption(t,cfg)
 roles=dict(background=bg,material=mat);roles.update(_card(cfg,t));roles.update(halo=halo,presenter=pres,stars=_stars(cfg,t),title_back=back,title_text=title,identity=identity,caption_shadow=shadow,caption=caption)
 at=cfg['wipe_at']
 if at is not None and at<=t<at+.4:
  right=210+310*(t-at)*25;left=right-1300;mask=Image.new('L',(1080,1920));ImageDraw.Draw(mask).polygon([(left,0),(right,0),(right-.18*1920,1920),(left-.18*1920,1920)],fill=255);wipe=raw.resize((1080,1920),Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(32));wipe.putalpha(mask);roles['whole_scene_diagonal_wipe']=wipe
 roles['whole_rgb_fade']=Image.new('RGBA',(1080,1920),(0,0,0,round(core.pilot.ease(*cfg['tail_fade'],t)*255)))
 return roles,dict(frame=n,matched_asset_id=current['id']if current else None,history_ids=[m['id']for m in cfg['materials']if current and m['start']<current['start']],text_card=card_active(cfg,t),picture_count=len(cfg['materials']),text_item_count=len(c['items']),head_alpha=False)
def composite(roles):
 out=F.blank()
 for v in roles.values():out.alpha_composite(v)
 return out.convert('RGB')
def render_mp4(cfg,output_dir):
 core.render_layers=render_layers;core.composite=composite;return core.render_mp4(cfg,output_dir)
