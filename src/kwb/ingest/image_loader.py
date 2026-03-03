"""Image ingestion — load images, extract metadata, prepare for AI vision."""
from __future__ import annotations
import base64, hashlib, mimetypes, struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class ImageProfile:
    path: str; filename: str; file_size_bytes: int; mime_type: str
    width: int | None = None; height: int | None = None
    exif: dict = field(default_factory=dict)
    hash_sha256: str = ""; base64_data: str = ""
    errors: list = field(default_factory=list)

def _detect_mime(path):
    mime, _ = mimetypes.guess_type(str(path))
    if mime: return mime
    with open(path,"rb") as f: h=f.read(16)
    if h[:3]==b"\xff\xd8\xff": return "image/jpeg"
    if h[:8]==b"\x89PNG\r\n\x1a\n": return "image/png"
    if h[:4] in (b"II\x2a\x00",b"MM\x00\x2a"): return "image/tiff"
    return "application/octet-stream"

def _jpeg_dims(path):
    try:
        with open(path,"rb") as f: data=f.read()
        i=2
        while i<len(data)-1:
            if data[i]!=0xFF: break
            mk=data[i+1]
            if mk==0xD9: break
            if mk in (0xC0,0xC1,0xC2):
                return struct.unpack(">H",data[i+7:i+9])[0],struct.unpack(">H",data[i+5:i+7])[0]
            if i+3<len(data): i+=2+struct.unpack(">H",data[i+2:i+4])[0]
            else: break
    except: pass
    return None,None

def _png_dims(path):
    try:
        with open(path,"rb") as f:
            f.read(8);f.read(4);f.read(4)
            return struct.unpack(">I",f.read(4))[0],struct.unpack(">I",f.read(4))[0]
    except: return None,None

def ingest_image(path, load_base64=True):
    path=Path(path)
    if not path.exists(): raise FileNotFoundError(path)
    mime=_detect_mime(path)
    w,h=(_jpeg_dims(path) if "jpeg" in mime else _png_dims(path) if "png" in mime else (None,None))
    sha=hashlib.sha256(); 
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(8192),b""): sha.update(chunk)
    p=ImageProfile(path=str(path),filename=path.name,file_size_bytes=path.stat().st_size,
                   mime_type=mime,width=w,height=h,hash_sha256=sha.hexdigest())
    if load_base64: p.base64_data=base64.b64encode(path.read_bytes()).decode("ascii")
    return p

def scan_image_directory(directory, extensions=None, load_base64=False):
    directory=Path(directory)
    if not directory.is_dir(): raise NotADirectoryError(directory)
    ext=extensions or {".jpg",".jpeg",".png",".tiff",".tif",".webp"}
    result=[]
    for p in sorted(directory.rglob("*")):
        if p.is_file() and p.suffix.lower() in ext:
            try: result.append(ingest_image(p,load_base64))
            except Exception as e:
                result.append(ImageProfile(path=str(p),filename=p.name,
                    file_size_bytes=0,mime_type="unknown",errors=[str(e)]))
    return result
