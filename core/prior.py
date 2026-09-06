"""
HierarchicalPrior — 分层先验
同类进程共享经验，加速新进程收敛
"""

class HierarchicalPrior:
    """进程分类 + 先验θ计算"""
    
    CATEGORIES = {
        "browser": ["chrome", "msedge", "firefox", "opera", "brave", "vivaldi"],
        "browser_child": ["chrome_child", "msedge_child", "firefox_child"],
        "ide": ["code", "devenv", "clion", "pycharm", "idea", "eclipse", "androidstudio"],
        "terminal": ["cmd", "powershell", "windowsterminal", "conhost", "wt"],
        "office": ["winword", "excel", "powerpnt", "outlook", "onenote", "word", "powerpoint"],
        "game": ["csgo", "dota2", "lol", "overwatch", "valorant", "fortnite", "steam", "epicgames"],
        "chat": ["wechat", "qq", "discord", "telegram", "slack", "teams"],
        "system": ["svchost", "services", "lsass", "csrss", "smss", "wininit", "lsm"],
        "compiler": ["cl", "gcc", "g++", "rustc", "javac", "node"],
        "db": ["sqlservr", "mysqld", "postgres", "mongod", "redis"],
    }
    
    @classmethod
    def classify(cls, name):
        name = name.lower()
        for cat, members in cls.CATEGORIES.items():
            if any(m in name for m in members):
                return cat
        return None
    
    @classmethod
    def initial_theta(cls, name, profiles):
        """返回该类进程的平均θ作为新进程的先验"""
        cat = cls.classify(name)
        if not cat:
            return 0.35  # 未知类别 → 默认
        
        # 同类进程中至少有 5 样本的
        # dict() 快照迭代（2026-09-06 审查 F2）：调用方传入的是 learner.profiles 活引用，
        # 手动优化线程可并发增键，直接迭代会 RuntimeError（与 pop_info/_compute_eris 同款防护）
        peers = []
        for n, p in dict(profiles).items():
            if cls.classify(n) == cat and p.total_samples >= 5:
                peers.append(p.thompson_theta)
        
        if len(peers) < 3:
            return 0.35  # 同类样本不足 → 默认

        return sum(peers) / len(peers)
