import time

class TemporalProfile:
    """24 小时时间槽 WS 模式"""
    
    def __init__(self):
        self.hourly_ws = [0.0] * 24
        self.hourly_samples = [0] * 24
        self.hourly_vol = [0.0] * 24
    
    def feed(self, ws, timestamp=None):
        h = time.localtime(timestamp or time.time()).tm_hour
        alpha = 0.3
        old_ws = self.hourly_ws[h]
        n = self.hourly_samples[h]
        if n == 0:
            self.hourly_ws[h] = float(ws)
        else:
            self.hourly_ws[h] = (1 - alpha) * old_ws + alpha * ws
        self.hourly_samples[h] += 1
        self.hourly_vol[h] = (1 - alpha) * self.hourly_vol[h] + alpha * abs(ws - self.hourly_ws[h])
    
    def is_active_hour(self, h=None):
        h = h or time.localtime().tm_hour
        total = sum(self.hourly_ws)
        count = sum(1 for v in self.hourly_ws if v > 0)
        avg = total / max(count, 1)
        if avg <= 0:
            return True
        return self.hourly_ws[h] > avg * 0.3
    
    def to_dict(self):
        return {
            "hourly_ws": self.hourly_ws,
            "hourly_samples": self.hourly_samples,
            "hourly_vol": self.hourly_vol,
        }
    
    @classmethod
    def from_dict(cls, d):
        t = cls()
        t.hourly_ws = d.get("hourly_ws", [0.0] * 24)
        t.hourly_samples = d.get("hourly_samples", [0] * 24)
        t.hourly_vol = d.get("hourly_vol", [0.0] * 24)
        return t
