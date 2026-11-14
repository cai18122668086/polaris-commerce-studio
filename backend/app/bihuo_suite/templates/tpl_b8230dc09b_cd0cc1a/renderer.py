from pathlib import Path
from functools import lru_cache
import json,subprocess,math
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageOps
from .vendor import visual as V
from .vendor.pilot import font,text_image,place_center
from .library.subtitles.cue_split_v1 import CueSplitV1,_glyph,_fade
from .library.subtitles.glyph_stagger_v1 import GlyphStaggerV1
from .library.subtitles.split_title import with_shadow
SIZE=(1080,1920)
ROLES=("background","presenter","header","identity","caption")

@lru_cache(maxsize=1)
def grid():
    data=json.loads((Path(__file__).parent/'grid.json').read_text('utf8'));im=Image.new('RGBA',SIZE,'black');d=ImageDraw.Draw(im)
    for line in data['lines']:d.line(line['xyxy'],fill=tuple(line['rgb'])+(255,),width=line['width'])
    return im
@lru_cache(maxsize=128)
def cue_object(serialized):return CueSplitV1(json.loads(serialized))
@lru_cache(maxsize=8)
def header_object(serialized):return GlyphStaggerV1(json.loads(serialized))
def render(raw,c,n,roles=False):
    windowed=n>=c['cut_frame'];box=c['window_xywh'] if windowed else [0,0,1080,1920];x,y,w,h=box
    texture=ImageOps.fit(raw,(1080,1080),Image.Resampling.LANCZOS).resize(SIZE,Image.Resampling.LANCZOS) if windowed else ImageOps.fit(raw,SIZE,Image.Resampling.LANCZOS)
    key={'time':0,'matrix':[[w/1080,0,x/2],[0,h/1920,y/2]],'rect':[x/2,y/2,(x+w)/2,(y+h)/2],'radius':10 if windowed else 0,'background_opacity':0}
    presenter=V.render('V02',texture,0,{'size':list(SIZE),'fps':25,'stage_color':[0,0,0],'visual_keys':[key]})['presenter']
    out={'background':grid().copy() if windowed else Image.new('RGBA',SIZE,'black'),'presenter':presenter,'header':blank(),'identity':blank(),'caption':blank()}
    for row in c['cues']:
        spec=row['component'];e=spec['events']
        if e['first']<=n<e['gone']:
            result=cue_object(json.dumps(spec,ensure_ascii=False,sort_keys=True)).render(n)
            for role in result['ordered_roles']:out['caption'].alpha_composite(role['image'])
    a,b=c['opening_exit'];q=1-ramp(n,a-1,b) if n>=a else 1
    if c['opening_title'] and q>0:
        size=128
        while font(c['font']['path'],size).getlength(c['opening_title'])>980 and size>40:size-=1
        if font(c['font']['path'],size).getlength(c['opening_title'])>980:raise ValueError('Opening title exceeds native width')
        tile,_,pad=text_image(c['opening_title'],c['font']['path'],size,(255,254,237,255),8,(64,56,12,255));tile=with_shadow(tile,{'shadowX':2,'shadowY':2,'shadowBlur':1});place_center(out['header'],tile,540,121-pad,q)
    if c['header']:
        hcfg=c['header']
        if min(hcfg['glyph_start'],default=c['frames'])-1<=n<hcfg['whole_exit'][1]:
            result=header_object(json.dumps(hcfg,ensure_ascii=False,sort_keys=True)).render(n)
            for role in result['ordered_glyph_roles']:out['header'].alpha_composite(role['image'])
    ident=c['identity']
    if ident['enabled'] and (ident['name'] or ident['description']) and q>0:
        yy=1120
        for text,size,style in [(ident['name'],40,'white'),(ident['description'],28,'gold')]:
            if not text:continue
            # Retain actual single-field roles; neither field infers the other.
            chunks=[];current=''
            for ch in text:
                if current and font(c['font']['path'],size).getlength(current+ch)>420:chunks.append(current);current=''
                current+=ch
            if current:chunks.append(current)
            if len(chunks)>2:raise ValueError('Identity requires shorter text, max2 natural lines per field')
            for line in chunks:
                tile=text_image(line,c['font']['path'],size,(244,196,24,255) if style=='gold' else (255,254,237,255))[0];tile=with_shadow(tile,{'shadowX':2,'shadowY':2,'shadowBlur':1});out['identity'].alpha_composite(opacity(tile,q),(64,yy));yy+=60
    start,end=c['outro']
    fade=1-ramp(n/25,start,end) if start<end else 1
    final=Image.new('RGBA',SIZE,(0,0,0,255))
    for layer in out.values():final.alpha_composite(layer)
    if fade<1:final=Image.blend(Image.new('RGBA',SIZE,(0,0,0,255)),final,fade)
    return (final.convert('RGB'),out) if roles else final.convert('RGB')


def blank(): return Image.new('RGBA',SIZE)

def ramp(t,a,b): return max(0.,min(1.,(t-a)/(b-a))) if b>a else float(t>=b)

def opacity(im,q):
    if q>=1: return im
    im=im.copy(); im.putalpha(im.getchannel('A').point(lambda a:round(a*max(0,q)))); return im

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
