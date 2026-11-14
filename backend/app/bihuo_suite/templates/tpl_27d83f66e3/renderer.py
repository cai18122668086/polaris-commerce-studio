from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import json,math,subprocess
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor import visual as V,media as M
from .vendor.pilot import font,text_image
SIZE=(1080,1920)
ROLES=('background','material_blur','history','current_material','room_glow','presenter_room','head_foreground','information_card','information_rows','title_bar','title','support','identity','semantic','caption_shadow','caption_body','caption_emphasis')


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
        mark=any(a<=i<b for a,b in spans); size=62; chars.append((ch,mark,size,float(font(c['font'],size).getlength(ch))))
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

@lru_cache(maxsize=1)
def gradient():
    y=np.linspace(0,1,1920)[:,None,None];a=np.uint8(np.round(np.array([45,43,119])[None,None,:]*(1-y)+np.array([18,18,58])[None,None,:]*y));return Image.fromarray(np.repeat(a,1080,axis=1)).convert('RGBA')
def person(raw,box,radius,out):
    out['presenter_room']=window(room(raw,box),box,radius)
    halo=blank();ImageDraw.Draw(halo).rounded_rectangle(tuple(box),radius=radius,fill='white');out['room_glow']=opacity(halo.filter(ImageFilter.GaussianBlur(24)),.7)
def head(raw,c,n,out):
    ref=c['foreground_alpha'].get(str(n))
    if not ref:raise ValueError(f'Missing actual foreground {n}')
    alpha=alpha_image(ref['path']);first=alpha_image(next(iter(c['foreground_alpha'].values()))['path']).getbbox()
    if not first:return
    scale=470/(first[2]-first[0]);dx=554-(first[0]+first[2])/2*scale;dy=548-first[1]*scale
    full=raw.resize((round(1080*scale),round(1920*scale)),Image.Resampling.LANCZOS);canvas=blank();canvas.alpha_composite(full,(round(dx),round(dy)))
    circle=Image.new('L',SIZE);ImageDraw.Draw(circle).ellipse((192,680,916,1400),fill=255)
    back=blurred(raw,35);back.alpha_composite(canvas);back.putalpha(circle);out['presenter_room']=back
    fg=raw.copy();fg.putalpha(alpha);fg=fg.resize(full.size,Image.Resampling.LANCZOS);out['head_foreground'].alpha_composite(fg,(round(dx),round(dy)));a=out['head_foreground'].getchannel('A');a.paste(0,(0,1400,1080,1920));out['head_foreground'].putalpha(a)
def opening(c,t,out):
    end=c['opening_end'];q=ramp(t,0,.3)*(1-ramp(t,end-.22,end+.16));text=c.get('title','')
    if text and q>0:
        size=108
        while font(c['font'],size).getlength(text)>900 and size>40:size-=1
        if font(c['font'],size).getlength(text)>900:raise ValueError('Opening title exceeds native width')
        w=font(c['font'],size).getlength(text);x=(1080-w-84)/2
        ImageDraw.Draw(out['title_bar']).polygon([(x+14,230),(x+w+84,230),(x+w+73,279),(x,279)],fill=(109,83,255,round(255*q)))
        tile,_,_=text_image(text,c['font'],size,(255,255,255,255),1,(20,15,60,255));out['title'].alpha_composite(opacity(tile,q),(round((1080-tile.width)/2),176))
    support=c.get('subtitle','')
    if support and q>0:
        size=76
        while font(c['font'],size).getlength(support)>940 and size>32:size-=1
        tile,_,_=text_image(support,c['font'],size,(255,220,75,255),1,(20,15,60,255));out['support'].alpha_composite(opacity(tile,q),(round((1080-tile.width)/2),342))
    info=c['creative_options'].get('identity') or c['creative_options'].get('name_card') or {}
    if info.get('enabled',True) and q>0:
        y=1160
        for key,size in [('name',62),('description',34)]:
            text=str(info.get(key,'')).strip()
            if text:
                tile,_,_=text_image(text,c['font'],size,(255,255,255,255),1,(0,0,0,200));out['identity'].alpha_composite(opacity(tile,q),(120,y));y+=80
    # A supplied emphasized phrase is an independent whole-word motion, not an identity.
    row=next((x for x in c['captions'] if x['time'][0]<=t<x['time'][1] and t<end),None)
    if row and row.get('lines'):
        spans=row['lines'][0].get('emphasis_spans',[])
        if spans:
            a,b=spans[0];txt=row['lines'][0]['text'][a:b];q=ramp(t,row['time'][0],row['time'][0]+.3);tile,_,_=text_image(txt,c['font'],112,(255,255,255,255),1,(20,15,60,255));out['semantic'].alpha_composite(opacity(tile,q),(66,round(490+20*(1-q))))
            if t>row['time'][0]+.36:ImageDraw.Draw(out['semantic']).line([(90+tile.width,514),(126+tile.width,548),(90+tile.width,582)],fill='white',width=14)
def progressive_caption(c,n,out):
    t=n/25;row=next((x for x in c['captions'] if x['time'][0]<=t<x['time'][1]),None)
    if not row:return
    ids={x['id']:i for i,x in enumerate(c.get('tokens',[]))}
    first=row.get('first_token_id');last=row.get('last_token_id')
    if first in ids and last in ids:
        tok=c['tokens'][ids[first]:ids[last]+1];visible=[x for x in tok if x['start_ms']<=t*1000]
        count=sum(len(x['text']) for x in visible);text=row['text'] if len(visible)==len(tok) else row['text'][:count]
        if not text:return
        row={**row,'text':text,'lines':[{'text':text,'emphasis_spans':[]}]};cc={**c,'captions':[row]};caption(cc,n,out)
    else:caption(c,n,out)
def render(raw,c,n,roles=False):
    t=n/25;out={k:blank() for k in ROLES};out['background']=gradient().copy()
    mats=c['materials'];active=[m for m in mats if m['start']<=t<m['end']+.28]
    rows=[r for r in c['text_items'] if r['slot_id'].startswith(('features-','points-'))]
    gallery_end=max([m['end']+.28 for m in mats] or [c['opening_end']])
    list_start=max(min([r['start'] for r in rows] or [c['final_start']]),gallery_end);list_end=max([r['end']+.2 for r in rows] or [list_start])
    if active:
        current=active[-1];idx=mats.index(current);history=mats[max(0,idx-3):idx];q=ramp(t,current['start'],current['start']+.6)
        out['material_blur']=blurred(photo(current['path'],1080,1920),40)
        if history:
            box=[44,118,610,1060]
            for i,m in enumerate(history):
                b=[[626,96,1038,404],[672,430,992,750],[626,768,1038,1090]][i];out['history'].alpha_composite(window(photo(m['path'],b[2]-b[0],b[3]-b[1]),b,20))
        else:box=[44,90,1036,1088]
        # An incoming left perspective plane rotates open; image text remains contained.
        x,y,x2,y2=box;w=x2-x;h=y2-y;tile=photo(current['path'],w,h);slant=150*(1-q);poly=np.float32([[x,y+slant],[x+w*max(.001,q),y],[x+w*max(.001,q),y2],[x,y2-slant]])
        mat=cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]),poly);out['current_material']=Image.fromarray(cv2.warpPerspective(np.asarray(tile),mat,SIZE,flags=cv2.INTER_CUBIC))
        person(raw,[292,1136,788,1510],44,out)
    elif rows and list_start<=t<list_end:
        out['material_blur']=opacity(blurred(raw,32),ramp(t,list_start,list_start+.36));person(raw,[230,1122,850,1590],44,out)
        eligible=[(i,r) for i,r in enumerate(rows) if t>=max(r['start'],list_start)]
        page=(eligible[-1][0]//3) if eligible else 0;shown=rows[page*3:(page+1)*3];h=len(shown)*72+156
        q=ramp(t,list_start,list_start+.36)*(1-ramp(t,list_end-.28,list_end));ImageDraw.Draw(out['information_card']).rounded_rectangle((72,444,1008,444+h),radius=44,fill=(244,242,252,round(255*q)))
        for i,r in enumerate(shown):
            start=max(r['start'],list_start);rq=ramp(t,start,start+.28)*q;size=60
            while font(c['font'],size).getlength(r['text'])>830 and size>30:size-=1
            if font(c['font'],size).getlength(r['text'])>830:raise ValueError('Information row exceeds native width')
            tile,_,_=text_image(r['text'],c['font'],size,(86,79,174,255),0,(0,0,0,0));out['information_rows'].alpha_composite(opacity(tile,rq),(134,518+i*72))
    elif t<c['opening_end']:
        person(raw,[108,550,972,1414],432,out)
    elif c.get('foreground_alpha'):head(raw,c,n,out)
    else:person(raw,[108,550,972,1414],432,out)
    opening(c,t,out);progressive_caption(c,n,out)
    composite=Image.new('RGBA',SIZE,(0,0,0,255))
    for layer in out.values():composite.alpha_composite(layer)
    if t>c['duration']-.52:composite=Image.blend(Image.new('RGBA',SIZE,(0,0,0,255)),composite,1-ramp(t,c['duration']-.52,c['duration']-.04))
    return (composite.convert('RGB'),out) if roles else composite.convert('RGB')
