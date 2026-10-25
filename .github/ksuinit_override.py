#!/usr/bin/env python3
"""ksuinit 补丁：从 metadata 分区加载 /ksu/kernelsu.ko（.ko 热更新）。

要点：
- ksuinit 早于 init，/sys 与 /dev/block/by-name 都不存在
- 自行把 sysfs 挂到 /mnt/ksys，用完立刻卸载（否则干扰 init 挂 /sys）
- 扫描 4~96MB 分区，只读挂载 ext4，找 /ksu/kernelsu.ko
"""
import sys

HELPER = r'''

// ==== ColorArchive: .ko 热更新（全程清理挂载）====
fn umount_quiet(p: &str) {
    let _ = unmount(p, UnmountFlags::DETACH);
}

fn mount_ro(src: &str, tgt: &str, fstype: &str) -> i32 {
    let _ = std::fs::create_dir_all(tgt);
    let c_src = match CString::new(src) {
        Ok(c) => c,
        Err(_) => return -1,
    };
    let c_tgt = match CString::new(tgt) {
        Ok(c) => c,
        Err(_) => return -1,
    };
    let c_fs = match CString::new(fstype) {
        Ok(c) => c,
        Err(_) => return -1,
    };
    unsafe { mount(c_src.as_ptr(), c_tgt.as_ptr(), c_fs.as_ptr(), 1, std::ptr::null()) }
}

fn try_load_from_partitions() -> bool {
    let mut devs: Vec<String> = Vec::new();
    if let Ok(rd) = std::fs::read_dir("/mnt/ksys/class/block") {
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            let base = format!("/mnt/ksys/class/block/{}", name);
            // 不依赖 DEVTYPE（早期可能还没写入 uevent）：按名字判断是否为分区
            let last_digit = name.chars().last().map(|c| c.is_ascii_digit()).unwrap_or(false);
            if !last_digit {
                continue;
            }
            let uev = std::fs::read_to_string(format!("{}/uevent", base)).unwrap_or_default();
            let sectors: u64 = std::fs::read_to_string(format!("{}/size", base))
                .ok()
                .and_then(|s| s.trim().parse().ok())
                .unwrap_or(0);
            let mb = sectors / 2048;
            if mb >= 4 && mb <= 96 {
                log::info!("override: cand {} {}MB", name, mb);
            }
            let devname = uev
                .lines()
                .find_map(|l| l.strip_prefix("DEVNAME="))
                .map(|s| s.to_string())
                .unwrap_or_else(|| name.clone());
            let by_name = format!("/dev/block/{}", devname);
            let by_num = std::fs::read_to_string(format!("{}/dev", base))
                .ok()
                .map(|d| format!("/dev/block/{}", d.trim()))
                .unwrap_or_default();
            if std::path::Path::new(&by_name).exists() {
                devs.push(by_name);
            } else if !by_num.is_empty() && std::path::Path::new(&by_num).exists() {
                devs.push(by_num);
            }
        }
    }
    log::info!("override: {} candidates", devs.len());
    for dev in devs {
        let rc = mount_ro(&dev, "/mnt/kmeta", "ext4");
        if rc != 0 {
            continue;
        }
        let path = "/mnt/kmeta/ksu/kernelsu.ko";
        let sz = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
        if sz > 0 {
            log::info!("override: found {} on {} ({} bytes)", path, dev, sz);
            if load_module_from_path(path).is_ok() {
                log::info!("override: loaded OK");
                umount_quiet("/mnt/kmeta");
                return true;
            }
            log::error!("override: load failed on {}", dev);
        }
        umount_quiet("/mnt/kmeta");
    }
    false
}

fn load_module_preferred() -> Result<()> {
    let rc = mount_ro("sysfs", "/mnt/ksys", "sysfs");
    log::info!("override: sysfs mount rc={}", rc);
    let mut done = false;
    if rc == 0 || std::path::Path::new("/mnt/ksys/class/block").exists() {
        done = try_load_from_partitions();
    }
    umount_quiet("/mnt/ksys");
    if done {
        return Ok(());
    }
    log::info!("fallback to ramdisk /kernelsu.ko");
    load_module_from_path("/kernelsu.ko")
}

unsafe extern "C" {
    fn mount(
        src: *const std::os::raw::c_char,
        tgt: *const std::os::raw::c_char,
        fstype: *const std::os::raw::c_char,
        flags: std::os::raw::c_ulong,
        data: *const std::os::raw::c_void,
    ) -> std::os::raw::c_int;
}
'''

def main(path: str) -> int:
    src = open(path, encoding="utf-8").read()
    if "load_module_preferred" in src:
        print("already patched, skip")
        return 0
    old = '    if let Err(e) = load_module_from_path("/kernelsu.ko") {'
    new = '    if let Err(e) = load_module_preferred() {'
    if old not in src:
        print("!! anchor not found")
        return 1
    src = src.replace(old, new, 1) + HELPER
    open(path, "w", encoding="utf-8").write(src)
    print("patched:", path)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "userspace/ksuinit/src/init.rs"))