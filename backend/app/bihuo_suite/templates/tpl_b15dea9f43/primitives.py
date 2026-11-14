import math
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageChops
SIZE=(1080,1920)
def blank():return Image.new('RGBA',SIZE)

def ramp(n,a,b):return max(0,min(1,(n-a)/(b-a)))if b>a else float(n>=b)

def fade(im,q):return opacity(im,q)

def cleanRGB(im):
 a=np.array(im);a[a[:,:,3]==0]=0;return Image.fromarray(a)

def tile(text,cfg,size,color,stroke=3):return word_tile(text,cfg['fonts']['body'],size,color,stroke,.12)

def put(out,text,cfg,size,color,x,y,stroke=3):
 if not text:return
 im=tile(text,cfg,size,color,stroke);assert x>=0 and x+im.width<=1080,(text,im.width,x);out.alpha_composite(im,(round(x),round(y)))

def titles(cfg,n):
 out={k:blank()for k in ['title_shadow','title_main','title_support']};baseline=cfg['mode']=='baseline';warm=baseline and n==0
 mainq=1 if warm else min(ramp(n,1,9),1-ramp(n,71,80));supportq=1 if warm else min(ramp(n,21,27),1-ramp(n,67,72))
 main=cfg.get('title','').strip();support=cfg.get('support','').strip();suffix=cfg.get('support_suffix','').strip()
 if main:
  im=tile(main,cfg,110,(255,255,255,255),5);assert im.width<=1020;out['title_main'].alpha_composite(im,(round((1080-im.width)/2),164));out['title_main']=fade(out['title_main'],mainq)
 if support or suffix:
  left=tile(support,cfg,100,(234,203,109,255),3)if support else None;right=tile(suffix,cfg,52,(255,255,255,255),3)if suffix else None
  width=(left.width if left else 0)+(right.width+12 if right else 0);assert width<=970,(support,suffix,width);x=94
  if left:out['title_support'].alpha_composite(left,(x,342));x+=left.width+12
  if right:out['title_support'].alpha_composite(right,(x,380))
  out['title_support']=fade(out['title_support'],supportq)
 for key in ['title_main','title_support']:
  alpha=out[key].getchannel('A');shadow=Image.new('RGBA',SIZE,(0,0,0,255));shadow.putalpha(alpha.point(lambda a:round(a*.75)));out['title_shadow'].alpha_composite(ImageChops.offset(shadow,5,6))
 return out

def identity(cfg,n):
 out=blank();ident=cfg.get('identity',{});name=str(ident.get('name','')).strip();desc=str(ident.get('description','')).strip()
 if not ident.get('enabled',True)or not(name or desc):return out
 q=1 if cfg['mode']=='baseline'and n==0 else min(ramp(n,3,12),1-ramp(n,71,76))
 if name:put(out,name,cfg,42,(255,255,255,255),130,958,1)
 if desc:put(out,desc,cfg,27,(255,255,255,255),130,1035,1)
 if name or desc:ImageDraw.Draw(out).rectangle((112,1017,258,1021),fill=(235,205,115,255))
 return fade(out,q)

def iris_radius(cfg,n):
 n=n-cfg.get('iris_shift',0)
 if cfg['mode']!='baseline':n=n-175+120
 samples=cfg['iris_samples'];first,last=samples[0][0],samples[-1][0]
 if n<first or n>last:return None
 return max(0,float(lerp(samples,n)[0]))

def lerp(keys,n):
 if n<=keys[0][0]:return keys[0][1]
 for (a,v),(b,w) in zip(keys,keys[1:]):
  if a<=n<=b:return np.asarray(v)*(1-(n-a)/(b-a))+np.asarray(w)*(n-a)/(b-a)
 return keys[-1][1]

def word_tile(text,path,size,color,stroke=0,shear=0):
 tile=text_image(text,path,size,color)[0];box=tile.getchannel('A').getbbox();tile=tile.crop(box)
 if stroke:
  alpha=tile.getchannel('A');back=Image.new('RGBA',tile.size,(14,14,18,255));back.putalpha(alpha.filter(ImageFilter.MaxFilter(stroke*2+1)));back.alpha_composite(tile);tile=back
 if shear:
  width=tile.width+math.ceil(abs(shear)*tile.height);tile=tile.transform((width,tile.height),Image.Transform.AFFINE,(1,shear,-shear*tile.height if shear>0 else 0,0,1,0),resample=Image.Resampling.BICUBIC)
 return tile
def opacity(im,q):
 out=im.copy();out.putalpha(out.getchannel("A").point(lambda z:round(z*max(0,min(1,q)))));return out
