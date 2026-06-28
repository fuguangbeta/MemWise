"""
Kalman Profile — 连续值最优估计器
替代 Beta 二值分布，直接建模预期释放量和PF代价
"""
import time

class KalmanProfile:
    """2维卡尔曼滤波: 追踪 (预期释放量, 预期PF代价)"""
    
    def __init__(self):
        self.x_freed = 0.0     # 预期释放量 (bytes)
        self.x_cost = 0.0      # 预期 PF 代价
        self.p_freed = 100.0   # 不确定性
        self.p_cost = 100.0
        self.q = 0.1           # 过程噪声 (行为变化速度)
        self.r = 5.0           # 测量噪声
        self.last_update = 0.0
    
    def predict(self):
        return max(0.0, self.x_freed), max(0.0, self.x_cost)
    
    def update(self, freed, pf_cost):
        now = time.time()
        dt = max(1.0, now - self.last_update) if self.last_update > 0 else 1.0
        self.last_update = now
        
        if dt > 60:
            decay = min(2.0, dt / 60)
            self.p_freed *= decay
            self.p_cost *= decay
        
        k_freed = self.p_freed / (self.p_freed + self.r * dt)
        k_cost = self.p_cost / (self.p_cost + self.r * dt)
        
        innov_freed = freed - self.x_freed
        innov_cost = pf_cost - self.x_cost
        
        self.x_freed += k_freed * innov_freed
        self.x_cost += k_cost * innov_cost
        
        self.p_freed = (1 - k_freed) * self.p_freed + self.q * dt
        self.p_cost = (1 - k_cost) * self.p_cost + self.q * dt
        
        # 自适应 q: 新息大→加速跟踪, 新息小→稳定滤波
        if freed > 0:
            if abs(innov_freed / freed) > 0.5:
                self.q = min(5.0, self.q * 1.2)
            elif abs(innov_freed / freed) < 0.1:
                self.q = max(0.01, self.q * 0.9)
    
    @property
    def confidence(self):
        total_p = self.p_freed + self.p_cost
        return 1.0 - min(1.0, total_p / 200.0)
    
    @property
    def roi(self):
        if self.x_cost < 1:
            return self.x_freed / (1 << 20)
        return (self.x_freed / (1 << 20)) / max(self.x_cost, 1)
    
    def to_dict(self):
        return {
            "x_freed": self.x_freed, "x_cost": self.x_cost,
            "p_freed": self.p_freed, "p_cost": self.p_cost,
            "q": self.q, "r": self.r,
            "last_update": self.last_update,
        }
    
    @classmethod
    def from_dict(cls, d):
        k = cls()
        k.x_freed = d.get("x_freed", 0.0)
        k.x_cost = d.get("x_cost", 0.0)
        k.p_freed = d.get("p_freed", 100.0)
        k.p_cost = d.get("p_cost", 100.0)
        k.q = d.get("q", 0.1)
        k.r = d.get("r", 5.0)
        k.last_update = d.get("last_update", 0.0)
        return k
