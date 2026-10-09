"""No-follow private filesystem operations, including every ancestor directory."""
import errno
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path


def absolute(path):
    p=Path(path).absolute()
    if '..' in p.parts: raise ValueError('Unsafe private path')
    return p


def directory(path,create=False):
    # The traversal anchor needs search access, not permission to read root.
    p=absolute(path);fd=os.open('/',getattr(os,'O_PATH',os.O_RDONLY)|os.O_DIRECTORY)
    try:
        # Reopen root itself too, so the returned descriptor supports chmod/fsync.
        for part in p.parts[1:] or ('.',):
            if create:
                try: os.mkdir(part,0o700,dir_fd=fd)
                except FileExistsError: pass
            try: nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            except OSError as e:
                if e.errno in (errno.ELOOP,errno.ENOTDIR): raise ValueError('Unsafe private directory') from None
                raise
            os.close(fd);fd=nxt
        return fd
    except BaseException:
        os.close(fd);raise


@contextmanager
def parent(path):
    p=absolute(path);fd=directory(p.parent)
    try: yield fd,p.name
    finally: os.close(fd)


def check(path):
    try: return _check(path)
    except FileNotFoundError: return

def _check(path):
    with parent(path) as (fd,name):
        try: info=os.stat(name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError: return
        if stat.S_ISLNK(info.st_mode): raise ValueError('Unsafe private file')


def mkdir(path):
    fd=directory(path,create=True)
    try: os.fchmod(fd,0o700)
    finally: os.close(fd)


def read_bytes(path,max_bytes=None):
    with parent(path) as (fd,name):
        try: file_fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        except OSError as e:
            if e.errno==errno.ELOOP: raise ValueError('Unsafe private file') from None
            raise
        with os.fdopen(file_fd,'rb') as f:
            if max_bytes is not None and os.fstat(f.fileno()).st_size>max_bytes: raise ValueError('Private input exceeds size limit')
            data=f.read() if max_bytes is None else f.read(max_bytes+1)
            if max_bytes is not None and len(data)>max_bytes: raise ValueError('Private input exceeds size limit')
            return data


def read_text(path): return read_bytes(path).decode('utf-8')


def write_text(path,text):
    check(path)
    with parent(path) as (fd,name):
        temp='.'+name+'-'+uuid.uuid4().hex
        file_fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(file_fd,'w',encoding='utf-8') as f:
                f.write(text);f.flush();os.fsync(f.fileno())
            os.rename(temp,name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
        finally:
            try: os.unlink(temp,dir_fd=fd)
            except FileNotFoundError: pass


def chmod(path,mode=0o600):
    with parent(path) as (fd,name):
        try: opened=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        except OSError as e:
            if e.errno==errno.ELOOP: raise ValueError('Unsafe private file') from None
            raise
        try: os.fchmod(opened,mode)
        finally: os.close(opened)


def move(source,destination):
    check(source);check(destination)
    with parent(source) as (src_fd,src_name),parent(destination) as (dst_fd,dst_name):
        os.rename(src_name,dst_name,src_dir_fd=src_fd,dst_dir_fd=dst_fd)


def check_tree(path):
    check(path)
    for folder,dirs,files in os.walk(path,followlinks=False):
        for name in dirs+files: check(Path(folder)/name)

@contextmanager
def lock(path):
    import fcntl
    with parent(path) as (fd,name):
        try: opened=os.open(name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=fd)
        except OSError as e:
            if e.errno==errno.ELOOP: raise ValueError('Unsafe private lock') from None
            raise
        try:
            fcntl.flock(opened,fcntl.LOCK_EX);yield
        finally: fcntl.flock(opened,fcntl.LOCK_UN);os.close(opened)


def create_bytes(path,data):
    with parent(path) as (fd,name):
        try: opened=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        except OSError as e:
            if e.errno==errno.ELOOP: raise ValueError('Unsafe private file') from None
            raise
        with os.fdopen(opened,'wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
