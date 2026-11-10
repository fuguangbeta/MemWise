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
        """按进程基名匹配（2026-11-08 修订）。
        旧实现「整名子串 + 固定类目顺序」有两处失效：
        ① browser_child 被 browser 永久遮蔽（"chrome" 先命中 chrome_child）；
        ② 短名误伤（"code" 命中 "codec"/"codeblocks"）。
        现取基名、按成员名长度降序：长名（≥5 字符）允许子串，短名只允许精确或下划线前缀。
        结果：chrome_child→browser_child、codec→None；msedgewebview2→browser、
        msteams→chat、Code.exe→ide 等历史命中保持不变。"""
        n = str(name or "").strip().lower()
        if n.endswith(".exe"):
            n = n[:-4]
        if not n:
            return None
        items = [(cat, m.lower()) for cat, ms in cls.CATEGORIES.items() for m in ms]
        for cat, m in sorted(items, key=lambda x: -len(x[1])):
            if len(m) >= 6:
                # 长名允许子串（msedgewebview2 → browser）
                if m in n:
                    return cat
            elif len(m) == 5:
                # 5 字符名只认"完整词"：精确 / 下划线前缀 / 结尾（msteams → chat，
                # 而不再被 "steam" 子串误判成 game；excel/opera/brave 等精确命中不变）
                if n == m or n.startswith(m + "_") or n.endswith(m) or n.endswith("_" + m):
                    return cat
            else:
                # ≤4 字符短名只认精确/下划线前缀（codec 不再被 "code" 误判成 ide）
                if n == m or n.startswith(m + "_"):
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
