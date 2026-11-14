from functools import lru_cache
import math
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter,ImageChops
SIZE=(1080,1920);YELLOW=(255,217,0,255)
def blank():return Image.new('RGBA',SIZE)

def clamp(x):return max(0,min(1,x))

def out(a,b,n):return 1-(1-clamp((n-a)/(b-a)))**3 if b>a else float(n>=b)

def op(im,q):
    if q>=1:return im
    a=im.copy();a.putalpha(a.getchannel('A').point(lambda x:round(x*clamp(q))));return a

def boxmix(a,b,q):return [round(x+(y-x)*q) for x,y in zip(a,b)]

@lru_cache(maxsize=120)
def text_tile(text,path,size,spans=(),bold=False,tracking=0,stroke=2,shadow=True,slant=0):
    face=font(path,size);box=face.getbbox(text,anchor='ls');width=math.ceil(sum(face.getlength(c) for c in text)+tracking*max(0,len(text)-1));height=box[3]-box[1]
    ink=Image.new('RGBA',(width+40,height+40));d=ImageDraw.Draw(ink);x=20
    for i,ch in enumerate(text):
        color=YELLOW if any(a<=i<b for a,b in spans) else (255,255,255,255)
        d.text((x,20-box[1]),ch,font=face,anchor='ls',fill=color,stroke_width=stroke,stroke_fill=(14,13,24,255));x+=face.getlength(ch)+tracking
    if slant:
        ink=ink.transform((ink.width+round(ink.height*abs(slant)),ink.height),Image.Transform.AFFINE,(1,slant,-slant*ink.height,0,1,0),Image.Resampling.BICUBIC)
    bb=ink.getchannel('A').getbbox();ink=ink.crop(bb);pad=12;tile=Image.new('RGBA',(ink.width+2*pad,ink.height+2*pad))
    if shadow:
        sh=Image.new('RGBA',tile.size,(4,3,10,0));mask=Image.new('L',tile.size);mask.paste(ink.getchannel('A'),(pad+2,pad+4));sh.putalpha(mask.filter(ImageFilter.GaussianBlur(2)).point(lambda a:round(a*.8)));tile.alpha_composite(sh)
    tile.alpha_composite(ink,(pad,pad));return tile,(pad,pad,ink.width,ink.height)

def place_text(layer,text,path,size,top,spans=(),tracking=0,stroke=2,shadow=True,slant=0,alpha=1,scale=1):
    tile,bb=text_tile(text,path,size,tuple(tuple(x) for x in spans),False,tracking,stroke,shadow,slant)
    pad,pad2,w,h=bb
    if scale!=1:
        tile=tile.resize((round(tile.width*scale),round(tile.height*scale)),Image.Resampling.LANCZOS)
    x=round((1080-w*scale)/2-pad*scale);y=round(top-pad2*scale-(h*(scale-1)/2))
    layer.alpha_composite(op(tile,alpha),(x,y));return {'ink_width':w*scale,'ink_height':h*scale,'ink_top':top,'fill_anchor_x':540,'font':path,'size':size,'scale':scale,'opacity':alpha}

def window(raw,box,radius=32,uv=1,source_plate=False):
    x,y,x2,y2=box;w=x2-x;h=y2-y
    if source_plate:texture=raw.resize((w,h),Image.Resampling.LANCZOS)
    else:
        # UV camera scale is independent of border geometry. At the wide-view event only available
        # clean-input pixels are used; beyond its portrait edges V02-style border replication is explicit.
        cover=max(w/raw.width,h/raw.height);contain=min(w/raw.width,h/raw.height);s=contain+(cover-contain)*uv
        matrix=np.float32([[s,0,(w-raw.width*s)/2],[0,s,(h-raw.height*s)*.35]])
        tex=cv2.warpAffine(np.array(raw.convert('RGB')),matrix,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE);texture=Image.fromarray(tex).convert('RGBA')
    texture=texture.resize(SIZE,Image.Resampling.LANCZOS)
    layer=visual.render('V02',texture,0,{'size':list(SIZE),'fps':25,'stage_color':[33,31,68],'visual_keys':[{'time':0,'matrix':[[w/1080,0,x/2],[0,h/1920,y/2]],'rect':[x/2,y/2,x2/2,y2/2],'radius':radius/2,'background_opacity':0}]})['presenter']
    ImageDraw.Draw(layer).rounded_rectangle(box,radius=radius,outline=(255,255,255,255),width=6);return layer

def paint(out,tile,x,y,op=1):out.alpha_composite(alpha(tile,op),(round(x),round(y)))

def split_rgba(layer,cut_y,dx=0,dy=15):
 """Shared primitive: split one full-frame text RGBA into its upper/lower masks.
 Upper moves (-dx,-dy), lower moves (+dx,+dy); supports vertical/diagonal variants.
 No duplication of complete text, no font or event policy in this primitive.
 """
 upmask=Image.new('L',layer.size);ImageDraw.Draw(upmask).rectangle((0,0,layer.width,round(cut_y)-1),fill=255);lomask=Image.new('L',layer.size);ImageDraw.Draw(lomask).rectangle((0,round(cut_y),layer.width,layer.height),fill=255)
 a=layer.copy();a.putalpha(ImageChops.multiply(a.getchannel('A'),upmask));b=layer.copy();b.putalpha(ImageChops.multiply(b.getchannel('A'),lomask));upper=Image.new('RGBA',layer.size);lower=Image.new('RGBA',layer.size);paint(upper,a,-dx,-dy);paint(lower,b,dx,dy);return upper,lower

def alpha(im,op):
 im=im.copy();im.putalpha(im.getchannel('A').point(lambda x:round(x*max(0,min(1,op)))));return im
