from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class ResearchConfig:
    seed: int = 7
    max_features_per_capture: int = 1200
    max_association_rows: int = 1800
    association_gates: tuple = (6., 9., 12.)
    iterations: int = 2
    max_nfev: int = 50
    training_budget: int = 4
    selection_strategy: str = 'contrast'
    outer_fraction: float = .3
    min_capture_blocks: int = 4
    min_relative_gain: float = .01
    minimum_singular: float = .02
    rank_rtol: float = 1e-5
    support_floor: float = .98
    evaluation_cap_px: float = 30.
    min_coverage: float = .9
    max_angle_rad: float = 1.
    bootstrap_reps: int = 500

    def __post_init__(self):
        for name in ('seed','max_features_per_capture','max_association_rows','iterations','max_nfev','training_budget','min_capture_blocks','bootstrap_reps'):
            if type(getattr(self,name)) is not int:
                raise ValueError(name+' must be an integer')
        values=[self.outer_fraction,self.min_relative_gain,self.minimum_singular,self.rank_rtol,self.support_floor,
                self.evaluation_cap_px,self.min_coverage,self.max_angle_rad,*self.association_gates]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('All numerical configuration values must be finite')
        if self.iterations<1 or self.max_nfev<1 or self.max_features_per_capture<30 or self.max_association_rows<30:
            raise ValueError('Positive fitting budgets and at least thirty features required')
        if not self.association_gates or min(self.association_gates)<=0 or not 0<=self.outer_fraction<.5:
            raise ValueError('Invalid association gates or outer fraction')
        if not 0<self.support_floor<=1 or self.minimum_singular<0 or self.training_budget<1:
            raise ValueError('Invalid information thresholds')
        if self.selection_strategy not in ('contrast','all','random','feature_count','d_optimal','e_optimal'):
            raise ValueError('Unknown capture selection strategy')
        if not 0<=self.min_relative_gain<1 or not 0<self.min_coverage<=1 or self.evaluation_cap_px<=0:
            raise ValueError('Invalid validation thresholds')
        if self.min_capture_blocks<2 or self.bootstrap_reps<2 or self.rank_rtol<0:
            raise ValueError('Invalid statistical or rank budgets')

    def to_dict(self):
        return asdict(self)
