from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import json,math,subprocess
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor import visual as V,media as M
from .vendor.pilot import font,text_image
SIZE=(1080,1920)
ROLES=('background','native_video','outline_cyan','outline_white','presenter_foreground','materials','material_text','identity','title','caption_shadow','caption_body','caption_emphasis')


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
    return text_image(ch,path,size,(255,255,255,255) if mark else (255,255,255,255),2,(26,26,24,255))

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
        mark=any(a<=i<b for a,b in spans); size=76; chars.append((ch,mark,size,float(font(c['font'],size).getlength(ch))))
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
    im=Image.new('RGBA',SIZE,(15,30,51,255));d=ImageDraw.Draw(im)
    for x in range(-1700,2800,170):
        d.line((x,0,540,960),fill=(46,72,111),width=3);d.line((x,1920,540,960),fill=(46,72,111),width=3)
    for y in [53,130,201,269,328,379,422,461,496,529,1392,1424,1459,1498,1541,1592,1650,1719,1789,1867]:d.line((0,y,1080,y),fill=(46,72,111),width=3)
    arr=np.asarray(im).copy(); yy=np.arange(1920);q=np.maximum(np.clip((730-yy)/200,0,1),np.clip((yy-1190)/200,0,1));arr[:,:,:3]=(arr[:,:,:3]*q[:,None,None]).astype(np.uint8)
    return Image.fromarray(arr)

def subject(raw,c,n,box,out,cyan=True):
    ref=c.get('foreground_alpha',{}).get(str(n))
    if not ref:raise ValueError(f'Missing real native foreground {n}')
    alpha=alpha_image(ref['path']);bbox=alpha.getbbox()
    if not bbox:return
    # True full-body alpha; no synthetic reflection or stored other-person mask.
    fg=raw.copy();fg.putalpha(alpha);fg=fg.crop(bbox)
    x,y,x2,y2=box;w,h=x2-x,y2-y;scale=min(w/fg.width,h/fg.height);fg=fg.resize((max(1,round(fg.width*scale)),max(1,round(fg.height*scale))),Image.Resampling.LANCZOS)
    layer=blank();layer.alpha_composite(fg,(round((x+x2-fg.width)/2),round(y)))
    aa=np.asarray(layer.getchannel('A'))
    if cyan:
        for k,r,color in [('outline_cyan',18,(29,223,255,255)),('outline_white',3,(240,255,255,255))]:
            edge=cv2.dilate(aa,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(r*2+1,r*2+1)));im=Image.new('RGBA',SIZE,color);im.putalpha(Image.fromarray(edge));out[k]=im
    out['presenter_foreground']=layer
def opening(c,t,out):
    end=c.get('opening_end',2.5);q=ramp(t,0,.32)*(1-ramp(t,max(.4,end-.2),end+.12))
    for text,size,top in [(c.get('title',''),112,125),(c.get('subtitle',''),56,280)]:
        if not text or q<=0:continue
        rows=lines_for(text,c['font'],size,980)
        if len(rows)>2:raise ValueError('Opening text exceeds two lines')
        for j,row in enumerate(rows):
            tile,_,_=text_image(row,c['font'],size,(255,255,255,255),2,(15,30,50,255));out['title'].alpha_composite(opacity(tile,q),(round((1080-tile.width)/2),top+j*(size+14)))
    info=c['creative_options'].get('identity') or c['creative_options'].get('name_card') or {}
    name=str(info.get('name','')).strip();desc=str(info.get('description','')).strip()
    if info.get('enabled',True) and (name or desc) and q>0:
        d=ImageDraw.Draw(out['identity']);d.rounded_rectangle((90,1033,450,1195),radius=18,fill=(12,30,54,round(230*q)))
        for i,text in enumerate([v for v in [name,desc] if v]):d.text((112,1050+i*60),text,font=font(c['font'],44),fill=(255,255,255,round(255*q)))
def card(tile,box,q=1):return opacity(window(tile,box,32),q)
def render(raw,c,n,roles=False):
    t=n/25;duration=c['duration'];out={k:blank() for k in ROLES};out['background']=grid().copy()
    active=[m for m in c['materials'] if m['start']<=t<m['end']+.28]
    texts=[x for x in c['text_items'] if x['start']<=t<x['end']+.2]
    late_start=min([x['start'] for x in c['text_items'] if x['start']>=duration*.58] or [c['final_start']])
    gallery=t>=max(late_start+.8,min(c['final_start'],late_start+2))
    if active:
        current=active[-1];idx=c['materials'].index(current);q=ramp(t,current['start'],current['start']+.52)*(1-ramp(t,current['end'],current['end']+.28))
        out['background']=blurred(photo(current['path'],1080,1920),42)
        subject(raw,c,n,[355,995,785,1908],out)
        if idx==0:
            # Native edge-on perspective expansion, not a uniform dissolve.
            l=540-497*q;r=540+497*q;poly=np.float32([[l,1250],[r,1250+70*(1-q)],[r,1691-70*(1-q)],[l,1691]])
            tile=photo(current['path'],994,441);mat=cv2.getPerspectiveTransform(np.float32([[0,0],[994,0],[994,441],[0,441]]),poly)
            out['materials']=opacity(Image.fromarray(cv2.warpPerspective(np.asarray(tile),mat,SIZE,flags=cv2.INTER_CUBIC)),q)
        else:
            previous=c['materials'][idx-1]
            # Previous asset is a labeled historical role during this handoff only.
            out['materials']=card(photo(previous['path'],410,414),[627,1264,1037,1678],q)
            out['materials'].alpha_composite(card(photo(current['path'],440,441),[106-180*(1-q),1250,546-180*(1-q),1691],q))
    elif texts and not gallery:
        subject(raw,c,n,[355,995,785,1908],out)
        text=texts[-1];early=t<late_start
        box=[43,1250,1037,1691] if early else [43,96,1037,716]
        tex=textcard(text['text'],c['font'],box[2]-box[0],box[3]-box[1]);out['material_text']=card(tex,box,ramp(t,text['start'],text['start']+.32))
    elif gallery and (c['materials'] or c['conclusion']):
        # Native hard handoff to room-background arch, not a fake alpha morph.
        box=[680,1182,1027,1643];mask=Image.new('L',(347,461));d=ImageDraw.Draw(mask);d.rounded_rectangle((0,0,347,461),radius=173,fill=255);d.rectangle((0,173,347,461),fill=255)
        tex=room(raw,box);tex=tex.resize((347,461));tex.putalpha(mask);out['native_video'].alpha_composite(tex,(680,1182))
        history=[m for m in c['materials'] if m['start']<=t][-2:]
        if history:
            for i,m in enumerate(history):
                box=[73,461+i*580,624,1013+i*580];out['materials'].alpha_composite(card(photo(m['path'],551,552),box))
        else:
            strings=[v['text'] for v in c['conclusion'].values() if isinstance(v,dict) and v.get('text') and t>=v.get('start',0)]
            if strings:out['material_text']=card(textcard(' '.join(strings),c['font'],551,552),[73,753,624,1305])
    else:out['native_video']=raw.convert('RGBA')
    opening(c,t,out);caption(c,n,out)
    composite=Image.new('RGBA',SIZE,(0,0,0,255))
    for layer in out.values():composite.alpha_composite(layer)
    if t>duration-.52:composite=Image.blend(Image.new('RGBA',SIZE,(0,0,0,255)),composite,1-ramp(t,duration-.52,duration-.04))
    return (composite.convert('RGB'),out) if roles else composite.convert('RGB')

@lru_cache(maxsize=10)
def alpha_image(path):return Image.open(path).convert('L')
