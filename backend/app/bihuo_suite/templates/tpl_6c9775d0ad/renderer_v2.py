from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import json,math,subprocess
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor import visual as V,media as M
from .vendor.pilot import font,text_image
SIZE=(1080,1920)
ROLES=('background','material','room_glow','presenter_room','head_foreground','title','support','swoosh','caption_shadow','caption_body','caption_emphasis')


def blank(): return Image.new('RGBA',SIZE)

def ramp(t,a,b): return max(0.,min(1.,(t-a)/(b-a))) if b>a else float(t>=b)

def opacity(im,q):
    if q>=1: return im
    im=im.copy(); im.putalpha(im.getchannel('A').point(lambda a:round(a*max(0,q)))); return im

def lerp(a,b,q): return np.array(a)*(1-q)+np.array(b)*q

def blurred(im,r=20): return im.resize((270,480)).filter(ImageFilter.GaussianBlur(r/4)).resize(SIZE,Image.Resampling.BILINEAR).convert('RGBA')

def window(texture,box,radius):
    x,y,x2,y2=box
    key={'time':0,'matrix':[[(x2-x)/1080,0,x/2],[0,(y2-y)/1920,y/2]],'rect':[v/2 for v in box],'radius':radius/2,'background_opacity':0}
    return V.render('V02',texture,0,{'size':list(SIZE),'fps':25,'stage_color':[0,0,0],'visual_keys':[key]})['presenter']

def room(raw,box):
    w,h=max(1,round(box[2]-box[0])),max(1,round(box[3]-box[1]))
    crop=raw.crop((0,100 if w/h<1.1 else 250,1080,1540 if w/h<1.1 else 1400))
    bg=M._fit(crop,w,h,{'fit':'cover'}).resize((max(1,w//4),max(1,h//4))).filter(ImageFilter.GaussianBlur(7)).resize((w,h))
    bg.alpha_composite(M._fit(crop,w,h,{'fit':'contain'})); return bg

@lru_cache(maxsize=30)
def photo(path,w,h):
    im=Image.open(path).convert('RGBA'); bg=M._fit(im,w,h,{'fit':'cover'}).filter(ImageFilter.GaussianBlur(25));bg.alpha_composite(M._fit(im,w,h,{'fit':'contain'})); return bg

def lines_for(text,path,size,maxw):
    rows=[]; s=''
    for ch in text:
        if s and font(path,size).getlength(s+ch)>maxw:
            if ch in '，。！？；：、' and len(s)>1: rows.append(s[:-1]); s=s[-1]
            else: rows.append(s);s=''
        s+=ch
    if s:rows.append(s)
    return rows

@lru_cache(maxsize=100)
def textcard(text,path,w,h):
    im=Image.new('RGBA',(w,h),(30,38,46,242)); d=ImageDraw.Draw(im)
    rows=lines_for(text,path,55,w-48)
    if len(rows)*76>h-40: raise ValueError('Information text exceeds native card capacity; split the planned item')
    y=(h-len(rows)*76)/2
    for row in rows:
        d.text((w/2,y),row,font=font(path,55),fill='white',anchor='mt',stroke_width=1,stroke_fill=(0,0,0));y+=76
    return im

@lru_cache(maxsize=600)
def glyph(ch,path,size,mark):
    return text_image(ch,path,size,(21,127,255,255) if mark else (255,255,255,255),2,(26,26,24,255))

def caption(c,n,out):
    t=n/25; row=next((q for q in c['captions'] if q['time'][0]<=t<q['time'][1]),None)
    if not row:return
    text=row['text']; spans=[]; cursor=0
    for line in row.get('lines',[]):
        pos=text.find(line.get('text',''),cursor)
        if pos>=0:
            spans += [(pos+a,pos+b) for a,b in line.get('emphasis_spans',[])];cursor=pos+len(line.get('text',''))
    chars=[]
    for i,ch in enumerate(text):
        mark=any(a<=i<b for a,b in spans); size=64; chars.append((ch,mark,size,float(font(c['font'],size).getlength(ch))))
    rows=[]; current=[];width=0
    for ch in chars:
        if current and width+ch[3]>1000:
            if ch[0] in '，。！？；：、' and len(current)>1: last=current.pop();rows.append(current);current=[last];width=last[3]
            else:rows.append(current);current=[];width=0
        current.append(ch);width+=ch[3]
    if current:rows.append(current)
    if len(rows)>3:raise ValueError('Caption exceeds native three-line capacity')
    q=min(1,(t-row['time'][0]+.04)/.28)
    for j,line in enumerate(rows):
        top=1598-(len(rows)-1)*112+j*112; x=(1080-sum(v[3] for v in line))/2
        for ch,mark,size,w in line:
            tile,b,pad=glyph(ch,c['font'],size,mark)
            ref=font(c['font'],size).getbbox('国',anchor='ls',stroke_width=2); baseline=top-ref[1]-(10 if mark else 0)
            out['caption_emphasis' if mark else 'caption_body'].alpha_composite(tile,(round(x+b[0]-pad),round(baseline+b[1]-pad)));x+=w
    for k in ['caption_body','caption_emphasis']:out[k]=opacity(out[k],q)
    a=Image.alpha_composite(out['caption_body'],out['caption_emphasis']).getchannel('A')
    sh=blank();sh.putalpha(a.filter(ImageFilter.GaussianBlur(2)).point(lambda a:round(a*.8)));out['caption_shadow'].alpha_composite(sh,(3,4))

def encode(c,out):
    cap=cv2.VideoCapture(c['source_path']);final=Path(out)/'final.mp4';log=open(Path(out)/'ffmpeg.log','wb')
    cmd=[c['ffmpeg'],'-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-i',c['source_path'],'-map','0:v:0','-map','1:a:0?','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(final)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log); raw=None;idx=-1
    try:
        for n in range(c['frames']):
            target=min(int(n*c['native_fps']/25),round(c['frames']*c['native_fps']/25)-1)
            while idx<target:
                ok,bgr=cap.read();idx+=1
                if not ok:raise RuntimeError(f'Source decode ended at {idx}')
                raw=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)).resize(SIZE).convert('RGBA')
            proc.stdin.write(np.asarray(render(raw,c,n)).tobytes())
            if n%50==0:print(f'frame {n}/{c["frames"]}',flush=True)
        proc.stdin.close();code=proc.wait()
        if code:raise RuntimeError(f'ffmpeg exit {code}; see ffmpeg.log')
    finally:cap.release();log.close()
    return final

@lru_cache(maxsize=1)
def grid():
    im=Image.new('RGBA',SIZE,(0,0,0,255));d=ImageDraw.Draw(im)
    for x in range(-1700,2800,170):
        d.line((x,0,540,960),fill=(54,54,54),width=3);d.line((x,1920,540,960),fill=(54,54,54),width=3)
    for y in [53,130,201,269,328,379,422,461,496,529,1392,1424,1459,1498,1541,1592,1650,1719,1789,1867]:d.line((0,y,1080,y),fill=(54,54,54),width=3)
    arr=np.asarray(im).copy(); yy=np.arange(1920);q=np.maximum(np.clip((730-yy)/200,0,1),np.clip((yy-1190)/200,0,1));arr[:,:,:3]=(arr[:,:,:3]*q[:,None,None]).astype(np.uint8)
    return Image.fromarray(arr)
def glowing_window(raw,box,radius,out):
    mask=blank();ImageDraw.Draw(mask).rounded_rectangle(tuple(box),radius=radius,fill=(255,255,255,255))
    halo=mask.filter(ImageFilter.GaussianBlur(25));out['room_glow']=opacity(halo,.65)
    out['presenter_room']=window(room(raw,box),box,radius)
def title(c,n,out):
    t=n/25;end=c['opening_end'];fade=1-ramp(t,max(.5,end-.22),end+.12)
    for key,text,size,x,y,delay in [('title',c.get('title',''),90,410,145,.12),('support',c.get('subtitle',''),52,410,313,.5)]:
        if not text or fade<=0:continue
        tile,b,pad=text_image(text,c['font'],size,(255,255,255,255),1,(22,69,165,255))
        if tile.width>640:
            size=max(28,round(size*640/tile.width));tile,b,pad=text_image(text,c['font'],size,(255,255,255,255),1,(22,69,165,255))
            if tile.width>660:raise ValueError('Title exceeds native safe width')
        shear=.18;tile=tile.transform((tile.width+round(tile.height*shear),tile.height),Image.Transform.AFFINE,(1,shear,-shear*tile.height,0,1,0),Image.Resampling.BICUBIC)
        q=ramp(t,delay,min(delay+.8,max(delay+.2,end-.25)));w=round(tile.width*q)
        if w:out[key].alpha_composite(opacity(tile.crop((0,0,w,tile.height)),fade),(x,y))
    if c.get('subtitle') and fade>0:
        q=ramp(t,.7,1.3);pts=[(480+i*5,394-15*math.sin(i/80*math.pi)) for i in range(round(80*q))]
        if len(pts)>1:ImageDraw.Draw(out['swoosh']).line(pts,fill=(21,127,255,round(255*fade)),width=6)
@lru_cache(maxsize=10)
def alpha_image(path):return Image.open(path).convert('L')
def head(raw,c,n,out):
    ref=c['foreground_alpha'].get(str(n))
    if not ref:raise ValueError(f'Missing head alpha at output {n}')
    alpha=alpha_image(ref['path']);bounds=alpha.getbbox()
    if not bounds:return
    box=[405,236,675,506];glowing_window(raw,box,135,out);out['presenter_room']=window(raw.crop((220,150,860,850)),box,135)
    # One stable source UV is calibrated from the first required native matte.
    first=alpha_image(next(iter(c['foreground_alpha'].values()))['path']).getbbox() or bounds
    scale=270/max(1,first[2]-first[0]);x=540-(first[0]+first[2])/2*scale;y=141-first[1]*scale
    fg=raw.copy();fg.putalpha(alpha);fg=fg.resize((round(1080*scale),round(1920*scale)),Image.Resampling.LANCZOS)
    canvas=blank();canvas.alpha_composite(fg,(round(x),round(y)));a=canvas.getchannel('A');a.paste(0,(0,506,1080,1920));allowed=out['presenter_room'].getchannel('A').copy();allowed.paste(255,(0,0,1080,236));a=Image.fromarray(np.minimum(np.asarray(a),np.asarray(allowed)));canvas.putalpha(a);out['head_foreground']=canvas
def render(raw,c,n,roles=False):
    t=n/25;out={k:blank() for k in ROLES};out['background']=grid().copy()
    active=[m for m in c['materials'] if m['start']<=t<m['end']+.16]
    text=[x for x in c['text_items'] if x['start']<=t<x['end']+.5]
    late=c.get('foreground_alpha') and c['head_start']<=t<c['final_start']
    if active:
        m=active[-1];out['background']=blurred(photo(m['path'],1080,1920),40);a=ramp(t,m['start'],m['start']+.32)*(1-ramp(t,m['end'],m['end']+.16))
        out['material']=opacity(window(photo(m['path'],972,1154),[54,312,1026,1466],38),a)
        glowing_window(raw,[105,132,387,412],140,out)
    elif late:
        head(raw,c,n,out)
        candidates=text[-1:]
        if candidates:
            x=candidates[0];tex=textcard(x['text'],c['font'],922,922);q=ramp(t,x['start'],x['start']+.3);out['material']=opacity(window(tex,[80,540,1002,1462],30),q)
    elif t<c['opening_end'] and (c.get('title') or c.get('subtitle')):
        out['background']=blurred(raw,35);glowing_window(raw,[105,132,387,412],140,out)
    elif t<c['final_start'] and c['materials'] and t>=c['materials'][-1]['end']:
        glowing_window(raw,[64,230,1016,1652],40,out)
    else:out['background']=raw.convert('RGBA')
    title(c,n,out);caption(c,n,out)
    # The entire sharp composition, including ordinary captions, is under the iris.
    mask=c.get('mask')
    if mask and mask[0]<=t<=mask[1]:
        q=abs(2*(t-mask[0])/(mask[1]-mask[0])-1);radius=round(1300*q*q);a=Image.new('L',SIZE);ImageDraw.Draw(a).ellipse((540-radius,884-radius,540+radius,884+radius),fill=255)
        outside=blurred(raw,42)
        sharp=blank()
        for layer in out.values():sharp.alpha_composite(layer)
        sharp.putalpha(a);outside.alpha_composite(sharp);out={k:blank() for k in ROLES};out['background']=outside
    composite=Image.new('RGBA',SIZE,(0,0,0,255))
    for layer in out.values():composite.alpha_composite(layer)
    if t>c['duration']-.5:composite=Image.blend(Image.new('RGBA',SIZE,(0,0,0,255)),composite,1-ramp(t,c['duration']-.5,c['duration']-.04))
    return (composite.convert('RGB'),out) if roles else composite.convert('RGB')
