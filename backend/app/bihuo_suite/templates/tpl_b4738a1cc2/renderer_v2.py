from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import json,math,subprocess
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor import visual as V,media as M
from .vendor.pilot import font,text_image
SIZE=(1080,1920)
ROLES=('background','history_material','current_material','material_text','presenter_glow','presenter_room','head_foreground','paper','theme','identity','accent','caption_shadow','caption_body','caption_emphasis')


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
    return text_image(ch,path,size,(255,226,64,255) if mark else (255,255,255,255),2,(26,26,24,255))

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

@lru_cache(maxsize=16)
def paper_title(text,path):
 size=110;im,b,pad=text_image(text,path,size,(255,255,255,255),3,(30,24,16,240));w=max(486,round(font(path,size).getlength(text))+46);h=180;rng=np.random.default_rng(1102);a=np.zeros((h,w,4),np.uint8);noise=rng.normal(0,4,(h,w));a[:,:,:3]=np.clip(np.array([157,123,79])[None,None,:]+noise[:,:,None],0,255);a[:,:,3]=255;paper=Image.fromarray(a);m=Image.new('L',(w,h));points=[(int(rng.integers(0,15)),0),(w-8,0)]+[(w-int(rng.integers(0,14)),y) for y in range(0,h,18)]+[(w,h),(8,h)]+[(int(rng.integers(0,15)),y) for y in range(h,0,-18)];ImageDraw.Draw(m).polygon(points,fill=255);paper.putalpha(m);letters=Image.new('RGBA',(w,h));letters.alpha_composite(im,((w-im.width)//2,(h-im.height)//2));return paper.rotate(3,resample=Image.Resampling.BICUBIC,expand=True),letters.rotate(3,resample=Image.Resampling.BICUBIC,expand=True)

def circle_head(raw,c,n,out):
    box=[389,1012,693,1316];out['presenter_room']=window(room(raw,box),box,152)
    halo=blank();ImageDraw.Draw(halo).ellipse(tuple(box),outline='white',width=5);out['presenter_glow']=halo.filter(ImageFilter.GaussianBlur(10))
    ref=c['foreground_alpha'].get(str(n))
    if not ref:raise ValueError(f'Missing source-bound alpha {n}')
    alpha=alpha_image(ref['path']);first=alpha_image(next(iter(c['foreground_alpha'].values()))['path']).getbbox()
    if not first:return
    scale=304/(first[2]-first[0]);x=541-(first[0]+first[2])/2*scale;y=980-first[1]*scale
    im=raw.copy();im.putalpha(alpha);im=im.resize((round(1080*scale),round(1920*scale)),Image.Resampling.LANCZOS);out['head_foreground'].alpha_composite(im,(round(x),round(y)))
    a=out['head_foreground'].getchannel('A');a.paste(0,(0,1316,1080,1920));allowed=out['presenter_room'].getchannel('A').copy();allowed.paste(255,(0,0,1080,1012));a=Image.fromarray(np.minimum(np.asarray(a),np.asarray(allowed)));out['head_foreground'].putalpha(a)
def theme(c,t,out):
    q=ramp(t,0,.24)*(1-ramp(t,c['opening_end']-.16,c['opening_end']+.28));txt=c.get('title','')
    if txt and q>0:
        paper,letters=paper_title(txt,c['font']);scale=min(1,1000/max(paper.width,letters.width))
        if scale<.5:raise ValueError('Paper title exceeds supported length')
        for role,im in [('paper',paper),('theme',letters)]:
            im=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.LANCZOS);out[role].alpha_composite(opacity(im,q),(round((1080-im.width)/2),85))
    ident=c['creative_options'].get('identity') or c['creative_options'].get('name_card') or {}
    if ident.get('enabled',True) and q>0:
        yy=1018
        for key,size in [('name',56),('description',38)]:
            text=str(ident.get(key,'')).strip()
            if not text:continue
            tile,_,_=text_image(text,c['font'],size,(255,255,255,255),1,(0,0,0,180));out['identity'].alpha_composite(opacity(tile,q),(76,yy));yy+=78
def accent(c,t,out):
    rows=[x for x in c['text_items'] if x['start']<=t<x['end']+.24]
    if t>=c['final_start']:rows=[v for v in c['conclusion'].values() if isinstance(v,dict) and v.get('text') and v['start']<=t<v['end']+.2][-1:]
    if not rows:return
    row=rows[-1];text=row['text'];parts=lines_for(text,c['font'],110,960)
    if len(parts)>2:parts=lines_for(text,c['font'],82,960)
    q=ramp(t,row['start'],row['start']+.28)*(1-ramp(t,row['end'],row['end']+.24))
    if len(parts)>3:raise ValueError('Accent text exceeds native capacity')
    for i,part in enumerate(parts):
        tile,_,_=text_image(part,c['font'],110 if len(parts)<=2 else 82,(255,225,52,255) if i%2 else (255,255,255,255),2,(28,23,20,255));w=round(tile.width*q)
        if w:out['accent'].alpha_composite(opacity(tile.crop((0,0,w,tile.height)),q),(round((1080-tile.width)/2),245+i*140))
    ImageDraw.Draw(out['accent']).rectangle((58,245,68,245+round(100*q)),fill=(255,225,52,round(255*q)))
def render(raw,c,n,roles=False):
    t=n/25;out={k:blank() for k in ROLES};out['background']=blurred(raw,48)
    active=[m for m in c['materials'] if m['start']<=t<m['end']+.28]
    semantic_text=[x for x in c['text_items'] if x['start']<=t<x['end']+.24]
    primary_end=max([m['end'] for m in c['materials']] or [c['opening_end']])
    if active:
        m=active[-1];idx=c['materials'].index(m);q=ramp(t,m['start'],m['start']+.36)*(1-ramp(t,m['end'],m['end']+.28));out['background']=blurred(photo(m['path'],1080,1920),40);circle_head(raw,c,n,out)
        if idx==0:
            box=np.array([18,302,1012,922]);mid=(box[:2]+box[2:])/2;extent=(box[2:]-box[:2])*(.4+.6*q)/2;box=np.r_[mid-extent,mid+extent]
            out['current_material']=opacity(window(photo(m['path'],994,620),box,22),q)
        else:
            old=c['materials'][idx-1];oldbox=lerp([18,302,1012,922],[602,338,1012,886],ramp(t,m['start'],m['start']+.4));out['history_material']=window(photo(old['path'],410,548),oldbox,22)
            out['current_material']=opacity(window(photo(m['path'],466,620),[68,302,534,922],22),q)
    elif semantic_text and t<primary_end:
        circle_head(raw,c,n,out);x=semantic_text[-1];out['material_text']=opacity(window(textcard(x['text'],c['font'],994,620),[18,302,1012,922],22),ramp(t,x['start'],x['start']+.3))
    elif t<=c['opening_end'] and c.get('title'):
        if c.get('foreground_alpha'):circle_head(raw,c,n,out)
        else:out['presenter_room']=raw.convert('RGBA')
    else:
        # Actual native circle->lower rounded rectangle after material exits.
        start=primary_end+.28;qq=ramp(t,start,start+.72);box=lerp([389,1012,693,1316],[96,480,984,1364],qq)
        out['presenter_room']=window(room(raw,box),box,152*(1-qq)+18*qq);accent(c,t,out)
    theme(c,t,out);caption(c,n,out)
    composite=Image.new('RGBA',SIZE,(0,0,0,255))
    for layer in out.values():composite.alpha_composite(layer)
    if t>c['duration']-.5:composite=Image.blend(Image.new('RGBA',SIZE,(0,0,0,255)),composite,1-ramp(t,c['duration']-.5,c['duration']-.04))
    return (composite.convert('RGB'),out) if roles else composite.convert('RGB')
