# 5.4.295 CVE 回迁补丁包

本目录是把 ColorArchive Ultra (Linux 5.4.295) 上完成的 CVE 修复**导出成可复用补丁**，
方便其他 5.4 内核或开发者按需套用。

## 内容

- `patches/` 每个 CVE 一个独立补丁（`git format-patch` 格式，含提交信息）
- `patches/series` 应用顺序（按提交时间）
- `DEFERRED.md` 尚未处理的 CVE 及原因

## 一次性套用全部

```bash
git am --3way cve/patches/*.patch
```

冲突时：

```bash
git am --show-current-patch=diff   # 看当前补丁
# 手工解决后
git add -A && git am --continue
```

## 只套用某一个 CVE

```bash
grep -i CVE-2026-31570 cve/patches/series   # 找到文件编号
git am --3way cve/patches/0xx.patch
```

## 来源与做法

1. **官方 stable 回迁**：5.4 分支最后一个版本是 5.4.302（2025-12 EOL）。
   5.4.296–5.4.302 之间的安全修复全部回迁。
2. **EOL 后自主 backport**：5.4 停更后由主线/社区修复、官方 5.4 不会再发的漏洞，
   从 5.10 / 6.x 主线取修复 commit，适配到 5.4 API 后合入。
3. 每个补丁都经过：编译验证 → 打包 boot → 真机刷入 → 冒烟测试。

## 验证清单（本仓库实测）

- [x] 开机正常
- [x] WiFi 连接与上网
- [x] 移动数据
- [x] 蓝牙
- [x] USB（MTP / ADB / gadget）
- [x] ext4 读写 + 扩展属性
- [x] 充电
- [x] root / 内核模块加载

## 注意

- 补丁基于 5.4.295 + 厂商改动，套到其他 5.4 树可能需要手工解冲突（尤其是
  `net/netfilter/nf_tables_api.c`、`fs/ext4/*`、`net/bluetooth/*`）。
- 部分 CVE 依赖较新的内核 API，已标注在 `DEFERRED.md`，不要盲目套用。
- 补丁顺序按提交时间排列，跨补丁有依赖（如 tls 两个补丁）请按 series 顺序。
