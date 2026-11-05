"""Validated LiDAR→camera geometry and local SO(3) updates, preserving fixed k3/k4."""
import copy
import numpy as np
from scipy.spatial.transform import Rotation
from .legacy_adapter import legacy_modules


class ProjectionModel(legacy_modules().cb.Model):
    def __init__(self, reference, size, circle, max_angle_rad=1.0):
        T = np.asarray(reference['extrinsics']['transform_lidar_to_camera'],float)
        super().__init__(T[:3,:3],size,circle)
        self.higher_order = np.r_[np.ravel(reference['intrinsics'].get('distortion_coefficients',[])),np.zeros(4)][2:4]
        self.max_angle_rad = float(max_angle_rad)
        if not 0<self.max_angle_rad<np.pi/2:
            raise ValueError('Declare a supported front-camera angular domain in (0, pi/2)')

    def project(self, Pc, p):
        Pc = np.asarray(Pc,float)
        front = Pc[:,2]>.2
        a,b = (Pc[:,:2]/np.where(front,Pc[:,2],1.)[:,None]).T
        r = np.hypot(a,b); theta = np.arctan(r); q = theta*theta
        k1,k2 = p[10:12]; k3,k4 = self.higher_order
        scale = np.where(r>1e-12,theta*(1+q*(k1+q*(k2+q*(k3+q*k4))))/np.maximum(r,1e-12),1.)
        u,v = p[6]*a*scale+p[8],p[7]*b*scale+p[9]
        c = self.circle
        inside = front & (theta<=self.max_angle_rad) & (u>=0)&(u<self.w)&(v>=0)&(v<self.h)
        inside &= (u-c['cx'])**2+(v-c['cy'])**2 <= (.97*c['radius'])**2
        return u,v,inside

    def matrices(self,p):
        K,D,T = super().matrices(p)
        D[2:4] = self.higher_order
        return K,D,T

    def valid(self,p):
        p = np.asarray(p,float)
        if p.shape!=(13,) or not np.isfinite(p).all() or min(p[6:8])<=0 or np.linalg.norm(p[3:6])>2.:
            return False
        t2 = np.linspace(0,self.max_angle_rad,150)**2
        k3,k4 = self.higher_order
        derivative = 1+3*p[10]*t2+5*p[11]*t2**2+7*k3*t2**3+9*k4*t2**4
        return bool(np.all(derivative>0) and .1*self.w<p[6]<5*self.w and .1*self.h<p[7]<5*self.h
                    and -.25*self.w<p[8]<1.25*self.w and -.25*self.h<p[9]<1.25*self.h and abs(p[12])<.05)


def parameters(reference):
    K = np.asarray(reference['intrinsics']['camera_matrix'],float)
    D = np.r_[np.ravel(reference['intrinsics'].get('distortion_coefficients',[])),np.zeros(4)][:4]
    p = np.zeros(13)
    p[3:6] = np.asarray(reference['extrinsics']['transform_lidar_to_camera'])[:3,3]
    p[6:10] = K[0,0],K[1,1],K[0,2],K[1,2]
    p[10:12] = D[:2]
    p[12] = np.radians(reference.get('beam_inflation_deg',0.))
    return p


def retract(reference,delta):
    p = np.asarray(reference,float)+np.asarray(delta,float)
    p[:3] = (Rotation.from_rotvec(delta[:3])*Rotation.from_rotvec(reference[:3])).as_rotvec()
    return p


def calibration_from_parameters(original,model,p):
    result = copy.deepcopy(original)
    K,D,T = model.matrices(p)
    baseline=parameters(original)
    if not np.array_equal(p[6:12],baseline[6:12]):
        result['intrinsics'].update(camera_matrix=K.tolist(),distortion_coefficients=D.tolist())
    if np.any(p[:3]!=0) or not np.array_equal(p[3:6],baseline[3:6]):
        result['extrinsics'] = dict(transform_lidar_to_camera=T.tolist())
    result['beam_inflation_deg'] = float(np.degrees(p[12]))
    # Historical reference scores/uncertainties must not masquerade as candidate evidence.
    metadata=result.pop('reference_metadata',{})
    for key in ('method','quality','confidence','uncertainty','selection','history','mounting'):
        if key in result: metadata[key]=result.pop(key)
    if metadata: result['reference_metadata']=metadata
    result['method']='Constrained research candidate; review the separate assessment report'
    return result
