import math
from functools import lru_cache
from PIL import Image
from .apple_minimal.pilot import text_image,font,ease
from .subtitle_engine.split_title import with_shadow
SIZE=(1080,1920)
def blank():return Image.new('RGBA',SIZE)

def alpha(im,q):im=im.copy();im.putalpha(im.getchannel('A').point([round(i*max(0,min(1,q))) for i in range(256)]));return im

@lru_cache(maxsize=512)
def tile(text,path,size,fill,stroke,edge):return text_image(text,path,size,fill,stroke,edge)

def put(layer,text,path,size,fill,stroke,edge,x,baseline,shadow=False):
 im,bb,pad=tile(text,path,size,fill,stroke,edge)
 if shadow:im=with_shadow(im,dict(shadowX=2,shadowY=2,shadowBlur=1))
 layer.alpha_composite(im,(round(x+bb[0]-pad),round(baseline+bb[1]-pad)))

def caption(c,n):
 layer=blank();layouts=[]
 row=next((r for r in c['captions'] if r['range'][0]<=n<r['range'][1]),None)
 if not row:return layer,layouts
 style=c.get('caption_style',{});gap=style.get('line_gap',90);anchor=style.get('baseline',1655);chars=list(row['text']);emph=[any(a<=i<b for a,b in row['emphasis_spans']) for i in range(len(chars))];sizes=[style.get('emphasis_size',90) if e else style.get('body_size',76) for e in emph];path=c['fonts']['body'];adv=[font(path,s).getlength(ch) for ch,s in zip(chars,sizes)];edges=[0]+row.get('line_breaks',[])+[len(chars)];widths=[sum(adv[a:b]) for a,b in zip(edges,edges[1:])];assert max(widths)<=1035,(row['text'],widths);line=0;x=(1080-widths[0])/2;baseline=anchor-gap*(len(widths)-1)
 for i,(ch,size,step,first,e) in enumerate(zip(chars,sizes,adv,row['glyph_firsts'],emph)):
  if i in edges[1:-1]:line+=1;x=(1080-widths[line])/2;baseline+=gap
  q=ease(first-.25,min(first+style.get('glyph_entry_frames',5),math.ceil(row['range'][1])-1) if c['mode']!='baseline' else first+style.get('glyph_entry_frames',5),n)
  if q>0:
   glyph=blank();put(glyph,ch,path,size,tuple(style.get('emphasis_fill',[255,218,54,255])) if e else tuple(style.get('body_fill',[255,248,229,255])),style.get('stroke',4),(44,34,25,255),x,baseline,style.get('shadow',True))
   # Fixed complete-line cursor; only this glyph's opacity/vertical growth changes.
   if q<1:
    start=style.get('grow_from',.87);scale=start+(1-start)*q;box=glyph.getchannel('A').getbbox()
    if box:
     part=glyph.crop(box);part=part.resize((part.width,max(1,round(part.height*scale))),Image.Resampling.BICUBIC);glyph=blank();glyph.alpha_composite(part,(box[0],round(baseline-(baseline-box[1])*scale)))
   layer.alpha_composite(alpha(glyph,q))
  layouts.append(dict(index=i,char=ch,first=first,x=x,advance=step,size=size,emphasis=e));x+=step
 return layer,dict(id=row['id'],line_widths=widths,baseline=baseline,glyphs=layouts,no_cursor=True,fixed_line_anchor=True)
original_caption=caption
