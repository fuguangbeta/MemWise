## Windows 智能内存看护工具 · *Intelligent Memory Custodian*

MemWise 是一款纯 ctypes Win32 API 构建的 Windows 内存优化与实时守护工具。通过调用 Windows 底层内存管理 API（NtSetSystemInformation、EmptyWorkingSet、SetSystemFileCacheSize 等），对进程闲置工作集、系统 Standby List、Modified Page List、内存压缩等进行细化治理，在不终止进程、不挂起线程、不注入、不联网的前提下实现物理内存的释放与压缩。支持 GUI 和命令行两种使用方式，以单 exe 分发（约 13.3 MB），零外部依赖。

*Built entirely on ctypes Win32 API with zero third-party dependencies, MemWise reclaims physical memory through disciplined management of idle working sets, standby lists, modified page lists, and memory compression — all without terminating processes, suspending threads, injecting code, or touching the network. Distributed as a single 13.3 MB executable.*


系统的核心价值在于"主动+持续"：在 Windows 自身内存压力感知机制启动之前提前介入回收，并在守护模式下保持 60 秒间隔内零空闲的持续优化。同时通过 Thompson Sampling、Kalman 滤波、泄漏检测、情景记忆、分层先验、五树投票等学习与决策机制，为每个进程建立独立画像，在最大化释放效率的同时抑制缺页副作用。

*MemWise intercepts memory pressure before Windows initiates its own reclamation, maintaining uninterrupted optimization at 60-second intervals in daemon mode. A cognitive engine combining Thompson Sampling, Kalman filtering, leak detection, episodic memory, hierarchical priors, and five-tree policy voting builds independent behavioral profiles per process, maximizing release efficiency while minimizing page-fault side effects.*

程序内嵌了轻量看门狗机制，可在意外崩溃后自动恢复运行状态，并为自身内存占用与运行功耗设立了严格的自律约束。

*An embedded watchdog subprocess restores daemon state within seconds of an unexpected crash. The program also enforces strict limits on its own memory footprint and power consumption.*

版本号 v2.4，构建于 PyInstaller 6.21.0 / Python 3.14.0。

*Version v2.4, built with PyInstaller 6.21.0 on Python 3.14.0.*