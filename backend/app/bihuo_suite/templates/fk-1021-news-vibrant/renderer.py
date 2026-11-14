from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import json,math,subprocess
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor import visual as V,media as M
from .vendor.pilot import font,text_image
from . import vibrant_helpers as H
SIZE=(1080,1920)
ROLES=('background','backplate','window_glow','bottom_window','window_edge','head_foreground','material','title','support','identity','caption_shadow','caption_body','caption_emphasis')
GEOM=json.loads((Path(__file__).parent/'return-geometry.json').read_text('utf8'))


def blank(): return Image.new('RGBA',SIZE)

def ramp(t,a,b): return max(0.,min(1.,(t-a)/(b-a))) if b>a else float(t>=b)

def opacity(im,q):
    if q>=1: return im
    im=im.copy(); im.putalpha(im.getchannel('A').point(lambda a:round(a*max(0,q)))); return im

def blurred(im,r=20): return im.resize((270,480)).filter(ImageFilter.GaussianBlur(r/4)).resize(SIZE,Image.Resampling.BILINEAR).convert('RGBA')

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

@lru_cache(maxsize=10)
def alpha_image(path):return Image.open(path).convert('L')

def slot_frames(c):return [{**m,'frames':[math.ceil(m['start']*25-1e-8),math.ceil(m['end']*25-1e-8)]} for m in c['materials']]
def phase_at(c,n):
    slots=slot_frames(c)
    if not slots:return 270
    for a in slots:
        first,last=a['frames']
        if first<=n<last:return 294+min(16,n-first)
    for i,a in enumerate(slots):
        first,last=a['frames'];prep=first-13
        if prep<=n<first:
            if i and slots[i-1]['frames'][1]+22>prep:return 292
            return 281+n-prep
    for i,a in enumerate(slots):
        first,last=a['frames'];following=slots[i+1] if i+1<len(slots) else None
        if last<=n<last+22:
            if following and following['frames'][0]-13<last+22 and n<following['frames'][0]:return 292
            return 474+n-last
        if following and last<=n<following['frames'][0]-13:return 496
    return 496 if n>=slots[-1]['frames'][1]+22 else 270
def pose(phase):
    if phase<474:return H.pose(phase)
    box=np.asarray(H.lerp(GEOM['box_knots'],min(496,phase)),float);radius=float(H.lerp([(r['frame'],[r['radius']]) for r in GEOM['records']],phase)[0]);return box,radius
def mapping(box,phase):
    if phase<474:
        q=max(0,min(1,(934-(box[2]-box[0]))/(934-305)));s=(934/1080)*(1-q)+.47*q;top=(497+20*(934/1080))*(1-q)+210*q
        return [s,s,(box[0]+box[2])/2-s*540,top-s*470]
    if phase>=496:return [1,1,0,0]
    s=float(H.lerp([(474,[.47]),(475,[.59]),(476,[.76]),(477,[.98]),(478,[1.15]),(482,[1.6]),(486,[1.35]),(490,[1.12]),(496,[1])],phase)[0]);top=float(H.lerp([(474,[210]),(475,[225]),(476,[210]),(477,[180]),(478,[150]),(482,[100]),(486,[250]),(490,[390]),(496,[470])],phase)[0]);return [s,s,540-s*540,top-s*470]
def titles(c,n,out):
    title_size=100
    while c.get('title') and H.word_tile(c['title'],c['font'],title_size,(255,255,255,255)).width+9>512 and title_size>32:title_size-=1
    support_size=52
    while c.get('subtitle') and H.word_tile(c['subtitle'],c['font'],support_size,(255,255,255,255),shear=-.08).width+6>1008 and support_size>24:support_size-=1
    if c.get('title') and H.word_tile(c['title'],c['font'],title_size,(255,255,255,255)).width+9>512:raise ValueError('Title exceeds complete prefix reveal width')
    if c.get('subtitle') and H.word_tile(c['subtitle'],c['font'],support_size,(255,255,255,255),shear=-.08).width+6>1008:raise ValueError('Support exceeds native canvas width')
    profile={'mode':'clean','fonts':{'title':c['font']},'title':c.get('title',''),'support':c.get('subtitle',''),'title_size':title_size,'support_size':support_size}
    local_phase=n/25/max(.2,c['opening_end'])*77*.8
    out.update(H.title_layers(profile,local_phase))
def captions(c,n,out):
    row=next((r for r in c['captions'] if r['time'][0]<=n/25<r['time'][1]),None)
    if not row:return
    text=row['text'];spans=[];cursor=0
    for line in row.get('lines',[]):
        pos=text.find(line.get('text',''),cursor)
        if pos>=0:spans.extend((pos+a,pos+b) for a,b in line.get('emphasis_spans',[]));cursor=pos+len(line.get('text',''))
    chunks=lines_for(text,c['font'],76,960)
    if len(chunks)>3:raise ValueError('Caption requires more than native three lines')
    offset=0;last=row is c['captions'][-1];phase=n-math.ceil(row['time'][0]*25)
    dx=float(H.lerp([(0,[16]),(1,[10]),(3,[-5]),(6,[2]),(10,[0]),(12,[5]),(15,[0])],phase)[0]) if last else 0
    dy=float(H.lerp([(0,[80]),(1,[40]),(3,[48]),(4,[44]),(7,[22]),(10,[0]),(12,[6]),(14,[4]),(17,[0])],phase)[0]) if last else 0
    for j,chunk in enumerate(chunks):
        ranges=[[max(0,a-offset),min(len(chunk),b-offset)] for a,b in spans if a<offset+len(chunk) and b>offset];parts=V.caption_parts({'text':chunk,'emphasis_spans':ranges});tiles=[(H.word_tile(txt,c['font'],76 if mark else 68,(250,245,0,255) if mark else (255,255,255,255),2,.17),mark) for txt,mark in parts]
        width=sum(tile.width for tile,mark in tiles)
        if width>1040:raise ValueError('Actual caption glyph width exceeds safe native reading width')
        x=(1080-width)/2+dx
        for tile,mark in tiles:
            y=(1552 if mark else 1557)-(len(chunks)-1)*100+j*100+dy;role='caption_emphasis' if mark else 'caption_body';out[role].alpha_composite(tile,(round(x),round(y)));shadow=Image.new('RGBA',tile.size,(0,0,0,255));shadow.putalpha(tile.getchannel('A').point(lambda v:round(v*.75)));out['caption_shadow'].alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)),(round(x+3),round(y+5)));x+=tile.width
        offset+=len(chunk)
    q=min(1,(n/25-row['time'][0]+.04)/.32)
    for role in ['caption_shadow','caption_body','caption_emphasis']:out[role]=opacity(out[role],q)
def identity(c,n,out):
    ident=c['creative_options'].get('identity') or c['creative_options'].get('name_card') or {};name=str(ident.get('name','')).strip();desc=str(ident.get('description','')).strip()
    if not ident.get('enabled',True) or not(name or desc) or not .28<=n/25<min(2.6,c['opening_end']):return
    rows=[]
    for text,size,color in [(name,54,(255,255,255,255)),(desc,34,(225,245,60,255))]:
        if not text:continue
        for row in lines_for(text,c['font'],size,360):rows.append(H.word_tile(row,c['font'],size,color))
    if len(rows)>4:raise ValueError('Identity exceeds supported reading rows')
    w=max(t.width for t in rows)+30;h=sum(t.height for t in rows)+16+10*(len(rows)-1);x=1000-w;y=1200;ImageDraw.Draw(out['identity']).rounded_rectangle((x,y,x+w,y+h),radius=10,fill=(0,0,0,240))
    for tile in rows:out['identity'].alpha_composite(tile,(x+15,y+8));y+=tile.height+10
def render(raw,c,n,roles=False):
    phase=phase_at(c,n);box,radius=pose(phase);matrix=mapping(box,phase);active=285<=phase<484;alpha=None
    if active:
        ref=c.get('foreground_alpha',{}).get(str(n))
        if not ref:raise ValueError(f'Missing actual source head alpha {n}')
        alpha=alpha_image(ref['path'])
    out={k:blank() for k in ROLES};out['background']=H.background(n,.6)
    windows,stats=H.window_layers(raw,box,radius,matrix,phase,alpha,active,glow=phase<284)
    if active:
        a=np.asarray(windows['head_foreground'].getchannel('A')).copy();a[:,:max(0,math.floor(box[0]))]=0;a[:,min(1080,math.ceil(box[2])):]=0;windows['head_foreground'].putalpha(Image.fromarray(a))
    out.update(windows)
    slot=next((m for m in slot_frames(c) if m['frames'][0]<=n<m['frames'][1]),None)
    if slot:
        a,b=slot['frames'];q=float(H.lerp([(0,[.067]),(2,[.408]),(4,[.633]),(6,[.806]),(8,[.892]),(11,[.953]),(16,[1])],n-a)[0])*min(1,max(0,(b-n)/12));tile=photo(slot['path'],995,1060);blur=max(0,(1-q)*8)
        if blur>.05:tile=tile.filter(ImageFilter.GaussianBlur(blur))
        out['material']=opacity(H.v02(tile.resize(SIZE),[995/1080,1060/1920,43,423],[43,423,1038,1483],32),q)
    titles(c,n,out);identity(c,n,out);captions(c,n,out)
    composite=Image.new('RGBA',SIZE,(0,0,0,255))
    for layer in out.values():composite.alpha_composite(layer)
    if n/25>c['duration']-.52:composite=Image.blend(Image.new('RGBA',SIZE,(0,0,0,255)),composite,1-ramp(n/25,c['duration']-.52,c['duration']-.04))
    return (composite.convert('RGB'),out) if roles else composite.convert('RGB')
