# MemWise v2.5

## Windows 智能内存看护工具 · *Intelligent Memory Custodian*

MemWise 是一款纯 ctypes Win32 API 构建的 Windows 内存优化与实时守护工具。通过调用 Windows 底层内存管理 API（NtSetSystemInformation、EmptyWorkingSet、SetSystemFileCacheSize 等），对进程闲置工作集、系统 Standby List、Modified Page List、内存压缩等进行细化治理，在不终止进程、不挂起线程、不注入、不联网的前提下实现物理内存的释放与压缩。支持 GUI 和命令行两种使用方式，以单 exe 分发（约 12.7 MB），零外部依赖。