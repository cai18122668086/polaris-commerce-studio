import math
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
SIZE=(1080,1920)
def fade(im,q):
 im=im.copy();im.putalpha(im.getchannel('A').point([round(a*max(0,min(1,q))) for a in range(256)]));return im

def word_tile(text,path,size,color,stroke=0,shear=0):
 tile=text_image(text,path,size,color)[0];box=tile.getchannel('A').getbbox();tile=tile.crop(box)
 if stroke:
  alpha=tile.getchannel('A');back=Image.new('RGBA',tile.size,(14,14,18,255));back.putalpha(alpha.filter(ImageFilter.MaxFilter(stroke*2+1)));back.alpha_composite(tile);tile=back
 if shear:
  width=tile.width+math.ceil(abs(shear)*tile.height);tile=tile.transform((width,tile.height),Image.Transform.AFFINE,(1,shear,-shear*tile.height if shear>0 else 0,0,1,0),resample=Image.Resampling.BICUBIC)
 return tile

def blank():return Image.new('RGBA',SIZE)

def ramp(n,a,b):return min(1,max(0,(n-a)/(b-a)))if b>a else float(n>=b)

def tile(text,path,size,color,stroke=0):return T.word_tile(text,path,size,color,stroke,0)

def place(out,text,path,size,color,x,y,stroke=0):
 if not text:return
 im=tile(text,path,size,color,stroke);assert x>=0 and x+im.width<=1080,(text,im.width,x);out.alpha_composite(im,(round(x),round(y)))

def caption_tile(text,cfg,size,color):
 core=tile(text,cfg['fonts']['body'],size,color);w,h=core.size;pad=10;alpha=Image.new('L',(w+pad*2,h+pad*2));alpha.paste(core.getchannel('A'),(pad,pad));alpha=alpha.filter(ImageFilter.MaxFilter(3));ink=Image.new('RGBA',alpha.size,color);ink.putalpha(alpha)
 edge=Image.new('RGBA',alpha.size,(15,15,19,255));edge.putalpha(alpha.filter(ImageFilter.MaxFilter(5)));edge.alpha_composite(ink)
 return edge,w,pad

def captions(cfg,n):
 out={k:blank()for k in ['caption_shadow','caption_body','caption_emphasis']};row=next((r for r in cfg['captions']if r['frames'][0]<=n<r['frames'][1]),None)
 if cfg['mode']=='baseline'and n==0:row=cfg['captions'][0]
 if row is None:return out,dict(active=False)
 q=1 if cfg['mode']=='baseline'and n==0 else min(1,(n-row['frames'][0]+1)/8)
 tiles=[(*caption_tile(text,cfg,cfg.get('caption_emphasis_size',84)if emph else cfg.get('caption_body_size',72),(236,205,94,255)if emph else(255,255,255,255)),emph)for text,emph in V.caption_parts(row)];width=sum(w for _,w,_,_ in tiles);assert width<=1040,(row['text'],width);x=(1080-width)/2
 for im,advance,pad,emph in tiles:
  out['caption_emphasis'if emph else'caption_body'].alpha_composite(im,(round(x-pad),1578-pad));shadow=Image.new('RGBA',im.size,(0,0,0,255));shadow.putalpha(im.getchannel('A'));out['caption_shadow'].alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)),(round(x-pad+3),1578-pad+4));x+=advance
 halo=blank()
 for key in ['caption_body','caption_emphasis']:halo.alpha_composite(out[key])
 a=halo.getchannel('A').filter(ImageFilter.GaussianBlur(10)).point(lambda v:round(v*.95));white=Image.new('RGBA',SIZE,(255,255,255,255));white.putalpha(a);white.alpha_composite(out['caption_shadow']);out['caption_shadow']=white
 return{k:fade(v,q)for k,v in out.items()},dict(active=True,text=row['text'],frames=row['frames'],fa_native_ms=row.get('fa_native_ms'),natural_width=width)
