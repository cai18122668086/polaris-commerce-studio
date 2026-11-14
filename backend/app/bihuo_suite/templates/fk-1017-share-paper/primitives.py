import math
from functools import lru_cache
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
W,H=1080,1920

def blank():return Image.new('RGBA',(W,H))

def fade(im,q):
 if q>=1:return im
 im=im.copy();im.putalpha(im.getchannel('A').point([round(a*max(0,q)) for a in range(256)]));return im

def out(a,b,t):
 q=max(0,min(1,(t-a)/(b-a))) if b>a else float(t>=b);return 1-(1-q)**3

@lru_cache(maxsize=1)
def paper():
 # Deterministic editable approximation, not recovered authortexture.
 rng=np.random.default_rng(1029);base=np.zeros((H,W,3),np.float32);noise=rng.normal(0,2.5,(H,W));low=np.asarray(Image.fromarray(rng.integers(0,255,(90,50),np.uint8)).resize((W,H),Image.Resampling.BICUBIC),np.float32)-127
 yy,xx=np.mgrid[:H,:W];grain=noise+low*.07
 for i in range(35):
  x=rng.uniform(-W,W*2);slope=rng.uniform(-.7,.7);dist=xx-(x+yy*slope+18*np.sin(yy/rng.uniform(90,300)));grain+=rng.uniform(-12,10)*np.exp(-dist*dist/rng.uniform(18,80)**2)
 for c,v in enumerate([177,153,120]):base[:,:,c]=v+grain
 return Image.fromarray(np.clip(base,0,255).astype(np.uint8)).convert('RGBA')

@lru_cache(maxsize=128)
def ink(text,path,size,fill,stroke=0,slant=0):
 im=text_image(text,path,size,fill,stroke,(30,29,27,255))[0];box=im.getchannel('A').getbbox();im=im.crop(box) if box else Image.new('RGBA',(1,1))
 if slant:
  shift=math.ceil(abs(slant)*im.height);im=im.transform((im.width+shift,im.height),Image.Transform.AFFINE,(1,slant,-shift,0,1,0),Image.Resampling.BICUBIC)
 return im

def place(layer,im,cx,top,q=1,scale=1):
 if q<=0:return
 if scale!=1:im=im.resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))),Image.Resampling.BICUBIC)
 layer.alpha_composite(fade(im,q),(round(cx-im.width/2),round(top)))

def material_rect(i,idx,t,cfg):
 m=cfg['materials'][i];current=cfg['materials'][idx];n=t*25
 first=[44,96,994,1018];later=[44,96,994,580];home=first if i==0 else later
 if i==idx:
  q=out(m.get('enter_motion_at',m['start'])*25,m.get('settle_at',m['start']+.4)*25,n);s=.85+.15*q;return [home[0]+home[2]*(1-s)/2,home[1]+home[3]*(1-s)/2,home[2]*s,home[3]*s]
 hist=[44+338*i,705,320,400]
 # Three columns are an actual max policy for this scoped4itemtrial; no empty slots.
 if idx>3:raise ValueError('Morethan3 history requires separately validated paging')
 if i<idx-1:return hist
 if cfg['mode']!='baseline' and cfg['materials'][idx-1]['end']<current['start']-.05:return hist
 at=current.get('demote_at',current['start']);q=out(at,at+.48,t)
 return (np.array(home)*(1-q)+np.array(hist)*q).tolist()

def gallery(t,cfg):
 layer=blank();idx,m=active(cfg,t)
 if cfg['mode']=='baseline':idx=max([-1]+[i for i,m in enumerate(cfg['materials']) if min(m['start'],m.get('demote_at',m['start']))<=t]);idx=0 if idx<0 and t>=62/25 and cfg['materials'] else idx;m=cfg['materials'][idx] if idx>=0 else None
 if m is None:return layer,None
 if cfg['mode']!='baseline' and t<m['start']:return layer,m
 for i,entry in enumerate(cfg['materials'][:idx+1]):
  if t<entry['start']:continue
  box=material_rect(i,idx,t,cfg);x,y,w,h=box
  media=dict(id=entry['id'],path=entry['path'],type=entry.get('kind','image'),start_frame=round(entry['start']*25),rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=15,entry_frames=0,fit=entry.get('fit','cover'),anchor=entry.get('history_anchor',[.5,.5]) if i<idx else [.5,.5])
  if entry.get('crop'):media['crop']=entry['crop']
  tile=next(iter(approved_media.render('V03',None,round(t*25),dict(size=[W,H],fps=25,media_entries=[media])).values()))
  q=out(entry['start']-.04,entry.get('settle_at',entry['start']+.36),t)
  if cfg['mode']=='baseline':q*=1-ease(263/25,270/25,t)
  elif t>m['end']-.16:q*=1-out(m['end']-.16,m['end'],t)
  layer.alpha_composite(fade(tile,q))
 return layer,m

@lru_cache(maxsize=16)
def blur_material(path):return approved_media._fit(approved_media._sample(dict(path=path,type='image',start_frame=0),0,25),W,H,dict(fit='cover')).filter(ImageFilter.GaussianBlur(45)).convert('RGBA')

def title(t,cfg):
 back=blank();text=blank();identity=blank();n=t*25;at=cfg['title_end'];q=1-out(at-.24,at,t)
 if q<=0:return back,text,identity
 if cfg.get('title'):
  poly=np.float32([(156,126),(960,96),(948,253),(144,279)])
  sourcequad=np.float32([[0,0],[807,0],[807,169],[0,169]])
  for offset,color,stroke in [(10,(255,214,72,255),None),(0,(24,24,31,255),'white')]:
   tile=Image.new('RGBA',(808,170));d=ImageDraw.Draw(tile);d.rounded_rectangle((1,1,806,168),radius=24,fill=color,outline=stroke,width=5)
   if offset==0:
    for yy in [30,80,135]:d.line((22,yy,786,yy),fill=(31,31,38,255),width=1)
   mat=cv2.getPerspectiveTransform(sourcequad,poly+offset);arr=cv2.warpPerspective(np.asarray(tile),mat,(W,H),flags=cv2.INTER_CUBIC);back.alpha_composite(Image.fromarray(arr))
  face=ink(cfg['title'],cfg['fonts']['title'],100,(255,255,255,255),0,.08);face=face.rotate(2,resample=Image.Resampling.BICUBIC,expand=True)
  if face.width>760:raise ValueError('Title requires meaningful wrapping, not fixedwidth shrink')
  enter=1 if n==0 and cfg.get('warm') else out(.04,.40,t);place(text,face,550,142,enter*q)
  back=fade(back,q)
 card=cfg.get('identity',{});name=card.get('name','');desc=card.get('description','')
 if name or desc:
  d=ImageDraw.Draw(identity);y=975
  for txt,size in [(name,62),(desc,38)]:
   if txt:
    im=ink(txt,cfg['fonts']['caption'],size,'white');identity.alpha_composite(im,(78,y));y+=im.height+12
  if name and desc:d.line((78,1040,242,1040),fill=(255,213,52,255),width=4)
  identity=fade(identity,q*(1 if cfg.get('warm') and t==0 else out(.04,.4,t)))
 return back,text,identity

def caption(t,cfg):
 body=blank();shadow=blank();cue=next((c for c in cfg['captions'] if c['time'][0]<=t<c['time'][1]),None)
 if cfg.get('warm') and t==0:cue=dict(text='不用安排得太满',time=[0,.04],lines=[dict(text='不用安排得太满',emphasis_spans=[[5,7]])])
 if cue is None:return shadow,body
 lines=cue.get('lines',[dict(text=cue['text'],emphasis_spans=[])]);parts=[approved_visual.caption_parts(l) for l in lines];size=74;path=cfg['fonts']['caption'];widths=[sum(font(path,size).getlength(txt) for txt,_ in pp) for pp in parts]
 # Preserve natural glyphratio. Long confirmed cue wraps at existing token boundary,
 # while cue timing and semantic emphasis remain exactly unchanged.
 if max(widths)>970:raise ValueError('Caption line exceeds natural readingwidth; precompile semantic wrap')
 top=1545-(len(lines)-1)*88
 for j,pp in enumerate(parts):
  x=(W-widths[j])/2
  for txt,mark in pp:
   im=ink(txt,path,size,(255,242,0,255) if mark else (255,255,255,255),3,.12);body.alpha_composite(im,(round(x),round(top+j*88)));x+=font(path,size).getlength(txt)
 a,b=cue['time'];q=1 if cfg.get('warm') and t==0 else out(a-.04,a+.28,t);scale=1+.08*(1-q)
 if q<1:tmp=blank();place(tmp,body.crop(body.getbbox()),W/2,top,q,scale);body=tmp
 # Independent dark soft drop shadow uses sameglyph alpha, never presenter/sourcepixels.
 alpha=body.getchannel('A').filter(ImageFilter.GaussianBlur(3));shadow=Image.new('RGBA',(W,H),(8,8,8,0));shadow.putalpha(alpha.point(lambda v:round(v*.42)));shadow=shadow.transform((W,H),Image.Transform.AFFINE,(1,0,-2,0,1,-3))
 return shadow,body
