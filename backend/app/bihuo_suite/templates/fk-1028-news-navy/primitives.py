from functools import lru_cache
import math,json
from pathlib import Path
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter
W,H=1080,1920
O=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding="utf8"))
@lru_cache(maxsize=1)
def measured():return read(O/'native-ticker-parameters-v2.json')

def blank():return Image.new('RGBA',(W,H))

def normalize(im):
 a=np.array(im.convert('RGBA'));a[a[:,:,3]==0,:3]=0;return Image.fromarray(a)

def opacity(im,q):
 if q>=1:return im
 out=im.copy();out.putalpha(out.getchannel('A').point(lambda x:round(x*max(0,q))));return out

@lru_cache(maxsize=512)
def tile(s,path,size,color):
 im=text_image(s,path,size,color)[0];b=im.getchannel('A').getbbox();return im.crop(b)if b else Image.new('RGBA',(1,1))

def ticker(cfg,n):
 roles={k:blank()for k in['ticker_plate','ticker_text','live']};data=cfg['ticker'];items=[s.strip()for s in data.get('items',[])if isinstance(s,str)and s.strip()]
 if not data.get('enabled',True)or not items:return roles,dict(active=False,items=0)
 native=cfg['mode']=='source';entry=measured()['entry']
 if native:
  q=entry[n]['opacity_contrast_candidate']if n<=25 else 1
  dx=14 if n==0 else 59 if n<=8 else 57 if n==9 else -3.6*(n-25);first=134.17+dx
 else:
  first_ink=cfg.get('ticker_entry_frame',5);mapped=n-first_ink+2;q=0 if mapped<2 else entry[mapped]['opacity_contrast_candidate']if mapped<=9 else 1;steady=first_ink+7;delay=cfg.get('scroll_delay_frames',0);z=n-delay-steady;distance=0 if z<0 else 2 if z==0 else 5+3.6*(z-1);first=193.17-distance
 if q<=0:return roles,dict(active=False,items=len(items),opacity=0)
 d=ImageDraw.Draw(roles['ticker_plate']);d.rounded_rectangle((24,160,1055,259),radius=20,fill=(242,244,249,255));live=roles['live'];d=ImageDraw.Draw(live);d.rounded_rectangle((24,160,181,259),radius=20,fill=(227,115,65,255));d.rectangle((160,160,181,259),fill=(227,115,65,255));face=cfg['fonts']['ticker'];size=cfg.get('ticker_size',30);dark=(10,31,53,255);livepath=cfg['fonts'].get('live',face);im=tile('LIVE',livepath,30,dark);live.alpha_composite(im,(80,198));dot=tile('•',face,22,(10,31,53,90));live.alpha_composite(dot,(round(61-dot.width/2),round(210-dot.height/2)))
 advance=[float(font(face,size).getlength(s))+58 for s in items];cycle=sum(advance);start=first%cycle-cycle;strip=Image.new('RGBA',(874,100));orange=(167,76,25,255);positions=[]
 while start<1056:
  xx=start
  for s,pitch in zip(items,advance):
   if xx+pitch>=182 and xx<1056:
    dot=tile('•',face,size,orange);strip.alpha_composite(dot,(round(xx-182-dot.width/2),round(210-160-dot.height/2)));im=tile(s,face,size,dark);strip.alpha_composite(im,(round(xx+31-182),round(211-160-im.height/2)));positions.append(dict(text=s,dot_x=xx,advance=pitch))
   xx+=pitch
  start+=cycle
 roles['ticker_text'].alpha_composite(strip,(182,160));roles={k:normalize(opacity(v,q))for k,v in roles.items()};return roles,dict(active=True,items=len(items),cycle=cycle,first_dot=first,opacity=q,visible_items=positions,source_cycle_is_not_universal=True)

def quadmask(poly,radius=0):
 scale=2;pts=np.array(poly,float);path=[]
 for i,p in enumerate(pts):
  a=pts[(i-1)%4]-p;b=pts[(i+1)%4]-p;r=min(radius,np.linalg.norm(a)/3,np.linalg.norm(b)/3)
  if r<=0:path.append(tuple(p*scale));continue
  a=p+a/np.linalg.norm(a)*r;b=p+b/np.linalg.norm(b)*r
  for q in np.linspace(0,1,9):path.append(tuple(((1-q)**2*a+2*(1-q)*q*p+q*q*b)*scale))
 m=Image.new('L',(2160,3840));ImageDraw.Draw(m).polygon(path,fill=255);return m.resize((1080,1920),Image.Resampling.LANCZOS)

def captions(cfg,n):
 roles={k:blank()for k in['caption_body','caption_emphasis','caption_outline','caption_shadow']};cue=next((r for r in cfg['captions']if r['frames'][0]<=n<r['frames'][1]),None)
 if not cue:return roles,[]
 pieces=[]
 for text,active in V.caption_parts(dict(text=cue['text'],emphasis_spans=cue.get('emphasis_spans',[]))):
  size=76 if active else cfg['body_size'];color=(255,144,53,255)if active else(255,255,255,255);im=T.tile(text,cfg['fonts']['body'],size,color);ext=round(cfg['body_shear']*im.height)+2;im=im.transform((im.width+ext,im.height),Image.Transform.AFFINE,(1,cfg['body_shear'],-ext,0,1,0),Image.Resampling.BICUBIC);im=im.crop(im.getchannel('A').getbbox());pieces.append((im,active,text))
 width=sum(im.width for im,_,_ in pieces)+max(0,len(pieces)-1);assert width<=1010,('Native caption capacity',cue['text'],width);x=round(540-width/2);meta=[]
 for im,active,text in pieces:
  y=1595-(6 if active else 0);k='caption_emphasis'if active else'caption_body';roles[k].alpha_composite(im,(x,y));meta.append(dict(text=text,active=active,bounds=[x,y,x+im.width,y+im.height]));x+=im.width+1
 both=blank();both.alpha_composite(roles['caption_body']);both.alpha_composite(roles['caption_emphasis']);m=both.getchannel('A');outline=Image.new('RGBA',(1080,1920),(0,0,0,0));outline.putalpha(m.filter(ImageFilter.MaxFilter(3)).point(lambda z:round(z*.9)));shadow=Image.new('RGBA',(1080,1920),(0,0,0,0));shift=Image.new('L',(1080,1920));shift.paste(m,(3,5));shadow.putalpha(shift.filter(ImageFilter.GaussianBlur(2)).point(lambda z:round(z*.8)));roles['caption_outline']=outline;roles['caption_shadow']=shadow;fit=read(O/'caption-entry-fit.json')['rows'];values=[r['opacity_contrast']for r in fit];q=float(np.interp(n-cue['frames'][0]+119,list(range(118,129)),values));roles={k:T.normalize(T.opacity(v,q))for k,v in roles.items()};return roles,meta

def identity(cfg,n):
 out=blank();row=cfg['identity'];name=row.get('name','').strip();desc=row.get('description','').strip()
 if not row.get('enabled',True)or not(name or desc)or n/25>=cfg['identity_end']:return out,dict(active=False)
 y=1370
 for text,size,color in[(name,40,(255,144,53,255)),(desc,32,(255,255,255,255))]:
  if not text:continue
  im=T.tile(text,cfg['fonts']['identity'],size,color);assert im.width<920;out.alpha_composite(im,(74,y));y+=52
 return T.normalize(out),dict(active=True,explicit_name=name,explicit_description=desc,native_source_identity=False)
