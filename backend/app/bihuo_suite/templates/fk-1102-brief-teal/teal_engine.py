"""Project-local DV11/DV10/DT04/DT02 choreography; imports pinned samplers."""
from pathlib import Path
import sys,json,math
from functools import lru_cache
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
S=Path(__file__).resolve().parent
from .vendor.apple_minimal import visual as V,media as M
from .vendor.apple_minimal.pilot import font,text_image,ease
W,H=1080,1920;MINT=(30,222,180,255)
def blank():return Image.new('RGBA',(W,H))
def fade(im,q):
 q=max(0,min(1,q));out=im.copy()
 if q<1:out.putalpha(out.getchannel('A').point([round(x*q) for x in range(256)]))
 return out
def out(a,b,t):return 1-(1-max(0,min(1,(t-a)/(b-a))))**3 if b>a else float(t>=b)
@lru_cache(maxsize=2)
def recovery():return {r['frame']:r for r in json.loads((S/'restricted-recovery-temporal.json').read_text('utf-8'))['frames']}
@lru_cache(maxsize=1)
def grid():
 tile=Image.open(S/'assets/grid-tile.png').convert('RGBA');im=blank()
 for y in range(-18,H,360):
  for x in range(0,W,360):im.alpha_composite(tile,(x,y))
 return im
@lru_cache(maxsize=1)
def clean_grid():
 im=Image.new('RGBA',(W,H),(5,14,12,255));d=ImageDraw.Draw(im)
 for x in range(0,W,60):d.line((x,0,x,H),fill=(15,27,24,255))
 for y in range(42,H,60):d.line((0,y,W,y),fill=(15,27,24,255))
 return im
def ink(text,path,size,color):
 tile=text_image(text,path,size,color)[0];box=tile.getchannel('A').getbbox();return tile.crop(box) if box else Image.new('RGBA',(1,1))
def put(layer,text,path,size,x,y,color,center=False):
 if not text:return
 im=ink(text,path,size,color);layer.alpha_composite(im,(round(x-im.width/2) if center else round(x),round(y)))
def match(cfg,t):return next((m for m in cfg['materials'] if m.get('start',-1)<=t<m.get('end',-1)),None)
def new_card(cfg,t):return cfg['information']['start']-.28<=t<cfg['information']['end']+.32
def _original_person_box(cfg,t):
 if cfg['mode']=='baseline':return recovery()[round(t*25)]['native_box']
 large=np.array([115,290,965,1800],float);small=np.array([395,1187,686,1573],float);medium=np.array([295,1126,786,1775],float)
 main=next((m for m in cfg['materials'] if m.get('scene_role')=='opening' and m['start']-.04<=t<m['end']+.24),None)
 if t<7.37:
  if main and main['start']-.04<=t<main['end']+.24:
   enter=out(main['start']-.04,main['start']+.32,t);leave=out(main['end']-.16,main['end']+.24,t);q=enter*(1-leave);return (large*(1-q)+small*q).tolist()
  return large.tolist()
 if t<cfg['information']['end']+.8:
  # A text-only card still has a complete role. No image placeholder exists when match() is absent.
  q=out(7.37,7.97,t)*(1-out(cfg['information']['end']+.32,cfg['information']['end']+.8,t));return (large*(1-q)+medium*q).tolist()
 return large.tolist()
def person(frame,t,cfg):
 box=person_box(cfg,t);x,y,x2,y2=box;w=x2-x;h=y2-y
 if cfg['mode']=='baseline':texture=Image.open(recovery()[round(t*25)]['texture']).convert('RGB')
 else:
  # Keep complete authorized source; modest aspect fitting, no huge portrait crop.
  texture=M._fit(frame,round(w),round(h),dict(fit='cover',anchor=[.5,.35]))
 texture=texture.resize((W,H),Image.Resampling.LANCZOS)
 key=dict(time=0,matrix=[[w/W,0,x/2],[0,h/H,y/2]],rect=[x/2,y/2,x2/2,y2/2],radius=15,background_opacity=0)
 layer=V.render('V02',texture,0,dict(size=[W,H],fps=25,stage_color=[5,14,12],visual_keys=[key]))['presenter']
 border=blank();d=ImageDraw.Draw(border)
 q=1
 if cfg['mode']=='baseline' and t>=263/25:q=1-out(263/25,267/25,t)
 if q:
  d.rounded_rectangle(box,radius=30,outline=MINT,width=4);glow=border.convert('RGBa').filter(ImageFilter.GaussianBlur(14)).convert('RGBA');glow.putalpha(glow.getchannel('A').point([min(255,x*5) for x in range(256)]));glow=fade(glow,.9*q);border=fade(border,q);glow.alpha_composite(border)
 else:glow=blank()
 return layer,glow
def image_slot(path,rect,t,enter=0,entry_frames=0,radius=28,fit='cover'):
 e=dict(id='slot',path=path,type='image',start_frame=round(enter*25),rect=[v/2 for v in rect],fit=fit,anchor=[.5,.5],radius=radius/2,entry_frames=entry_frames,entry_blur=0,end_policy='hold',audio='muted')
 return M.render('V03',None,round(t*25),dict(size=[W,H],fps=25,media_entries=[e]))['media-slot']
def card_motion(im,t,cfg):
 if cfg['mode']=='baseline':n=t*25
 elif t<cfg['information']['start']+.35:n=193+(t-(cfg['information']['start']-.04))*25
 elif t>=cfg['information']['end']:n=248+(t-cfg['information']['end'])*28.125
 else:return im
 if n<200:
  keys=[(193,.96,70),(194,.96,62),(195,.972,49),(196,.982,33),(198,.996,7),(200,1,0)]
 elif n>=248:keys=[(248,1,0),(249,1.0065,-8.4),(252,1.0224,-33.6),(257,1.045,-75)]
 else:return im
 a=keys[0];b=keys[-1]
 for aa,bb in zip(keys,keys[1:]):
  if aa[0]<=n<=bb[0]:a,b=aa,bb;break
 q=max(0,min(1,(n-a[0])/(b[0]-a[0])));scale=a[1]*(1-q)+b[1]*q;dy=a[2]*(1-q)+b[2]*q;cx,cy=540,742
 im=im.transform((W,H),Image.Transform.AFFINE,(1/scale,0,cx-cx/scale,0,1/scale,cy-(cy+dy)/scale),Image.Resampling.BICUBIC)
 blur=(max(0,n-248)/9*5) if n>=248 else max(0,200-n)/7*2
 if blur:im=im.convert('RGBa').filter(ImageFilter.GaussianBlur(blur)).convert('RGBA')
 return im
def _original_materials(cfg,t):
 layer=blank();office=blank();cards=blank();labels=blank();bullets=blank()
 if cfg['mode']=='baseline':
  n=round(t*25);q=1 if n==0 else out(12/25,20/25,t);q*=1-ease(164/25,170/25,t)
  if q:office.alpha_composite(fade(image_slot(cfg['materials'][0]['path'],[410,194,1010,589],t),q))
  enter=194/25;full=200/25;exit1=249/25;exit2=257/25;cardq=ease(enter-.04,full,t)*(1-ease(exit1,exit2,t))
  rect=[72,501,1008,982];imgbox=[134,560,945,854];path=cfg['materials'][1]['path'];label='直播智能体';items=[dict(text='不是单纯循环视频',start=225/25,near=235/25)];labelat=203/25
 else:
  m=match(cfg,t);cardq=ease(cfg['information']['start']-.28,cfg['information']['start'],t)*(1-ease(cfg['information']['end'],cfg['information']['end']+.32,t));label=cfg['information']['label'];items=cfg['information']['items'];labelat=cfg['information']['start']
  if m and m.get('scene_role')=='opening':
   office.alpha_composite(fade(image_slot(m['path'],[410,194,1010,589],t,fit='contain'),ease(m['start']-.04,m['start']+.32,t)*(1-ease(m['end']-.24,m['end'],t))))
  detail=next((m for m in cfg['materials'] if m.get('scene_role')=='first-card' and m['start']-.04<=t<m['end']),None) or next((m for m in cfg['materials'] if m.get('scene_role')=='first-card'),None)
  if detail is None:labelat=cfg['information']['start']-.28
  imageq=(ease(detail['start']-.04,detail['start']+.32,t)*(1-ease(detail['end']-.24,detail['end'],t))) if detail else 0
  path=detail['path'] if detail and imageq>0 else None
  weight=(1-out(detail['end']-.24,detail['end'],t))*float(t>=cfg['information']['start']-.28) if detail else 0
  rect=(np.array([150,600,930,1010])*(1-weight)+np.array([72,410,1008,1010])*weight).tolist();imgbox=[134,470,945,764];cardq*=float(t>=cfg['information']['start']-.28)
  if detail:cardq*=ease(detail['start']-.04,detail['start']+.28,t) if t<cfg['information']['start']+.35 else 1
 if cardq>0:
  ImageDraw.Draw(cards).rounded_rectangle(rect,radius=42,fill=(255,255,255,255))
  if path:
   image=image_slot(path,imgbox,t,radius=28,fit='contain' if cfg['mode']=='new' else 'cover');layer.alpha_composite(fade(image,cardq*(imageq if cfg['mode']=='new' else 1)))
  # Labels and bullet list remain independently editable and independently timed.
  top=(580 if cfg['mode']=='baseline' else 625-135*weight);left=152 if cfg['mode']=='baseline' else 190-35*weight
  labelim=ink(label,cfg['fonts']['bold'],26,(0,20,16,255));ld=ImageDraw.Draw(labels);ld.rounded_rectangle([left,top,left+labelim.width+82,top+54],radius=27,fill=MINT);ld.rectangle([left+26,top+19,left+42,top+35],outline=(0,20,16,255),width=2);ld.line([left+31,top+20,left+31,top+34],fill=(0,20,16,255),width=2);labels.alpha_composite(labelim,(round(left+56),round(top+13)));labels=fade(labels,ease(labelat-.04,labelat+.2,t)*cardq)
  ybase=877 if cfg['mode']=='baseline' else 715+90*weight
  for i,item in enumerate(items):
   row=blank();y0=ybase+i*75;d=ImageDraw.Draw(row);d.ellipse([135 if cfg['mode']=='baseline' else 190,y0-8,180 if cfg['mode']=='baseline' else 235,y0+37],fill=(241,244,243,255));xx=149 if cfg['mode']=='baseline' else 204
   for dx,dy in [(0,0),(11,0),(0,11),(11,11)]:d.rectangle([xx+dx,y0+5+dy,xx+dx+6,y0+11+dy],outline=(0,158,124,255),width=2)
   put(row,item['text'],cfg['fonts']['bold'],30,202 if cfg['mode']=='baseline' else 256,y0+4,(5,14,11,255));bullets.alpha_composite(fade(row,ease(item['start']-.04,item['near'],t)*cardq))
  cards=fade(cards,cardq)
 cards=card_motion(cards,t,cfg);layer=card_motion(layer,t,cfg);labels=card_motion(labels,t,cfg);bullets=card_motion(bullets,t,cfg);office.alpha_composite(layer)
 return cards,office,labels,bullets
def identity(cfg,t):
 layer=blank();card=cfg['identity'];name=card.get('name','').strip();desc=card.get('description','').strip()
 if not card.get('enabled') or not(name or desc):return layer
 q=(1 if cfg['mode']=='baseline' and t==0 else ease(.04,.32,t))*(1-ease(*cfg.get('identity_exit',[67/25,76/25]),t))
 d=ImageDraw.Draw(layer)
 if name:
  tile=ink(name,cfg['fonts']['bold'],84,(0,18,13,255));w=max(202,tile.width+30);d.rectangle([605,1123,605+w,1230],fill=MINT);layer.alpha_composite(tile,(620,1146))
 if desc:
  tile=ink(desc,cfg['fonts']['body'],52,(255,255,255,255));y=1240 if name else 1123;d.rectangle([605,y,605+tile.width+30,y+79],fill=(0,0,0,155));layer.alpha_composite(tile,(620,y+13))
 return fade(layer,q)
def caption(cfg,t,shadow=True):
 textlayer=blank();sh=blank();cue=next((c for c in cfg['captions'] if c['time'][0]<=t<c['time'][1]),None)
 if cfg['mode']=='baseline' and t==0:cue=cfg['captions'][0]
 if cue is None:return sh,textlayer
 lines=cue['lines'];path=cfg['fonts'].get('caption',cfg['fonts']['bold'])
 for j,line in enumerate(lines):
  parts=V.caption_parts(line);width=sum(font(path,cfg.get('caption_size',58)+10 if emph else cfg.get('caption_size',58)).getlength(txt) for txt,emph in parts)
  if width>990:raise ValueError('Semantic caption requires wrapping, not forced squeeze')
  x=(W-width)/2;baseline=1664+j*76-(len(lines)-1)*38
  d=ImageDraw.Draw(textlayer)
  for txt,emph in parts:
   d.text((round(x),baseline),txt,font=font(path,cfg.get('caption_size',58)+10 if emph else cfg.get('caption_size',58)),fill=MINT if emph else 'white',anchor='ls',stroke_width=1,stroke_fill=(0,27,21,210));x+=font(path,cfg.get('caption_size',58)+10 if emph else cfg.get('caption_size',58)).getlength(txt)
 if shadow:
  alpha=textlayer.getchannel('A');sh.putalpha(alpha);sh=Image.fromarray(np.dstack([np.zeros((H,W,3),np.uint8),np.asarray(alpha)]));sh=sh.filter(ImageFilter.GaussianBlur(3));shift=blank();shift.alpha_composite(sh,(2,4));sh=shift
 a,b=cue['time'];near=cue.get('near',a+.32);q=ease(a-.04,near,t)
 if cfg['mode']=='baseline' and t==0:q=1
 return fade(sh,q),fade(textlayer,q)
def render_layers(frame,t,cfg):
 background=(grid() if cfg['mode']=='baseline' else clean_grid()).copy();personlayer,glow=person(frame,t,cfg);cards,media,labels,bullets=materials(cfg,t);shadow,cap=caption(cfg,t)
 if cfg['mode']=='baseline' and t>=280/25:
  background=frame.filter(ImageFilter.GaussianBlur(45)).convert('RGBA')
 return dict(background=background,card=cards,material=media,presenter=personlayer,presenter_glow=glow,card_label=labels,card_items=bullets,identity=identity(cfg,t),caption_shadow=shadow,caption=cap)
def composite(layers):
 im=blank()
 for layer in layers.values():im.alpha_composite(layer)
 return im.convert('RGB')

def person_box(cfg,t):
 if cfg['mode']=='baseline':return _original_person_box(cfg,t)
 large=np.array([115,290,965,1800.]);small=np.array([395,1187,686,1573.]);medium=np.array([295,1126,786,1775.]);rect=large.copy()
 main=next((m for m in cfg['materials'] if m.get('scene_role')=='opening' and m['start']-.04<=t<m['end']+.24),None)
 if main:
  q=out(main['start']-.04,main['start']+.32,t)*(1-out(main['end']-.16,main['end']+.24,t));rect=large*(1-q)+small*q
 info=cfg['information']
 if info.get('enabled',True) and (info.get('label') or info.get('items') or any(m.get('scene_role')=='first-card' for m in cfg['materials'])):
  q=out(info['start']-.28,info['start']+.32,t)*(1-out(info['end']+.32,info['end']+.8,t));rect=rect*(1-q)+medium*q
 return rect.tolist()

def materials(cfg,t):
 if cfg['mode']=='baseline':return _original_materials(cfg,t)
 info=cfg['information']
 if not info.get('enabled',True) or not(info.get('label') or info.get('items') or any(m.get('scene_role')=='first-card' for m in cfg['materials'])):
  local=dict(cfg,information=dict(info,start=-100,end=-99,label='',items=[]));return _original_materials(local,t)
 return _original_materials(cfg,t)
