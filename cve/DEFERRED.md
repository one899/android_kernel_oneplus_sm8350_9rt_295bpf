# 尚未处理的 CVE

以下 CVE 已确认与 5.4 相关，但**未**包含在补丁包中，原因见备注。

## 需要适配 5.4 缺失的 API（重写工作量较大）

| CVE | 子系统 | 原因 |
|---|---|---|
| CVE-2025-39770 | net/core/dev.c | 依赖 `ipv6_has_hopopt_jumbo()`，5.4 无此函数 |
| CVE-2025-21629 | net/core/dev.c | 同上 |
| CVE-2026-23447 | drivers/net/usb/cdc_ncm.c | 依赖 `struct_size_t()`，5.6+ 才有 |
| CVE-2026-72052 | net/ipv6/ip6_gre.c | 依赖 `rtnl_dev_link_net_capable()`，5.14+ |
| CVE-2025-38643 | net/wireless/reg.c | 补丁用 `wiphy_lock()`，5.4 需改用 rtnl |
| CVE-2026-74302 | net/bluetooth/hci_core.c | 依赖 `struct hci_dev::ncmd_timer`，5.4 无此字段 |
| CVE-2026-64584 | usb gadget f_midi | 依赖 `struct f_midi::work`，5.4 结构不同 |
| CVE-2026-23145 | fs/ext4/xattr.c | 补丁位置与 5.4 差异大，需重写 |

## 需要手工重写（改动面大）

| CVE | 子系统 | 原因 |
|---|---|---|
| CVE-2025-21816 | kernel/time/hrtimer.c | 103 行改动，5.4 hrtimer 结构差异大 |
| CVE-2025-39683 | kernel/trace/trace.c | 需先实现 `trace_parser_fail()` |
| CVE-2025-68325 | net/sched/sch_cake.c | enqueue 逻辑需重构 |
| CVE-2026-46331 | net/sched/act_pedit.c | 涉及 `tcf_pedit_parms` 结构体布局 |
| CVE-2025-21792 | net/ax25/af_ax25.c | 5.4 无 `netdev_hold()`，引用计数需重写 |
| CVE-2026-43309 | drivers/md/md.c | hunk 冲突 |
| CVE-2026-53076 | kernel/bpf/hashtab.c | hunk 冲突 |
| CVE-2026-53078 | net/core/filter.c | hunk 冲突 |
| CVE-2026-64478 | sound/usb/mixer_quirks.c | hunk 冲突 |
| CVE-2026-72314 | drivers/regulator/core.c | hunk 冲突 |
| CVE-2026-46083 | drivers/spi/spi.c | fuzzy 应用后 label 错位 |
| CVE-2026-43049 | drivers/hid/hid-logitech-hidpp.c | fuzzy 应用后不可编译 |
| CVE-2026-43093 | net/xdp/xdp_umem.c | fuzzy 应用后不可编译 |
| CVE-2026-45997 | drivers/scsi/sd.c | fuzzy 应用后引用不存在的变量 |
| CVE-2026-46146 | sound/usb/stream.c | fuzzy 应用后不可编译 |
| CVE-2026-63912 | net/ipv4/esp4.c, net/ipv6/esp6.c | fuzzy 应用后不可编译 |
| CVE-2026-80866 | net/tipc/core.c, net/tipc/udp_media.c | fuzzy 应用后不可编译 |

## 经核实不适用

约 46 个 CVE 对应的驱动/子系统在本设备 defconfig 中未启用（如 iwlwifi、rtw88、
nvme、cifs、batman-adv、nfs、hfsplus、padata、tee 等），或代码结构在 5.4 中不存在，
因此不需要修复。
