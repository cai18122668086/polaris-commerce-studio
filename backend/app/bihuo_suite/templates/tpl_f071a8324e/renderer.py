"""Native room-window, material handoff, slanted evidence and return renderer."""
from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import json, math, subprocess
import cv2, numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor import visual as V,media as M
from .vendor.pilot import font,text_image
SIZE=(1080,1920)
ROLES=('background','materials','material_text','presenter_border','presenter_room','caption_shadow','caption_body','caption_emphasis')
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
def warp_room(raw,quad):
    texture=room(raw,[0,0,504,960]); texture=texture.resize((504,960))
    mat=cv2.getPerspectiveTransform(np.float32([[0,0],[504,0],[504,960],[0,960]]),np.float32(quad))
    return Image.fromarray(cv2.warpPerspective(np.asarray(texture),mat,SIZE,flags=cv2.INTER_LINEAR))
@lru_cache(maxsize=600)
def glyph(ch,path,size,mark):
    return text_image(ch,path,size,(255,219,62,255) if mark else (255,255,255,255),2,(26,26,24,255))
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
        mark=any(a<=i<b for a,b in spans); size=90 if mark else 76; chars.append((ch,mark,size,float(font(c['font'],size).getlength(ch))))
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
def render(raw,c,n,roles=False):
    t=n/25; out={k:blank() for k in ROLES}; out['background']=blurred(raw,44)
    mats=c['materials']; texts=c['text_items']; final=c['final_start']; duration=c['duration']
    # Each asset is selected by its own semantic interval, never by upload count.
    active=[m for m in mats if m['start']<=t<m['end']+.16]
    early_text=[x for x in texts if x['start']<=t<x['end']+.16 and x['start']<duration*.58]
    late=[x for x in texts if duration*.5<=x['start']<final and x['start']<=t<min(final,x['end']+2.4)]
    late_mode=bool(late) and not active
    pose=[0,0,1080,1920];radius=0
    if active or early_text:
        obj=(active or early_text)[-1]; index=next((i for i,m in enumerate(mats) if m is obj),1)
        pose=[64,190,390,516] if index==0 else [284,118,788,500]; radius=163 if index==0 else 20
        a=obj['start'];b=obj['end'];q=ramp(t,a,a+.32)*(1-ramp(t,b,b+.16))
        pose=lerp([0,0,1080,1920],pose,ramp(t,a,a+.32)); radius*=ramp(t,a,a+.32)
        base=[28,570,1052,1480] if index==0 else [54,546,1018,1460]
        scale=.4+.6*ramp(t,a,a+.32);mid=(np.array(base[:2])+base[2:])/2;half=(np.array(base[2:])-base[:2])*scale/2;box=np.r_[mid-half,mid+half]
        tex=photo(obj['path'],round(base[2]-base[0]),round(base[3]-base[1])) if active else textcard(obj['text'],c['font'],base[2]-base[0],base[3]-base[1])
        out['materials' if active else 'material_text']=opacity(window(tex,box,20),q)
    elif late_mode:
        q=ramp(t,min(x['start'] for x in late)-.12,min(x['start'] for x in late)+.3)
        quad=lerp([[284,118],[788,118],[788,500],[284,500]],[[144,250],[548,250],[448,1210],[44,1210]],q)
        back=blank();ImageDraw.Draw(back).polygon([tuple(p+20) for p in quad],fill=(255,210,28,255));out['presenter_border']=back
        out['presenter_room']=warp_room(raw,quad)
        shown=late[-2:]
        for i,x in enumerate(shown):
            box=[600,408 if len(shown)>1 and i==0 else 740 if len(shown)>1 else 574,1014,720 if len(shown)>1 and i==0 else 1052 if len(shown)>1 else 886]
            q=ramp(t,x['start'],x['start']+.32); box[2]=box[0]+(box[2]-box[0])*max(.001,q)
            tile=textcard(x['text'],c['font'],414,312);out['material_text'].alpha_composite(opacity(window(tile,box,20),q))
    elif t>=final and (texts or mats):
        pose=[96,480,984,1364];radius=18
    if not late_mode:
        if np.max(np.abs(np.array(pose)-[0,0,1080,1920]))<.1:out['background']=raw.convert('RGBA')
        else:
            out['presenter_room']=window(room(raw,pose),pose,radius)
            border=blank();ImageDraw.Draw(border).rounded_rectangle(tuple(pose),radius=radius,outline=(235,190,70,255),width=3);out['presenter_border']=border
    caption(c,n,out)
    mask=c.get('mask')
    if mask and mask[0]<=t<=mask[1]:
        q=abs((t-mask[0])/(mask[1]-mask[0])*2-1)
        # Shared sharp foreground compression includes ordinary captions.
        for k in ROLES[1:]:
            im=out[k];w=max(1,round(1080*q));compressed=im.resize((w,1920));layer=blank();layer.alpha_composite(compressed,((1080-w)//2,0));out[k]=layer
    if t>duration-.52:
        q=1-ramp(t,duration-.52,duration-.04)
        for k in out:out[k]=opacity(out[k],q)
    composite=Image.new('RGBA',SIZE,(0,0,0,255))
    for im in out.values():composite.alpha_composite(im)
    return (composite.convert('RGB'),out) if roles else composite.convert('RGB')
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
