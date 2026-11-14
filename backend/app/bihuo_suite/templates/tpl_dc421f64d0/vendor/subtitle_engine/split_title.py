"""N07 corrected split-title role. Original visual provider is read-only referenced."""
from pathlib import Path
import json,math
from functools import lru_cache
from PIL import Image,ImageDraw,ImageFont,ImageFilter,ImageChops
from .core import blank,progress,alpha,text_tile,puttext,W,H

def paint(out,tile,x,y,op=1):out.alpha_composite(alpha(tile,op),(round(x),round(y)))

def split_rgba(layer,cut_y,dx=0,dy=15):
 """Shared primitive: split one full-frame text RGBA into its upper/lower masks.
 Upper moves (-dx,-dy), lower moves (+dx,+dy); supports vertical/diagonal variants.
 No duplication of complete text, no font or event policy in this primitive.
 """
 upmask=Image.new('L',layer.size);ImageDraw.Draw(upmask).rectangle((0,0,layer.width,round(cut_y)-1),fill=255);lomask=Image.new('L',layer.size);ImageDraw.Draw(lomask).rectangle((0,round(cut_y),layer.width,layer.height),fill=255)
 a=layer.copy();a.putalpha(ImageChops.multiply(a.getchannel('A'),upmask));b=layer.copy();b.putalpha(ImageChops.multiply(b.getchannel('A'),lomask));upper=Image.new('RGBA',layer.size);lower=Image.new('RGBA',layer.size);paint(upper,a,-dx,-dy);paint(lower,b,dx,dy);return upper,lower

def with_shadow(layer,style):
 mask=layer.getchannel('A');shift=Image.new('L',layer.size);shift.paste(mask,(round(style.get('shadowX',1)),round(style.get('shadowY',1))));shadow=Image.new('RGBA',layer.size,'#020306');shadow.putalpha(shift.filter(ImageFilter.GaussianBlur(style.get('shadowBlur',.5))).point(lambda v:round(v*.85)));shadow.alpha_composite(layer);return shadow

@lru_cache(maxsize=64)
def glyph_run(text,style_json,tracking=0):
 s=json.loads(style_json);font=ImageFont.truetype(s['font'],round(s['size']*4));ascent,descent=font.getmetrics();adv=[font.getlength(ch)/4 for ch in text];total=sum(adv)+max(0,len(text)-1)*tracking
 # Shared baseline; glyph top variation retained, not normalized per character.
 layer=Image.new('RGBA',(round((total+20)*4),round((ascent+descent)/4*4+80)));d=ImageDraw.Draw(layer);cursor=40;baseline=40+ascent
 for ch,width in zip(text,adv):d.text((round(cursor),baseline),ch,font=font,anchor='ls',fill=s.get('fill','#fffef7'));cursor+=(width+tracking)*4
 bb=layer.getchannel('A').getbbox();body=layer.crop(bb);body=body.resize((round(body.width/4),round(body.height/4)),Image.Resampling.LANCZOS);return body,adv

def title_layers(n,c):
 s=c['splitSubtitle'];e=s['events'];style=s['whiteStyle'];text=s['white'];tile,_=glyph_run(text,json.dumps(style,sort_keys=True),s.get('tracking',0));tw,th=tile.size;x=s['cx']-tw/2;y=s['whiteY'];p=progress(n,e['splitStart'],e['splitSettle']);p=1-(1-p)**3;distance=s['splitDistance']*p
 upper=blank();lower=blank();gold=blank();body=blank()
 if n>=e['entryStart']:
  # Non-adjacent letters become visible before intervening glyphs; same baseline.
  if n<e['entrySettle']:
   font=ImageFont.truetype(style['font'],round(style['size']*4));ad=[font.getlength(ch)/4+s.get('tracking',0) for ch in text];cx=s['cx']-sum(ad)/2;order=s.get('entryOrder',list(range(len(text))))
   for k,ch in enumerate(text):
    start=e['entryStart']+order.index(k)*s.get('glyphStagger',1);q=progress(n,start,start+5);single,_=text_tile(ch,json.dumps(style,sort_keys=True));paint(body,single,cx-6,y-6,q);cx+=ad[k]
  else:paint(body,tile,x,y)
  body=with_shadow(body,style)
  if p>0:
   # Cut ONE text layer along its actual ink midline. Neither half is a full duplicated line.
   cut=round(y+th*s.get('splitRatio',.5));upper,lower=split_rgba(body,cut,0,distance)
  else:upper=body
 if n>=e['goldStart']:
  cached,_=glyph_run(s['gold'],json.dumps(s['goldStyle'],sort_keys=True),s.get('goldTracking',0));tile=cached.copy();q=progress(n,e['goldStart'],e['goldSettle']);gx=s['cx']-tile.width/2;gy=s['goldY']+(1-q)*5
  # Horizontal reveal from narrow center slot into the measured gold phrase.
  mask=Image.new('L',tile.size);a=round(tile.width*(1-q)/2);ImageDraw.Draw(mask).rectangle((a,0,tile.width-a,tile.height),fill=255);tile.putalpha(ImageChops.multiply(tile.getchannel('A'),mask));paint(gold,tile,gx,gy,q)
 gold=with_shadow(gold,s['goldStyle']);return {'whiteUpper':upper,'whiteLower':lower,'goldMiddle':gold}

def subtitle(family,n,c):
 if family!='T04':raise ValueError(family)
 s=c['splitSubtitle'];out=title_layers(n,c);mark=blank();x,y,w,h=s['marker']['rect'];q=progress(n,*s['marker']['clock'])
 if q>0:
  overlay=Image.new('RGBA',(W,H));ImageDraw.Draw(overlay).rectangle((x,y,x+w*q,y+h),fill=(244,201,26,150));mark.alpha_composite(overlay)
 out['documentMarker']=mark
 # Ordinary setup speech is a support layer, not a new subtitle family.
 speech=blank()
 for cue in s.get('setupCues',[]):
  if cue['in']<=n<cue['out']:puttext(speech,cue['text'],s['setupStyle'],142,s.get('setupY',332))
 out['setupSpeech']=speech;return out
