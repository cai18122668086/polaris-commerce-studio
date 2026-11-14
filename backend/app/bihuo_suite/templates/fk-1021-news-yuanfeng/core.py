"""Portable Copper full-suite runtime. Host supplies resolved transcript/media/fonts.

No fixed person, fixed transcript, model/provider or original finished pixels.
"""
from pathlib import Path
import copy,hashlib,importlib,importlib.util,json,math,subprocess,sys
from functools import lru_cache
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageOps
HERE=Path(__file__).resolve().parent
PACKAGE='_bihuo_yuanfeng_pinned_v1'
if PACKAGE not in sys.modules:
 spec=importlib.util.spec_from_file_location(PACKAGE,HERE/'vendor/__init__.py',submodule_search_locations=[str(HERE/'vendor')]);module=importlib.util.module_from_spec(spec);sys.modules[PACKAGE]=module;spec.loader.exec_module(module)
pilot=importlib.import_module(PACKAGE+'.pilot');visual=importlib.import_module(PACKAGE+'.visual');media=importlib.import_module(PACKAGE+'.media')
def _sha(p):
 with Path(p).open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()

def _dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n','utf8')

def _blank():return Image.new('RGBA',(1080,1920))

def _text(t):return str(t or '').strip()

def _style_fonts(fonts):
 title=fonts.get('title')or fonts.get('main')or fonts.get('caption_bold');body=fonts.get('caption')or fonts.get('caption_bold')or fonts.get('body')or title
 if not title or not body or not Path(title).is_file()or not Path(body).is_file():raise ValueError('Existing host title/main and caption/body fonts required')
 return dict(title=str(title),caption=str(body))

def render_mp4(cfg,output_dir):
 out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);final=out/'final.mp4';digest=hashlib.sha256(json.dumps(cfg,ensure_ascii=False,sort_keys=True).encode()).hexdigest();receipt=out/'render-receipt.json'
 if final.exists():
  prior=json.loads(receipt.read_text('utf8'))if receipt.exists()else{}
  if prior.get('config_sha256')==digest and prior.get('final_sha256')==_sha(final):return final
  raise ValueError('Output exists for a different request; use a new directory')
 _dump(out/'input.json',cfg);ff=cfg.get('ffmpeg','ffmpeg');cmd=[ff,'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','25','-i','pipe:0','-i',cfg['source_path'],'-map','0:v:0','-map','1:a:0?','-t',str(cfg['frames']/25),'-c:v','libx264','-preset','veryfast','-threads','2','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',str(final)]
 with(out/'encode.log').open('wb')as log:
  process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
  try:
   for n in range(cfg['frames']):
    roles,meta=render_layers(cfg,n);rgb=composite(roles);process.stdin.write(rgb.tobytes())
  finally:process.stdin.close();code=process.wait();media.clear_cache()
  if code:raise RuntimeError('Neon encoder failed; see encode.log')
 _dump(receipt,dict(template_id=cfg['template_id'],config_sha256=digest,final_sha256=_sha(final),frames=cfg['frames'],fps=25,duration=cfg['frames']/25,host_decode_required=True,unretimed_source_audio=True,source_sha256=cfg['source_sha256'],complete_caption_rows=len(cfg['captions']),material_slots=len(cfg.get('materials',[])),encoder_command=cmd,source_raw_not_required=True));return final
