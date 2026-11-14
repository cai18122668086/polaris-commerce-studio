"""Reference-specific mechanisms; transferable parameters, no source-video pixels in text layers."""
from pathlib import Path
from functools import lru_cache
import json,math,hashlib
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter,ImageEnhance
W,H=284,504;S=4

def progress(n,a,b):return max(0,min(1,(n-a)/max(1,b-a)))
def alpha(im,op):
 im=im.copy();im.putalpha(im.getchannel('A').point(lambda x:round(x*max(0,min(1,op)))));return im
def blank():return Image.new('RGBA',(W,H))
@lru_cache(maxsize=256)
def text_tile(text,style_json):
 s=json.loads(style_json);font=ImageFont.truetype(s['font'],round(s['size']*4));bb=font.getbbox(text);mask=Image.new('L',(bb[2]-bb[0]+16,bb[3]-bb[1]+16));ImageDraw.Draw(mask).text((8-bb[0],8-bb[1]),text,font=font,fill=255,stroke_width=round(s.get('weight',0)*4));mask=mask.crop(mask.getbbox())
 if s.get('inkWidth') and s.get('inkHeight'):mask=mask.resize((round(s['inkWidth']*4),round(s['inkHeight']*4)),Image.Resampling.LANCZOS)
 if s.get('skew'):
  sk=s['skew'];mask=mask.transform((mask.width+round(mask.height*abs(sk)),mask.height),Image.Transform.AFFINE,(1,sk,-mask.height*sk,0,1,0),Image.Resampling.BICUBIC)
 pad=24;out=Image.new('RGBA',(mask.width+48,mask.height+48));shadow=Image.new('L',out.size);shadow.paste(mask,(pad+round(s.get('shadowX',.6)*4),pad+round(s.get('shadowY',.8)*4)));layer=Image.new('RGBA',out.size,'#08090c');layer.putalpha(shadow.filter(ImageFilter.GaussianBlur(s.get('shadowBlur',.35)*4)).point(lambda a:round(a*.85)));out.alpha_composite(layer)
 color=Image.new('RGBA',mask.size,s.get('fill','#ffffff'));color.putalpha(mask);out.alpha_composite(color,(pad,pad))
 return out.resize((round(out.width/4),round(out.height/4)),Image.Resampling.LANCZOS),(mask.width/4,mask.height/4)

def puttext(out,text,style,cx,y,op=1,scale=1,glow=0):
 tile,(w,h)=text_tile(text,json.dumps(style,sort_keys=True));pad=6
 if glow:
  g=Image.new('RGBA',tile.size,'#ffe38a');g.putalpha(tile.getchannel('A').filter(ImageFilter.GaussianBlur(3)).point(lambda a:round(min(255,a*1.8*glow))));out.alpha_composite(g,(round(cx-w/2-pad),round(y-pad)))
 if scale!=1:tile=tile.resize((round(tile.width*scale),round(tile.height*scale)),Image.Resampling.BICUBIC)
 out.alpha_composite(alpha(tile,op),(round(cx-w*scale/2-pad*scale),round(y-(h*(scale-1))/2-pad*scale)))
