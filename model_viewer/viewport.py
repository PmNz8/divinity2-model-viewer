"""Tk native WGL viewport; GPU shaders/VBOs, no browser runtime."""
import math
import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader
from PIL import Image
from pyopengltk import OpenGLFrame


VERTEX = '''#version 120
attribute vec3 position;
attribute vec3 normal;
attribute vec2 uv;
attribute vec3 tangent;
attribute vec3 bitangent;
attribute vec2 normal_uv;
uniform mat4 mvp;
varying vec3 n;
varying vec3 t;
varying vec3 b;
varying vec2 texcoord;
varying vec2 normalcoord;
void main(){ gl_Position=mvp*vec4(position,1.0); n=normal; t=tangent; b=bitangent; texcoord=uv; normalcoord=normal_uv; }
'''
FRAGMENT = '''#version 120
varying vec3 n;
varying vec3 t;
varying vec3 b;
varying vec2 texcoord;
varying vec2 normalcoord;
uniform sampler2D diffuse;
uniform sampler2D normal_map;
uniform bool textured;
uniform bool normal_mapped;
uniform int normal_mode;
uniform float normal_y;
uniform vec4 color;
void main(){
  vec4 base=color;
  if(textured) base*=texture2D(diffuse,texcoord);
  vec3 N=normalize(n);
  if(normal_mapped){
    vec4 tex=texture2D(normal_map,normalcoord);
    vec3 map=vec3(normal_mode==0?tex.r:tex.a,tex.g,tex.b)*2.0-1.0;
    map.y*=normal_y;
    if(normal_mode==2) map.z=sqrt(max(0.0,1.0-dot(map.xy,map.xy)));
    if(dot(map,map)<0.000001) map=vec3(0.0,0.0,1.0);
    vec3 T=normalize(t-N*dot(N,t));
    vec3 B=normalize(cross(N,T))* (dot(cross(N,T),b)<0.0?-1.0:1.0);
    N=normalize(mat3(T,B,N)*normalize(map));
  }
  float light=.35+.65*abs(dot(N,normalize(vec3(.4,.7,.6))));
  gl_FragColor=vec4(base.rgb*light,base.a);
}
'''


def normals(vertices, triangles):
    vertices, triangles = np.asarray(vertices, dtype=np.float32), np.asarray(triangles, dtype=np.uint32)
    result = np.zeros_like(vertices)
    p = vertices[triangles]
    face = np.cross(p[:,1]-p[:,0], p[:,2]-p[:,0])
    for k in range(3):
        np.add.at(result, triangles[:,k], face)
    length = np.linalg.norm(result, axis=1)
    result /= np.maximum(length[:,None], 1e-20)
    result[length<1e-20]=(0,0,1)
    return result


def tangent_basis(vertices,triangles,ns,uv):
    p=np.asarray(vertices,dtype=np.float32)[triangles]; tex=np.asarray(uv,dtype=np.float32)[triangles]
    edge1=p[:,1]-p[:,0]; edge2=p[:,2]-p[:,0]; d1=tex[:,1]-tex[:,0]; d2=tex[:,2]-tex[:,0]
    det=d1[:,0]*d2[:,1]-d1[:,1]*d2[:,0]; inv=np.zeros_like(det); valid=np.abs(det)>1e-12; inv[valid]=1/det[valid]
    ts=(edge1*d2[:,1,None]-edge2*d1[:,1,None])*inv[:,None]
    bs=(edge2*d1[:,0,None]-edge1*d2[:,0,None])*inv[:,None]
    tangent=np.zeros_like(ns); bitangent=np.zeros_like(ns)
    for k in range(3): np.add.at(tangent,triangles[:,k],ts); np.add.at(bitangent,triangles[:,k],bs)
    tangent-=ns*np.sum(ns*tangent,axis=1)[:,None]
    lengths=np.linalg.norm(tangent,axis=1); bad=lengths<1e-12
    reference=np.zeros_like(ns); reference[:,0]=1; reference[np.abs(ns[:,0])>.9]=(0,1,0)
    tangent[bad]=np.cross(reference[bad],ns[bad]); tangent/=np.maximum(np.linalg.norm(tangent,axis=1)[:,None],1e-20)
    cross=np.cross(ns,tangent); signs=np.where(np.sum(cross*bitangent,axis=1)<0,-1.,1.)
    return tangent,cross*signs[:,None]


class Viewport(OpenGLFrame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.program = None
        self.meshes = []
        self.line_vbo = None
        self.line_count = 0
        self.show_visual = True
        self.disposed = False
        self.center = np.zeros(3)
        self.radius = 100.
        self.yaw, self.pitch, self.zoom = -.6, .3, 1.
        self.animate = 16
        self.context_info = {}
        self._mouse = None
        self.normal_enabled=True; self.normal_mode='AUTO'; self.normal_flip_y=False
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._orbit)
        self.bind('<MouseWheel>', self._wheel)

    def _press(self, event):
        self._mouse = (event.x, event.y)

    def _orbit(self, event):
        if self._mouse:
            x, y = self._mouse
            self.yaw += (event.x-x)*.01
            self.pitch = max(-1.5, min(1.5, self.pitch+(event.y-y)*.01))
        self._mouse = (event.x, event.y)

    def _wheel(self, event):
        self.zoom = max(.05, min(20., self.zoom*math.exp(-event.delta*.001)))

    def initgl(self):
        if self.program is None:
            self.program = compileProgram(compileShader(VERTEX, GL.GL_VERTEX_SHADER), compileShader(FRAGMENT, GL.GL_FRAGMENT_SHADER))
            self.context_info = {key: GL.glGetString(value).decode() for key, value in
                                 (('vendor',GL.GL_VENDOR), ('renderer',GL.GL_RENDERER), ('version',GL.GL_VERSION))}
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glClearColor(.045, .055, .075, 1.)

    def set_meshes(self, meshes, fit=True):
        """Input dictionaries: vertices, triangles, optional UV/image/color."""
        self.tkMakeCurrent()
        for old in self.meshes:
            GL.glDeleteBuffers(2, [old['vbo'],old['ibo']])
            if old['texture']:
                GL.glDeleteTextures([old['texture']])
            if old.get('normal_texture'): GL.glDeleteTextures([old['normal_texture']])
        self.meshes = []
        for mesh in meshes:
            vertices = np.asarray(mesh['vertices'], dtype=np.float32)
            indices = np.asarray(mesh['triangles'], dtype=np.uint32).reshape(-1)
            ns = normals(vertices, indices.reshape(-1,3))
            uv = np.asarray(mesh.get('uv', np.zeros((len(vertices),2))), dtype=np.float32)
            normal_uv=np.asarray(mesh.get('normal_uv',uv),dtype=np.float32)
            tangent,bitangent=tangent_basis(vertices,indices.reshape(-1,3),ns,normal_uv)
            data = np.concatenate((vertices, ns, uv,tangent,bitangent,normal_uv), axis=1).astype(np.float32)
            vbo, ibo = GL.glGenBuffers(2)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER,vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER,data.nbytes,data,GL.GL_DYNAMIC_DRAW)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER,ibo)
            GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER,indices.nbytes,indices,GL.GL_STATIC_DRAW)
            texture = 0
            if mesh.get('image') is not None:
                texture = GL.glGenTextures(1)
                GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
                width, height = mesh['image'].size
                pixels = np.frombuffer(mesh['image'].tobytes(), dtype=np.uint8).reshape(height,width,4)
                GL.glTexImage2D(GL.GL_TEXTURE_2D,0,GL.GL_RGBA,pixels.shape[1],pixels.shape[0],0,GL.GL_RGBA,GL.GL_UNSIGNED_BYTE,pixels)
                filtering = GL.GL_NEAREST if mesh.get('filter') == 'nearest' else GL.GL_LINEAR
                GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MIN_FILTER,filtering)
                GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MAG_FILTER,filtering)
                clamp = mesh.get('clamp', 3)
                GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_WRAP_S,GL.GL_REPEAT if clamp & 2 else GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_WRAP_T,GL.GL_REPEAT if clamp & 1 else GL.GL_CLAMP_TO_EDGE)
            normal_texture=0; mode='RGB'
            if mesh.get('normal_image') is not None and self.normal_enabled:
                from .normal_maps import suggest_mode
                im=mesh['normal_image']; raw=im.tobytes(); mode=suggest_mode(raw) if self.normal_mode=='AUTO' else self.normal_mode
                normal_texture=GL.glGenTextures(1); GL.glBindTexture(GL.GL_TEXTURE_2D,normal_texture)
                GL.glTexImage2D(GL.GL_TEXTURE_2D,0,GL.GL_RGBA,*im.size,0,GL.GL_RGBA,GL.GL_UNSIGNED_BYTE,raw)
                filtering=GL.GL_NEAREST if mesh.get('normal_filter')=='nearest' else GL.GL_LINEAR
                GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MIN_FILTER,filtering); GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MAG_FILTER,filtering)
                clamp=mesh.get('normal_clamp',3)
                GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_WRAP_S,GL.GL_REPEAT if clamp&2 else GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_WRAP_T,GL.GL_REPEAT if clamp&1 else GL.GL_CLAMP_TO_EDGE)
            self.meshes.append(dict(vbo=vbo,ibo=ibo,count=indices.size,texture=texture,normal_texture=normal_texture,normal_mode=mode,
                                    color=mesh.get('color',(.65,.72,.83,1.)),data=data,indices=indices))
        if fit and self.meshes:
            points = np.concatenate([m['data'][:,:3] for m in self.meshes])
            low, high = points.min(axis=0), points.max(axis=0)
            self.center, self.radius = (low+high)/2, max(float(np.linalg.norm(high-low))/2, .1)

    def update_vertices(self, positions):
        self.tkMakeCurrent()
        for mesh, vertices in zip(self.meshes, positions):
            mesh['data'][:,:3] = vertices
            mesh['data'][:,3:6] = normals(vertices,mesh['indices'].reshape(-1,3))
            t,b=tangent_basis(vertices,mesh['indices'].reshape(-1,3),mesh['data'][:,3:6],mesh['data'][:,14:16])
            mesh['data'][:,8:11]=t; mesh['data'][:,11:14]=b
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER,mesh['vbo'])
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER,0,mesh['data'].nbytes,mesh['data'])

    def set_skeleton(self, parents, world, visible=True):
        self.tkMakeCurrent()
        points = [world[i][axis][3] for child, parent in parents.items()
                  for i in (parent, child) for axis in range(3)] if visible else []
        vertices = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        self.line_count = len(vertices)
        if not self.line_count:
            return
        if self.line_vbo is None:
            self.line_vbo = GL.glGenBuffers(1)
        data = np.zeros((len(vertices), 16), dtype=np.float32)
        data[:, :3] = vertices
        data[:, 5] = 1.
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.line_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_DYNAMIC_DRAW)

    def redraw(self):
        if self.program is None:
            return
        import ctypes
        width, height = max(self.winfo_width(),1), max(self.winfo_height(),1)
        GL.glViewport(0,0,width,height)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT|GL.GL_DEPTH_BUFFER_BIT)
        direction = np.array((math.cos(self.pitch)*math.sin(self.yaw),math.cos(self.pitch)*math.cos(self.yaw),math.sin(self.pitch)))
        eye = self.center+direction*self.radius*3*self.zoom
        z = direction
        x = np.cross((0.,0.,1.),z); x /= np.linalg.norm(x)
        y = np.cross(z,x)
        view = np.eye(4); view[:3,:3] = (x,y,z); view[:3,3] = -view[:3,:3]@eye
        near, far = self.radius*.005, self.radius*100
        f = 1/math.tan(math.radians(45)/2)
        proj = np.array(((f*height/width,0,0,0),(0,f,0,0),(0,0,(far+near)/(near-far),2*far*near/(near-far)),(0,0,-1,0)))
        GL.glUseProgram(self.program)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self.program,'mvp'),1,True,np.asarray(proj@view,dtype=np.float32))
        for mesh in self.meshes:
            if not self.show_visual:
                continue
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER,mesh['vbo'])
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER,mesh['ibo'])
            for name, size, offset in (('position',3,0),('normal',3,12),('uv',2,24),('tangent',3,32),('bitangent',3,44),('normal_uv',2,56)):
                loc = GL.glGetAttribLocation(self.program,name)
                GL.glEnableVertexAttribArray(loc)
                GL.glVertexAttribPointer(loc,size,GL.GL_FLOAT,False,64,ctypes.c_void_p(offset))
            GL.glUniform4f(GL.glGetUniformLocation(self.program,'color'),*mesh['color'])
            GL.glUniform1i(GL.glGetUniformLocation(self.program,'textured'),bool(mesh['texture']))
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D,mesh['texture'])
            GL.glUniform1i(GL.glGetUniformLocation(self.program,'diffuse'),0)
            GL.glActiveTexture(GL.GL_TEXTURE1); GL.glBindTexture(GL.GL_TEXTURE_2D,mesh['normal_texture'])
            GL.glUniform1i(GL.glGetUniformLocation(self.program,'normal_map'),1)
            GL.glUniform1i(GL.glGetUniformLocation(self.program,'normal_mapped'),bool(mesh['normal_texture']))
            GL.glUniform1i(GL.glGetUniformLocation(self.program,'normal_mode'),('RGB','AGB','AG').index(mesh['normal_mode']))
            GL.glUniform1f(GL.glGetUniformLocation(self.program,'normal_y'),-1. if self.normal_flip_y else 1.)
            GL.glDrawElements(GL.GL_TRIANGLES,mesh['count'],GL.GL_UNSIGNED_INT,None)
        if self.line_count:
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.line_vbo)
            for name, size, offset in (('position',3,0),('normal',3,12),('uv',2,24),('tangent',3,32),('bitangent',3,44),('normal_uv',2,56)):
                loc = GL.glGetAttribLocation(self.program,name)
                GL.glEnableVertexAttribArray(loc)
                GL.glVertexAttribPointer(loc,size,GL.GL_FLOAT,False,64,ctypes.c_void_p(offset))
            GL.glUniform4f(GL.glGetUniformLocation(self.program,'color'),1.,.7,.15,1.)
            GL.glUniform1i(GL.glGetUniformLocation(self.program,'textured'),False)
            GL.glUniform1i(GL.glGetUniformLocation(self.program,'normal_mapped'),False)
            GL.glDisable(GL.GL_DEPTH_TEST)
            GL.glDrawArrays(GL.GL_LINES, 0, self.line_count)
            GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glUseProgram(0)

    def destroy(self):
        if not self.disposed:
            self.animate = 0
            if self.cb:
                self.after_cancel(self.cb)
                self.cb = None
            if self.context_created:
                # pyopengltk 0.0.4 Windows wrapper does not release its WGL/DC.
                # Access is intentionally tied to that pinned implementation.
                import ctypes
                from OpenGL.WGL import wglMakeCurrent, wglDeleteContext
                dc = self._OpenGLFrame__window
                context = self._OpenGLFrame__context
                wglMakeCurrent(dc, context)
                for mesh in self.meshes:
                    GL.glDeleteBuffers(2, [mesh['vbo'], mesh['ibo']])
                    if mesh['texture']:
                        GL.glDeleteTextures([mesh['texture']])
                    if mesh.get('normal_texture'): GL.glDeleteTextures([mesh['normal_texture']])
                if self.line_vbo is not None:
                    GL.glDeleteBuffers(1, [self.line_vbo])
                if self.program:
                    GL.glDeleteProgram(self.program)
                wglMakeCurrent(None, None)
                wglDeleteContext(context)
                release = ctypes.windll.user32.ReleaseDC
                release.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                release.restype = ctypes.c_int
                release(self.winfo_id(), dc)
            self.disposed = True
        super().destroy()

    def capture(self, path):
        """Capture this renderer's backbuffer, not the desktop."""
        self.tkMakeCurrent()
        self.redraw()
        width, height = self.winfo_width(), self.winfo_height()
        data = GL.glReadPixels(0,0,width,height,GL.GL_RGBA,GL.GL_UNSIGNED_BYTE)
        Image.frombytes('RGBA',(width,height),data).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(path)
