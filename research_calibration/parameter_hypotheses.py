"""Competing allowed-change models; names are not verified physical fault labels."""
from dataclasses import dataclass
import numpy as np

PARAMETERS = ('wx','wy','wz','tx','ty','tz','fx','fy','cx','cy','k1','k2','beam')
GROUPS = {'R': (0,1,2), 'T': (3,4,5), 'I': (6,7,8,9,10,11)}
NUISANCE = (12,)


@dataclass(frozen=True)
class Hypothesis:
    name: str
    groups: tuple

    @property
    def indices(self):
        return tuple(sorted({index for group in self.groups for index in GROUPS[group]} | set(NUISANCE)))


HYPOTHESES = tuple(Hypothesis(name, groups) for name, groups in (
    ('KEEP', ()), ('R', ('R',)), ('T', ('T',)), ('I', ('I',)),
    ('RT', ('R','T')), ('RI', ('R','I')), ('TI', ('T','I')), ('RTI', ('R','T','I'))))


def parameter_scales(reference):
    """Declared physical increments, not measured parameter standard deviations."""
    p = np.asarray(reference, float)
    if p.shape != (13,) or not np.isfinite(p).all() or min(p[6:8]) <= 0:
        raise ValueError('Expected thirteen finite parameters with positive focal lengths')
    return np.array([*([np.pi/180]*3), *([.01]*3), .01*p[6], .01*p[7], 1., 1., .01, .01, np.pi/1800])
