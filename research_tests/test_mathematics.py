"""Small algebra/geometry verification fixtures, not a sensor simulator."""
import copy
import unittest
import numpy as np
import cv2
from scipy.spatial.transform import Rotation
from research_calibration.geometry import ProjectionModel,parameters,retract,calibration_from_parameters
from research_calibration.legacy_adapter import read_calibration
from research_calibration.observability import (profile,numerical_jacobian,analyze_observability,
    stable_subspace,hypothesis_basis,ensemble_attribution,supported_svd)
from research_calibration.selective_optimizer import optimize_selective
from research_calibration.uncertainty import cluster_uncertainty
from research_calibration.residuals import AssociationBatch,evaluate_capture
from research_calibration.parameter_hypotheses import parameter_scales
from research_calibration.config import ResearchConfig


def reference():
    return dict(image_size=[484,366],intrinsics=dict(camera_matrix=[[200.,0,242.],[0,205.,183.],[0,0,1]],
        distortion_coefficients=[.01,-.02,.03,-.01]),extrinsics=dict(transform_lidar_to_camera=np.eye(4).tolist()))


class MathematicsTests(unittest.TestCase):
    def test_so3_left_retraction_and_rigid_convention(self):
        p=parameters(reference()); p[:3]=[.2,-.1,.05]; p[3:6]=[.1,.2,.3]
        d=np.zeros(13); d[:3]=[.01,.02,-.01]; d[3]=.02
        q=retract(p,d)
        np.testing.assert_allclose(Rotation.from_rotvec(q[:3]).as_matrix(),
            Rotation.from_rotvec(d[:3]).as_matrix()@Rotation.from_rotvec(p[:3]).as_matrix(),atol=1e-13)
        model=ProjectionModel(reference(),[484,366],dict(cx=242,cy=183,radius=180))
        X=np.array([[.1,.2,2.]])
        np.testing.assert_allclose(model.to_camera(X,np.zeros(1),q),X@Rotation.from_rotvec(q[:3]).as_matrix().T+q[3:6])

    def test_jacobian_independent_nonlinear_derivative(self):
        x=np.array([.2,.7]); fun=lambda q:np.array([np.sin(q[0])+q[1]**2,np.exp(q[0])*q[1]])
        expected=[[np.cos(x[0]),2*x[1]],[np.exp(x[0])*x[1],np.exp(x[0])]]
        np.testing.assert_allclose(numerical_jacobian(fun,x,np.array([.01,2.])),expected,rtol=1e-7)

    def test_geometric_rotation_jacobian(self):
        ref=reference(); p=parameters(ref); p[:3]=[.1,.02,-.04]
        model=ProjectionModel(ref,[484,366],dict(cx=242,cy=183,radius=180))
        X=np.array([[.1,.3,2.],[.4,-.2,3.]])
        fun=lambda q:model.to_camera(X,np.zeros(2),q).ravel()
        J=numerical_jacobian(fun,p,parameter_scales(p),retract)
        Y=fun(p).reshape(-1,3)-p[3:6]
        expected=np.vstack([np.array([[0,z,-y],[-z,0,x],[y,-x,0]]) for x,y,z in Y])
        np.testing.assert_allclose(J[:,:3],expected,atol=2e-9)

    def test_projection_matches_opencv_and_preserves_higher_terms(self):
        ref=reference(); p=parameters(ref)
        model=ProjectionModel(ref,[484,366],dict(cx=242,cy=183,radius=180))
        X=np.array([[.1,.2,1.],[.7,.1,2.],[-.3,.4,1.]])
        u,v,_=model.project(X,p)
        expected,_=cv2.fisheye.projectPoints(X.reshape(-1,1,3),np.zeros(3),np.zeros(3),
            np.array(ref['intrinsics']['camera_matrix'],float),np.array(ref['intrinsics']['distortion_coefficients']))
        np.testing.assert_allclose(np.c_[u,v],expected[:,0],atol=1e-10)
        changed=calibration_from_parameters(ref,model,p)
        self.assertEqual(changed['intrinsics']['distortion_coefficients'][2:],ref['intrinsics']['distortion_coefficients'][2:])

    def test_export_preserves_frozen_groups_and_separates_old_quality(self):
        ref=reference(); ref['quality']={'old_error':123}; ref['uncertainty']={'old_std':4}
        ref['extrinsics']['transform_camera_to_lidar']=np.eye(4).tolist()
        model=ProjectionModel(ref,[484,366],dict(cx=242,cy=183,radius=180)); p=parameters(ref)
        p[6]+=1
        out=calibration_from_parameters(ref,model,p)
        self.assertEqual(out['extrinsics'],ref['extrinsics'])
        self.assertNotIn('quality',out); self.assertEqual(out['reference_metadata']['quality'],ref['quality'])
        p=parameters(ref); p[0]=.01
        out=calibration_from_parameters(ref,model,p)
        self.assertEqual(out['intrinsics'],ref['intrinsics'])
        self.assertNotIn('transform_camera_to_lidar',out['extrinsics'])

    def test_projection_schur_equivalence_with_singular_nuisance(self):
        rng=np.random.default_rng(4); A=rng.normal(size=(30,3)); b=rng.normal(size=(30,1)); N=np.c_[b,2*b,np.zeros((30,1))]
        C=profile(A,N)
        schur=A.T@A-A.T@N@np.linalg.pinv(N.T@N)@N.T@A
        np.testing.assert_allclose(C.T@C,schur,atol=1e-12)
        np.testing.assert_allclose(N.T@C,0,atol=1e-12)

    def test_rank_alias_and_principal_angles(self):
        J=np.eye(5); J[:,1]=J[:,0]
        out=analyze_observability(J,np.ones(5),{'R':(0,),'T':(1,),'I':(2,)},(4,),minimum_singular=.01)
        self.assertEqual(out['groups']['R']['rank'],1)
        self.assertEqual(out['groups']['R']['unique_rank'],0)
        np.testing.assert_allclose(out['pairwise']['R|T']['principal_angles_deg'],0,atol=1e-6)
        self.assertEqual(supported_svd(np.diag([4,1,0]),minimum_singular=.02)[2].shape[1],2)

    def test_stability_requires_every_variant_and_joint_support(self):
        result=stable_subspace([np.eye(2)]*9+[np.array([[1.,0.]])],support_floor=.89)
        self.assertEqual(result['rank'],1)
        np.testing.assert_allclose(result['basis']@result['basis'].T,np.diag([1,0]),atol=1e-12)
        self.assertEqual(stable_subspace([np.eye(2),np.zeros((1,2))])['rank'],0)

    def test_hypothesis_estimability_does_not_prove_attribution(self):
        J=np.zeros((4,13)); J[0,0]=J[0,3]=2; J[1,12]=1
        result=hypothesis_basis([J],(0,12),(12,),np.ones(13))
        self.assertEqual(result['calibration_rank'],1)
        contrasts=ensemble_attribution([J],np.ones(13),{'R':(0,),'T':(3,)})
        self.assertEqual(contrasts['R']['rank'],0)
        self.assertEqual(contrasts['T']['rank'],0)

    def test_consistent_unit_rescaling(self):
        rng=np.random.default_rng(2); J=rng.normal(size=(20,4)); s=np.array([.1,1,2,3]); conversion=np.array([1,1000,1,1])
        a=analyze_observability(J,s,{'R':(0,1),'T':(2,)},(3,))
        b=analyze_observability(J/conversion,s*conversion,{'R':(0,1),'T':(2,)},(3,))
        np.testing.assert_allclose(a['groups']['R']['conditional_information'],b['groups']['R']['conditional_information'])

    def test_optimizer_freezes_forbidden_and_null_directions(self):
        p=np.zeros(3); basis=np.array([[1.],[0.],[0.]])
        out=optimize_selective(lambda q:np.array([q[0]-2.,q[1]-8.]),p,(0,),np.ones(3),basis)
        self.assertTrue(out['success']); np.testing.assert_allclose(out['parameters'],[2,0,0],atol=1e-5)
        with self.assertRaises(ValueError):
            optimize_selective(lambda q:q,p,(0,),np.ones(3),np.eye(3))

    def test_invalid_solution_rejected(self):
        result=optimize_selective(lambda q:q-2,np.zeros(1),(0,),np.ones(1),valid=lambda q:q[0]<=0)
        self.assertLessEqual(result['parameters'][0],0)

    def test_invalid_numeric_contracts(self):
        with self.assertRaises(ValueError): numerical_jacobian(lambda q:np.array([np.nan]),np.zeros(1),np.ones(1))
        with self.assertRaises(ValueError): profile(np.ones((2,1)),np.ones((3,1)))
        with self.assertRaises(ValueError): stable_subspace([np.array([[np.inf]])])
        with self.assertRaises(ValueError): ResearchConfig(min_coverage=2)
        ref=reference(); ref['intrinsics']['camera_matrix'][0][0]=-1
        with self.assertRaises(ValueError): read_calibration(ref)
        ref=reference(); ref['intrinsics']['camera_matrix'][0][1]=1
        with self.assertRaises(ValueError): read_calibration(ref)

    def test_invisible_training_points_are_penalized(self):
        model=ProjectionModel(reference(),[484,366],dict(cx=242,cy=183,radius=180)); p=parameters(reference())
        batch=AssociationBatch(np.array([[0.,0.,-2.]]),np.zeros(1),np.array([[242.,183.]]),np.array([[1.,0.]]),np.ones(1),np.zeros(1),6.)
        self.assertGreater(abs(batch.residual(model,p)[0]),10)

    def test_fixed_evaluation_support_penalizes_visibility_loss(self):
        from types import SimpleNamespace
        model=ProjectionModel(reference(),[484,366],dict(cx=242,cy=183,radius=180)); p=parameters(reference())
        cap=SimpleNamespace(xyz=np.array([[0.,0.,1.],[.1,0,1.]]),sgn=np.zeros(2),img={'q':np.array([[242.,183.]])})
        q=p.copy(); q[3]=10
        before=evaluate_capture(cap,model,p,p); after=evaluate_capture(cap,model,q,p)
        self.assertEqual(before['points'],after['points']); self.assertEqual(after['coverage'],0)
        self.assertEqual(after['capped_edge_rmse_px'],30)

    def test_uncertainty_unknown_directions_and_cluster_rank(self):
        J=np.tile(np.eye(2),(6,1)); ids=np.repeat(np.arange(6),2); r=np.arange(12)/10
        B=np.array([[1.],[0.]])
        out=cluster_uncertainty(J,r,ids,np.ones(2),B)
        self.assertEqual(out['status'],'CONDITIONAL_ONLY'); self.assertIsNone(out['standard_deviations'][1])
        few=cluster_uncertainty(J[:4],r[:4],ids[:4],np.ones(2),B)
        self.assertEqual(few['status'],'INSUFFICIENT_CLUSTERS_OR_SUPPORT')
        zero=cluster_uncertainty(J,np.zeros(12),ids,np.ones(2),B)
        self.assertEqual(zero['status'],'INSUFFICIENT_CLUSTER_RANK')


if __name__=='__main__': unittest.main()
